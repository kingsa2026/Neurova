"""成长系统接口 - Growth System Endpoint（聚合器）

2026-09-16 模块化拆分：本文件原 1078 行单文件多域端点，按域拆为
  - personality_router.py   /personality /personality/traits /personality/evolve
  - constitution_router.py  /constitution /constitution/rules[/{id}]
  - personality_persistence.py / constitution_persistence.py（持久层叶子模块）
  - growth_common.py        共享依赖（agent 解析 / request_id / envelope）
拆分是纯结构迁移：全部路由路径与响应契约不变
（envelope 契约见 test_growth_envelope_consistency.py，路由快照见
test_growth_route_livability.py）。本文件挂载上述子 router 并保留
reflection / questions / proactive / motivation / overview 端点。

提供以下API:
1. 成长总览 (GET /api/v1/growth)
2. 能力成长 (GET /api/v1/growth/capabilities)
3. 反思日志 (GET/POST /api/v1/growth/reflection)
4. 问题队列 (GET/POST /api/v1/growth/questions)
5. 主动行为 (GET/POST /api/v1/growth/proactive)
6. 动机水平 (GET/PUT /api/v1/growth/motivation)
7. 人格系统 (GET/PUT /api/v1/growth/personality)  → personality_router
8. 宪法系统 (GET/PUT /api/v1/growth/constitution) → constitution_router
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from neurova.api.auth import get_current_user, Depends
from neurova.core.logger import get_logger
from pydantic import BaseModel, Field

from neurova.api.endpoints.constitution_router import router as _constitution_router
from neurova.api.endpoints.growth_common import envelope, get_agent as _get_agent_impl, get_request_id as _get_request_id_impl
from neurova.api.endpoints.personality_router import router as _personality_router

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])
router.include_router(_personality_router)
router.include_router(_constitution_router)

# ---------------------------------------------------------------------------
# 兼容 re-export（2026-09-16 拆分前这些名字定义在本文件；测试与潜在外部读者
# 经 growth.<name> 引用。持久层真身在 personality_persistence /
# constitution_persistence / growth_common，patch 持久层常量请打叶子模块）。
# ---------------------------------------------------------------------------
from neurova.api.endpoints.constitution_persistence import (  # noqa: E402,F401
    CONSTITUTION_DIR as _CONSTITUTION_DIR,
    ConstitutionRule,
    ConstitutionRuleCreate,
    ConstitutionRuleUpdate,
    load_constitution_rules as _load_constitution_rules,
    rule_to_model as _rule_to_model,
    save_constitution_rules as _save_constitution_rules,
)
from neurova.api.endpoints.growth_common import (  # noqa: E402,F401
    get_agent as _get_agent,
    get_request_id as _get_request_id,
)
from neurova.api.endpoints.personality_persistence import (  # noqa: E402,F401
    PERSONALITY_DIR as _PERSONALITY_DIR,
    PersonalityUpdate,
    load_personality_data as _load_personality_data,
    save_personality_data as _save_personality_data,
)


def _get_request_id(request: Request) -> str:
    """获取请求ID（本文件端点局部别名，转发 growth_common）"""
    return _get_request_id_impl(request)


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例（本文件端点局部别名，转发 growth_common；测试 patch 此名）"""
    return _get_agent_impl(agent_id)


def _get_experience_knowledge_base():
    """EKB 单例（局部别名便于测试替换；惰性导入避免模块加载期拉库）"""
    from neurova.skills.experience_knowledge_base import get_experience_knowledge_base

    return get_experience_knowledge_base()


def _authorized_question_agent(agent_id, current_user):
    from neurova.api.agent_access import can_access_agent, resolve_agent_owner

    agent = _get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    user_id = current_user.get("user_id") or current_user.get("neuser_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated identity required")
    if not can_access_agent(user_id, current_user.get("role", "user"),
                            resolve_agent_owner(agent_id, state_agent=agent)):
        raise HTTPException(status_code=403, detail="Agent access denied")
    return agent, user_id


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

    id: str = ""
    question_id: str
    agent_id: str
    timestamp: float
    created_at: float = 0
    question_type: str = "curiosity"
    question: str = ""
    status: str = "pending"
    answered: bool = False
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


