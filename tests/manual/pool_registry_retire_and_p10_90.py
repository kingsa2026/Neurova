#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · B6-10 批次 E/F + 探针 P10）：真链路自证。

跑的是真生产对象，不是单测替身：

A) 门面层已退场，而 `build_system_prompt` 仍跑得通：
   真 `Agent`（`agent_core` 同型成员）→ 真 `ContextOrchestrator` → 直调同步方法；
B) 池注册表只剩单池读侧：真编排器构造池（就地 `adopt`）→ `get_context_pool`
   按身份取回**同一实例**；多池机制已不在类上；
C) 探针 P10：真 `MetricsCollector.observe_context_health()` → 真 `/metrics` 文本，
   健康/降级两态在观测面上**可分辨**。

跑法：`PYTHONPATH=. python tests/manual/pool_registry_retire_and_p10_90.py`
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaBatchEF90_"))


def _agentShell(agentId: str):
    from neurova.agent_core import Agent

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = agentId
    agent.config.constitution = ""
    # 与 AgentConfig 默认同型（`build_system_prompt` 的「行为规则」段靠它出现）
    agent.config.behavior_rules = ["- 始终使用中文交流", "- 保持温和、友善的语气"]
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.user_id = "u-live"
    agent.agent_id = agentId
    agent.question_queue_manager = None
    agent.soul = "你是 live-verify 助手"
    agent.personality = ""
    return agent


def main() -> int:
    print("A) 门面层退场，工具方法跑得通")
    assert not (PROJECT_ROOT / "neurova/context/context_facade.py").exists(), (
        "门面模块仍在仓"
    )
    from neurova.agent_core import Agent
    from neurova.context.orchestrator import ContextOrchestrator

    agent = _agentShell("a-live-E")
    orch = ContextOrchestrator(agent, use_pool=True)
    prompt = orch.build_system_prompt()
    print(f"   build_system_prompt 首行 = {prompt.splitlines()[0][:40]!r}")
    assert prompt.strip(), "工具方法直调返回空串 —— 保留它的依据失效"
    for leg in ("行为规则", "中文交流"):
        assert leg in prompt, f"契约腿 {leg!r} 不在真面 prompt 里"
    print("   契约腿（行为规则 / 中文交流）在真面上仍在")

    print("B) 池注册表只剩单池读侧")
    from neurova.context_pool import get_context_pool
    from neurova.context_pool_registry import ContextPoolRegistry, get_registry

    leftover = [
        name
        for name in ("get_or_create", "query_agent", "list_sessions", "clear_session", "get_pool_count")
        if hasattr(ContextPoolRegistry, name)
    ]
    print(f"   多池机制遗留 = {leftover}")
    assert not leftover, f"多池机制仍在：{leftover}"

    registry = get_registry()
    pool = getattr(orch, "context_pool", None)
    assert pool is not None, "编排器未构造池（前置不成立）"
    found = get_context_pool(user_id="u-live", agent_id="a-live-E")
    print(f"   按身份取回同一实例 = {found is pool}")
    assert found is pool, "按身份取不回同一实例 —— 单池读侧接线被破坏"
    print(f"   登记池数 = {len(registry._pools)}")

    print("C) 探针 P10：降级位在 /metrics 上可分辨")
    healthyAgent = _agentShell("a-live-p10-healthy")
    healthyOrch = ContextOrchestrator(healthyAgent, use_pool=True)
    healthyAgent.context_orchestrator = healthyOrch

    degradedAgent = _agentShell("a-live-p10-degraded")
    with patch.dict("sys.modules", {"neurova.context.summarizing_compressor": None}):
        degradedOrch = ContextOrchestrator(degradedAgent, use_pool=True)
    degradedAgent.context_orchestrator = degradedOrch

    class _State:
        agents = {
            "a-live-p10-healthy": healthyAgent,
            "a-live-p10-degraded": degradedAgent,
        }

    from neurova.core.metrics import generate_metrics_text, get_metrics

    get_metrics().observe_context_health(_State())
    lines = [
        line
        for line in generate_metrics_text().splitlines()
        if line.startswith("neurova_context_health_value{")
        and 'kind="summarizer"' in line
        and 'field="enabled"' in line
    ]
    for line in lines:
        print(f"   {line}")
    values = {
        line.split('agent="', 1)[1].split('"', 1)[0]: float(line.rsplit(" ", 1)[1])
        for line in lines
    }
    assert values.get("a-live-p10-healthy") == 1.0, f"健康态位不是 1：{values}"
    assert values.get("a-live-p10-degraded") == 0.0, f"降级态位不是 0：{values}"
    print("   两态取值不同 → 只读 /metrics 也能分辨降级")

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
