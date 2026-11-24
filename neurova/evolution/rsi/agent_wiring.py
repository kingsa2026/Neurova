"""Agent ↔ RSI 装配线（R1）。

为什么从 `agent_core.Agent._init_cognitive_graph` 迁出到独立模块：

1. **时序缺陷**（2026-11-21 live-verify 实证，与生产 rsi_summaries.jsonl 1018 轮
   `placeholder_systems=["experience","tool_memory"]` 完全吻合）：RSI 原在
   cognitive-graph 段装配，而 `a.tool_memory` 在其后才赋值、`a.evolution` 单例
   要到 `init_evolution` 才存在 ⇒ RSI 眼里 experience/tool_memory 两族**恒为
   占位替身**，参数面从源头缺失，步进候选永产不出（no_candidate/placeholder_host）。
2. **尺寸棘轮**：agent_core 只降不升，装配逻辑落独立模块，不回填。

调用时序：`SubSystemContainer.init_evolution()` 在 memory（含 tool_memory 赋值）
与 evolution 单例之后运行——本函数被调用时四闭环系统全部就位。
"""

from __future__ import annotations

from neurova.core.logger import get_logger

logger = get_logger(__name__)


def wireAgentRsi(agent) -> None:
    """装配 agent 的 RSI 编排器并注入 evolution 单例（根因 3 的接线唯一落点）。

    - 四大闭环系统按当下实况取用：缺席者以 `_NullSystem` 占位（只供中性信号、
      不供参数面，工单 018 契约不变）；
    - 至少一个闭环系统可用才装配（全缺席装配一个只会空转的编排器没有意义）；
    - 装配成功即注入 `evolution.rsi_orchestrator`，经验/工具/记忆信号从此能
      触发递归进化（缺注入 = 经验→RSI 闭环死路，见根因 3 工单）。
    """
    from neurova.agent_core import _NullSystem

    # 部分初始化的 agent（如测试桩）可能缺任一属性——一律 getattr 探测，
    # 不假设装配面完整；日志标签取不到就用 agent_id/类名兜底。
    config = getattr(agent, "config", None)
    label = (getattr(config, "name", None) or getattr(config, "agent_id", None)
             or type(agent).__name__)

    agent.rsi_orchestrator = None
    try:
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        # 获取四大闭环系统（此刻 tool_memory 与 evolution 单例均已就位）
        sleep_system = getattr(agent, "sleep_consolidation", None)
        memory_manager = getattr(agent, "memory_manager", None)
        emotion_system = (
            getattr(memory_manager, "_emotion_module", None) if memory_manager else None
        )
        evolution = getattr(agent, "evolution", None)
        experience_system = getattr(evolution, "experience_feedback", None) if evolution else None
        tool_memory_system = getattr(agent, "tool_memory", None)

        # 只有当至少一个闭环系统可用时才初始化 RSI
        available_systems = [
            s for s in [sleep_system, emotion_system, experience_system, tool_memory_system]
            if s is not None
        ]
        if not available_systems:
            logger.info("Agent %s: RSI 未初始化（无可用闭环系统）", label)
            return

        # 情感保护桥（RSI 活表收尾）：EmotionModule 的保护参数此前
        # 零消费——衰减真正发生在 a.temperature_engine（默认参数构造），
        # 装桥后 RSI 调整经 setter 转发到引擎（factor/threshold 激活）
        if emotion_system is not None and hasattr(emotion_system, "attach_temperature_engine"):
            emotion_system.attach_temperature_engine(getattr(agent, "temperature_engine", None))

        agent.rsi_orchestrator = RSIOrchestrator(
            sleep_system=sleep_system or _NullSystem(),
            emotion_system=emotion_system or _NullSystem(),
            experience_system=experience_system or _NullSystem(),
            tool_memory_system=tool_memory_system or _NullSystem(),
            agent_id=str(getattr(config, "agent_id", "") or ""),
        )
        # P1-3：世代编排器挂接（世代账本+门禁链+影子验证接进 RSI 迭代）。
        # 可选件：装配失败只降级为"无世代管线"（generationOrchestrator 保持
        # None，RSI 零行为变化），不阻断 agent 构造与生产 chat 链路。
        try:
            from neurova.evolution.rsi.generation_orchestrator import (
                GenerationOrchestrator,
            )

            generationOrchestrator = GenerationOrchestrator(
                rsiOrchestrator=agent.rsi_orchestrator
            )
            agent.rsi_orchestrator.generationOrchestrator = generationOrchestrator
            # P0-③ 断点续跑：装配即从世代账本重放在途状态（canary 观测窗重挂、
            # 轮次→世代门禁可见性恢复、上代进程孤儿影子根清扫）。失败不阻断装配。
            try:
                generationOrchestrator.resumeInterrupted()
            except Exception as e:  # noqa: BLE001 - 续跑失败按无在途运行
                logger.warning(
                    "Agent %s: 世代管线断点续跑失败（按无在途运行）: %s", label, e
                )
        except Exception as e:  # noqa: BLE001 - 世代管线缺席不阻断 RSI
            logger.warning(
                "Agent %s: 世代编排器装配失败（RSI 无世代管线运行）: %s", label, e
            )
        logger.info(
            "Agent %s: RSI 编排器已初始化 (%s/4 闭环系统可用)",
            label, len(available_systems),
        )
    except Exception as e:  # noqa: BLE001 - RSI 装配失败不阻断 agent 构造
        logger.warning("Agent %s: RSI 初始化失败: %s", label, e)
        return

    # 根因 3 修复: 将 RSI 注入到 evolution 单例, 让经验/工具/记忆信号能触发递归进化
    evolution = getattr(agent, "evolution", None)
    if evolution is not None:
        evolution.rsi_orchestrator = agent.rsi_orchestrator
        logger.info(
            "Agent %s: RSI 已注入到 EvolutionOrchestrator 单例, 闭环已激活",
            label,
        )
