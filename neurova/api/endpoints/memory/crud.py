"""
记忆接口 - 基本 CRUD
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Query, Request

from neurova.api.auth import get_current_user_or_default
from neurova.api.deps import require_admin
from neurova.cognitive_layers.memory_layer.models import MemoryType
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
    ErrorCodes,
    success_response,
)

from .base import (
    AddMemoryRequest,
    UpdateMemoryRequest,
    _get_request_id,
    agentWidePrivilege,
    get_memory_manager,
    logger,
    memory_to_dict,
    memories_to_dicts,
    router,
)


@router.get("", summary="搜索记忆")
async def search_memories(
    query: str = Query(default="", min_length=0, description="搜索关键词"),
    category: Optional[str] = Query(default=None, description="按分类过滤"),
    memory_type: Optional[str] = Query(default=None, description="按记忆类型过滤，逗号分隔多值 (semantic/episodic/procedural/pattern/emotional/working/workflow_experience)"),
    limit: int = Query(default=10, ge=1, le=100, description="返回条数"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """搜索记忆 - query 为空时返回全部"""
    # memory_type 逐段校验（逗号多值）：任一非法整体 422（fail-fast），
    # 合法多值原样透传 recall（长期记忆页签 = 排除 working 的五类）。
    # 校验在 try 之前：HTTPException 不能被下方 except Exception 收编成 APIError。
    if memory_type:
        _valid_types = {t.value for t in MemoryType}
        for _token in memory_type.split(","):
            _token = _token.strip()
            if _token and _token not in _valid_types:
                raise HTTPException(status_code=422, detail=f"非法 memory_type: {_token}")
    try:
        manager = get_memory_manager(agent_id, user)
        memories = manager.recall(
            query=query, category=category, limit=limit, agent_wide=True,
            memory_type=memory_type or None,
        )

        return success_response(
            data={
                "count": len(memories),
                "memories": memories_to_dicts(
                    manager, memories, agentWide=agentWidePrivilege(user)
                ),
            },
            message="搜索成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        # 曾经这里捕住 AGENT_NOT_INITIALIZED 返回 200 + 空列表（"记忆系统未初始化，请先创建 Agent"）——
        # 那是把故障画成成功：界面一片空白、日志零故障、指标不涨，看的人以为"就是没有记忆"。
        # 未就绪由全局处理器如实落成 503（见 `api/error_handlers.py` 的码表）。
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
            memory_type=request.memory_type,
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
        stats = manager.get_stats(agent_wide=True)
        return success_response(data=stats, message="获取成功", request_id=_get_request_id(None))
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取记忆统计失败: %s", e)
        raise APIError.internal(f"获取记忆统计失败: {str(e)}")


# 注意：GET/DELETE /{memory_id} 路径参数路由必须在本文件所有字面路由
# （/stats、/hot、/crystallized、/decay）之后注册，否则它们会被吞掉
# （FastAPI 按注册顺序匹配，/hot 曾被当成 memory_id="hot" 处理）。
# 管理通道 `/management/{memory_id}` 是两段路径，不会被一段的 `/{memory_id}` 吞掉。


# ─────────────────────────────────────────────────────────────────────────────
# 单条记忆的读／改／删各只有一份实现（下面这两个 `*Entry` 口）。两条通道的差别
# 只有 `agentWide` 一个参数：常规通道按三层隔离，他人用户域"视同不存在"（P1-6）；
# 管理通道先过 `deps.require_admin()` 这道 role 门，再按 agent 口径读写。
# 写成两份实现就会分家——教义第 7 条要求同功能先比后合、其余退役。
# ─────────────────────────────────────────────────────────────────────────────


def _readEntry(manager, memory_id: str, agentWide: bool) -> dict:
    """读一条记忆并投影成响应体；归属判定单点在 `manager.get_memory`（P1-6 收口处）。

    原写法 `manager.storage.get(memory_id)` 读的 `MemoryManager._storage` 全仓零写入方，
    于是这条详情路由对归属者也恒 404，且绕过校验构成"按 id 匿名读任意记录"的潜伏面
    （取证见 audit-reports/memory-isolation-2026-10-05.md）。
    """
    try:
        memory_data = manager.get_memory(memory_id, agent_wide=agentWide)
        if not memory_data:
            raise APIError.not_found(f"记忆不存在: {memory_id}")

        return memory_to_dict(
            memory_data, owned=manager.isOwnedByRequestScope(memory_data, agentWide)
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取记忆失败: %s", e)
        # 故障不许折成"不存在"（台账 §6-126）：读面出错与查无此条是两件事——
        # 真查无此条走上面那条 `APIError.not_found`（7002→404），这里回 7001。
        # 7001 不在 `error_handlers` 的码→状态表里，天然落 500，两类从此分得开。
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"获取记忆失败: {str(e)}")


def _updateEntry(manager, memory_id: str, payload: dict, agentWide: bool) -> dict:
    """改一条并读回投影。空 payload 由调用方先拦（422 是请求形状问题，不是归属问题）。

    读回失败（行在改动后消失）如实落成 404，不再回 `data: null`——「改成功了但
    拿不到结果」这种半态对前端没有意义。
    """
    try:
        if not manager.update_memory(memory_id, agent_wide=agentWide, **payload):
            raise APIError.not_found(f"记忆不存在: {memory_id}")
    except APIError:
        raise
    except Exception as e:
        logger.exception("更新记忆失败: %s", e)
        raise APIError.internal(f"更新记忆失败: {str(e)}")

    return _readEntry(manager, memory_id, agentWide)


def _forgetEntry(manager, memory_id: str, agentWide: bool) -> dict:
    """删一条记忆。`agentWide=True` 只在过了 role 门的管理通道上给得出。

    落地形态是 `forget(soft=True)` 的**软遗忘**（`lifecycle_stage → forgotten`），
    行仍按 id 读得到——这是既有端点语义，本批没改它。
    """
    try:
        if not manager.forget(memory_id, agent_wide=agentWide):
            raise APIError.not_found(f"记忆不存在: {memory_id}")

        return {"memory_id": memory_id}

    except APIError:
        raise
    except Exception as e:
        logger.exception("删除记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"删除记忆失败: {str(e)}")



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
        memories = manager.get_hot_memories(limit=limit, agent_wide=True)

        return success_response(
            data={
                "count": len(memories),
                "memories": memories_to_dicts(
                    manager, memories, agentWide=agentWidePrivilege(user)
                ),
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
        memories = manager.get_crystallized(limit=limit, agent_wide=True)

        return success_response(
            data={
                "count": len(memories),
                "memories": memories_to_dicts(
                    manager, memories, agentWide=agentWidePrivilege(user)
                ),
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
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """获取指定记忆的详细信息（本人作用域；他人用户域视同不存在）。"""
    manager = get_memory_manager(agent_id, user)
    return success_response(
        data=_readEntry(manager, memory_id, False),
        message="获取成功",
        request_id=_get_request_id(req),
    )


@router.get("/management/{memory_id}", summary="获取记忆详情（管理通道）")
async def getMemoryViaManagement(
    memory_id: str,
    agent_id: Optional[str] = None,
    req: Request = None,
    _roleGate: Dict[str, Any] = Depends(require_admin()),
):
    """管理员按 id 读**他人用户域**的记忆——带 role 门的显式通道。

    常规 `GET /{memory_id}` 的三层隔离一个字没放宽（管理员走那条也一样 404）；
    跨用户可见性需要的特权只在这条门上给。这就是本文件 DELETE 处原注释
    "管理页口径若需要，另开带 role 门的显式端点"预留的那条路
    （用户 2026-10-26 在三态票外的裁定）。
    """
    manager = get_memory_manager(agent_id, _roleGate)
    return success_response(
        data=_readEntry(manager, memory_id, True),
        message="获取成功",
        request_id=_get_request_id(req),
    )


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
    method: str = Query(default="bfs", pattern="^(bfs|dfs|causal)$"),
    max_depth: int = Query(default=3, ge=1, le=10),
    target_id: Optional[str] = Query(default=None, description="causal 模式的终点记忆"),
    include_loops: bool = Query(default=False, description="causal 模式是否做全图环检测"),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """从指定记忆出发遍历关系图（graph.min_strength 过滤弱关系）。

    `method=causal` 走 `MemoryManager.analyze_causal`：多跳效应、根因、因果链、
    解释与可选的因果环检测；其余方法保持原 BFS/DFS 遍历。
    """
    try:
        manager = get_memory_manager(agent_id, user)
        if method == "causal":
            result = manager.analyze_causal(
                memory_id, target_id=target_id, includeLoops=include_loops)
        else:
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


@router.put("/{memory_id}", summary="更新记忆")
async def update_memory(
    memory_id: str,
    body: UpdateMemoryRequest,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """更新指定记忆的字段（记忆页的「编辑内容」入口，本人作用域）。

    此前前端 `memoryApi.updateMemory` 发 `PUT /api/v1/memory/{id}`，而本文件
    从未注册过 PUT 路由 —— 实测 405，页面「编辑」按钮点下去必失败。
    能力早已在 `MemoryManager.update_memory(memory_id, **kwargs)`，缺的只是 HTTP 面。
    """
    manager = get_memory_manager(agent_id, user)
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="没有可更新的字段")

    return success_response(
        data=_updateEntry(manager, memory_id, payload, False),
        message="更新成功",
        request_id=_get_request_id(None),
    )


@router.put("/management/{memory_id}", summary="更新记忆（管理通道）")
async def updateMemoryViaManagement(
    memory_id: str,
    body: UpdateMemoryRequest,
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
    _roleGate: Dict[str, Any] = Depends(require_admin()),
):
    """管理员改他人用户域的记忆——与常规 PUT 同一份实现，只多一道 role 门。"""
    manager = get_memory_manager(agent_id, _roleGate)
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=422, detail="没有可更新的字段")

    return success_response(
        data=_updateEntry(manager, memory_id, payload, True),
        message="更新成功",
        request_id=_get_request_id(None),
    )


@router.delete("/{memory_id}", summary="删除记忆")
async def delete_memory(
    memory_id: str,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """删除指定记忆 (遗忘)，本人作用域。

    这里不传 `agent_wide=True`：那会把三层隔离的第 2、3 层显式关掉，于是知道 id 的人
    （含无凭证请求）都能"遗忘"他人记忆。跨用户操作的特权通道已经开出来了
    （`DELETE /management/{memory_id}`，挂 `require_admin()`）。
    """
    manager = get_memory_manager(agent_id, user)
    return success_response(
        data=_forgetEntry(manager, memory_id, False),
        message="记忆已删除",
        request_id=_get_request_id(None),
    )


@router.delete("/management/{memory_id}", summary="删除记忆（管理通道）")
async def deleteMemoryViaManagement(
    memory_id: str,
    agent_id: Optional[str] = None,
    _roleGate: Dict[str, Any] = Depends(require_admin()),
):
    """管理员删他人用户域的记忆——与常规 DELETE 同一份实现，只多一道 role 门。"""
    manager = get_memory_manager(agent_id, _roleGate)
    return success_response(
        data=_forgetEntry(manager, memory_id, True),
        message="记忆已删除",
        request_id=_get_request_id(None),
    )
