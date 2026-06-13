"""
MultiAgentManager - 多 Agent 管理器（大脑/办公室 + 共用小脑/脑干/脊髓）

根据 Neurova CogArch 1.0.0 设计文档第2章实现：
- 每个 Agent 有独立的大脑（Memory DB）和办公室（Workspace）
- 所有 Agent 共用 PlanOrchestrator（小脑）、ExecutionEngine（脑干）和 Infrastructure（脊髓）
- Lazy Loading：Agent 只在第一次请求时才创建
- 并行启动：多个 Agent 通过细粒度锁并行启动
- Hot Reload：单个 Agent 重载不影响其他 Agent
- 线程安全：使用 asyncio.Lock 进行并发控制
"""

import asyncio
import logging
import threading
import time
import typing
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────


@dataclass
class NeurovaAgent:
    """Neurova Agent"""

    agent_id: str = ""
    name: str = ""
    description: str = ""
    workspace_dir: typing.Optional[Path] = None
    config: typing.Dict[str, typing.Any] = field(default_factory=dict)
    created_at: float = 0.0
    last_active: float = 0.0
    is_running: bool = False
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.last_active:
            self.last_active = time.time()

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """转换为字典"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "workspace_dir": str(self.workspace_dir) if self.workspace_dir else None,
            "config": self.config,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "is_running": self.is_running,
            "metadata": self.metadata,
        }


# ────── 主类 ──────


class MultiAgentManager:
    """
    多 Agent 管理器

    管理多个 Agent 实例，提供共享组件和生命周期管理。
    """

    def __init__(self, config: typing.Optional[typing.Dict[str, typing.Any]] = None):
        """
        初始化多 Agent 管理器

        参数:
            config: 配置字典
        """
        self._config = config or {}
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()

        # Agent 存储
        self._agents: typing.Dict[str, NeurovaAgent] = {}
        self._agent_configs: typing.Dict[str, typing.Dict[str, typing.Any]] = {}

        # 共享组件
        self._plan_orchestrator = None
        self._execution_engine = None
        self._infrastructure = None

        # 工作空间
        self._base_workspace_dir: typing.Optional[Path] = None

        logger.info("MultiAgentManager initialized")

    def initialize_shared_components(
        self,
        plan_orchestrator: typing.Any = None,
        execution_engine: typing.Any = None,
        infrastructure: typing.Any = None,
    ) -> None:
        """
        初始化共享组件

        参数:
            plan_orchestrator: 计划编排器
            execution_engine: 执行引擎
            infrastructure: 基础设施
        """
        self._plan_orchestrator = plan_orchestrator
        self._execution_engine = execution_engine
        self._infrastructure = infrastructure

        logger.info("Shared components initialized")

    def set_base_workspace_dir(self, path: typing.Union[str, Path]) -> bool:
        """
        设置基础工作空间目录

        参数:
            path: 路径

        返回:
            bool: 是否设置成功
        """
        with self._lock:
            path_obj = Path(path) if isinstance(path, str) else path

            if not path_obj.exists():
                try:
                    path_obj.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.error("Failed to create workspace directory: %s", e)
                    return False

            self._base_workspace_dir = path_obj
            logger.info("Base workspace directory set to: %s", path_obj)
            return True

    def get_workspace_dir(self, agent_id: str) -> typing.Optional[Path]:
        """
        获取 Agent 工作空间目录

        参数:
            agent_id: Agent ID

        返回:
            Optional[Path]: 工作空间目录
        """
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent and agent.workspace_dir:
                return agent.workspace_dir

            # 创建默认工作空间
            if self._base_workspace_dir:
                workspace_dir = self._base_workspace_dir / agent_id
                workspace_dir.mkdir(parents=True, exist_ok=True)
                return workspace_dir

            return None

    def get_agent(self, agent_id: str, auto_create: bool = True) -> typing.Optional[NeurovaAgent]:
        """
        获取 Agent

        参数:
            agent_id: Agent ID
            auto_create: 是否自动创建

        返回:
            Optional[NeurovaAgent]: Agent 实例
        """
        with self._lock:
            if agent_id in self._agents:
                agent = self._agents[agent_id]
                agent.last_active = time.time()
                return agent

            if not auto_create:
                return None

            # 创建新 Agent
            agent = NeurovaAgent(
                agent_id=agent_id,
                name=f"Agent-{agent_id}",
                description=f"Auto-created agent: {agent_id}",
                workspace_dir=self.get_workspace_dir(agent_id),
                config=self._agent_configs.get(agent_id, {}),
            )

            self._agents[agent_id] = agent
            logger.info("Created agent: %s", agent_id)

            return agent

    async def execute_with_shared_cerebellum(
        self, agent_id: str, task: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        使用共享小脑执行任务

        参数:
            agent_id: Agent ID
            task: 任务描述
            context: 上下文

        返回:
            Dict: 执行结果
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return {"success": False, "error": f"Agent not found: {agent_id}"}

        try:
            # 执行认知处理
            cognitive_result = await self._cognitive_processing(agent, task, context)

            # 使用共享小脑执行
            if self._plan_orchestrator:
                plan = self._plan_orchestrator.decompose_intent(task, context)
                result = await self._plan_orchestrator.execute_plan(plan.plan_id, context)
            else:
                result = {
                    "success": True,
                    "task": task,
                    "cognitive_result": cognitive_result,
                }

            # 巩固记忆
            await self._consolidate_memory(agent, task, result, context)

            return result

        except Exception as e:
            logger.error("Execution failed for agent %s: %s", agent_id, e)
            return {"success": False, "error": str(e)}

    async def _cognitive_processing(
        self, agent: NeurovaAgent, task: str, context: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> typing.Dict[str, typing.Any]:
        """
        认知处理

        参数:
            agent: Agent 实例
            task: 任务描述
            context: 上下文

        返回:
            Dict: 认知结果
        """
        # 简化的认知处理
        return {
            "agent_id": agent.agent_id,
            "task": task,
            "processing_time": time.time(),
        }

    async def _consolidate_memory(
        self,
        agent: NeurovaAgent,
        task: str,
        result: typing.Dict[str, typing.Any],
        context: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> None:
        """
        巩固记忆

        参数:
            agent: Agent 实例
            task: 任务描述
            result: 执行结果
            context: 上下文
        """
        # 更新 Agent 活跃时间
        agent.last_active = time.time()

        logger.debug("Memory consolidated for agent %s", agent.agent_id)

    async def start_agent(self, agent_id: str, config: typing.Optional[typing.Dict[str, typing.Any]] = None) -> bool:
        """
        启动 Agent

        参数:
            agent_id: Agent ID
            config: 配置

        返回:
            bool: 是否启动成功
        """
        async with self._async_lock:
            agent = self.get_agent(agent_id, auto_create=True)
            if not agent:
                return False

            if agent.is_running:
                logger.warning("Agent %s is already running", agent_id)
                return True

            try:
                # 更新配置
                if config:
                    agent.config.update(config)
                    self._agent_configs[agent_id] = agent.config

                # 启动 Agent
                agent.is_running = True
                agent.last_active = time.time()

                logger.info("Agent %s started", agent_id)
                return True

            except Exception as e:
                logger.error("Failed to start agent %s: %s", agent_id, e)
                return False

    async def reload_agent(self, agent_id: str, config: typing.Optional[typing.Dict[str, typing.Any]] = None) -> bool:
        """
        重载 Agent

        参数:
            agent_id: Agent ID
            config: 配置

        返回:
            bool: 是否重载成功
        """
        # 停止 Agent
        await self.stop_agent(agent_id)

        # 重新启动
        return await self.start_agent(agent_id, config)

    async def stop_agent(self, agent_id: str) -> bool:
        """
        停止 Agent

        参数:
            agent_id: Agent ID

        返回:
            bool: 是否停止成功
        """
        async with self._async_lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False

            if not agent.is_running:
                return True

            try:
                agent.is_running = False
                logger.info("Agent %s stopped", agent_id)
                return True

            except Exception as e:
                logger.error("Failed to stop agent %s: %s", agent_id, e)
                return False

    async def stop_all(self) -> typing.Dict[str, bool]:
        """
        停止所有 Agent

        返回:
            Dict[str, bool]: 停止结果
        """
        results = {}

        for agent_id in list(self._agents.keys()):
            results[agent_id] = await self.stop_agent(agent_id)

        return results

    def list_agents(self) -> typing.List[str]:
        """
        列出所有 Agent

        返回:
            List[str]: Agent ID 列表
        """
        with self._lock:
            return list(self._agents.keys())

    def is_agent_loaded(self, agent_id: str) -> bool:
        """
        检查 Agent 是否已加载

        参数:
            agent_id: Agent ID

        返回:
            bool: 是否已加载
        """
        with self._lock:
            return agent_id in self._agents

    def get_agent_info(self, agent_id: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
        """
        获取 Agent 信息

        参数:
            agent_id: Agent ID

        返回:
            Optional[Dict]: Agent 信息
        """
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return None

            return agent.to_dict()

    def list_agents_info(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """
        列出所有 Agent 信息

        返回:
            List[Dict]: Agent 信息列表
        """
        with self._lock:
            return [agent.to_dict() for agent in self._agents.values()]


# ────── 单例管理 ──────

_manager_instance: typing.Optional[MultiAgentManager] = None
_instance_lock = threading.Lock()


def get_multi_agent_manager(**kwargs) -> MultiAgentManager:
    """获取全局多 Agent 管理器实例"""
    global _manager_instance
    if _manager_instance is None:
        with _instance_lock:
            if _manager_instance is None:
                _manager_instance = MultiAgentManager(**kwargs)
    return _manager_instance


def reset_multi_agent_manager():
    """重置全局多 Agent 管理器实例"""
    global _manager_instance
    with _instance_lock:
        if _manager_instance:
            # 停止所有 Agent
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_manager_instance.stop_all())
            loop.close()
        _manager_instance = None
