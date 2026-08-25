"""
AgentTeam 多角色编排。

对齐升级方案 P1-2.1：复用 collaboration_template.AgentRole 角色定义，
把「同一实例多角色」升级为基于 ACP 消息协议的多 agent 协作：

- add_member: 成员注册（角色 + ACP handler）
- orchestrate: 按步骤序列派发 task_assignment 消息，收集 task_result
- 全编排共享一个 trace_id，贯穿所有消息

设计约束（AGENTS.md）:
- 深模块：不 import Agent；成员执行体以 ACP handler 注入
- 每步失败不中断后续步骤（容错编排）
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from neurova.agent.protocols.acp_runtime import ACPRuntime, DeliveryStatus
from neurova.agent.protocols.message_protocol import AgentMessage, MessageType
from neurova.agent.templates.collaboration_template import AgentRole

logger = logging.getLogger(__name__)


@dataclass
class TeamStepResult:
    """单步编排结果。"""

    role: AgentRole
    action: str
    agent_id: Optional[str] = None
    success: bool = False
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class TeamOrchestrationResult:
    """一次完整编排的结果。"""

    goal: str
    trace_id: Optional[str] = None
    steps: List[TeamStepResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.steps) and all(s.success for s in self.steps)


@dataclass
class _Member:
    role: AgentRole
    handler: Callable


class AgentTeam:
    """基于 ACP 协议的多角色团队。"""

    def __init__(self, runtime: Optional[ACPRuntime] = None, team_id: Optional[str] = None):
        self.team_id = team_id or f"team-{uuid.uuid4().hex[:8]}"
        self._runtime = runtime or ACPRuntime()
        self._members: Dict[str, _Member] = {}

    # ── 成员管理 ────────────────────────────────────────────────

    def add_member(self, agent_id: str, role: AgentRole, handler: Callable) -> None:
        """注册成员：角色元数据 + ACP 消息处理器。"""
        self._members[agent_id] = _Member(role=role, handler=handler)
        self._runtime.register_agent(agent_id, handler)

    def remove_member(self, agent_id: str) -> None:
        self._members.pop(agent_id, None)
        self._runtime.unregister_agent(agent_id)

    def get_role_agents(self, role: AgentRole) -> List[str]:
        return [aid for aid, m in self._members.items() if m.role == role]

    def list_members(self) -> Dict[str, str]:
        return {aid: m.role.value for aid, m in self._members.items()}

    # ── 编排 ────────────────────────────────────────────────────

    async def orchestrate(
        self,
        goal: str,
        steps: Sequence[Dict[str, Any]],
        step_timeout: float = 30.0,
    ) -> TeamOrchestrationResult:
        """
        按步骤序列编排任务。

        Args:
            goal: 本次协作的总目标（写入每条消息 metadata）
            steps: [{"role": AgentRole, "action": str, "params": {...}}, ...]
            step_timeout: 单步等待响应超时（秒）

        Returns:
            TeamOrchestrationResult；单步失败记录错误并继续后续步骤。
        """
        trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        outcome = TeamOrchestrationResult(goal=goal, trace_id=trace_id)

        for raw_step in steps:
            role = raw_step.get("role")
            action = raw_step.get("action", "")
            params = raw_step.get("params") or {}

            candidates = self.get_role_agents(role)
            if not candidates:
                logger.warning("编排缺员: 角色 %s 无成员，步骤 '%s' 记为失败", role, action)
                outcome.steps.append(
                    TeamStepResult(
                        role=role,
                        action=action,
                        success=False,
                        error=f"角色 {role.value if isinstance(role, AgentRole) else role} 无可用成员",
                    )
                )
                continue

            assignee = candidates[0]
            message = AgentMessage(
                sender_id=self.team_id,
                sender_name="agent-team",
                receiver_id=assignee,
                type=MessageType.TASK_ASSIGNMENT,
                action=action,
                params=params,
                data={"goal": goal},
                trace_id=trace_id,
                metadata={"team_id": self.team_id},
            )

            reply = await self._runtime.request(message, timeout=step_timeout)
            if reply is not None:
                # create_response 的 result 直接放入 data，且可能为任意类型
                # （字符串/字典等）；非字典结果统一包一层便于下游消费
                data = reply.data
                step_result = dict(data) if isinstance(data, dict) else {"value": data}
                outcome.steps.append(
                    TeamStepResult(
                        role=role,
                        action=action,
                        agent_id=assignee,
                        success=True,
                        result=step_result,
                        error=(reply.metadata or {}).get("error"),
                    )
                )
            else:
                stats = self._runtime.get_stats()
                outcome.steps.append(
                    TeamStepResult(
                        role=role,
                        action=action,
                        agent_id=assignee,
                        success=False,
                        error=f"步骤无响应或派发失败（sent={stats['sent']}）",
                    )
                )

        logger.info(
            "AgentTeam %s 编排完成: goal=%s steps=%d/%d 成功",
            self.team_id,
            goal,
            sum(1 for s in outcome.steps if s.success),
            len(outcome.steps),
        )
        return outcome


__all__ = ["AgentTeam", "TeamStepResult", "TeamOrchestrationResult"]
