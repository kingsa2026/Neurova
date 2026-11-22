# -*- coding: utf-8 -*-
"""Git 仓库连接器（U-conn 扩展批）：仓库文件清单作为行集。

走系统 ``git`` 二进制（不引 GitPython 等新依赖）：clone --depth 1 到临时
工作副本，fetchBatch 按文件清单 offset 切页——行 = {path, size_bytes}。
凭据走 NEUROVA_KB_SECRET 指针纪律（credentialEnv：{username, token}，
仅 https 远端时拼入 URL；**日志与异常一律用脱敏 URL**，带凭据的 URL
不进任何日志）。公共仓免凭据。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_GIT_TIMEOUT_SECONDS = 120


class GitAdapter:
    """`sourceType=git` 的 Protocol 实现（仓库文件清单只读拉取）。"""

    def __init__(self, descriptor: Dict[str, Any], sourceId: str,
                 tenantId: str = "default") -> None:
        self._descriptor = dict(descriptor or {})
        self._sourceId = str(sourceId)
        self._tenantId = str(tenantId or "default")
        self._repoUrl = str(self._descriptor.get("repo_url") or "")
        self._branch = str(self._descriptor.get("branch") or "")
        self._fileGlob = str(self._descriptor.get("file_glob") or "**/*")
        creds = dict(self._descriptor.get("credentialEnv") or {})
        self._username = str(creds.get("username") or "")
        self._tokenEnv = str(creds.get("token") or "")
        self._prepared = False

    def _token(self) -> str:
        import os

        envName = self._tokenEnv.strip()
        return os.environ.get(envName, "") if envName else ""

    def _authedUrl(self) -> str:
        """https 远端拼凭据（user:token@）；非 https 原样。永不进日志。"""
        url = self._repoUrl
        if url.startswith("https://") and self._username and self._token():
            url = "https://%s:%s@%s" % (self._username, self._token(),
                                        url[len("https://"):])
        return url

    def _sanitized(self, url: str) -> str:
        if "@" in url:
            return url.split("@", 1)[0] + "@***"
        return url

    def _workDir(self) -> Path:
        digest = hashlib.sha1(("%s|%s|%s" % (self._sourceId, self._repoUrl,
                                             self._branch)).encode()).hexdigest()[:12]
        return Path(tempfile.gettempdir()) / ("neurova_git_%s" % digest)

    def _runGit(self, args: List[str], cwd: Optional[Path] = None) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise RuntimeError("git %s 失败：%s" % (args[0], proc.stderr.strip()[:300]))
        return proc.stdout

    def _prepare(self) -> Path:
        work = self._workDir()
        url = self._authedUrl()
        if not (work / ".git").exists():
            import shutil

            shutil.rmtree(work, ignore_errors=True)
            args = ["clone", "--depth", "1"]
            if self._branch:
                args += ["--branch", self._branch]
            args += [url, str(work)]
            self._runGit(args)
        else:
            self._runGit(["fetch", "--depth", "1", "origin",
                          self._branch or "HEAD"], cwd=work)
            self._runGit(["reset", "--hard", "FETCH_HEAD"], cwd=work)
        self._prepared = True
        return work

    def _files(self) -> List[Dict[str, Any]]:
        import fnmatch

        work = self._prepare()
        rows: List[Dict[str, Any]] = []
        for path in sorted(work.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(work).as_posix()
            if relative.startswith(".git/"):
                continue
            if not fnmatch.fnmatch(relative, self._fileGlob):
                continue
            rows.append({"path": relative,
                         "size_bytes": path.stat().st_size,
                         "source_id": self._sourceId})
        return rows

    async def describeSchema(self) -> Any:
        from .protocols import SourceSchema

        tables = self._descriptor.get("tables") or [
            {"table_name": "git_files",
             "columns": [{"column_name": "path"}, {"column_name": "size_bytes"}]}]
        return SourceSchema(sourceId=self._sourceId, sourceType="git",
                            tables=[dict(t) for t in tables])

    async def health(self) -> Any:
        from .protocols import SourceHealth

        if not self._repoUrl:
            return SourceHealth(status="error", reason="repo_url 缺失（描述符）")
        try:
            self._runGit(["ls-remote", "--heads", self._authedUrl()])
            return SourceHealth(status="ok")
        except Exception as exc:  # noqa: BLE001 - health 是读数不是断言
            return SourceHealth(status="error", reason=self._sanitized(str(exc)))

    async def close(self) -> None:
        return None

    async def fetchBatch(self, cursor: Any, limit: int) -> Any:
        from .protocols import ChangeBatch, SourceCursor

        if not self._repoUrl:
            return ChangeBatch(rows=[], nextCursor=None, hasMore=False)
        offset = 0
        if cursor and getattr(cursor, "token", ""):
            try:
                offset = int(json.loads(cursor.token).get("offset", 0))
            except (ValueError, TypeError):
                offset = 0
        try:
            rows = self._files()
        except Exception as exc:  # noqa: BLE001 - 拉取失败诚实空批＋脱敏日志
            logger.warning("git: 拉取失败 %s: %s",
                           self._sanitized(self._repoUrl), exc)
            rows = []
        window = rows[offset:offset + max(1, int(limit))]
        hasMore = offset + len(window) < len(rows)
        nextCursor = SourceCursor(token=json.dumps({"offset": offset + len(window)})) \
            if hasMore else None
        return ChangeBatch(rows=window, nextCursor=nextCursor, hasMore=hasMore)
