"""
运行时子代理 (SubAgent)。

对齐升级方案 P1-2.1：Agent.spawn_subagent(role, task) → 独立上下文、可并发。

- SubAgent: 携带角色/任务/独立上下文的可执行单元
- SubAgentManager: spawn 注册 + run_all 并发/顺序执行
- 独立上下文：spawn 时对传入 context 做浅拷贝，子代理内的修改不回泄

设计约束（AGENTS.md）:
- 深模块：不 import Agent；执行体由调用方注入（executor 回调）
- 单例生命周期: get_subagent_manager() / reset_subagent_manager()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# executor 签名：(task, context) -> 任意结果（可为协程函数）
SubAgentExecutor = Callable[[str, Dict[str, Any]], Any]


@dataclass
class SubAgent:
    """一个运行时子代理实例。"""

    role: str
    task: str
    context: Dict[str, Any] = field(default_factory=dict)
    trace_id: Optional[str] = None
    agent_id: str = ""

    def __post_init__(self):
        if not self.agent_id:
            self.agent_id = f"sub-{uuid.uuid4().hex[:12]}"
        # 独立上下文：拷贝一份，修改不泄漏回调用方
        self.context = dict(self.context)
        if self.trace_id:
            self.context.setdefault("trace_id", self.trace_id)

    async def run(self, executor: SubAgentExecutor) -> "SubAgentResult":
        """执行任务；executor 异常捕获为失败结果，不向上抛。"""
        t0 = time.monotonic()
        try:
            outcome = executor(self.task, self.context)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            return SubAgentResult(
                agent_id=self.agent_id,
                role=self.role,
                task=self.task,
                success=True,
                output=outcome,
                duration=time.monotonic() - t0,
                trace_id=self.trace_id,
            )
        except Exception as e:  # noqa: BLE001 - 子代理故障隔离，不影响兄弟任务
            logger.warning("SubAgent %s (%s) 执行失败: %s", self.agent_id, self.role, e)
            return SubAgentResult(
                agent_id=self.agent_id,
                role=self.role,
                task=self.task,
                success=False,
                error=str(e),
                duration=time.monotonic() - t0,
                trace_id=self.trace_id,
            )


@dataclass
class SubAgentResult:
    """子代理执行结果。"""

    agent_id: str
    role: str
    task: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    trace_id: Optional[str] = None


class SubAgentManager:
    """子代理派生与并发编排。"""

    def __init__(self):
        self._spawned: List[SubAgent] = []
        self._lock = threading.RLock()

    def spawn(
        self,
        role: str,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> SubAgent:
        """派生一个子代理并登记。"""
        agent = SubAgent(role=role, task=task, context=context or {}, trace_id=trace_id)
        with self._lock:
            self._spawned.append(agent)
        logger.info("SubAgent 已派生: %s role=%s task=%s", agent.agent_id, role, task)
        return agent

    def list_spawned(self) -> List[SubAgent]:
        with self._lock:
            return list(self._spawned)

    async def run_all(
        self,
        jobs: Sequence[Tuple[SubAgent, SubAgentExecutor]],
        concurrent: bool = True,
    ) -> List[SubAgentResult]:
        """
        执行一组 (子代理, 执行体) 任务。

        Args:
            jobs: (SubAgent, executor) 序列
            concurrent: True 并发（asyncio.gather），False 按序执行

        Returns:
            与 jobs 顺序一致的 SubAgentResult 列表
        """
        if concurrent:
            results = await asyncio.gather(*(agent.run(executor) for agent, executor in jobs))
            return list(results)
        return [await agent.run(executor) for agent, executor in jobs]


# ── 单例生命周期 ────────────────────────────────────────────────

_subagent_manager_instance: Optional[SubAgentManager] = None


def get_subagent_manager() -> SubAgentManager:
    global _subagent_manager_instance
    if _subagent_manager_instance is None:
        _subagent_manager_instance = SubAgentManager()
    return _subagent_manager_instance


def reset_subagent_manager() -> None:
    global _subagent_manager_instance
    _subagent_manager_instance = None


__all__ = [
    "SubAgent",
    "SubAgentResult",
    "SubAgentManager",
    "get_subagent_manager",
    "reset_subagent_manager",
]
