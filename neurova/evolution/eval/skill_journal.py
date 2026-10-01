"""技能正文 git 日志仓 — 候选即 commit（P2-11）。

per-agent 独立 bare 仓（data/ 不受主仓跟踪，不能依赖主仓；隔离也防误推）。
decide approve 一 proposal 一 commit：blob=批准后正文全量快照，
message=proposal_id + 证据摘要；主分支头=incumbent，回滚=按父提交正文回写。

实现走本地 plumbing（init --bare / hash-object / ls-tree / mktree /
commit-tree / update-ref），无网络、不碰任何工作树、不建远端。
git 缺失或失败 → append 返回 None、history 返回 []（诚实降级，
审批主链不受损——降级是文档化的显式契约，不是静默吞错）。

与 skill.config["revisions"] 双轨期：revisions 管 config 级快照（既有，
不动），journal 管正文级可追溯链。
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Optional

from neurova.core.git_runner import commit_message, run_git
from neurova.core.logger import get_logger
from neurova.evolution.eval.history_ledger import sanitize_key

logger = get_logger(__name__)

_BRANCH = "refs/heads/main"
_IDENTITY = {
    "GIT_AUTHOR_NAME": "neurova-evolution",
    "GIT_AUTHOR_EMAIL": "evolution@neurova.local",
    "GIT_COMMITTER_NAME": "neurova-evolution",
    "GIT_COMMITTER_EMAIL": "evolution@neurova.local",
}
_TIMEOUT = 30


def _blob_path(skill_id: str) -> str:
    # 仓库根单层文件（mktree 不接受带斜杠路径）：键即文件名，sanitize 防逃逸
    return f"{sanitize_key(skill_id)}.txt"


class SkillJournal:
    """per-agent 技能正文日志仓（线程安全：appends 串行化）。"""

    def __init__(self, journal_dir: Path | str):
        self._dir = Path(journal_dir)
        self._lock = threading.Lock()

    # ── git 基础设施 ──

    def _git(self, *args: str, stdin: Optional[str] = None) -> subprocess.CompletedProcess:
        """transport 委托 neurova.core.git_runner（Windows 三坑的单源防线：
        二进制 transport / str stdin utf-8 编码）。这里只做 str 输出适配。"""
        proc = run_git(*args, git_dir=str(self._dir), stdin=stdin, timeout=_TIMEOUT,
                       env_extra=_IDENTITY)
        return subprocess.CompletedProcess(
            proc.args, proc.returncode,
            stdout=proc.stdout.decode("utf-8", "replace"),
            stderr=proc.stderr.decode("utf-8", "replace"),
        )

    def _ensure_repo(self) -> bool:
        if (self._dir / "HEAD").exists():
            return True
        proc = self._git("init", "--bare", "--quiet", str(self._dir))
        return proc.returncode == 0

    # ── 写入面 ──

    def append(self, *, skill_id: str, before: str, after: str,
               proposal_id: str, evidence: dict) -> Optional[str]:
        """一次批准一条 commit，返回 commit hash；失败返回 None。"""
        if not skill_id or not proposal_id:
            return None
        with self._lock:
            try:
                if not self._ensure_repo():
                    logger.debug("日志仓初始化失败: %s", self._dir)
                    return None
                blob = self._git("hash-object", "-w", "--stdin", stdin=after)
                if blob.returncode != 0:
                    logger.debug("blob 写入失败: %s", blob.stderr[:120])
                    return None
                parent_rev = self._git("rev-parse", "--verify", "--quiet", _BRANCH)
                parent = parent_rev.stdout.strip() if parent_rev.returncode == 0 else ""
                # 全量树：既有条目（ls-tree 输出即 mktree 输入格式）替换本技能条目
                if parent:
                    ls = self._git("ls-tree", parent)
                    old_lines = ls.stdout.splitlines() if ls.returncode == 0 else []
                else:
                    old_lines = []
                entry = f"100644 blob {blob.stdout.strip()}\t{_blob_path(skill_id)}"
                tree_lines = [ln for ln in old_lines
                              if not ln.endswith(f"\t{_blob_path(skill_id)}")]
                tree_lines.append(entry)
                tree = self._git("mktree", stdin="\n".join(tree_lines) + "\n")
                if tree.returncode != 0:
                    logger.debug("mktree 失败: %s", tree.stderr[:120])
                    return None
                # subject 与 body 之间必须空行——git 的 %s 会把首个空行前的
                # 所有行折叠成一行 subject（无空行则 body 并入 subject）
                # message 走 stdin + subject/body 空行规范（坑 2/3 的单源
                # 防线见 neurova.core.git_runner）
                cmd = ["commit-tree", tree.stdout.strip()]
                if parent:
                    cmd += ["-p", parent]
                commit = self._git(*cmd, stdin=commit_message(
                    f"evolution: {skill_id} {proposal_id}",
                    json.dumps(evidence or {}, ensure_ascii=False)))
                if commit.returncode != 0:
                    logger.debug("commit-tree 失败: %s", commit.stderr[:120])
                    return None
                sha = commit.stdout.strip()
                update = self._git("update-ref", _BRANCH, sha)
                if update.returncode != 0:
                    logger.debug("update-ref 失败: %s", update.stderr[:120])
                    return None
                logger.info("技能正文已入日志仓: %s %s -> %s", skill_id, proposal_id, sha[:10])
                return sha
            except Exception as e:  # noqa: BLE001 - git 缺失/故障诚实降级（文档化契约）
                logger.debug("技能日志仓写入降级: %s", e)
                return None

    # ── 读取面 ──

    def history(self, skill_id: str, limit: int = 20) -> list[dict]:
        """该技能的正文变更链（新→旧）：[{commit, ts, proposal_id, content, evidence}]。"""
        if not skill_id or not (self._dir / "HEAD").exists():
            return []
        try:
            log = self._git(
                "log", _BRANCH, f"-n{max(1, int(limit))}",
                "--format=%H%x1f%aI%x1f%s%x1f%b%x1e",
                "--", _blob_path(skill_id),
            )
            if log.returncode != 0 or not log.stdout.strip():
                return []
            items: list[dict] = []
            for chunk in log.stdout.split("\x1e"):
                parts = chunk.strip("\n").split("\x1f")
                if len(parts) < 4 or not parts[0].strip():
                    continue
                sha, ts, subject, body = parts[0], parts[1], parts[2], parts[3]
                pid = subject.split()[-1] if subject.split() else ""
                try:
                    evidence = json.loads(body) if body.strip() else {}
                except json.JSONDecodeError:
                    evidence = {}
                content = self._git("cat-file", "blob", f"{sha}:{_blob_path(skill_id)}")
                items.append({
                    "commit": sha, "ts": ts, "proposal_id": pid,
                    "evidence": evidence,
                    "content": content.stdout if content.returncode == 0 else "",
                })
            return items
        except Exception as e:  # noqa: BLE001 - 读取面同样诚实降级
            logger.debug("技能日志仓读取降级: %s", e)
            return []
