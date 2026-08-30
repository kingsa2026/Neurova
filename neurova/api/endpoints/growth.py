from __future__ import annotations

"""
成长系统接口 - Growth System Endpoint

提供以下API:
1. 反思日志 (GET/POST /api/v1/growth/reflection)
2. 问题队列 (GET/POST /api/v1/growth/questions)
3. 主动行为 (GET/POST /api/v1/growth/proactive)
4. 动机水平 (GET/POST /api/v1/growth/motivation)
5. 人格系统 (GET/PUT /api/v1/growth/personality)
6. 宪法系统 (GET/PUT /api/v1/growth/constitution)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


class ReflectionLog(BaseModel):
    """反思日志"""

    log_id: str
    agent_id: str
    timestamp: float
    reflection_type: str = "general"
    content: str = ""
    insights: List[str] = []
    confidence: float = 0
    related_memories: List[str] = []


class ReflectionLogCreate(BaseModel):
    """创建反思日志请求"""

    reflection_type: str = Field(default="general", description="反思类型")
    content: str = Field(..., description="反思内容")
    insights: List[str] = Field(default_factory=list, description="洞察")
    confidence: float = Field(default=0.5, ge=0, le=1, description="置信度")
    related_memories: List[str] = Field(default_factory=list, description="相关记忆")


class QuestionItem(BaseModel):
    """问题条目"""

    question_id: str
    agent_id: str
    timestamp: float
    question_type: str = "curiosity"
    question: str = ""
    status: str = "pending"
    answer: Optional[str] = None
    priority: int = 0


class QuestionCreate(BaseModel):
    """创建问题请求"""

    question_type: str = Field(default="curiosity", description="问题类型")
    question: str = Field(..., description="问题内容")
    priority: int = Field(default=0, ge=0, le=10, description="优先级")


class ProactiveAction(BaseModel):
    """主动行为记录"""

    action_id: str
    agent_id: str
    timestamp: float
    action_type: str = "communication"
    trigger: str = ""
    content: str = ""
    success: bool = True
    response_received: bool = False


class ProactiveActionCreate(BaseModel):
    """触发主动行为请求"""

    action_type: str = Field(default="communication", description="行为类型")
    trigger: str = Field(default="", description="触发条件")
    content: str = Field(..., description="行为内容")


class MotivationLevel(BaseModel):
    """动机水平"""

    agent_id: str
    timestamp: float
    overall_motivation: float = 0.5
    curiosity: float = 0.5
    creativity: float = 0.5
    persistence: float = 0.5
    social: float = 0.5
    factors: Dict[str, float] = {}


class MotivationLevelUpdate(BaseModel):
    """更新动机水平请求"""

    overall_motivation: Optional[float] = None
    curiosity: Optional[float] = None
    creativity: Optional[float] = None
    persistence: Optional[float] = None
    social: Optional[float] = None


class Personality(BaseModel):
    """人格信息"""

    agent_id: str
    timestamp: float
    traits: Dict[str, float] = {}
    values: List[str] = []
    communication_style: str = "balanced"
    decision_style: str = "analytical"


class PersonalityUpdate(BaseModel):
    """更新人格请求"""

    traits: Optional[Dict[str, float]] = None
    values: Optional[List[str]] = None
    communication_style: Optional[str] = None
    decision_style: Optional[str] = None


class ConstitutionRule(BaseModel):
    """宪法规则"""

    rule_id: str
    agent_id: str
    timestamp: float
    rule_type: str = "behavior"
    content: str = ""
    priority: int = 0
    enabled: bool = True


class ConstitutionRuleCreate(BaseModel):
    """创建宪法规则请求"""

    rule_type: str = Field(default="behavior", description="规则类型")
    content: str = Field(..., description="规则内容")
    priority: int = Field(default=0, ge=0, le=10, description="优先级")


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_growth_manager(agent_id: str = "default"):
    """获取成长管理器"""
    agent = _get_agent(agent_id)
    if not agent:
        return None

    # 尝试获取成长管理器
    if hasattr(agent, "growth_log_manager"):
        return agent.growth_log_manager
    if hasattr(agent, "proactive_behavior_engine"):
        return agent.proactive_behavior_engine

    return None


def _reflection_entry_to_item(entry, agent_id: str) -> Dict[str, Any]:
    """把 GrowthLogManager 的 ReflectionLogEntry 序列化为 ReflectionLog 兼容 dict

    根因修复: 此前端点调用不存在的 get_recent_logs/add_log（真实 API 是
    read_logs/generate_log），反思数据永远为空或被 mock 假数据掩盖。
    """
    from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionLogStatus

    related = []
    if getattr(entry, "context", None) and isinstance(entry.context, dict):
        related = entry.context.get("related_memories", []) or []
    return {
        "log_id": entry.id,
        "agent_id": agent_id,
        "timestamp": entry.timestamp,
        "reflection_type": entry.type.value,
        "content": entry.content,
        "insights": list(entry.insights or []),
        "confidence": entry.confidence,
        "related_memories": related,
        "status": entry.status.value if hasattr(entry, "status") else ReflectionLogStatus.PENDING.value,
    }


def _question_entry_to_item(entry, agent_id: str) -> Dict[str, Any]:
    """把 QuestionEntry 序列化为 QuestionItem 兼容 dict"""
    priority_rank = {"high": 0, "normal": 1, "low": 2}
    priority_value = entry.priority.value if hasattr(entry.priority, "value") else str(entry.priority)
    return {
        "question_id": entry.id,
        "agent_id": agent_id,
        "timestamp": entry.created_at,
        "question_type": (entry.metadata or {}).get("question_type", "curiosity"),
        "question": entry.content,
        "status": entry.status.value if hasattr(entry.status, "value") else str(entry.status),
        "answer": (entry.metadata or {}).get("answer"),
        "priority": priority_rank.get(priority_value, 1),
    }


@router.get("", response_model=Dict[str, Any])
async def get_agent_growth(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取 Agent 的成长数据（前端 GrowthPage.vue 调用）"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 收集成长数据
    growth_data = {
        "agent_id": agent_id,
        "timestamp": time.time(),
        "reflection_logs": [],
        "questions": [],
        "proactive_actions": [],
        "motivation_level": None,
        "personality": None,
        "constitution": [],
    }

    # 获取反思日志（根因修复: get_recent_logs 不存在 → read_logs 真实读取）
    if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
        try:
            entries = agent.growth_log_manager.read_logs(limit=10)
            growth_data["reflection_logs"] = [_reflection_entry_to_item(e, agent_id) for e in entries]
        except Exception as e:
            logger.warning("Failed to get reflection logs: %s", e)

    # 获取问题队列（根因修复: get_pending_questions 无 limit 参数 → 结果切片）
    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            pending = agent.question_queue_manager.get_pending_questions()
            growth_data["questions"] = [_question_entry_to_item(q, agent_id) for q in pending[:10]]
        except Exception as e:
            logger.warning("Failed to get questions: %s", e)

    # 获取主动行为
    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "get_recent_actions"):
                growth_data["proactive_actions"] = agent.proactive_behavior_engine.get_recent_actions(limit=10)
        except Exception as e:
            logger.warning("Failed to get proactive actions: %s", e)

    # 获取动机水平
    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "get_motivation_level"):
                growth_data["motivation_level"] = agent.proactive_behavior_engine.get_motivation_level()
        except Exception as e:
            logger.warning("Failed to get motivation level: %s", e)

    # 获取人格
    if hasattr(agent, "personality") and agent.personality:
        growth_data["personality"] = {
            "traits": agent.personality.get("traits", {}),
            "values": agent.personality.get("values", []),
            "communication_style": agent.personality.get("communication_style", "balanced"),
            "decision_style": agent.personality.get("decision_style", "analytical"),
        }

    # 获取宪法
    if hasattr(agent, "constitution") and agent.constitution:
        growth_data["constitution"] = agent.constitution

    return {
        "code": 0,
        "message": "success",
        "data": growth_data,
        "request_id": request_id,
    }


@router.get("/reflection", response_model=List[ReflectionLog])
async def get_reflection_logs(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取反思日志列表"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    logs = []
    if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
        try:
            # 根因修复: get_recent_logs 不存在 → read_logs 真实读取（含 offset 切片）
            entries = agent.growth_log_manager.read_logs(limit=limit + offset)
            logs = [_reflection_entry_to_item(e, agent_id) for e in entries][offset:offset + limit]
        except Exception as e:
            logger.warning("Failed to get reflection logs: %s", e)

    # 仅在无管理器时回退模拟数据（与 sleep 端点契约一致：有真实数据源时不得造假）
    if not logs and agent.growth_log_manager is None:
        for i in range(min(limit, 5)):
            logs.append(
                ReflectionLog(
                    log_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    timestamp=time.time() - (i * 3600),
                    reflection_type="general",
                    content=f"Reflection on conversation topic {i+1}",
                    insights=[f"Insight {j+1}" for j in range(2)],
                    confidence=0.7 - i * 0.1,
                    related_memories=[f"memory_{j}" for j in range(2)],
                )
            )

    return logs


@router.post("/reflection", response_model=ReflectionLog)
async def create_reflection_log(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ReflectionLogCreate = ReflectionLogCreate(content=""),
):
    """创建新的反思日志"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 创建反思日志（根因修复: add_log 不存在 → generate_log 真实落库）
    created_entry = None
    if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
        try:
            from neurova.cognitive_layers.meta_cognition_layer.growth_log import ReflectionType

            try:
                reflection_type = ReflectionType(body.reflection_type)
            except ValueError:
                reflection_type = ReflectionType.PERFORMANCE
            created_entry = await agent.growth_log_manager.generate_log(
                type=reflection_type,
                title=f"手动反思 - {body.reflection_type}",
                content=body.content,
                insights=list(body.insights or []),
                action_items=[],
                confidence=body.confidence,
            )
        except Exception as e:
            logger.warning("Failed to create reflection log: %s", e)

    if created_entry is not None:
        return ReflectionLog(**_reflection_entry_to_item(created_entry, agent_id))

    # 管理器缺失时返回请求回显（不落库，诚实响应）
    return ReflectionLog(
        log_id=str(uuid.uuid4()),
        agent_id=agent_id,
        timestamp=time.time(),
        reflection_type=body.reflection_type,
        content=body.content,
        insights=body.insights,
        confidence=body.confidence,
        related_memories=body.related_memories,
    )


