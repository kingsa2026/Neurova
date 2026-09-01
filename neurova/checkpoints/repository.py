"""
检查点 Git 裸仓库层（P1-5）

零新依赖：git CLI plumbing（hash-object / write-tree / commit-tree /
update-ref / cat-file / ls-tree），bare 仓库驻 data/checkpoints/{agent_id}.git。

ref 规范：refs/{kind}/{session_key}/{ts}
- kind: auto（自动快照）/ snap（手动）/ pre-restore（恢复前留档）
- ts: time.strftime("%Y%m%dT%H%M%S") + 微短随机后缀（同秒不冲突）

设计约束：仅调用 git 进程，不做任何工作区 checkout；内容以 blob+tree
入对象库，读取用 cat-file（内存态），恢复动作由 service 拼装。
"""

from __future__ import annotations

import datetime
import secrets
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ref 中 kind 白名单（防 ref 注入：session_key/ts 同样经校验）
_KINDS = ("auto", "snap", "pre-restore")

_REF_FORBIDDEN = set("/~^:?*[\\\x00 ") | {".."}


def _sanitize_part(part: str, max_len: int = 80) -> str:
    """ref 路径段消毒：空/超长/含 git 非法字符即拒绝。"""
    if not part or len(part) > max_len or any(c in _REF_FORBIDDEN for c in part):
        raise ValueError(f"非法 ref 段: {part!r}")
    if part.startswith("-"):
        raise ValueError(f"非法 ref 段（选项注入）: {part!r}")
    return part


_TS_COUNTER = 0


def _make_ts() -> str:
    """快照时间戳：秒级时钟 + 进程内单调计数后缀。

    同秒内多次快照的后缀严格递增（十六进制），保证字符串序=时间序——
    排序断言与"最新在前"语义在同秒密集写入下依然成立。
    """
    global _TS_COUNTER
    _TS_COUNTER += 1
    return datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + format(_TS_COUNTER, "04x")


make_ts = _make_ts


class CheckpointRepository:
    """git 裸仓库读写封装（子进程 plumbing，无工作区）。"""

    def __init__(self, git_dir: str):
        self.git_dir = Path(git_dir)
        if not self.git_dir.exists():
            self.git_dir.mkdir(parents=True, exist_ok=True)
            self._git("init", "--bare", "-q", str(self.git_dir))

    # ── git 进程封装 ──

    def _git(self, *args: str, input_bytes: Optional[bytes] = None) -> bytes:
        proc = subprocess.run(
            ["git", "--git-dir", str(self.git_dir), *args],
            capture_output=True,
            input=input_bytes,
            timeout=30,
        )
        if proc.returncode != 0:
            # git show-ref 在空仓库（无任何 ref）返回 1——语义上等同无输出
            if args[0] == "show-ref":
                return b""
            raise RuntimeError(
                f"git {args[0]} 失败: {proc.stderr.decode('utf-8', 'replace')[:300]}"
            )
        return proc.stdout

    # ── 写路径 ──

    def hash_object(self, content: bytes) -> str:
        out = self._git("hash-object", "-w", "-t", "blob", "--stdin", input_bytes=content)
        return out.decode("ascii").strip()

    def write_tree_from_files(self, files: Dict[str, bytes]) -> str:
        """把 {safe_key: bytes} 写成单个 flat tree（键不含 '/'，由 service 保证）。"""
        tree_entries: List[str] = []
        for path in sorted(files):
            _sanitize_part(path, max_len=120)
            if "/" in path:
                raise ValueError(f"tree 键不允许 '/': {path!r}")
            blob = self.hash_object(files[path])
            tree_entries.append(f"100644 blob {blob}\t{path}")
        # 构造 tree 的另一条路：mktree
        out = self._git(
            "mktree", input_bytes="\n".join(tree_entries).encode("utf-8")
        )
        return out.decode("ascii").strip()

    def commit_tree(self, tree_sha: str, message: str, parent: Optional[str] = None) -> str:
        args = ["commit-tree", tree_sha, "-m", message]
        if parent:
            args.extend(["-p", parent])
        out = self._git(*args)
        return out.decode("ascii").strip()

    def update_ref(self, ref: str, commit_sha: str) -> None:
        parts = ref.split("/")
        if len(parts) != 4 or parts[0] != "refs" or parts[1] not in _KINDS:
            raise ValueError(f"非法 ref 规范: {ref}")
        _sanitize_part(parts[2])
        _sanitize_part(parts[3])
        self._git("update-ref", ref, commit_sha)

    def delete_ref(self, ref: str) -> None:
        self._git("update-ref", "-d", ref)

    # ── 读路径 ──

    def rev_parse(self, ref: str) -> Optional[str]:
        try:
            out = self._git("rev-parse", "--verify", "-q", ref)
            return out.decode("ascii").strip() or None
        except RuntimeError:
            return None

    def cat_blob(self, blob_sha: str) -> bytes:
        return self._git("cat-file", "blob", blob_sha)

    def list_tree(self, tree_sha: str) -> Dict[str, str]:
        out = self._git("ls-tree", tree_sha).decode("utf-8")
        files: Dict[str, str] = {}
        for line in out.splitlines():
            if not line.strip():
                continue
            meta, path = line.split("\t", 1)
            _mode, otype, sha = meta.split()
            if otype == "blob":
                files[path] = sha
        return files

    def list_refs(self, kind_prefix: str) -> List[Dict[str, Any]]:
        """列出 refs/{kind_prefix}/*（按 commit 时间降序）。kind_prefix 可含
        '/'（如 "auto/sess-A"），各段分别消毒。

        排序用 git committerdate（for-each-ref --sort=-committerdate）——
        同秒内多个快照的 ts 随机后缀不保时间序，字符串排序会错。
        """
        parts = kind_prefix.split("/")
        safe = "/".join(_sanitize_part(p) for p in parts)
        prefix = f"refs/{safe}/"
        out = self._git(
            "for-each-ref",
            "--sort=-committerdate",
            "--format=%(refname) %(objectname) %(committerdate:unix)",
            f"refs/{safe}/**",
        ).decode("utf-8", "replace")
        rows: List[Dict[str, Any]] = []
        for line in out.splitlines():
            if not line.strip() or line.count(" ") < 2:
                continue
            ref, sha, date_s = line.rsplit(" ", 2)
            if not ref.startswith(prefix):
                continue
            tail = ref[len(prefix):]
            if "/" in tail:
                session_key, ts = tail.rsplit("/", 1)
            else:
                session_key, ts = (parts[1] if len(parts) > 1 else ""), tail
            try:
                date_f = float(date_s)
            except ValueError:
                date_f = 0.0
            rows.append(
                {"ref": ref, "sha": sha, "session_key": session_key,
                 "ts": ts, "timestamp": date_f}
            )
        # 破平：committerdate 秒级相同时按 ts 后缀降序（make_ts 单调计数
        # 保证字符串序=写入序），"最新在前"语义对同秒密集写入成立
        rows.sort(
            key=lambda r: (r["timestamp"], r["ref"].rsplit("/", 1)[-1]),
            reverse=True,
        )
        return rows

    def delete_ref_by_pattern(self, ref: str) -> None:
        self.delete_ref(ref)

    make_ts = staticmethod(_make_ts)

    def last_commit_time(self, commit_sha: str) -> float:
        out = self._git("show", "-s", "--format=%ct", commit_sha)
        return float(out.decode("ascii").strip())
