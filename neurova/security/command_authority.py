# -*- coding: utf-8 -*-
"""指挥资格单一判定落点（批 H1）＋ 判定台账（批 H2）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 H，
T6 已裁本轮动）："这一轮谁能指挥 agent"由两道门分治——渠道准入
（`channels/access_policy.chatAccessDecision`，消费点 channel_router）与治理
工具策略（`security/governance.evaluate_tool_call`，消费点 tool_executor）。
两门各自正确，但没有任何一处能完整回答"发送者 S 经渠道 C 指挥 agent A 执行
W 的资格"，审计面只有各自的半张。本模块是那个"一处"：

- **组合规则**：适用的门全判，任一拒绝即整体拒绝（短路——渠道拒绝时不再问
  治理门）；缺事实的门如实记 n-a（它的裁决由拥有该事实的消费点在更早的
  生命周期做出，这里不越权代答）。
- **fail-closed 口径**：有事实的门答不出按拒绝（access_policy 未知策略即拒、
  白名单空即拒的既有口径经此透传）。
- **判定台账**：每次判定落一行（谁/哪渠道/什么工具/哪道门/结果），读面
  可按发送者聚合——"谁在指挥"从此可查。

存储纪律：独立 SQLite（security 域自有，路径 callerPath＋env 覆盖）＋RLock＋
WAL；打开失败判定照常（台账是观测面不是主链），但必须出声。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS command_authority (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    sender_id TEXT NOT NULL DEFAULT '',
    channel_type TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    channel_gate INTEGER,
    policy_gate INTEGER,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    bound_user TEXT NOT NULL DEFAULT ''
)
"""


@dataclass
class AuthorityDecision:
    """一次指挥资格判定的结论。stage: channel/policy/pass/not_supported。"""

    allowed: bool
    stage: str
    reason: str = ""
    channel_gate: Optional[bool] = None
    policy_gate: Optional[bool] = None
    raw: Any = field(default=None, repr=False)


