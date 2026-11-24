"""
检查点服务门面（P1-5）

范围：会话 JSON + 知识库文件。ref 规范 {auto,snap,pre-restore}/{session_key}/{ts}。
- 恢复语义：restore 前**自动**把当前最新内容留档 pre-restore ref（可回退本次恢复）
- 自动快照防抖：同 session_key 距上次 auto 快照 < debounce_seconds 时跳过
- GC：keep_count（每 session 每 kind 保留数）+ keep_days（时间窗）双维度
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from neurova.checkpoints.repository import CheckpointRepository, make_ts
from neurova.core.data_root import callerPath
from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 会话 JSON 在 tree 中的固定文件名
_SESSION_ENTRY = "_session.json"


# ── scope 化检查点（任务卡 B3，对齐 T3 Code 编排检查点）──

# scope 检查点 ref 前缀：refs/neurova/checkpoints/<scope 摘要>/ordinal/<N>
SCOPE_REF_PREFIX = "refs/neurova/checkpoints"
# 每 scope 默认保留的 ordinal 数（pruneScope 缺省）
DEFAULT_SCOPE_KEEP = 20


class CheckpointNotFoundError(Exception):
    """目标检查点 ref 不存在（restore/rollback 显式失败，绝不静默回退）。"""


def _scopeDigest(scope_id: str) -> str:
    """scope_id → 32 位十六进制摘要（sha256 前 32 hex；ref 段安全字符集）。"""
    return hashlib.sha256(scope_id.encode("utf-8")).hexdigest()[:32]


def scopeRefFor(scope_id: str, ordinal: int) -> str:
    """scope+ordinal 的确定性 ref 名。

    同 scope 同 ordinal 恒得同一 ref（重捕获即覆盖同一 ref）；
    不同 scope 摘要不同，ref 空间天然隔离。
    """
    return f"{SCOPE_REF_PREFIX}/{_scopeDigest(scope_id)}/ordinal/{int(ordinal)}"


class CheckpointService:
    """单 Agent 检查点门面（bare repo 持久化）。"""

    def __init__(
        self,
        agent_id: str,
        base_dir: str = "",
        debounce_seconds: float = 300.0,
    ):
        self.agent_id = agent_id
        self.debounce_seconds = max(0.0, float(debounce_seconds))
        # 缺省落点：`data/<agent_id>/checkpoints.git`。显式 base_dir 仍按
        # `<base_dir>/<agent_id>.git` 解释（测试与多实例部署注入用）。
        if base_dir:
            repo_path = callerPath(base_dir) / f"{agent_id}.git"
        else:
            from neurova.core.agent_workspaces import get_agent_checkpoints_dir

            repo_path = get_agent_checkpoints_dir(agent_id)
        # 建目录门（2026-11-24 审计 RISK 7）：生产数据根下未知 agent 不长
        # checkpoints.git/（admin 面的 404 路径此前也会把目录建出来）；
        # 显式 base_dir 注入与隔离根（测试/多实例）不设限。
        from neurova.core.agent_workspaces import agentRootIsIsolated, is_registered_agent_id

        if (repo_path.parent.exists() or base_dir or is_registered_agent_id(agent_id)
                or agentRootIsIsolated()):
            repo_path.parent.mkdir(parents=True, exist_ok=True)
        self.repo = CheckpointRepository(str(repo_path))
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

    # ── scope 化检查点（B3）──

    @staticmethod
    def _scopeEncodePayload(payload: Dict[str, bytes]) -> Dict[str, bytes]:
        """{文件名: bytes} → flat tree 键值。

        tree 键不含 '/'（git flat tree 限制），原文件名（可含路径分隔符）
        记入 _index.json，恢复时按索引还原——与 snapshot() 的 f{i} 映射同构。
        """
        index = {"files": []}
        tree_files: Dict[str, bytes] = {}
        for i, (path, content) in enumerate(sorted(payload.items())):
            key = f"f{i}"
            index["files"].append({"key": key, "path": path})
            tree_files[key] = (
                content if isinstance(content, bytes) else str(content).encode("utf-8")
            )
        tree_files["_index.json"] = json.dumps(index, ensure_ascii=False).encode("utf-8")
        return tree_files

    def _scopeDecodePayload(self, commit_sha: str) -> Dict[str, bytes]:
        """commit → {文件名: bytes}（bytes 原样返回，不做 str 强转）。"""
        tree_files = self.repo.list_tree(commit_sha)
        index_blob = tree_files.get("_index.json")
        if index_blob is None:
            # 无索引（直存形态）：tree 键即文件名
            return {path: self.repo.cat_blob(b) for path, b in tree_files.items()}
        index = json.loads(self.repo.cat_blob(index_blob).decode("utf-8"))
        return {
            item["path"]: self.repo.cat_blob(tree_files[item["key"]])
            for item in index.get("files", [])
            if item["key"] in tree_files
        }

    def captureScope(self, scope_id: str, ordinal: int, payload: Dict[str, bytes],
                     message: str = "") -> str:
        """按 scope+ordinal 写检查点，返回 ref。payload 为 {文件名: bytes}。

        同 scope 同 ordinal 重捕获：更新同一 ref 指向新 commit
        （旧 commit 成垃圾由 gc 管）。
        """
        ref = scopeRefFor(scope_id, ordinal)
        tree = self.repo.write_tree_from_files(self._scopeEncodePayload(payload))
        parent = self.repo.rev_parse(ref)
        commit = self.repo.commit_tree(
            tree, message or f"scope: {scope_id} ordinal={ordinal}", parent=parent
        )
        self.repo.updateRefRaw(ref, commit)
        logger.info("scope 检查点 %s (ordinal=%s)", ref, ordinal)
        return ref

    def restoreScope(self, scope_id: str, ordinal: int) -> Dict[str, bytes]:
        """按 ref 恢复，返回 {文件名: bytes}。

        ref 不存在 → CheckpointNotFoundError（绝不静默回退 HEAD/空）。
        """
        ref = scopeRefFor(scope_id, ordinal)
        sha = self.repo.rev_parse(ref)
        if sha is None:
            raise CheckpointNotFoundError(f"scope 检查点不存在: {ref}")
        return self._scopeDecodePayload(sha)

    def listScopeOrdinals(self, scope_id: str) -> List[int]:
        """该 scope 现存 ordinal 升序列表（从 ref 名解析）。"""
        rows = self.repo.list_refs(f"neurova/checkpoints/{_scopeDigest(scope_id)}")
        ordinals = set()
        for row in rows:
            if row.get("session_key") != "ordinal":
                continue
            try:
                ordinals.add(int(row["ts"]))
            except (TypeError, ValueError):
                continue
        return sorted(ordinals)

    def pruneScope(self, scope_id: str, keep: int = DEFAULT_SCOPE_KEEP) -> int:
        """每 scope 只保留最近 keep 个 ordinal（删除更老 ref），返回删除数。"""
        keep = int(keep)
        ordinals = self.listScopeOrdinals(scope_id)
        stale = list(ordinals) if keep <= 0 else ordinals[: max(0, len(ordinals) - keep)]
        for o in stale:
            self.repo.delete_ref(scopeRefFor(scope_id, o))
        if stale:
            logger.info("scope 检查点修剪 %s：删除 %d 个旧 ordinal", scope_id, len(stale))
        return len(stale)

    def rollbackScope(self, scope_id: str, target_ordinal: int, apply_fn=None, *,
                      isolation_check=None) -> Dict[str, Any]:
        """回滚到 target_ordinal。

        - isolation_check: Callable[[], Optional[str]]——返回非空字符串=存在
          共享冲突（如其他活跃 run 共享同一工作区）→ 只做会话级回退：不恢复
          文件、不删 ref，返回 {"files_restored": False, "conversation_only":
          True, "reason": <该字符串>}，会话级回退动作由调用方执行。
        - 无冲突：restoreScope 恢复文件；apply_fn 非 None 时调 apply_fn(payload)
          （异常上抛，由调用方决定回滚事务）；然后删除 target 之后
          （>target_ordinal）的 stale ordinal refs。返回 {"files_restored": True,
          "conversation_only": False, "restored_ordinal": N, "pruned": 删除数}。
        - target ordinal 不存在 → CheckpointNotFoundError。
        """
        ref = scopeRefFor(scope_id, target_ordinal)
        if self.repo.rev_parse(ref) is None:
            raise CheckpointNotFoundError(f"scope 检查点不存在: {ref}")
        if isolation_check is not None:
            reason = isolation_check()
            if reason:
                logger.warning(
                    "scope 回滚受隔离约束，仅会话级回退（scope=%s target=%s）: %s",
                    scope_id, target_ordinal, reason,
                )
                return {
                    "files_restored": False,
                    "conversation_only": True,
                    "reason": reason,
                }
        payload = self.restoreScope(scope_id, target_ordinal)
        if apply_fn is not None:
            apply_fn(payload)
        stale = [o for o in self.listScopeOrdinals(scope_id) if o > target_ordinal]
        for o in stale:
            self.repo.delete_ref(scopeRefFor(scope_id, o))
        if stale:
            logger.info("scope 回滚清理 %d 个 stale ordinal（scope=%s target=%s）",
                        len(stale), scope_id, target_ordinal)
        return {
            "files_restored": True,
            "conversation_only": False,
            "restored_ordinal": int(target_ordinal),
            "pruned": len(stale),
        }
