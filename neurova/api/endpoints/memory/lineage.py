"""记忆世代链接口 — supersedes 链读路径化（T1）

DCPM 启发（docs/04-plans/2026-11-18-dcpm-memory-inspiration-plan.md T1）：
世代链三处写点（S16 世代失效/导入取代/睡眠合并）此前只写不读。本端点是
链的**唯一读面出口**：给定链上任意一代，返回完整演化弧线（旧值是什么、
被谁依据什么修订、合并吸收了哪些源）。

只读、fail-closed：起点不存在或越出请求作用域一律 404（与 get_memory 的
"视同不存在"同规则，不给按 id 探测他人记录的入口）；链遍历深度有界。
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Query, Request

from neurova.api.auth import get_current_user_or_default
from neurova.cognitive_layers.memory_layer.lineage import (
    LINEAGE_MAX_DEPTH,
    memoryLineage,
)
from neurova.interfaces.api_standard import APIError, success_response

from .base import _get_request_id, get_memory_manager, logger, router


@router.get("/{memory_id}/lineage", summary="记忆世代链：这条结论从哪来、被谁依据什么修订")
async def get_memory_lineage(
    request: Request,
    memory_id: str,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    depth: int = Query(
        default=LINEAGE_MAX_DEPTH, ge=1, le=10, description="链遍历跳数上限"
    ),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """读取一条记忆的世代演化弧线（纯只读）。

    返回 ``nodes``（链上各行，内容为预览）与 ``edges``（旧代→新代的
    ``superseded_by``/``merged_into`` 边，supersede 边带 basis/at 依据）。
    退役行（forgotten/archived）经本端点按 id 可见——它们不进召回列表，
    但作为信念演化史可追溯；作用域与 get_memory 同一仲裁器。
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = memoryLineage(manager, memory_id, max_depth=depth)
        if result is None:
            raise APIError.not_found(f"记忆不存在: {memory_id}") from None
        return success_response(
            data=result,
            message=f"世代链共 {len(result['nodes'])} 代、{len(result['edges'])} 次修订/合并",
            request_id=_get_request_id(request),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记忆世代链读取失败: %s", e)
        raise APIError.internal(f"记忆世代链读取失败: {str(e)}") from e
