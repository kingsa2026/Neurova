from __future__ import annotations

"""
睡眠管理接口 - Sleep Management Endpoint

功能:
1. 获取睡眠状态 (GET /api/v1/sleep/{agent_id}/status)
2. 获取睡眠设置 (GET /api/v1/sleep/{agent_id}/settings)
3. 更新睡眠设置 (PUT /api/v1/sleep/{agent_id}/settings)
4. 获取梦境日志 (GET /api/v1/sleep/{agent_id}/dreams)
5. 获取梦境洞察 (GET /api/v1/sleep/{agent_id}/insights)
6. 获取记忆合并历史 (GET /api/v1/sleep/{agent_id}/merges)
7. 获取冲突解决历史 (GET /api/v1/sleep/{agent_id}/conflicts)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel

from neurova.api.auth import get_current_user

logger = get_logger(__name__)

# P2-B 根因修复: 此前全部路由无 JWT 鉴权（对比 chat/agent 端点均用
# Depends(get_current_user)），任何人可读取睡眠数据、触发睡眠/唤醒。
# 前端对每个请求附带 Bearer token（NeurUI/src/api/index.ts），严格鉴权安全。
router = APIRouter(dependencies=[Depends(get_current_user)])


class SleepStatusResponse(BaseModel):
    """睡眠状态响应"""

    agent_id: str
    is_sleeping: bool = False
    sleep_phase: str = "awake"
    last_sleep_time: Optional[float] = None
    last_wake_time: Optional[float] = None
    total_sleep_duration: float = 0
    sleep_cycles: int = 0


class SleepSettings(BaseModel):
    """睡眠设置"""

    auto_sleep_enabled: bool = True
    sleep_threshold_minutes: int = 30
    sleep_duration_minutes: int = 60
    dream_replay_enabled: bool = True
    memory_consolidation_enabled: bool = True
    conflict_resolution_enabled: bool = True


class SleepSettingsRequest(BaseModel):
    """睡眠设置更新请求"""

    auto_sleep_enabled: Optional[bool] = None
    sleep_threshold_minutes: Optional[int] = None
    sleep_duration_minutes: Optional[int] = None
    dream_replay_enabled: Optional[bool] = None
    memory_consolidation_enabled: Optional[bool] = None
    conflict_resolution_enabled: Optional[bool] = None


class DreamLogItem(BaseModel):
    """梦境日志条目"""

    dream_id: str
    agent_id: str
    timestamp: float
    dream_type: str = "replay"
    content: str = ""
    memories_involved: List[str] = []
    insights_generated: int = 0
    duration: float = 0


class DreamInsightItem(BaseModel):
    """梦境洞察条目"""

    insight_id: str
    dream_id: str
    agent_id: str
    timestamp: float
    insight_type: str = "pattern"
    content: str = ""
    confidence: float = 0
    related_memories: List[str] = []


class MemoryMergeItem(BaseModel):
    """记忆合并条目"""

    merge_id: str
    agent_id: str
    timestamp: float
    source_memories: List[str] = []
    target_memory: str = ""
    merge_type: str = "consolidation"
    success: bool = True
    conflicts_resolved: int = 0


class ConflictResolutionItem(BaseModel):
    """冲突解决条目"""

    resolution_id: str
    agent_id: str
    timestamp: float
    conflict_type: str = "memory"
    source_memories: List[str] = []
    resolution_strategy: str = "merge"
    resolution_result: str = ""
    success: bool = True


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_sleep_manager(agent_id: str = "default"):
    """获取睡眠管理器"""
    agent = _get_agent(agent_id)
    if not agent:
        return None

    # 尝试获取睡眠管理器
    if hasattr(agent, "sleep_manager"):
        return agent.sleep_manager
    if hasattr(agent, "sleep_consolidation"):
        return agent.sleep_consolidation

    return None


def _generate_mock_dreams(agent_id: str, limit: int = 10) -> List[DreamLogItem]:
    """生成模拟梦境数据"""
    dreams = []
    for i in range(min(limit, 5)):
        dreams.append(
            DreamLogItem(
                dream_id=str(uuid.uuid4()),
                agent_id=agent_id,
                timestamp=time.time() - (i * 3600),
                dream_type="replay",
                content=f"Dream replay of conversation about topic {i+1}",
                memories_involved=[f"memory_{j}" for j in range(3)],
                insights_generated=i % 3,
                duration=60.0 + i * 10,
            )
        )
    return dreams


def _generate_mock_insights(agent_id: str, limit: int = 10) -> List[DreamInsightItem]:
    """生成模拟梦境洞察数据"""
    insights = []
    for i in range(min(limit, 3)):
        insights.append(
            DreamInsightItem(
                insight_id=str(uuid.uuid4()),
                dream_id=str(uuid.uuid4()),
                agent_id=agent_id,
                timestamp=time.time() - (i * 7200),
                insight_type="pattern",
                content=f"Discovered pattern in user preferences: pattern_{i+1}",
                confidence=0.8 - i * 0.1,
                related_memories=[f"memory_{j}" for j in range(2)],
            )
        )
    return insights


def _generate_mock_merges(agent_id: str, limit: int = 10) -> List[MemoryMergeItem]:
    """生成模拟记忆合并数据"""
    merges = []
    for i in range(min(limit, 4)):
        merges.append(
            MemoryMergeItem(
                merge_id=str(uuid.uuid4()),
                agent_id=agent_id,
                timestamp=time.time() - (i * 1800),
                source_memories=[f"memory_{j}" for j in range(2, 4)],
                target_memory=f"consolidated_memory_{i}",
                merge_type="consolidation",
                success=True,
                conflicts_resolved=i % 2,
            )
        )
    return merges


def _generate_mock_conflicts(agent_id: str, limit: int = 10) -> List[ConflictResolutionItem]:
    """生成模拟冲突解决数据"""
    conflicts = []
    for i in range(min(limit, 2)):
        conflicts.append(
            ConflictResolutionItem(
                resolution_id=str(uuid.uuid4()),
                agent_id=agent_id,
                timestamp=time.time() - (i * 3600),
                conflict_type="memory",
                source_memories=[f"memory_{j}" for j in range(2)],
                resolution_strategy="merge",
                resolution_result="Successfully merged conflicting memories",
                success=True,
            )
        )
    return conflicts


@router.get("/{agent_id}/status", response_model=SleepStatusResponse)
async def get_sleep_status(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
):
    """获取 Agent 的睡眠状态"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 获取睡眠状态
    sleep_manager = _get_sleep_manager(agent_id)

    is_sleeping = False
    sleep_phase = "awake"
    last_sleep_time = None
    last_wake_time = None
    total_sleep_duration = 0
    sleep_cycles = 0

    if sleep_manager:
        if hasattr(sleep_manager, "is_sleeping"):
            is_sleeping = sleep_manager.is_sleeping()
        if hasattr(sleep_manager, "get_sleep_phase"):
            sleep_phase = sleep_manager.get_sleep_phase()
        if hasattr(sleep_manager, "get_last_sleep_time"):
            last_sleep_time = sleep_manager.get_last_sleep_time()
        if hasattr(sleep_manager, "get_last_wake_time"):
            last_wake_time = sleep_manager.get_last_wake_time()
        if hasattr(sleep_manager, "get_total_sleep_duration"):
            total_sleep_duration = sleep_manager.get_total_sleep_duration()
        if hasattr(sleep_manager, "get_sleep_cycles"):
            sleep_cycles = sleep_manager.get_sleep_cycles()

    return SleepStatusResponse(
        agent_id=agent_id,
        is_sleeping=is_sleeping,
        sleep_phase=sleep_phase,
        last_sleep_time=last_sleep_time,
        last_wake_time=last_wake_time,
        total_sleep_duration=total_sleep_duration,
        sleep_cycles=sleep_cycles,
    )