@router.get("/reflection/stats")
async def get_reflection_stats(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取反思统计"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    stats = {
        "total_reflections": 0,
        "average_confidence": 0,
        "reflection_types": {},
        "recent_insights": [],
    }

    if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
        try:
            # 根因修复: get_stats 不存在 → get_statistics（异步）真实统计
            stats = await agent.growth_log_manager.get_statistics()
        except Exception as e:
            logger.warning("Failed to get reflection stats: %s", e)

    return {
        "code": 0,
        "message": "success",
        "data": stats,
    }


@router.get("/questions", response_model=List[QuestionItem])
async def get_question_queue(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取问题队列"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    questions = []
    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionStatus

            # 根因修复: get_questions(status=, limit=) 不存在 → 按状态取真实数据
            qm = agent.question_queue_manager
            if status:
                try:
                    entries = qm.get_questions_by_status(QuestionStatus(status))
                except ValueError:
                    entries = []
            else:
                entries = qm.get_pending_questions() + qm.get_questions_by_status(QuestionStatus.COOLDOWN)
            questions = [_question_entry_to_item(e, agent_id) for e in entries[:limit]]
        except Exception as e:
            logger.warning("Failed to get questions: %s", e)

    # 仅在无管理器时回退模拟数据（与 reflection 端点契约一致）
    if not questions and getattr(agent, "question_queue_manager", None) is None:
        for i in range(min(limit, 3)):
            questions.append(
                QuestionItem(
                    question_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    timestamp=time.time() - (i * 1800),
                    question_type="curiosity",
                    question=f"What is the meaning of concept {i+1}?",
                    status="pending",
                    priority=i,
                )
            )

    return questions


@router.post("/questions", response_model=QuestionItem)
async def add_question(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: QuestionCreate = QuestionCreate(question=""),
):
    """添加新问题"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    question_id = str(uuid.uuid4())
    timestamp = time.time()

    # 添加新问题（根因修复: add_question 不存在 → generate_question 真实入队）
    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionPriority

            priority_rank = {0: QuestionPriority.HIGH, 1: QuestionPriority.NORMAL, 2: QuestionPriority.LOW}
            priority = priority_rank.get(int(body.priority), QuestionPriority.NORMAL)
            created_question = agent.question_queue_manager.generate_question(
                content=body.question,
                priority=priority,
                metadata={"question_type": body.question_type},
            )
            question_id = created_question.id
            timestamp = created_question.created_at
        except Exception as e:
            logger.warning("Failed to add question: %s", e)

    return QuestionItem(
        question_id=question_id,
        agent_id=agent_id,
        timestamp=timestamp,
        question_type=body.question_type,
        question=body.question,
        status="pending",
        priority=body.priority,
    )


@router.get("/questions/next")
async def get_next_question(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取下一个待解答问题"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            # 根因修复: QuestionEntry dataclass 无法被 FastAPI 序列化 → 转 dict
            question = agent.question_queue_manager.get_next_question()
            if question:
                return {
                    "code": 0,
                    "message": "success",
                    "data": _question_entry_to_item(question, agent_id),
                }
        except Exception as e:
            logger.warning("Failed to get next question: %s", e)

    return {
        "code": 0,
        "message": "No pending questions",
        "data": None,
    }


@router.put("/questions/{question_id}/answer")
async def mark_question_answered(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    question_id: str = Path(..., description="问题ID"),
    answer: str = Query(default="", description="答案"),
):
    """标记问题已回答"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            if hasattr(agent.question_queue_manager, "mark_answered"):
                agent.question_queue_manager.mark_answered(question_id, answer)
        except Exception as e:
            logger.warning("Failed to mark question answered: %s", e)

    return {
        "code": 0,
        "message": f"Question '{question_id}' marked as answered",
        "data": {"question_id": question_id, "answer": answer},
        "request_id": request_id,
    }


@router.get("/proactive", response_model=List[ProactiveAction])
async def get_proactive_actions(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取主动行为记录"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    actions = []
    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "get_recent_actions"):
                actions = agent.proactive_behavior_engine.get_recent_actions(limit=limit)
        except Exception as e:
            logger.warning("Failed to get proactive actions: %s", e)

    # 如果没有数据，返回模拟数据
    if not actions:
        for i in range(min(limit, 3)):
            actions.append(
                ProactiveAction(
                    action_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    timestamp=time.time() - (i * 7200),
                    action_type="communication",
                    trigger="inactivity",
                    content=f"Proactive message about topic {i+1}",
                    success=True,
                    response_received=i % 2 == 0,
                )
            )

    return actions


@router.post("/proactive", response_model=ProactiveAction)
async def trigger_proactive_action(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ProactiveActionCreate = ProactiveActionCreate(content=""),
):
    """触发主动行为"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    action_id = str(uuid.uuid4())
    timestamp = time.time()

    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "trigger_action"):
                agent.proactive_behavior_engine.trigger_action(
                    action_id=action_id,
                    action_type=body.action_type,
                    trigger=body.trigger,
                    content=body.content,
                )
        except Exception as e:
            logger.warning("Failed to trigger proactive action: %s", e)

    return ProactiveAction(
        action_id=action_id,
        agent_id=agent_id,
        timestamp=timestamp,
        action_type=body.action_type,
        trigger=body.trigger,
        content=body.content,
        success=True,
        response_received=False,
    )


@router.get("/motivation", response_model=MotivationLevel)
async def get_motivation_level(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取内在动机水平"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    motivation = MotivationLevel(
        agent_id=agent_id,
        timestamp=time.time(),
    )

    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "get_motivation_level"):
                data = agent.proactive_behavior_engine.get_motivation_level()
                if isinstance(data, dict):
                    motivation = MotivationLevel(
                        agent_id=agent_id,
                        timestamp=time.time(),
                        **data,
                    )
        except Exception as e:
            logger.warning("Failed to get motivation level: %s", e)

    return motivation


@router.put("/motivation", response_model=MotivationLevel)
async def update_motivation_level(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: MotivationLevelUpdate = MotivationLevelUpdate(),
):
    """更新动机水平"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "update_motivation"):
                update_data = body.dict(exclude_unset=True)
                agent.proactive_behavior_engine.update_motivation(update_data)
        except Exception as e:
            logger.warning("Failed to update motivation level: %s", e)

    return await get_motivation_level(request, agent_id)


@router.get("/personality", response_model=Personality)
async def get_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取人格信息"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    personality = Personality(
        agent_id=agent_id,
        timestamp=time.time(),
    )

    if hasattr(agent, "personality") and agent.personality:
        if isinstance(agent.personality, dict):
            personality = Personality(
                agent_id=agent_id,
                timestamp=time.time(),
                traits=agent.personality.get("traits", {}),
                values=agent.personality.get("values", []),
                communication_style=agent.personality.get("communication_style", "balanced"),
                decision_style=agent.personality.get("decision_style", "analytical"),
            )

    return personality