class CommandAuthorityLedger:
    """判定台账（追加写 + 过滤读）。"""

    def __init__(self, db_path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.execute(_SCHEMA)
        # H3：旧库补 bound_user 列（本表自有、量小，就地 ALTER 而非注册表迁移）
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(command_authority)")}
        if "bound_user" not in cols:
            with self._conn:
                self._conn.execute("ALTER TABLE command_authority ADD COLUMN bound_user TEXT NOT NULL DEFAULT ''")

    def recordJudgment(self, *, sender_id: str, channel_type: str, agent_id: str,
                       tool_name: str, channel_gate: Optional[bool],
                       policy_gate: Optional[bool], decision: str, reason: str = "",
                       bound_user: str = "") -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO command_authority (ts, sender_id, channel_type, agent_id,"
                " tool_name, channel_gate, policy_gate, decision, reason, bound_user)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), sender_id or "", channel_type or "", agent_id or "",
                 tool_name or "", channel_gate, policy_gate, decision, reason or "",
                 bound_user or ""),
            )
            return int(cur.lastrowid)

    def queryAuthorityLog(self, *, sender_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if sender_id:
            clauses.append("sender_id = ?")
            params.append(sender_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, sender_id, channel_type, agent_id, tool_name,"
                " channel_gate, policy_gate, decision, reason, bound_user"
                f" FROM command_authority {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
        keys = ("id", "ts", "sender_id", "channel_type", "agent_id", "tool_name",
                "channel_gate", "policy_gate", "decision", "reason", "bound_user")
        return [dict(zip(keys, r)) for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_ledgerInstance: Optional[CommandAuthorityLedger] = None
_ledgerLock = threading.RLock()


def getCommandAuthorityLedger() -> CommandAuthorityLedger:
    """台账单例（DCL＋RLock；读面/端点与本模块共用）。打开失败向上抛——
    判定主链按 fail-soft 处理并出声。"""
    global _ledgerInstance
    if _ledgerInstance is None:
        with _ledgerLock:
            if _ledgerInstance is None:
                import os

                from neurova.core.data_root import callerPath

                _ledgerInstance = CommandAuthorityLedger(
                    db_path=callerPath(
                        os.environ.get("NEUROVA_COMMAND_AUTHORITY_DB"),
                        "command_authority.db",
                    )
                )
    return _ledgerInstance


def resetCommandAuthorityLedger() -> None:
    """测试隔离钩子：弃掉单例（新数据根下重开）。"""
    global _ledgerInstance
    with _ledgerLock:
        if _ledgerInstance is not None:
            try:
                _ledgerInstance.close()
            except Exception:  # noqa: BLE001 - 关闭失败不阻断重置
                pass
        _ledgerInstance = None


def _resolveBoundUser(agentId: str, channelType: str, senderId: str) -> Optional[str]:
    """渠道发送者 → 平台账号（批 H3）：复用 identity_binding 既有单源反查，
    不建第二张映射表（教义第 6 条）。未绑定返回 None（调用方按缺省兜底记
    anonymous）；反查故障向上抛（调用方记空并出声，不劫持判定主链）。"""
    from neurova.channels.user_identity import UserIdentityManager

    return UserIdentityManager().resolveUserId(agentId, channelType, senderId)


def _judgePolicy(*, userId: str, toolName: str, params, scanAll: bool):
    """治理门（单一事实源：governance.evaluate_tool_call）。"""
    from neurova.security.governance import get_governance

    return get_governance().evaluate_tool_call(
        toolName, params, user_id=userId, scan_all=scanAll,
    )


def resolveCommandAuthority(
    *,
    senderId: str = "",
    channelType: str = "",
    chatType: str = "",
    channelCfg: Optional[Dict[str, Any]] = None,
    agentId: str = "default",
    userId: str = "",
    toolName: str = "",
    params: Optional[Dict[str, Any]] = None,
    scanAll: bool = False,
) -> AuthorityDecision:
    """指挥资格判定（唯一组合点）：适用的门全判，任一拒绝即拒，判定落台账。

    - 渠道门：给了 `channelCfg` 才判（消费点＝渠道路由准入）；
    - 治理门：给了 `toolName` 才判（消费点＝工具执行预检；raw verdict 原样
      透传，SANDBOX/审计语义由消费方承接）；
    - 两门事实都缺 → not_supported（诚实点名，不假装放行）。
    """
    channelGate: Optional[bool] = None
    policyGate: Optional[bool] = None
    decision = "pass"
    reason = ""
    verdict: Any = None

    if channelCfg is not None:
        from neurova.channels.access_policy import chatAccessDecision

        allowed, deny_reason = chatAccessDecision(chatType, channelCfg, senderId)
        channelGate = bool(allowed)
        if not allowed:
            decision = "deny_channel"
            reason = deny_reason

    if decision != "deny_channel" and toolName:
        verdict = _judgePolicy(userId=userId, toolName=toolName, params=params,
                               scanAll=scanAll)
        if verdict is None:
            policyGate = True  # 无可裁决内容 → 放行（既有语义）
        else:
            from neurova.security.governance import GovernanceDecision

            policyGate = verdict.decision != GovernanceDecision.DENY
            if not policyGate:
                decision = "deny_policy"
                reason = "; ".join(verdict.reasons)

    if channelGate is None and policyGate is None:
        decision = "not_supported"
        reason = "无渠道事实也无工具事实，判定无从做起"

    allowed = decision in ("pass",)

    # H3 归属：有渠道事实才反查"这是谁"——未绑定按缺省兜底纪律记 anonymous，
    # 反查故障记空（未知）并出声，不劫持判定主链
    boundUser = ""
    if channelCfg is not None and senderId:
        try:
            boundUser = _resolveBoundUser(agentId, channelType, senderId) or "anonymous"
        except Exception as e:  # noqa: BLE001 - 归属是观测增强，不是判定前提
            logger.warning("指挥归属反查失败（sender=%s）: %s", senderId, e)

    try:
        getCommandAuthorityLedger().recordJudgment(
            sender_id=senderId, channel_type=channelType, agent_id=agentId,
            tool_name=toolName, channel_gate=channelGate, policy_gate=policyGate,
            decision=decision, reason=reason, bound_user=boundUser,
        )
    except Exception as e:  # noqa: BLE001 - 台账是观测面不是主链，但必须出声
        logger.warning("指挥资格台账写入失败（判定不受影响）: %s", e)

    return AuthorityDecision(allowed=allowed, stage=decision, reason=reason,
                             channel_gate=channelGate, policy_gate=policyGate,
                             raw=verdict)