@router.get("/{agent_id}/settings", response_model=SleepSettings)
async def get_sleep_settings(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
):
    """获取 Agent 的睡眠设置"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 获取设置
    settings = SleepSettings()

    if sleep_manager and hasattr(sleep_manager, "get_settings"):
        try:
            manager_settings = sleep_manager.get_settings()
            if isinstance(manager_settings, dict):
                settings = SleepSettings(**manager_settings)
        except Exception as e:
            logger.warning("Failed to get sleep settings: %s", e)

    return settings


@router.put("/{agent_id}/settings", response_model=SleepSettings)
async def update_sleep_settings(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    body: SleepSettingsRequest = SleepSettingsRequest(),
):
    """更新 Agent 的睡眠设置"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 更新设置
    if sleep_manager and hasattr(sleep_manager, "update_settings"):
        try:
            update_data = body.dict(exclude_unset=True)
            sleep_manager.update_settings(update_data)
        except Exception as e:
            logger.warning("Failed to update sleep settings: %s", e)

    # 返回更新后的设置
    return await get_sleep_settings(request, agent_id)


@router.get("/{agent_id}/dreams", response_model=List[DreamLogItem])
async def get_dream_logs(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取梦境日志列表"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 获取梦境日志
    dreams = []
    if sleep_manager and hasattr(sleep_manager, "get_dream_logs"):
        try:
            dreams = sleep_manager.get_dream_logs(limit=limit, offset=offset)
        except Exception as e:
            logger.warning("Failed to get dream logs: %s", e)

    # 根因修复: 仅在完全没有睡眠管理器时才回退模拟数据；
    # 管理器存在但无数据时应返回空列表（此前真实数据被 mock 假数据掩盖）
    if not dreams and sleep_manager is None:
        dreams = _generate_mock_dreams(agent_id, limit)

    return dreams


@router.get("/{agent_id}/dreams/{dream_id}", response_model=DreamLogItem)
async def get_dream_log(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    dream_id: str = Path(..., description="梦境ID"),
):
    """获取单个梦境详情"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 获取梦境详情（优先真实数据，无管理器时才回退模拟数据）
    sleep_manager = _get_sleep_manager(agent_id)
    dreams = []
    if sleep_manager and hasattr(sleep_manager, "get_dream_logs"):
        try:
            dreams = sleep_manager.get_dream_logs(limit=100, offset=0)
        except Exception as e:
            logger.warning("Failed to get dream logs: %s", e)
    if not dreams and sleep_manager is None:
        dreams = _generate_mock_dreams(agent_id, 100)
    for dream in dreams:
        dream_id_value = dream.dream_id if hasattr(dream, "dream_id") else dream.get("dream_id")
        if dream_id_value == dream_id:
            return dream

    raise HTTPException(status_code=404, detail=f"Dream '{dream_id}' not found")


@router.get("/{agent_id}/insights", response_model=List[DreamInsightItem])
async def get_dream_insights(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取梦境洞察列表"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 获取梦境洞察
    insights = []
    if sleep_manager and hasattr(sleep_manager, "get_dream_insights"):
        try:
            insights = sleep_manager.get_dream_insights(limit=limit, offset=offset)
        except Exception as e:
            logger.warning("Failed to get dream insights: %s", e)

    # 仅在无管理器时回退模拟数据（与 dreams 端点契约一致）
    if not insights and sleep_manager is None:
        insights = _generate_mock_insights(agent_id, limit)

    return insights


@router.get("/{agent_id}/insights/{insight_id}", response_model=DreamInsightItem)
async def get_dream_insight(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    insight_id: str = Path(..., description="洞察ID"),
):
    """获取单个梦境洞察详情"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 获取洞察详情（优先真实数据，无管理器时才回退模拟数据）
    sleep_manager = _get_sleep_manager(agent_id)
    insights = []
    if sleep_manager and hasattr(sleep_manager, "get_dream_insights"):
        try:
            insights = sleep_manager.get_dream_insights(limit=100, offset=0)
        except Exception as e:
            logger.warning("Failed to get dream insights: %s", e)
    if not insights and sleep_manager is None:
        insights = _generate_mock_insights(agent_id, 100)
    for insight in insights:
        insight_id_value = insight.insight_id if hasattr(insight, "insight_id") else insight.get("insight_id")
        if insight_id_value == insight_id:
            return insight

    raise HTTPException(status_code=404, detail=f"Insight '{insight_id}' not found")


@router.get("/{agent_id}/merges", response_model=List[MemoryMergeItem])
async def get_memory_merges(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取记忆合并历史"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 获取记忆合并历史
    merges = []
    if sleep_manager and hasattr(sleep_manager, "get_memory_merges"):
        try:
            merges = sleep_manager.get_memory_merges(limit=limit, offset=offset)
        except Exception as e:
            logger.warning("Failed to get memory merges: %s", e)

    # 仅在无管理器时回退模拟数据（与 dreams 端点契约一致）
    if not merges and sleep_manager is None:
        merges = _generate_mock_merges(agent_id, limit)

    return merges


@router.get("/{agent_id}/merges/{merge_id}", response_model=MemoryMergeItem)
async def get_memory_merge(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    merge_id: str = Path(..., description="合并ID"),
):
    """获取单个记忆合并详情"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 获取合并详情（优先真实数据，无管理器时才回退模拟数据）
    sleep_manager = _get_sleep_manager(agent_id)
    merges = []
    if sleep_manager and hasattr(sleep_manager, "get_memory_merges"):
        try:
            merges = sleep_manager.get_memory_merges(limit=100, offset=0)
        except Exception as e:
            logger.warning("Failed to get memory merges: %s", e)
    if not merges and sleep_manager is None:
        merges = _generate_mock_merges(agent_id, 100)
    for merge in merges:
        merge_id_value = merge.merge_id if hasattr(merge, "merge_id") else merge.get("merge_id")
        if merge_id_value == merge_id:
            return merge

    raise HTTPException(status_code=404, detail=f"Merge '{merge_id}' not found")


@router.get("/{agent_id}/conflicts", response_model=List[ConflictResolutionItem])
async def get_conflict_resolutions(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取冲突解决历史"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 获取冲突解决历史
    conflicts = []
    if sleep_manager and hasattr(sleep_manager, "get_conflict_resolutions"):
        try:
            conflicts = sleep_manager.get_conflict_resolutions(limit=limit, offset=offset)
        except Exception as e:
            logger.warning("Failed to get conflict resolutions: %s", e)

    # 仅在无管理器时回退模拟数据（与 dreams 端点契约一致）
    if not conflicts and sleep_manager is None:
        conflicts = _generate_mock_conflicts(agent_id, limit)

    return conflicts


@router.get("/{agent_id}/conflicts/{resolution_id}", response_model=ConflictResolutionItem)
async def get_conflict_resolution(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    resolution_id: str = Path(..., description="解决ID"),
):
    """获取单个冲突解决详情"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 获取冲突详情（优先真实数据，无管理器时才回退模拟数据）
    sleep_manager = _get_sleep_manager(agent_id)
    conflicts = []
    if sleep_manager and hasattr(sleep_manager, "get_conflict_resolutions"):
        try:
            conflicts = sleep_manager.get_conflict_resolutions(limit=100, offset=0)
        except Exception as e:
            logger.warning("Failed to get conflict resolutions: %s", e)
    if not conflicts and sleep_manager is None:
        conflicts = _generate_mock_conflicts(agent_id, 100)
    for conflict in conflicts:
        resolution_id_value = (
            conflict.resolution_id if hasattr(conflict, "resolution_id") else conflict.get("resolution_id")
        )
        if resolution_id_value == resolution_id:
            return conflict

    raise HTTPException(status_code=404, detail=f"Conflict resolution '{resolution_id}' not found")


@router.post("/{agent_id}/wake")
async def wake_agent(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
):
    """唤醒 Agent"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 唤醒 Agent
    if sleep_manager and hasattr(sleep_manager, "wake"):
        try:
            sleep_manager.wake()
        except Exception as e:
            logger.warning("Failed to wake agent: %s", e)

    return {
        "code": 0,
        "message": f"Agent '{agent_id}' woken up",
        "data": {"agent_id": agent_id, "status": "awake"},
        "request_id": request_id,
    }


@router.post("/{agent_id}/sleep")
async def start_sleep(
    request: Request,
    agent_id: str = Path(..., description="Agent ID"),
    duration_minutes: int = Query(default=60, ge=1, le=1440, description="睡眠时长(分钟)"),
):
    """启动 Agent 睡眠"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    sleep_manager = _get_sleep_manager(agent_id)

    # 启动睡眠
    if sleep_manager and hasattr(sleep_manager, "start_sleep"):
        try:
            sleep_manager.start_sleep(duration_minutes=duration_minutes)
        except Exception as e:
            logger.warning("Failed to start sleep: %s", e)

    return {
        "code": 0,
        "message": f"Agent '{agent_id}' started sleeping",
        "data": {
            "agent_id": agent_id,
            "status": "sleeping",
            "duration_minutes": duration_minutes,
        },
        "request_id": request_id,
    }
