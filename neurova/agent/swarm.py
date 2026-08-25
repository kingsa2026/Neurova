"""
SwarmManager — 蜂群编排核心（主 Agent 动态派生子 Agent）

ZCode 式蜂群模型：主 Agent 在对话/工作流中通过 spawn 工具动态派生子 Agent
执行子任务，可并行（多次调用）、可后台（background=True）。

输出双通道回流：
1. 直传（主通道）：最终报告作为工具结果返回主 Agent，同时经 SessionSyncManager
   广播 SUBAGENT_STARTED / SUBAGENT_CHUNK / SUBAGENT_COMPLETED 到聊天会话
   （前端子 Agent 对话小窗的数据源）
2. 池归档（辅助通道）：报告归档进发起者 Agent 的上下文池（EXPERIENCE 源），
   供后续轮次语义召回（活水）

设计约束（AGENTS.md）：
- 深模块：延迟导入 Agent 注册中心（neurova.api.endpoints），避免循环依赖
- 子 Agent 故障隔离：异常捕获为失败结果，不向上抛
- 单例生命周期: get_swarm_manager() / reset_swarm_manager()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 事件发射器签名：(event_type, data) -> None，event_type ∈ {"content", "reasoning"}
StreamEmitter = Callable[[str, Any], None]


@dataclass
class SubAgentRun:
    """一次子 Agent 运行的状态记录"""

    subagent_id: str = field(default_factory=lambda: f"swarm_{uuid.uuid4().hex[:12]}")
    agent_id: str = ""
    agent_name: str = ""
    task: str = ""
    origin: str = "chat"  # chat | workflow
    session_id: Optional[str] = None
    status: str = "pending"  # pending | running | completed | failed
    report: str = ""
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    node_id: Optional[str] = None  # workflow 来源时的节点 id
    execution_id: Optional[str] = None  # workflow 来源时的执行 id

    @property
    def duration(self) -> float:
        if self.finished_at:
            return self.finished_at - self.started_at
        return time.time() - self.started_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subagent_id": self.subagent_id,
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "task": self.task,
            "origin": self.origin,
            "session_id": self.session_id,
            "status": self.status,
            "report": self.report,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "node_id": self.node_id,
            "execution_id": self.execution_id,
        }


class SwarmManager:
    """蜂群管理器：派生、执行、事件广播、结果回流"""

    def __init__(self):
        self._runs: Dict[str, SubAgentRun] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = threading.RLock()

    # ── 公共接口 ──────────────────────────────────────────────

    async def spawn(
        self,
        task: str,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        background: bool = False,
        origin: str = "chat",
        stream: bool = True,
        initiator_agent: Optional[Any] = None,
        node_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """派生子 Agent 执行任务

        Args:
            task: 交给子 Agent 的完整任务描述
            agent_id: 目标子 Agent ID；None 用 default；不存在回退 default
            session_id: 聊天会话 ID（事件广播目标；None 则不广播）
            background: True 后台执行（立即返回 subagent_id）
            origin: 来源（chat | workflow），用于事件追踪
            stream: True 时子 Agent 的 content/reasoning 逐 chunk 广播
            initiator_agent: 发起者 Agent 实例（用于结果归档进其上下文池）
            node_id / execution_id: workflow 来源时的定位信息

        Returns:
            前台: {subagent_id, agent_id, agent_name, status, report, duration, ...}
            后台: {subagent_id, agent_id, agent_name, status: "pending", background: True}
        """
        if not task or not str(task).strip():
            return {"error": "task 不能为空"}

        agent, resolved_id, fallback = self._resolve_agent(agent_id)
        if agent is None:
            return {"error": f"未找到可用的子 Agent（请求: {agent_id or 'default'}）"}

        run = SubAgentRun(
            agent_id=resolved_id,
            agent_name=getattr(agent.config, "name", resolved_id) if hasattr(agent, "config") else resolved_id,
            task=str(task),
            origin=origin,
            session_id=session_id,
            node_id=node_id,
            execution_id=execution_id,
        )
        with self._lock:
            self._runs[run.subagent_id] = run

        if fallback:
            logger.info("Swarm: 请求的 agent_id=%s 不存在，回退到 %s", agent_id, resolved_id)

        if background:
            asyncio_task = asyncio.create_task(
                self._execute(run, agent, initiator_agent, stream)
            )
            with self._lock:
                self._tasks[run.subagent_id] = asyncio_task
            return {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "status": "pending",
                "background": True,
                "hint": "使用 subagent_status 工具查询执行结果",
            }

        await self._execute(run, agent, initiator_agent, stream)
        return run.to_dict()

    def status(self, subagent_id: str) -> Dict[str, Any]:
        """查询子 Agent 运行状态"""
        with self._lock:
            run = self._runs.get(subagent_id)
        if run is None:
            return {"error": f"未找到子 Agent 运行记录: {subagent_id}"}
        return run.to_dict()

    def list_active(self) -> List[Dict[str, Any]]:
        """列出未结束的子 Agent 运行"""
        with self._lock:
            runs = [r for r in self._runs.values() if r.status in ("pending", "running")]
        return [r.to_dict() for r in runs]

    def list_all(self, limit: int = 50) -> List[Dict[str, Any]]:
        """列出全部运行记录（新→旧）"""
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)
        return [r.to_dict() for r in runs[:limit]]

    # ── 内部实现 ──────────────────────────────────────────────

    def _resolve_agent(self, agent_id: Optional[str]) -> tuple:
        """解析子 Agent 实例；请求的 id 不存在时回退 default。

        Returns:
            (agent 实例或 None, resolved_id, 是否发生回退)
        """
        try:
            from neurova.api.endpoints import get_agent_instance

            if agent_id:
                agent = get_agent_instance(agent_id)
                if agent is not None:
                    return agent, agent_id, False

            default_agent = get_agent_instance("default")
            if default_agent is not None:
                return default_agent, "default", bool(agent_id and agent_id != "default")

            # 兜底：注册表中取第一个可用实例
            state = None
            try:
                from neurova.api.endpoints import get_app_state

                state = get_app_state()
            except ImportError:
                pass
            if state:
                agents = state.get("agents", {})
                for aid, inst in agents.items():
                    if inst is not None:
                        return inst, aid, True
        except ImportError:
            logger.warning("Swarm: Agent 注册中心不可用（neurova.api.endpoints 未初始化）")
        return None, agent_id or "default", True

    async def _execute(
        self,
        run: SubAgentRun,
        agent: Any,
        initiator_agent: Optional[Any],
        stream: bool,
    ) -> None:
        """执行子 Agent 任务：广播 STARTED → chat（可流式）→ 广播 COMPLETED → 池归档"""
        run.status = "running"
        await self._broadcast(
            run,
            "subagent_started",
            {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "task": run.task,
                "origin": run.origin,
                "node_id": run.node_id,
                "execution_id": run.execution_id,
            },
        )

        emitter: Optional[StreamEmitter] = None
        if stream:
            emitter = self._make_emitter(run)

        try:
            # [签名约束] Agent.chat(user_input, *, stream, save_memory, session_id,
            # metadata, enable_tts) —— 不接受 temperature/max_tokens，
            # 子 Agent 使用自身 llm_config（独立模型/人设是蜂群的前提）。
            # event_emitter 经 metadata 透传（chat_pipeline._init_agent_state 提取）
            spawn_metadata = {"source": "swarm", "origin": run.origin, "subagent_id": run.subagent_id}
            if emitter is not None:
                spawn_metadata["event_emitter"] = emitter
            response = await agent.chat(
                run.task,
                session_id=None,  # 子 Agent 用独立上下文，不复用主会话历史
                metadata=spawn_metadata,
            )
            report = self._extract_text(response)
            run.report = report
            run.status = "completed"
            run.finished_at = time.time()
        except Exception as e:  # noqa: BLE001 - 子 Agent 故障隔离
            logger.warning("Swarm: 子 Agent %s 执行失败: %s", run.subagent_id, e)
            run.status = "failed"
            run.error = str(e)
            run.finished_at = time.time()

        await self._broadcast(
            run,
            "subagent_completed",
            {
                "subagent_id": run.subagent_id,
                "agent_id": run.agent_id,
                "agent_name": run.agent_name,
                "status": run.status,
                "report": run.report,
                "error": run.error,
                "duration": run.duration,
                "node_id": run.node_id,
                "execution_id": run.execution_id,
            },
        )

        # 双通道之池归档：报告进入发起者上下文池，供后续语义召回
        self._archive_to_pool(initiator_agent, run)

    @staticmethod
    def _extract_text(response: Any) -> str:
        """从 Agent.chat 返回值提取文本（dict{"text"} / str / 对象.content）"""
        if isinstance(response, dict):
            return str(response.get("text", ""))
        if hasattr(response, "content"):
            return str(response.content)
        return str(response) if response is not None else ""

    def _make_emitter(self, run: SubAgentRun) -> StreamEmitter:
        """构造流式发射器：子 Agent 的 content/reasoning chunk → SUBAGENT_CHUNK 事件

        发射器由 ChatPipeline 在异步流式循环中同步调用，此处用 create_task
        调度广播（chunk 级 fire-and-forget 可接受，不阻塞生成循环）。
        """

        def emitter(event_type: str, data: Any) -> None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(
                self._broadcast(
                    run,
                    "subagent_chunk",
                    {
                        "subagent_id": run.subagent_id,
                        "agent_name": run.agent_name,
                        "chunk_type": event_type,
                        "data": data,
                    },
                )
            )

        return emitter

    async def _broadcast(self, run: SubAgentRun, event_name: str, payload: Dict[str, Any]) -> None:
        """向聊天会话广播子 Agent 事件；无 session 或同步管理器不可用时静默跳过"""
        if not run.session_id:
            return
        try:
            from neurova.sync.session_sync_manager import (
                EventType,
                SessionEvent,
                get_session_sync_manager,
            )

            mgr = get_session_sync_manager()
            mgr.register_or_create_session(session_id=run.session_id, user_id="swarm")
            event = SessionEvent(
                event_type=EventType(event_name),
                session_id=run.session_id,
                source_channel="swarm",
                payload=payload,
            )
            await mgr.broadcast_event(run.session_id, event)
        except Exception as e:  # noqa: BLE001 - 广播失败不影响主流程
            logger.debug("Swarm: 事件广播失败 (%s): %s", event_name, e)

    def _archive_to_pool(self, initiator_agent: Optional[Any], run: SubAgentRun) -> None:
        """双通道之池归档：子 Agent 报告进入发起者的上下文池（活水，按需召回）"""
        if initiator_agent is None or run.status != "completed" or not run.report:
            return
        try:
            from neurova.context_pool import ContextInput, ContextSource

            pool = getattr(initiator_agent, "context_pool", None)
            if pool is None:
                return
            content = f"[子Agent报告] {run.agent_name}({run.agent_id}) 关于「{run.task[:80]}」: {run.report[:2000]}"
            pool.add_context(
                ContextInput(source=ContextSource.EXPERIENCE, content=content, priority=70)
            )
            logger.info("Swarm: 子 Agent 报告已归档进发起者上下文池 (%s)", run.subagent_id)
        except Exception as e:  # noqa: BLE001 - 归档失败不影响返回
            logger.debug("Swarm: 报告归档失败: %s", e)


# ── 单例生命周期 ────────────────────────────────────────────────

_swarm_manager_instance: Optional[SwarmManager] = None


def get_swarm_manager() -> SwarmManager:
    global _swarm_manager_instance
    if _swarm_manager_instance is None:
        _swarm_manager_instance = SwarmManager()
    return _swarm_manager_instance


def reset_swarm_manager() -> None:
    global _swarm_manager_instance
    _swarm_manager_instance = None


__all__ = [
    "SubAgentRun",
    "SwarmManager",
    "get_swarm_manager",
    "reset_swarm_manager",
]