class MotivationWeightsUpdate(BaseModel):
    """驱动权重更新（全量替换：未传键置 0，自动归一）"""

    drive_weights: Dict[str, float] = Field(default_factory=dict, description="{competence|autonomy|growth|purpose: 权重}")


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
    """把 QuestionEntry 序列化为 QuestionItem 兼容 dict

    2026-09-15 契约对齐: 补 id（前端 GrowthQuestion 契约名）/answered/created_at，
    status 保留枚举值原文供筛选回显。
    """
    from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionStatus

    priority_rank = {"high": 0, "normal": 1, "low": 2}
    priority_value = entry.priority.value if hasattr(entry.priority, "value") else str(entry.priority)
    status_value = entry.status.value if hasattr(entry.status, "value") else str(entry.status)
    return {
        "id": entry.id,
        "question_id": entry.id,
        "agent_id": agent_id,
        "timestamp": entry.created_at,
        "created_at": entry.created_at,
        "question_type": (entry.metadata or {}).get("question_type", "curiosity"),
        "question": entry.content,
        "status": status_value,
        "answered": status_value == QuestionStatus.ANSWERED.value,
        "answer": (entry.metadata or {}).get("answer"),
        "priority": priority_rank.get(priority_value, 1),
    }


def _all_questions(qm):
    """按创建时间倒序返回全部状态的问题。

    2026-09-15 根因修复: 原端点只取 pending+cooldown，而主动提问闭环运行后
    状态即 ASKED 终态 → 生产 22 条全 asked 队列页面恒空。
    """
    from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionStatus

    entries = []
    for status in QuestionStatus:
        entries.extend(qm.get_questions_by_status(status))
    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def _capabilities_payload(agent) -> Optional[Dict[str, Any]]:
    """读 GrowthAnalyzer 真实成长状态；未装配返回 None（不得造假分数）

    2026-09-15 根因修复: analyzer 每轮对话写 growth.json，但 API 全层零消费
    端点 → 能力数据是信息孤岛，成长页永远看不到。
    """
    analyzer = getattr(agent, "growth_analyzer", None)
    if analyzer is None:
        return None
    try:
        status = analyzer.get_growth_status()
        status["capability_scores"] = analyzer.get_capability()
        return status
    except Exception as e:
        logger.warning("Failed to get growth capabilities: %s", e)
        return None


