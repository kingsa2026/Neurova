"""
检查点服务门面（P1-5）

范围：会话 JSON + 知识库文件。ref 规范 {auto,snap,pre-restore}/{session_key}/{ts}。
- 恢复语义：restore 前**自动**把当前最新内容留档 pre-restore ref（可回退本次恢复）
- 自动快照防抖：同 session_key 距上次 auto 快照 < debounce_seconds 时跳过
- GC：keep_count（每 session 每 kind 保留数）+ keep_days（时间窗）双维度
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.checkpoints.repository import CheckpointRepository, make_ts
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 会话 JSON 在 tree 中的固定文件名
_SESSION_ENTRY = "_session.json"


class CheckpointService:
    """单 Agent 检查点门面（bare repo 持久化）。"""

    def __init__(
        self,
        agent_id: str,
        base_dir: str = "data/checkpoints",
        debounce_seconds: float = 300.0,
    ):
        self.agent_id = agent_id
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        base = Path(base_dir)
        base.mkdir(parents=True, exist_ok=True)
        self.repo = CheckpointRepository(str(base / f"{agent_id}.git"))
        self._last_auto_at: Dict[str, float] = {}

    # ── 快照 ──

    def snapshot(
        self,
        kind: str,
        session_key: str,
        session_data: Any,
        kb_files: Optional[Dict[str, str]],
        message: str = "",
    ) -> str:
        """写入快照并返回 ref。kind: auto | snap。"""
        kb_files = kb_files or {}
        # 索引映射：tree 键用安全名（f0/f1...），原始相对路径记录在 _index.json
        # （git flat tree 不允许 '/'，且原路径可能含任意字符）
        index = {"session": _SESSION_ENTRY, "kb": []}
        payload: Dict[str, bytes] = {
            _SESSION_ENTRY: json.dumps(
                session_data, ensure_ascii=False, default=str
            ).encode("utf-8")
        }
        for i, (path, content) in enumerate(sorted(kb_files.items())):
            key = f"f{i}"
            index["kb"].append({"key": key, "path": path})
            payload[key] = (
                content.encode("utf-8") if isinstance(content, str) else content
            )
        payload["_index.json"] = json.dumps(index, ensure_ascii=False).encode("utf-8")

        tree = self.repo.write_tree_from_files(payload)
        parent = self.repo.rev_parse(f"refs/{kind}/{session_key}")
        ts = make_ts()
        commit = self.repo.commit_tree(
            tree, message or f"{kind}: {session_key} @ {ts}", parent=parent
        )
        ref = f"refs/{kind}/{session_key}/{ts}"
        self.repo.update_ref(ref, commit)
        logger.info("检查点快照 %s (%s)", ref, message or kind)
        return ref

    def snapshot_auto(self, session_key: str, session_data: Any, kb_files: Optional[Dict[str, str]] = None) -> str:
        """自动快照（带防抖：debounce_seconds 内同 session 跳过，返回已存在的最新 ref）。"""
        now = time.monotonic()
        last = self._last_auto_at.get(session_key)
        if (
            self.debounce_seconds > 0
            and last is not None
            and now - last < self.debounce_seconds
        ):
            refs = self.repo.list_refs(f"auto/{session_key}")
            if refs:
                return refs[0]["ref"]
        ref = self.snapshot("auto", session_key, session_data, kb_files)
        self._last_auto_at[session_key] = now
        return ref

    def snapshot_manual(self, session_key: str, session_data: Any, kb_files: Optional[Dict[str, str]] = None) -> str:
        """手动快照（不受防抖约束）。"""
        return self.snapshot("snap", session_key, session_data, kb_files)

    # ── 读取 ──

    def _read_ref(self, ref: str) -> Dict[str, bytes]:
        sha = self.repo.rev_parse(ref)
        if sha is None:
            raise ValueError(f"检查点不存在: {ref}")
        tree_files = self.repo.list_tree(sha)
        return {
            path: self.repo.cat_blob(blob).decode("utf-8")
            for path, blob in tree_files.items()
        }

    def restore_snapshot(self, ref: str) -> Dict[str, Any]:
        """恢复：先自动留档 pre-restore（当前最新内容），再返回目标内容。

        Returns:
            {"session_json": str, "kb_files": {path: str}, "pre_restore_ref": str|None}
        """
        # 当前最新 = 同 session 的 auto 最新（存在才留档）
        session_key = ref.split("/")[2]
        pre_ref: Optional[str] = None
        current = self.repo.list_refs(f"auto/{session_key}")
        if current:
            kind, _, ts = ("pre-restore", session_key, make_ts())
            pre_ref = f"refs/{kind}/{session_key}/{ts}"
            src_sha = current[0]["sha"]
            self.repo.update_ref(pre_ref, src_sha)
            logger.info("恢复前留档 %s", pre_ref)

        content = self._read_ref(ref)
        index = json.loads(content.get("_index.json", "{}"))
        kb_files = {
            item["path"]: content.get(item["key"], "")
            for item in index.get("kb", [])
        }
        return {
            "session_json": content.get(_SESSION_ENTRY, "{}"),
            "kb_files": kb_files,
            "pre_restore_ref": pre_ref,
        }

    def list_snapshots(
        self,
        session_key: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """列出快照（时间降序）。kind 过滤（auto/snap/pre-restore）。"""
        kinds = [kind] if kind else ["auto", "snap", "pre-restore"]
        out: List[Dict[str, Any]] = []
        for k in kinds:
            prefix = f"{k}/{session_key}" if session_key else k
            for row in self.repo.list_refs(prefix):
                out.append(
                    {
                        "ref": row["ref"],
                        "kind": k,
                        "session_key": row["session_key"],
                        # git committerdate（真时间序，同秒随机后缀不受影响）
                        "timestamp": row.get("timestamp", 0.0),
                        "sha": row["sha"],
                    }
                )
        # 破平：committerdate 秒级相同时按 ts 后缀降序（ts 含单调递增的
        # 进程内随机十六进制不保证序，改为捕获顺序不可靠——用 ref 中的
        # 完整 ts 字符串做次级键，同秒写入由 git ref 更新顺序天然单调）
        out.sort(
            key=lambda r: (r["timestamp"], r["ref"].rsplit("/", 1)[-1]),
            reverse=True,
        )
        return out

    # ── 事务化恢复（P2-c） ──

    def restore_with_rollback(self, ref: str, apply_fn: Any) -> Dict[str, Any]:
        """事务化恢复：apply_fn 失败 → 自动用 pre-restore 内容重放（回滚）。

        语义：
        1. restore_snapshot(ref) 取目标内容并自动留档 pre-restore
        2. apply_fn(payload) 执行写回（会话/文件恢复动作由调用方注入）
        3. apply_fn 抛异常 → 用 pre-restore 快照内容再次调用 apply_fn 回滚；
           回滚仍失败则抛 RuntimeError（提示手工介入，携带两个错误）

        Args:
            ref: 目标快照 ref
            apply_fn: callable(payload)——payload 形如 restore_snapshot 返回值

        Returns:
            成功时返回目标内容 payload
        """
        payload = self.restore_snapshot(ref)
        try:
            apply_fn(payload)
            return payload
        except Exception as apply_err:
            pre_ref = payload.get("pre_restore_ref")
            if not pre_ref:
                logger.error("恢复失败且无 pre-restore 留档，无法回滚: %s", apply_err)
                raise RuntimeError(
                    f"恢复失败且无回滚点: {apply_err}"
                ) from apply_err
            try:
                rollback_payload = self._read_ref_payload(pre_ref)
                apply_fn(rollback_payload)
                logger.warning(
                    "恢复失败已回滚到 pre-restore（ref=%s）: %s", pre_ref, apply_err
                )
                raise RuntimeError(
                    f"恢复失败（已回滚到恢复前状态）: {apply_err}"
                ) from apply_err
            except RuntimeError:
                raise
            except Exception as rollback_err:
                raise RuntimeError(
                    f"恢复失败且回滚也失败——需手工介入: "
                    f"apply_err={apply_err}; rollback_err={rollback_err}"
                ) from rollback_err

    def _read_ref_payload(self, ref: str) -> Dict[str, Any]:
        """读取 ref 内容为 restore_snapshot 同形 payload（不触发留档）。"""
        content = self._read_ref(ref)
        index = json.loads(content.get("_index.json", "{}"))
        kb_files = {
            item["path"]: content.get(item["key"], "")
            for item in index.get("kb", [])
        }
        return {
            "session_json": content.get(_SESSION_ENTRY, "{}"),
            "kb_files": kb_files,
            "pre_restore_ref": None,
        }

    def diff_snapshots(self, ref_a: str, ref_b: str) -> Dict[str, Any]:
        """差异化对比：两个快照间的文件变化（P2-c 只写 delta 的依据）。

        Returns:
            {"changed": [path...], "unchanged": [path...], "added": [...], "removed": [...]}
        """
        a = self._read_ref_payload(ref_a)
        b = self._read_ref_payload(ref_b)
        a_files = a["kb_files"]
        b_files = b["kb_files"]
        changed, unchanged = [], []
        for path in sorted(set(a_files) | set(b_files)):
            if path not in b_files:
                continue  # removed
            if path not in a_files:
                continue  # added
            (unchanged if a_files[path] == b_files[path] else changed).append(path)
        added = sorted(set(b_files) - set(a_files))
        removed = sorted(set(a_files) - set(b_files))
        return {"changed": changed, "unchanged": unchanged, "added": added, "removed": removed}

    # ── GC ──

    def gc(self, keep_count: int = 10, keep_days: int = 30) -> int:
        """双维度回收：每 (kind, session_key) 保留最近 keep_count 个；
        且丢弃 committerdate 早于 keep_days 的快照。返回删除数。"""
        cutoff = time.time() - keep_days * 86400
        by_group: Dict[tuple, List[Dict[str, Any]]] = {}
        for snap in self.list_snapshots():
            key = (snap["kind"], snap["session_key"])
            by_group.setdefault(key, []).append(snap)

        removed = 0
        for (kind, session_key), snaps in by_group.items():
            keep = 0
            for snap in snaps:  # 已按时间降序
                expired = snap["timestamp"] < cutoff
                if expired or keep >= keep_count:
                    self.repo.delete_ref(snap["ref"])
                    removed += 1
                else:
                    keep += 1
        if removed:
            logger.info("检查点 GC 清理 %d 个快照（keep_count=%d keep_days=%d）",
                        removed, keep_count, keep_days)
        return removed
