# -*- coding: utf-8 -*-
"""受限子会话的通道纪律（单一实现点）。

受限子会话（`/review` 的评审、目标验收的判定）都是"纯文本进出、不带 tools、
不产生副作用"的一次调用。它们的 `llmChat` 由调用方注入，而**注入进来的形态
并不统一**：

- 低层 `LLMClient.chat` 是**同步**方法（`llm_client.py:339`）。直接 await 会报
  "object is not awaitable"；在事件循环里裸调又会阻塞整个服务，故必须
  `asyncio.to_thread` 搬出去。
- Agent 门面 `AgentLLMClient.chat`（`agent_core.py:170`）是 **async** 方法，
  也是/条生产调用点实际注入的形态。对它套 `to_thread` 只会得到一只从未被
  await 的 coroutine——调用方拿到空正文，子会话静默退化成"解析失败"。

两种形态都要支持，纪律只应写一份，本模块就是那一份。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, List


async def callSubSessionChannel(llmChat: Callable, messages: List[Dict], **kwargs) -> Any:
    """在受限子会话里发一次请求，兼容同步/异步两种注入形态。

    `llmChat(messages)` 是注入契约的唯一要求；返回值需带 `content` 属性
    （或为含 `content` 键的 dict），由调用方解析。

    分支判定发生在**调用之前**（`inspect.iscoroutinefunction`），
    否则同步重活会先阻塞事件循环再被发现。
    """
    if inspect.iscoroutinefunction(llmChat):
        return await llmChat(messages, **kwargs)
    result = await asyncio.to_thread(llmChat, messages, **kwargs)
    # 同步包装器返回可等待对象（`lambda m: client.chat(m)` 这类形态）：
    # 调用已经在线程里完成，只差一次 await，此处补齐而不是把 coroutine 交回去。
    if inspect.isawaitable(result):
        return await result
    return result
