# -*- coding: utf-8 -*-
"""M9（多模态追平批一）：生成产物入活水池的单一接线点。

改前根因：生成完成回执只进 REST 响应与任务账本，会话的活水上下文池
永远看不到「这轮生成过什么」——池侧的来源枚举也没有生成物位。

本模块是生成 → 池的唯一接线：
- 来源：``ContextSource.GENERATION``（``context/pool_models.py`` 单源枚举）；
- 写入：一律经 ``ContextPool.add_context`` 单源咽喉（隔离标签由池注入）；
- 取池：``ContextPoolRegistry``（编排器构造池时已 adopt，读侧唯一入口）——
  不在端点里另造池（审计 P2-3：各造各的池、写入即丢）。

池不可得（请求未带会话归属 / 该身份无已登记池）时诚实跳过并留 warn 日志，
不阻断生成主流程；入池失败同样 warn 可见，不静默吞掉。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


async def archiveGenerationToPool(
    kind: str,
    prompt: str,
    urls: List[str],
    task_id: str,
    protocol: str = "",
    model: str = "",
    user_id: str = "",
    agent_id: str = "",
    session_id: str = "",
    turn: int = 0,
    tenant_id: str = "",
) -> bool:
    """把一条生成产物归档进该会话归属的活水上下文池，返回是否入池。

    content 带提示词摘要与产物 URL（池 draw/query 语义召回用）；
    metadata 带 session_id/turn/task_id/kind/protocol/model/tenant_id——
    满足「生成物可按会话与轮次追溯」的读侧需求。池既有折叠/淘汰/租户
    隔离语义不变（隔离标签仍由 add_context 注入）。
    """
    clean_urls = [str(u) for u in (urls or []) if u]
    if not clean_urls:
        return False
    try:
        from neurova.context.pool_models import ContextInput, ContextSource
        from neurova.context_pool_registry import get_registry

        pool = get_registry().get_pool(user_id or "", agent_id or "", "")
        if pool is None:
            logger.warning(
                "生成产物未入池（该身份无已登记池）: task=%s kind=%s user=%s agent=%s",
                task_id, kind, user_id or "(empty)", agent_id or "(default)")
            return False
        shown = "；".join(clean_urls[:3])
        payload: Dict[str, Any] = {
            "kind": kind,
            "task_id": task_id,
            "session_id": session_id or "",
            "turn": int(turn or 0),
            "protocol": protocol,
            "model": model,
            "user_id": user_id or "",
            "agent_id": agent_id or "",
            "tenant_id": tenant_id or "",
        }
        pool.add_context(ContextInput(
            source=ContextSource.GENERATION,
            content=f"[生成产物:{kind}] {prompt} 产物: {shown}",
            metadata=payload,
            tags=["generation", str(kind or "media")],
        ))
        return True
    except Exception as e:  # noqa: BLE001 — 入池失败不阻断生成主流程，但必须可见
        logger.warning("生成产物入池失败: task=%s kind=%s err=%s", task_id, kind, e)
        return False
