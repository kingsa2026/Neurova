# -*- coding: utf-8 -*-
"""NeuacpMemberAdapter：把外部编码代理包成 swarm 成员。

鸭子面（设计文档 §4.2，与 swarm._run_member 的调用约定严格对齐）：
- ``async chat(user_input, *, stream, session_id, metadata) -> {"text": str}``
  恒以 stream=True 被调用；必须消费 ``metadata["event_emitter"]`` 流式产出；
  失败抛异常或返回 "[LLM Error] ..." 前缀文本。
- ``config.name`` → 事件/台账/审批卡里的 agent_name。
- ``current_session_id`` = run.member_session_id。
- ``llm_client.chat`` → 验收/评审判定通道（D2 裁定提供；由装配方注入
  本仓 provider 通道）。
- ``permission_asker(action, reason, context) -> {"approved": bool}``：
  同步裁决钩子，由 B1 桥接审批链；未注入时一律 deny（fail-closed）。
"""
from types import SimpleNamespace
from typing import Any, Callable, Optional

from neurova.agent.neuacp.executor import NeuacpSessionContext


class NeuacpMemberAdapter:
    """chat 兼容适配器：swarm 名册 executor 成员经此驱动外部执行体。"""

    def __init__(
        self,
        executor,
        *,
        name: str,
        cwd: str = "",
        permission_asker: Optional[Callable] = None,
        verify_channel: Optional[Any] = None,
        prompt_timeout: Optional[float] = None,
    ) -> None:
        self._executor = executor
        self._cwd = cwd or ""
        self._permission_asker = permission_asker
        self._prompt_timeout = prompt_timeout
        self.config = SimpleNamespace(name=name)
        self.llm_client = verify_channel
        self.current_session_id: Optional[str] = None

    async def chat(self, user_input: str, *, stream: bool = True, session_id: Optional[str] = None, metadata: Optional[dict] = None, **_ignored) -> dict:
        # swarm._run_member 的签名约束（swarm.py:2256-2259）：不接受 temperature/max_tokens。
        emitter = (metadata or {}).get("event_emitter")
        if session_id:
            self.current_session_id = session_id
        context = NeuacpSessionContext(
            member_session_id=self.current_session_id or "",
            task_text=user_input,
            cwd=self._cwd,
            permission_mode="chain",
            metadata=dict(metadata or {}),
        )
        await self._executor.start(context)
        result = await self._executor.prompt(user_input, emitter, self._permission_asker)
        return {"text": result.text}

    async def cancel(self) -> None:
        await self._executor.cancel()

    async def close(self) -> None:
        await self._executor.close()
