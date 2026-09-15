# -*- coding: utf-8 -*-
"""技能流转记录 store（Wave H-W4，三层库流转的持久待办账）

三层库的跨库动作不是即时生效，而是"提案 → 确认/审批 → 应用"：
- agent→user（推送/升级）：需**用户确认**（agent 自主产物不得直写用户域）；
- user→public：走既有 submissions **管理员审批**（不在此 store，kind=update
  单型已支持升级）——本 store 只承载"人确认"型流转；
- public→user / public→agent（公共库升级推送）：需**用户确认**（升级副本
  影响其可见行为，接受权在人）。

形态对齐 market_submissions：单 JSON 文件 + 原子写 + pending/accepted/
rejected 状态机 + notify 收件人 = target_owner 的账号键。
落盘 data/skill_transfers.json（测试 env：NEUROVA_SKILL_TRANSFERS）。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

# transfer_type 常量（三链路收敛为两类确认型 + 直连型）
TT_AGENT_TO_USER = "agent_to_user"        # 需求 3/4：agent 私库 → 用户私库（用户确认）
TT_PUBLIC_TO_USER = "public_to_user"      # 需求 5：公共库升级 → 用户私库副本（用户确认）
TT_PUBLIC_TO_AGENT = "public_to_agent"    # 需求 5：公共库升级 → agent 私库副本（用户确认，owner 代管）


def _transfers_path() -> Path:
    return Path(os.environ.get("NEUROVA_SKILL_TRANSFERS", str(Path("data") / "skill_transfers.json")))


class SkillTransferStore:
    """流转待办账（线程安全，JSON 原子落盘）。"""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _transfers_path()
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.warning("skill_transfers 读取失败（按空处理）: %s", e)
        return {}

    def _save(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def create(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """登记一条流转提案（幂等键可选 transfer_key——同源同目标同类型去重）。"""
        with self._lock:
            data = self._load()
            tkey = str(fields.get("transfer_key") or "")
            if tkey:
                for row in data.values():
                    if row.get("transfer_key") == tkey and row.get("status") == STATUS_PENDING:
                        return dict(row)  # 同键 pending 复用（防每轮重复弹卡）
            tid = f"tr_{uuid.uuid4().hex[:12]}"
            now = time.time()
            entry = {
                "transfer_id": tid,
                "transfer_type": str(fields.get("transfer_type") or ""),
                "skill_id": str(fields.get("skill_id") or ""),
                "src_pool": str(fields.get("src_pool") or ""),
                "src_owner": str(fields.get("src_owner") or ""),
                "dst_pool": str(fields.get("dst_pool") or ""),
                "dst_owner": str(fields.get("dst_owner") or ""),
                # 确认责任人（库归属人未必是能登录的账号：public→agent 的确认
                # 权在 agent 属主）；缺省=dst_owner。
                "confirm_owner": str(fields.get("confirm_owner") or fields.get("dst_owner") or ""),
                "kind": str(fields.get("kind") or "initial"),  # initial|upgrade
                "version": str(fields.get("version") or ""),
                "name": str(fields.get("name") or ""),
                "transfer_key": tkey,
                "status": STATUS_PENDING,
                "decided_by": "",
                "decided_at": None,
                "note": str(fields.get("note") or ""),
                "created_at": now,
                "updated_at": now,
            }
            data[tid] = entry
            self._save(data)
            return dict(entry)

    def get(self, transfer_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._load().get(transfer_id) or {}) or None

    def list(self, status: Optional[str] = None, confirm_owner: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = list(self._load().values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if confirm_owner is not None:
            rows = [r for r in rows if str(r.get("confirm_owner") or "") == confirm_owner]
        rows.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
        return rows

    def set_status(self, transfer_id: str, status: str, decided_by: str = "", note: str = "") -> Optional[Dict[str, Any]]:
        if status not in (STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED):
            raise ValueError(f"非法流转状态: {status}")
        with self._lock:
            data = self._load()
            row = data.get(transfer_id)
            if not row:
                return None
            if row.get("status") != STATUS_PENDING:
                raise ValueError("only pending transfers can be decided")
            row["status"] = status
            row["decided_by"] = str(decided_by or "")
            row["decided_at"] = time.time()
            if note:
                row["note"] = str(note)
            row["updated_at"] = time.time()
            self._save(data)
            return dict(row)

    def delete(self, transfer_id: str) -> bool:
        with self._lock:
            data = self._load()
            if transfer_id not in data:
                return False
            del data[transfer_id]
            self._save(data)
            return True


_store_singleton: Optional[SkillTransferStore] = None
_store_lock = threading.RLock()


def get_skill_transfer_store() -> SkillTransferStore:
    global _store_singleton
    with _store_lock:
        if _store_singleton is None:
            _store_singleton = SkillTransferStore()
        return _store_singleton


def reset_skill_transfer_store() -> None:
    """测试隔离：重置单例（下次读取重建，路径按 env 现值解析）。"""
    global _store_singleton
    with _store_lock:
        _store_singleton = None