@router.put("/personality", response_model=Personality)
async def update_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: PersonalityUpdate = PersonalityUpdate(),
):
    """更新人格信息"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "personality") and agent.personality:
        if isinstance(agent.personality, dict):
            update_data = body.dict(exclude_unset=True)
            agent.personality.update(update_data)

    return await get_personality(request, agent_id)


@router.get("/personality/traits")
async def get_personality_traits(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取人格特质列表"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    traits = {}
    if hasattr(agent, "personality") and agent.personality:
        if isinstance(agent.personality, dict):
            traits = agent.personality.get("traits", {})

    return {
        "code": 0,
        "message": "success",
        "data": {"traits": traits},
    }


@router.post("/personality/evolve")
async def evolve_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    learning_data: Dict[str, Any] = {},
):
    """根据学习数据进化人格"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # TODO: 实现人格进化逻辑
    return {
        "code": 0,
        "message": "Personality evolution not implemented yet",
        "data": {
            "agent_id": agent_id,
            "learning_data": learning_data,
        },
        "request_id": request_id,
    }


@router.get("/constitution")
async def get_constitution(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取宪法信息"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    constitution = []
    if hasattr(agent, "constitution") and agent.constitution:
        constitution = agent.constitution

    return {
        "code": 0,
        "message": "success",
        "data": {"constitution": constitution},
    }


@router.put("/constitution")
async def update_constitution(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    constitution: List[Dict[str, Any]] = [],
):
    """更新宪法"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if hasattr(agent, "constitution"):
        agent.constitution = constitution

    return {
        "code": 0,
        "message": "Constitution updated",
        "data": {"constitution": constitution},
        "request_id": request_id,
    }


@router.get("/constitution/rules", response_model=List[ConstitutionRule])
async def get_constitution_rules(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取宪法规则列表"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    rules = []
    if hasattr(agent, "constitution") and agent.constitution:
        for i, rule in enumerate(agent.constitution):
            if isinstance(rule, dict):
                rules.append(
                    ConstitutionRule(
                        rule_id=rule.get("rule_id", str(uuid.uuid4())),
                        agent_id=agent_id,
                        timestamp=rule.get("timestamp", time.time()),
                        rule_type=rule.get("rule_type", "behavior"),
                        content=rule.get("content", ""),
                        priority=rule.get("priority", 0),
                        enabled=rule.get("enabled", True),
                    )
                )

    return rules


@router.post("/constitution/rules", response_model=ConstitutionRule)
async def add_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ConstitutionRuleCreate = ConstitutionRuleCreate(content=""),
):
    """添加宪法规则"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    rule_id = str(uuid.uuid4())
    timestamp = time.time()

    if not hasattr(agent, "constitution") or agent.constitution is None:
        agent.constitution = []

    new_rule = {
        "rule_id": rule_id,
        "timestamp": timestamp,
        "rule_type": body.rule_type,
        "content": body.content,
        "priority": body.priority,
        "enabled": True,
    }
    agent.constitution.append(new_rule)

    return ConstitutionRule(
        rule_id=rule_id,
        agent_id=agent_id,
        timestamp=timestamp,
        rule_type=body.rule_type,
        content=body.content,
        priority=body.priority,
        enabled=True,
    )


@router.put("/constitution/rules/{rule_id}", response_model=ConstitutionRule)
async def update_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    rule_id: str = Path(..., description="规则ID"),
    body: ConstitutionRuleCreate = ConstitutionRuleCreate(content=""),
):
    """更新宪法规则"""
    _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if not hasattr(agent, "constitution") or agent.constitution is None:
        raise HTTPException(status_code=404, detail="No constitution rules found")

    # 查找并更新规则
    for rule in agent.constitution:
        if isinstance(rule, dict) and rule.get("rule_id") == rule_id:
            rule.update(
                {
                    "rule_type": body.rule_type,
                    "content": body.content,
                    "priority": body.priority,
                }
            )
            return ConstitutionRule(
                rule_id=rule_id,
                agent_id=agent_id,
                timestamp=rule.get("timestamp", time.time()),
                rule_type=body.rule_type,
                content=body.content,
                priority=body.priority,
                enabled=rule.get("enabled", True),
            )

    raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")


@router.delete("/constitution/rules/{rule_id}")
async def delete_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    rule_id: str = Path(..., description="规则ID"),
):
    """删除宪法规则"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    if not hasattr(agent, "constitution") or agent.constitution is None:
        raise HTTPException(status_code=404, detail="No constitution rules found")

    # 查找并删除规则
    for i, rule in enumerate(agent.constitution):
        if isinstance(rule, dict) and rule.get("rule_id") == rule_id:
            agent.constitution.pop(i)
            return {
                "code": 0,
                "message": f"Rule '{rule_id}' deleted",
                "data": {"rule_id": rule_id},
                "request_id": request_id,
            }

    raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")


@router.post("/constitution/evaluate")
async def evaluate_against_constitution(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    action: str = Query(..., description="待评估的行为"),
):
    """评估行为是否符合宪法"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 简单评估逻辑
    is_compliant = True
    violations = []

    if hasattr(agent, "constitution") and agent.constitution:
        for rule in agent.constitution:
            if isinstance(rule, dict) and rule.get("enabled", True):
                # TODO: 实现真正的规则评估逻辑
                pass

    return {
        "code": 0,
        "message": "success",
        "data": {
            "action": action,
            "is_compliant": is_compliant,
            "violations": violations,
        },
    }