@router.get("", response_model=Dict[str, Any])
async def get_agent_growth(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 的成长数据（前端 GrowthPage.vue 调用）"""
    request_id = _get_request_id(request)

    agent, user_id = _authorized_question_agent(agent_id, current_user)

    # 收集成长数据
    growth_data = {
        "agent_id": agent_id,
        "timestamp": time.time(),
        "capabilities": _capabilities_payload(agent),
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

    # 获取问题队列（2026-09-15 根因修复: 原只取 pending，主动提问后状态即
    # asked 终态导致页面恒空 → 全状态按时间倒序）
    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            growth_data["questions"] = [
                _question_entry_to_item(q, agent_id) for q in [e for e in _all_questions(agent.question_queue_manager)
                          if agent.question_queue_manager.visible_to(e, agent_id, user_id)][:10]
            ]
        except Exception as e:
            logger.warning("Failed to get questions: %s", e)

    # 获取主动行为
    if hasattr(agent, "proactive_behavior_engine") and agent.proactive_behavior_engine:
        try:
            if hasattr(agent.proactive_behavior_engine, "get_recent_actions"):
                growth_data["proactive_actions"] = agent.proactive_behavior_engine.get_recent_actions(limit=10)
        except Exception as e:
            logger.warning("Failed to get proactive actions: %s", e)

    # 获取动机水平（真实快照；未装配保持 None，不吐常量）
    ledger = getattr(agent, "intrinsic_motivation", None)
    if ledger:
        try:
            growth_data["motivation_level"] = ledger.snapshot()
        except Exception as e:
            logger.warning("Failed to get motivation level: %s", e)

    # 获取人格（读独立持久源；agent.personality 是 md 文本不可当 dict 用）
    pdata = _load_personality_data(agent_id)
    growth_data["personality"] = {
        "traits": pdata.get("traits", {}),
        "values": pdata.get("values", []),
        "communication_style": pdata.get("communication_style", "balanced"),
        "decision_style": pdata.get("decision_style", "analytical"),
    }

    # 获取宪法（读独立持久源，与 constitution_router 同源）
    growth_data["constitution"] = _load_constitution_rules(agent_id)

    return envelope(request_id, growth_data)


@router.get("/capabilities", response_model=Dict[str, Any])
async def get_growth_capabilities(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取 Agent 能力成长分数（GrowthAnalyzer 真实数据；未装配返回 data=null）"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return envelope(request_id, _capabilities_payload(agent))


@router.get("/reflection", response_model=Dict[str, Any])
async def get_reflection_logs(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
):
    """获取反思日志列表（envelope.data 为列表，与 /questions /proactive 同族契约）"""
    request_id = _get_request_id(request)
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

    # 2026-09-16 契约收口：删除无管理器时编造假反思的回退分支（与 /proactive
    # 2026-09-12 诚实化同规），管理器缺位/无日志均如实返回空列表。
    return envelope(request_id, logs)


@router.post("/reflection", response_model=Dict[str, Any])
async def create_reflection_log(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ReflectionLogCreate = ReflectionLogCreate(content=""),
):
    """创建新的反思日志（envelope.data 为创建后的 ReflectionLog dict）"""
    request_id = _get_request_id(request)

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
        return envelope(request_id, _reflection_entry_to_item(created_entry, agent_id))

    # 管理器缺失时返回请求回显（不落库，诚实响应）
    return envelope(request_id, {
        "log_id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "timestamp": time.time(),
        "reflection_type": body.reflection_type,
        "content": body.content,
        "insights": body.insights,
        "confidence": body.confidence,
        "related_memories": body.related_memories,
    })


@router.get("/reflection/stats")
async def get_reflection_stats(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取反思统计"""
    request_id = _get_request_id(request)
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

    return envelope(request_id, stats)


@router.get("/questions", response_model=Dict[str, Any])
async def get_question_queue(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    answered: Optional[bool] = Query(default=None, description="已回答过滤：true 仅已回答，false 含 pending/cooldown/asked"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
    offset: int = Query(default=0, ge=0, description="偏移量"),
    current_user: dict = Depends(get_current_user),
):
    """获取问题队列（默认返回全部状态，含已提问 asked——主动提问闭环的终态）"""
    request_id = _get_request_id(request)
    agent, user_id = _authorized_question_agent(agent_id, current_user)

    questions = []
    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            from neurova.cognitive_layers.meta_cognition_layer.question_queue import QuestionStatus

            qm = agent.question_queue_manager
            if status:
                try:
                    entries = qm.get_questions_by_status(QuestionStatus(status))
                except ValueError:
                    entries = []
            else:
                entries = _all_questions(qm)
            if answered is not None:
                entries = [e for e in entries if (e.status == QuestionStatus.ANSWERED) == answered]
            entries = [e for e in entries if qm.visible_to(e, agent_id, user_id)]
            questions = [_question_entry_to_item(e, agent_id) for e in entries[offset : offset + limit]]
        except Exception as e:
            logger.warning("Failed to get questions: %s", e)

    # 2026-09-16 契约收口：删除无管理器时编造假问题的回退分支（同 /proactive 诚实化）
    return envelope(request_id, questions)


@router.post("/questions", response_model=Dict[str, Any])
async def add_question(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: QuestionCreate = QuestionCreate(question=""),
    current_user: dict = Depends(get_current_user),
):
    """添加新问题（envelope.data 为创建后的 QuestionItem dict）"""
    request_id = _get_request_id(request)

    agent, user_id = _authorized_question_agent(agent_id, current_user)

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
                metadata={"question_type": body.question_type, "agent_id": agent_id, "user_id": user_id},
            )
            question_id = created_question.id
            timestamp = created_question.created_at
        except Exception as e:
            logger.warning("Failed to add question: %s", e)

    return envelope(request_id, {
        "id": question_id,
        "question_id": question_id,
        "agent_id": agent_id,
        "timestamp": timestamp,
        "created_at": timestamp,
        "question_type": body.question_type,
        "question": body.question,
        "status": "pending",
        "answered": False,
        "answer": None,
        "priority": body.priority,
    })


@router.get("/questions/next")
async def get_next_question(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    current_user: dict = Depends(get_current_user),
):
    """获取下一个待解答问题"""
    request_id = _get_request_id(request)
    agent, user_id = _authorized_question_agent(agent_id, current_user)

    if hasattr(agent, "question_queue_manager") and agent.question_queue_manager:
        try:
            # 根因修复: QuestionEntry dataclass 无法被 FastAPI 序列化 → 转 dict
            question = next((q for q in agent.question_queue_manager.get_pending_questions()
                             if agent.question_queue_manager.visible_to(q, agent_id, user_id)), None)
            if question:
                return envelope(request_id, _question_entry_to_item(question, agent_id))
        except Exception as e:
            logger.warning("Failed to get next question: %s", e)

    return envelope(request_id, None, message="No pending questions")


@router.put("/questions/{question_id}/answer")
async def mark_question_answered(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    question_id: str = Path(..., description="问题ID"),
    answer: str = Query(default="", description="答案"),
    current_user: dict = Depends(get_current_user),
):
    """标记问题已回答"""
    request_id = _get_request_id(request)

    agent, user_id = _authorized_question_agent(agent_id, current_user)

    queue = getattr(agent, "question_queue_manager", None)
    if queue is None:
        raise HTTPException(status_code=503, detail="Question queue unavailable")
    entry = queue.get_question(question_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Question not found")

    if not answer.strip():
        raise HTTPException(status_code=422, detail="Answer must not be empty")
    with queue._lock:
        if not queue.visible_to(entry, agent_id, user_id):
            raise HTTPException(status_code=404, detail="Question not found")
        previous = entry.metadata.get("lesson") or {}
        lesson = previous if previous.get("answer") == answer else {
            "question_id": question_id, "question": entry.content, "answer": answer,
            "agent_id": agent_id, "answerer_id": user_id,
            "neuser_id": current_user.get("neuser_id") or user_id,
            "source": "growth_question", "revision": str(uuid.uuid4()),
        }
        if not queue.mark_answered(question_id, answer, lesson=lesson, require_durable=True):
            raise HTTPException(status_code=503, detail={"answer_saved": False, "retryable": True})
        try:
            published = _get_experience_knowledge_base().publish_growth_lesson(lesson)
        except Exception as e:
            logger.warning("Failed to publish saved growth answer: %s", e)
            raise HTTPException(status_code=503, detail={"answer_saved": True, "publication": "pending", "retryable": True}) from e
    if not published:
        return envelope(request_id, {"question_id": question_id, "answer": answer,
                                     "publication": "indexed", "revision": lesson["revision"]})

    # 2026-09-15 真实化回流：用户对主动提问的回答 → 主动行为标记已回应
    # + 使命感驱动观察（purpose 的真实信号源之一）
    engine = getattr(agent, "proactive_behavior_engine", None)
    if engine:
        try:
            engine.mark_response_received_by_trigger(f"proactive_question:{question_id}")
        except Exception as e:
            logger.debug("主动行为回应回流失败: %s", e)
    ledger = getattr(agent, "intrinsic_motivation", None)
    if ledger:
        try:
            ledger.observe_purpose(contribution=f"主动提问获得回答: {question_id[:8]}", impact=0.8)
        except Exception as e:
            logger.debug("动机 purpose 观察失败: %s", e)

    return envelope(request_id, {"question_id": question_id, "answer": answer},
                    message=f"Question '{question_id}' marked as answered")


@router.get("/proactive", response_model=Dict[str, Any])
async def get_proactive_actions(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取主动行为记录（envelope.data 为列表，与 /reflection /questions 同族契约）"""
    request_id = _get_request_id(request)
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

    # 2026-09-12 诚实化：原实现在无数据时用 uuid 编造 3 条
    # "Proactive message about topic i" mock（活跃假数据违规）。
    # proactive_behavior_engine 全仓未实例化 → 如实返回空列表。
    return envelope(request_id, actions)


@router.post("/proactive", response_model=Dict[str, Any])
async def trigger_proactive_action(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ProactiveActionCreate = ProactiveActionCreate(content=""),
):
    """触发主动行为（真实落账本；未装配引擎诚实 400，不再回显假记录）"""
    request_id = _get_request_id(request)

    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    engine = getattr(agent, "proactive_behavior_engine", None)
    if not engine:
        raise HTTPException(status_code=400, detail="proactive_behavior_engine 未装配，无法记录主动行为")

    action = engine.record_action(
        action_type=body.action_type,
        trigger=body.trigger or "manual",
        content=body.content,
    )
    return envelope(request_id, {
        "action_id": action["action_id"],
        "agent_id": agent_id,
        "timestamp": action["timestamp"],
        "action_type": action["action_type"],
        "trigger": action["trigger"],
        "content": action["content"],
        "success": action["success"],
        "response_received": action["response_received"],
    })


@router.get("/motivation", response_model=Dict[str, Any])
async def get_motivation_level(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取内在动机真实快照（MotivationLedger；未装配返回 data=null，不吐常量假状态）"""
    request_id = _get_request_id(request)
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    ledger = getattr(agent, "intrinsic_motivation", None)
    return envelope(request_id, ledger.snapshot() if ledger else None)


@router.put("/motivation", response_model=Dict[str, Any])
async def update_motivation_level(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: MotivationWeightsUpdate = MotivationWeightsUpdate(),
):
    """更新驱动权重（全量替换语义：传入键=完整分布，未传键置 0，自动归一）"""
    agent = _get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    ledger = getattr(agent, "intrinsic_motivation", None)
    if not ledger:
        raise HTTPException(status_code=400, detail="intrinsic_motivation 未装配，无法调整权重")

    try:
        ledger.update_drive_weights(body.drive_weights)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return await get_motivation_level(request, agent_id)
