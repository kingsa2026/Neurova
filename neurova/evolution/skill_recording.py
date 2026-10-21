"""技能进化采集的装配（工单 013）。

从 `Agent.init_router` 抽出成独立函数，两个理由：

1. **可测**：注册门原本是 `if self.tool_memory and self._skill_registry:`，
   埋在 init_router 里无法单独证明"四条记账与 tool_memory 无关"。
2. **尺寸棘轮**：`agent_core.py` 受
   `tests/unit/agent/test_agent_core_size_ratchet.py` 约束（只许减不许增），
   装配体的解释性内容必须落在别处。

根因说明：`a.tool_memory` 在 `agent_core.py:590` 先置 None、仅 `:600`
`ToolMemoryIntegration` 构造成功才赋值，而那次构造包在 try/except 里只 warning。
于是"工具记忆子系统可用性"这一件事静默关掉了四条**与它无关**的进化记账
（`skill_improver.record_usage` / `SkillService.record_skill_usage` /
`skill_experience.record_usage` / `genetic_engine.record_reuse`），
使 `AutoSkillImprover` 恒收不到使用数据 → 每轮 0 改进提案。
handler 末段本就有 `if not self.tool_memory: return` 自行分流，外层那颗 AND 门是多余的。
"""

from neurova.core.logger import get_logger
from neurova.evolution.skill_evidence import recordExecutionEvidence, summarizeSkillIO
from neurova.skill_system import SkillEvent

logger = get_logger(__name__)


def recordSkillUsage(agent, skill, result, **kwargs) -> None:
    """把一次技能执行写入进化侧的三本账（失败不影响主流程）。"""
    try:
        from neurova.evolution.skill_experience import get_skill_experience_store
        from neurova.evolution.skill_improver import get_skill_improver
        from neurova.skills.library_service import agentLibrary
        from neurova.skills.skill_contract import resolve_skill_identity

        skill_id = resolve_skill_identity(skill)
        if not skill_id:
            return
        agent_id = agent.config.agent_id
        evidence = recordExecutionEvidence(
            agent_id,
            skill_id,
            user_input=getattr(agent, "_current_user_input", "") or "",
            params=kwargs.get("params"),
            result=result,
            context=kwargs.get("context"),
            trace=kwargs.get("trace"),
        )
        metadata = {
            "agent_id": agent_id,
            "evidence_kind": evidence["evidence_kind"],
            "tool_trace_count": evidence.get("tool_trace_count", 0),
        }
        if evidence.get("evidence_ref"):
            metadata["evidence_ref"] = evidence["evidence_ref"]
        get_skill_improver().record_usage(
            skill_id=skill_id,
            success=bool(result and result.success),
            duration=float(getattr(result, "execution_time", 0.0) or 0.0),
            error_message=str(getattr(result, "error", "") or ""),
            input_summary=evidence["input_summary"],
            output_summary=evidence["output_summary"],
            metadata=metadata,
        )
        agentLibrary(agent_id).record_skill_usage(
            skill_id, success=bool(result and result.success)
        )
        get_skill_experience_store().record_usage(
            skill_id, success=bool(result and result.success)
        )
    except Exception as e:  # noqa: BLE001 - 记账失败不阻断技能执行
        logger.debug("技能使用记录失败: %s", e)


def wire_skill_evolution_recording(agent) -> bool:
    """把技能 POST_EXECUTE 事件接到 Agent 的使用采集 handler。

    真实前置条件只有 SkillRegistry 一项。返回是否完成注册。
    """
    if not agent._skill_registry:
        logger.warning(
            "Agent %s: SkillRegistry 缺席，技能使用采集与进化提案链未启用",
            agent.config.name,
        )
        return False

    agent._skill_registry.register_event_callback(
        SkillEvent.POST_EXECUTE,
        agent._on_skill_post_execute,
    )
    logger.info(
        "Agent %s: 技能进化采集回调已注册（tool_memory=%s）",
        agent.config.name,
        "on" if agent.tool_memory else "off",
    )
    return True
