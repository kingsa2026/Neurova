"""
记忆接口 - 基本 CRUD
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, Query, Request

from neurova.api.auth import get_current_user_or_default
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
    ErrorCodes,
    success_response,
)

from .base import (
    AddMemoryRequest,
    _get_request_id,
    _get_user_ids_from_token,
    get_memory_manager,
    logger,
    memory_to_dict,
    router,
)


@router.get("", summary="搜索记忆")
async def search_memories(
    query: str = Query(default="", min_length=0, description="搜索关键词"),
    category: Optional[str] = Query(default=None, description="按分类过滤"),
    limit: int = Query(default=10, ge=1, le=100, description="返回条数"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """搜索记忆 - query 为空时返回全部"""
    try:
        manager = get_memory_manager(agent_id, user)
        memories = manager.recall(query=query, category=category, limit=limit)

        return success_response(
            data={
                "count": len(memories),
                "memories": [memory_to_dict(m) for m in memories],
            },
            message="搜索成功",
            request_id=_get_request_id(None),
        )

    except APIError as e:
        if e.code == ErrorCodes.AGENT_NOT_INITIALIZED:
            return success_response(
                data={"count": 0, "memories": []},
                message="记忆系统未初始化，请先创建 Agent",
                request_id=_get_request_id(None),
            )
        raise
    except Exception as e:
        logger.exception("记忆搜索失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_SEARCH_FAILED, f"记忆搜索失败: {str(e)}") from e


@router.post("", summary="添加记忆")
async def add_memory(
    request: AddMemoryRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    添加新记忆 (支持自动分类)
    """
    try:
        manager = get_memory_manager(agent_id, user)

        memory_id = manager.remember(
            content=request.content,
            category=request.category,
            is_important=request.is_important,
            is_crystallized=request.is_crystallized,
            emotion_score=request.emotion_score,
            perspective=request.perspective,
            metadata=request.metadata,
            auto_analyze_emotion=request.auto_analyze_emotion,
            auto_classify=request.auto_classify,
            classification_context=request.classification_context,
        )

        return success_response(
            data={
                "memory_id": memory_id,
                "timestamp": datetime.now().isoformat(),
            },
            message="记忆已添加",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("添加记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"添加记忆失败: {str(e)}") from e


@router.get("/stats", summary="获取记忆统计")
async def get_memory_stats(
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    try:
        manager = get_memory_manager(agent_id, user)
        stats = manager.get_stats()
        return success_response(data=stats, message="获取成功", request_id=_get_request_id(None))
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取记忆统计失败: %s", e)
        raise APIError.internal(f"获取记忆统计失败: {str(e)}")


# 注意：GET/DELETE /{memory_id} 路径参数路由必须在本文件所有字面路由
# （/stats、/hot、/crystallized、/decay）之后注册，否则它们会被吞掉
# （FastAPI 按注册顺序匹配，/hot 曾被当成 memory_id="hot" 处理）。


@router.get("/hot", summary="获取高温记忆")
async def get_hot_memories(
    limit: int = Query(default=10, ge=1, le=50, description="返回条数"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取高温记忆 (temperature >= 50)
    """
    try:
        manager = get_memory_manager(agent_id, user)
        memories = manager.get_hot_memories(limit=limit)

        return success_response(
            data={
                "count": len(memories),
                "memories": [memory_to_dict(m) for m in memories],
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取高温记忆失败: %s", e)
        raise APIError.internal(f"获取高温记忆失败: {str(e)}")


@router.get("/crystallized", summary="获取固化记忆")
async def get_crystallized_memories(
    limit: int = Query(default=20, ge=1, le=50, description="返回条数"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取固化记忆 (永不遗忘的重要记忆)
    """
    try:
        manager = get_memory_manager(agent_id, user)
        memories = manager.get_crystallized(limit=limit)

        return success_response(
            data={
                "count": len(memories),
                "memories": [memory_to_dict(m) for m in memories],
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取固化记忆失败: %s", e)
        raise APIError.internal(f"获取固化记忆失败: {str(e)}")


@router.post("/decay", summary="执行温度衰减")
async def run_decay_cycle(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    手动执行一轮温度衰减
    (通常应通过定时任务自动执行)
    """
    try:
        manager = get_memory_manager(agent_id, user)
        # 有界 + 节流：无界全量遍历 116 万级记忆库会长时间阻塞甚至拖垮服务
        updated_count = manager.run_decay_cycle(
            max_memories=5000, min_interval_seconds=300
        )

        return success_response(
            data={"updated_count": updated_count},
            message=f"已更新 {updated_count} 条记忆温度",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("温度衰减失败: %s", e)
        raise APIError.internal(f"温度衰减失败: {str(e)}")


@router.get("/{memory_id}", summary="获取记忆详情")
async def get_memory(
    memory_id: str,
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    获取指定记忆的详细信息
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, {"neuser_id": neuser_id, "user_id": user_id})

        # BUG-40: 使用 storage.get 替代搜索，提高效率
        memory_data = manager.storage.get(memory_id)
        if not memory_data:
            raise APIError.not_found(f"记忆不存在: {memory_id}")

        from neurova.cognitive_layers.memory_layer.models import Memory

        target = Memory.from_dict(memory_data)

        return success_response(
            data=memory_to_dict(target),
            message="获取成功",
            request_id=_get_request_id(req),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_NOT_FOUND, f"获取记忆失败: {str(e)}")


@router.post("/compress", summary="压缩低重要性记忆")
async def compress_low_value_memories(
    dry_run: bool = Query(default=True, description="True 只返回合并计划不执行"),
    limit: int = Query(default=500, ge=1, le=5000, description="候选上限"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """对低重要性相似记忆执行压缩/合并（参数见 compression.* 配置组）"""
    try:
        manager = get_memory_manager(agent_id, user)
        report = manager.compress_low_value_memories(dry_run=dry_run, limit=limit)
        return success_response(
            data=report,
            message="压缩计划" if dry_run else "压缩完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记忆压缩失败: %s", e)
        raise APIError.internal(f"记忆压缩失败: {str(e)}")


@router.get("/relations/{memory_id}/traverse", summary="遍历记忆关系图")
async def traverse_relations(
    memory_id: str,
    method: str = Query(default="bfs", pattern="^(bfs|dfs)$"),
    max_depth: int = Query(default=3, ge=1, le=10),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """从指定记忆出发遍历关系图（graph.min_strength 过滤弱关系）"""
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.traverse_relations(memory_id, method=method, max_depth=max_depth)
        return success_response(
            data=result,
            message="遍历完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("关系图遍历失败: %s", e)
        raise APIError.internal(f"关系图遍历失败: {str(e)}")


@router.delete("/{memory_id}", summary="删除记忆")
async def delete_memory(
    memory_id: str,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    删除指定记忆 (遗忘)
    """
    try:
        manager = get_memory_manager(agent_id, user)
        success = manager.forget(memory_id)

        if not success:
            raise APIError.not_found(f"记忆不存在: {memory_id}")

        return success_response(
            data={"memory_id": memory_id},
            message="记忆已删除",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("删除记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"删除记忆失败: {str(e)}")
