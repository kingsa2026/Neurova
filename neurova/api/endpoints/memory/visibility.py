"""
记忆跨进程可见性接口 — 让运行中的后端看见别的进程写下的记忆（F-05）

为什么需要这条端点：记忆快照只在进程构造时读一次盘（`MemoryManager._load_from_db`），
CLI 在**另一个进程**导入的记忆因此对运行中的服务一条都看不见。此前只有 CLI 输出里
一句"需后端重启后才可见"的诚实暴露——用户没有不重启就看见的路。

可见性条件只有两条：**服务重启** 或 **显式 reload**。本模块兑现后者，且**只**兑现
这一件事：不新增写路径，不新造第二套快照口径。
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Query, Request

from neurova.api.auth import get_current_user_or_default
from neurova.interfaces.api_standard import APIError, ErrorCodes, success_response

from .base import _get_request_id, get_memory_manager, logger, router


@router.post("/reload", summary="与盘对账：并入外进程写入的行、回收已被撤销的行")
async def reload_memories(
    request: Request,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """重新读盘与盘对账（不新增写路径）。

    双向：并入盘上新增的行（外进程导入）并回收盘上已消失的行（外进程撤销）。
    只补缺不回收就兑现不了撤销——另一进程 `undo` 删掉的行会留在快照里，还能被
    用户的一次强化写回盘上（实测 0 → 1 行、重开实例复活）。

    返回**真实发生的两个读数**（幂等：无事发生时为 0），不给"看起来成功"的计数。
    """
    try:
        manager = get_memory_manager(agent_id, user)
        if not hasattr(manager, "reload_memories"):
            raise APIError(
                ErrorCodes.MEMORY_OPERATION_FAILED,
                "当前记忆管理器不支持增量重新读盘",
            )
        outcome = manager.reload_memories()
        return success_response(
            data={"reloaded": outcome["reloaded"], "reaped": outcome["reaped"]},
            message=f"已并入 {outcome['reloaded']} 条、回收 {outcome['reaped']} 条记忆",
            request_id=_get_request_id(request),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记忆重新读盘失败: %s", e)
        raise APIError.internal(f"记忆重新读盘失败: {str(e)}") from e
