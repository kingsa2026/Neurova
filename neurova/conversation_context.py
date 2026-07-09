"""
ConversationContext — agent.conversation_history 的 deep module 封装

将裸 list[Dict] 升级为带 invariant 的类：
- role 校验（user/assistant/system）
- 长度限制（max_messages，默认 100，与 mem_core.py:676 现有逻辑一致）
- 线程安全（threading.RLock）
- 只读快照（to_list 深拷贝）

兼容性：
- Agent.conversation_history 保持 list 兼容（通过 property 代理 to_list()）
- MemCore.update_history 内部改用 ConversationContext.append

候选 #6 落地。设计参考 ADR-0008（SessionRepository 统一接口）的 deep module 模式。
"""
from __future__ import annotations

import copy
from threading import RLock
from typing import Any, Dict, Iterator, List, Optional


VALID_ROLES = frozenset({"user", "assistant", "system"})


class InvalidRoleError(ValueError):
    """role 不在 user/assistant/system 中时抛出。"""


class ConversationContext:
    """对话上下文 deep module。

    封装 LLM 对话历史，集中 invariant：
    - role 校验：append/extend 拒绝非法 role
    - 长度限制：append 后自动 trim 到 max_messages
    - 线程安全：所有读写通过 RLock 保护
    - 只读快照：to_list() 深拷贝，外部修改不影响内部状态

    用法：
        ctx = ConversationContext(max_messages=100)
        ctx.append("user", "你好")
        ctx.append("assistant", "你好，有什么可以帮你？")
        messages = ctx.to_list()  # [{"role": "user", ...}, {"role": "assistant", ...}]
    """

    def __init__(self, max_messages: int = 100):
        self._max_messages = max_messages
        self._messages: List[Dict[str, Any]] = []
        self._lock = RLock()

    # ── 属性 ──────────────────────────────────────────────

    @property
    def max_messages(self) -> int:
        """最大消息数。"""
        return self._max_messages

    @max_messages.setter
    def max_messages(self, value: int) -> None:
        with self._lock:
            self._max_messages = value
            self._trim_locked(value)

    # ── 核心方法 ──────────────────────────────────────────

    def append(
        self,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """追加单条消息。

        Args:
            role: 必须是 user/assistant/system 之一
            content: 消息内容
            metadata: 可选元数据（如 timestamp/source）

        Raises:
            InvalidRoleError: role 非法时
        """
        if role not in VALID_ROLES:
            raise InvalidRoleError(
                f"role 必须是 {sorted(VALID_ROLES)} 之一，实际 {role!r}"
            )

        msg: Dict[str, Any] = {"role": role, "content": content}
        if metadata:
            msg["metadata"] = metadata

        with self._lock:
            self._messages.append(msg)
            self._trim_locked(self._max_messages)

    def extend(self, messages: List[Dict[str, Any]]) -> None:
        """批量追加消息。

        非法 role 的消息会被跳过（不抛异常），便于从外部数据源导入。

        Args:
            messages: 消息列表，每条至少含 role/content
        """
        with self._lock:
            for msg in messages:
                role = msg.get("role", "")
                if role not in VALID_ROLES:
                    continue
                new_msg: Dict[str, Any] = {
                    "role": role,
                    "content": msg.get("content", ""),
                }
                # 透传其他字段（timestamp/metadata 等）
                for k, v in msg.items():
                    if k not in ("role", "content"):
                        new_msg[k] = v
                self._messages.append(new_msg)
            self._trim_locked(self._max_messages)

    def to_list(self) -> List[Dict[str, Any]]:
        """返回消息列表的深拷贝（只读快照）。

        外部修改返回值不影响内部状态。
        """
        with self._lock:
            return copy.deepcopy(self._messages)

    def clear(self) -> None:
        """清空所有消息。"""
        with self._lock:
            self._messages.clear()

    def trim(self, max_messages: Optional[int] = None) -> None:
        """显式 trim 到指定长度。

        Args:
            max_messages: None 表示用 self.max_messages；否则用传入值
        """
        with self._lock:
            limit = max_messages if max_messages is not None else self._max_messages
            self._trim_locked(limit)

    def _trim_locked(self, max_messages: int) -> None:
        """内部 trim（调用方必须已持锁）。保留最新 max_messages 条。"""
        if max_messages <= 0:
            return
        if len(self._messages) > max_messages:
            self._messages = self._messages[-max_messages:]

    # ── 协议 ──────────────────────────────────────────────

    def __len__(self) -> int:
        with self._lock:
            return len(self._messages)

    def __iter__(self) -> Iterator[Dict[str, Any]]:
        """迭代返回 dict 副本（避免外部修改内部状态）。"""
        with self._lock:
            return iter(copy.deepcopy(self._messages))

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"ConversationContext(len={len(self._messages)}, "
                f"max={self._max_messages})"
            )
