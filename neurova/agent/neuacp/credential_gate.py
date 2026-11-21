# -*- coding: utf-8 -*-
"""凭据变更闸门（C4）：凭据轮换期间诚实拒绝新会话启动。

外部编码代理会话启动时会从凭据面按租户+agent 作用域取凭据并建立进程/会话。
凭据轮换（换 API key、换订阅账号）进行中若照常启动新会话，会以旧凭据建立
半生命周期会话——轮换完成后旧凭据失效，会话中途断链。故设闸门：

- 轮换开始：``beginCredentialRotation(agent_id)``（幂等）；
- 轮换期间：``assertNoRotation(agent_id)`` 抛 ``CredentialRotationInProgress``
  （诚实拒绝，带「稍后重试」指引），由 acp_member 会话启动路径调用；
- 轮换结束：``endCredentialRotation(agent_id)``（幂等）后放行。

线程安全：模块级 ``RLock`` + 活跃轮换集合，多 agent 按 agent_id 独立记账、
互不干扰。本闸门只做「拒绝/放行」判定，不存取凭据本身——凭据的存取仍走
凭据面单一事实源。闸门键为空（无法归属身份）时不拦截：拦不住无法识别的
目标，误拦所有无身份会话属另一更宽政策，不在此暗设。
"""
import threading
from typing import Set

#: 活跃凭据轮换的 agent_id 集合（进程内事实源；``_ROTATION_LOCK`` 保护）。
_ACTIVE_ROTATIONS: Set[str] = set()
_ROTATION_LOCK = threading.RLock()


class CredentialRotationInProgress(RuntimeError):
    """凭据轮换进行中——新会话启动被闸门诚实拒绝。"""

    def __init__(self, agentId: str) -> None:
        self.agent_id = str(agentId or "")
        super().__init__(
            f"agent `{self.agent_id}` 凭据轮换进行中，暂不能启动新会话；"
            "请稍后重试（轮换结束后自动放行）。"
        )


def _normalizeAgentId(agentId) -> str:
    """闸门键归一：转字符串去空白；空串表示无法归属身份（不拦截）。"""
    return str(agentId or "").strip()


def beginCredentialRotation(agentId) -> None:
    """标记 agent 凭据轮换开始（幂等：重复 begin 不报错、集合语义不重复计数）。"""
    key = _normalizeAgentId(agentId)
    if not key:
        return
    with _ROTATION_LOCK:
        _ACTIVE_ROTATIONS.add(key)


def endCredentialRotation(agentId) -> None:
    """标记 agent 凭据轮换结束（幂等：未在轮换/重复 end 均不报错）。"""
    key = _normalizeAgentId(agentId)
    if not key:
        return
    with _ROTATION_LOCK:
        _ACTIVE_ROTATIONS.discard(key)


def isRotationActive(agentId) -> bool:
    """查询 agent 是否处于凭据轮换中。"""
    key = _normalizeAgentId(agentId)
    if not key:
        return False
    with _ROTATION_LOCK:
        return key in _ACTIVE_ROTATIONS


def assertNoRotation(agentId) -> None:
    """旋转期间抛 ``CredentialRotationInProgress``（诚实拒绝 + 稍后重试指引）。

    由会话启动路径（acp_member.chat → executor.start 之前）调用；未在轮换
    则直接放行。
    """
    key = _normalizeAgentId(agentId)
    if not key:
        return
    with _ROTATION_LOCK:
        active = key in _ACTIVE_ROTATIONS
    if active:
        raise CredentialRotationInProgress(key)
