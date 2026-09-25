# -*- coding: utf-8 -*-
"""P10：摘要器降级的**显式位**必须在生产观测面上可读（Issue #90 §13 探针 P10）。

## 先核 B6-8 的读数面（不重复造第二份读数）

B6-8 已交付 `get_context_health()["summarizer"] = {enabled, attempts, last_error}`，
实测（2026-09-26）：

```
健康态: {'enabled': True,  'attempts': 1, 'last_error': None}
降级态: {'enabled': False, 'attempts': 1, 'last_error': 'ModuleNotFoundError: ...'}
```

`get_context_health()` 这一面**已满足**「显式降级并可观测」——不需要新造第二份读数。

## 但它在**生产观测面**上丢了

`/metrics` 的抓取路径 `MetricsCollector.observe_context_health()` 会把
`get_context_health()` 的数值字段搬进 `neurova_context_health_value` gauge。
实测同两个 agent（一个健康、一个装配失败）：

```
neurova_context_health_value{agent="a1",field="attempts",kind="summarizer"} 1.0
neurova_context_health_value{agent="a2",field="attempts",kind="summarizer"} 1.0
```

**两行一模一样**——`enabled` 这个降级位根本没上去，`last_error` 也不上去
（后者是有意的：点名串塞进数字会变成不可判读的编码）。于是只读 `/metrics`
的人看到的是「两个 agent 都 attempts=1」，**分不出谁的能力被关掉了**。
这正是 P2-5 的原始形态换了层皮：「能力被关掉了」与「这轮本来不需要」长得一样。

## 根因（在上游，不在消费方）

导出器的过滤条件是 `isinstance(value, bool) or not isinstance(value, (int, float))`
—— 把**布尔**与**非数值**合成了一条。但布尔**就是**数值：

- `bool` 是 `int` 的子类，`float(True) == 1.0` 无歧义；
- 降级位天然是 0/1 gauge（Prometheus 里标准做法），不是"不可判读的编码"；
- 真正需要排除的是**字符串**（`last_error`），那一条判据本身没错。

把布尔一起丢掉，是过滤条件**过宽**：副作用是所有 `enabled` 位在生产读数上消失
（本仓 `ledger` 与 `summarizer` 两处都带 `enabled`，`fold_resolution` 也带）。
修法是在根因处收窄过滤条件，不是给 summarizer 单开一个 gauge——那是第二份读数。

## 本守卫钉什么

1. 降级位必须出现在 `/metrics` 文本里，且**取值与 `get_context_health()` 一致**；
2. 健康态与降级态在 `/metrics` 上**可分辨**（这是"可观测"的定义本身）；
3. 点名串（`last_error`）仍不得出现在 gauge 里（不引入不可判读的编码）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaP10Bit_"))

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_summarizer_degradation_bit_observable.py"


def _agentShell(agentId: str):
    """与 `agent_core` 构造面同型的真 Agent 壳（`__new__` + 成员，不跑全量 init）。"""
    from neurova.agent_core import Agent

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = agentId
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.user_id = "u-p10"
    agent.agent_id = agentId
    agent.question_queue_manager = None
    return agent


#: gauge 是进程级单例：每个用例用**独立 agent id**，读数才不串用例
#: （Prometheus 的 label 不会因为重复 set 而重置，同名会读到上一个用例的值）。
def _healthy(tag: str):
    from neurova.context.orchestrator import ContextOrchestrator

    agent = _agentShell(f"a-p10-healthy-{tag}")
    orch = ContextOrchestrator(agent, use_pool=True)
    agent.context_orchestrator = orch
    return agent, orch


def _degraded(tag: str):
    """真装配失败形状：`SummarizingCompressor` 导入被拦（B6-8 的原路径）。"""
    from neurova.context.orchestrator import ContextOrchestrator

    agent = _agentShell(f"a-p10-degraded-{tag}")
    with patch.dict("sys.modules", {"neurova.context.summarizing_compressor": None}):
        orch = ContextOrchestrator(agent, use_pool=True)
    agent.context_orchestrator = orch
    return agent, orch


def _scrape(agents):
    from neurova.core.metrics import generate_metrics_text, get_metrics

    class _State:
        pass

    state = _State()
    state.agents = agents
    get_metrics().observe_context_health(state)
    return generate_metrics_text()


def _summarizerLines(text: str):
    return [
        line
        for line in text.splitlines()
        if line.startswith("neurova_context_health_value{") and 'kind="summarizer"' in line
    ]


class TestDegradationBitReachesTheScrapeFace:
    def test_enabled_bit_is_exported(self):
        agent, orch = _healthy("exported")
        text = _scrape({agent.agent_id: agent})
        fields = {
            line.split('field="', 1)[1].split('"', 1)[0]
            for line in _summarizerLines(text)
            if f'agent="{agent.agent_id}"' in line
        }
        assert "enabled" in fields, (
            f"降级位没上 /metrics —— 只读观测面的人分不出能力开没开。"
            f"实测导出的字段：{sorted(fields)}\n"
            "根因在导出器的过滤条件（把 bool 与字符串合成了一条），"
            "不是缺一个 summarizer 专属 gauge。"
        )
        assert orch.get_context_health()["summarizer"]["enabled"] is True

    def test_degraded_and_healthy_are_distinguishable(self):
        """「可观测」的定义本身：两种状态在 /metrics 上必须取到不同的值。"""
        healthyAgent, _orchA = _healthy("cmp")
        degradedAgent, _orchB = _degraded("cmp")
        text = _scrape({
            healthyAgent.agent_id: healthyAgent,
            degradedAgent.agent_id: degradedAgent,
        })

        def _value(agent: str) -> float:
            for line in _summarizerLines(text):
                if f'agent="{agent}"' in line and 'field="enabled"' in line:
                    return float(line.rsplit(" ", 1)[1])
            raise AssertionError(
                f"{agent} 的 summarizer.enabled 没出现在 /metrics 里：\n  "
                + "\n  ".join(_summarizerLines(text))
            )

        healthy, degraded = (
            _value(healthyAgent.agent_id),
            _value(degradedAgent.agent_id),
        )
        assert healthy == 1.0 and degraded == 0.0, (
            f"健康态={healthy} 降级态={degraded} —— 两态在观测面上没分开，"
            "等于降级不可观测（P2-5 的形态换了一层皮）。"
        )

    def test_exported_bit_matches_the_readout_face(self):
        """取值必须与单源读数一致：不一致就是第二份读数。"""
        agent, orch = _degraded("match")
        text = _scrape({agent.agent_id: agent})
        expected = 1.0 if orch.get_context_health()["summarizer"]["enabled"] else 0.0
        got = [
            float(line.rsplit(" ", 1)[1])
            for line in _summarizerLines(text)
            if f'agent="{agent.agent_id}"' in line and 'field="enabled"' in line
        ]
        assert got and got[0] == expected, (
            f"gauge 值 {got} 与 `get_context_health()['summarizer']['enabled']`"
            f"（{expected}）不一致 —— 观测面与读数面不同源。"
        )


class TestNamedErrorsStayOutOfGauges:
    """反向控制：点名串（`last_error`）不得落 gauge。

    它们是**不可判读的编码** —— 把 "ModuleNotFoundError: ..." 塞进一个数字
    会让读数失去意义。收窄过滤条件时要保证这条纪律没被破。
    """

    def test_last_error_is_not_exported_as_a_gauge(self):
        agent, _orch = _degraded("noleak")
        text = _scrape({agent.agent_id: agent})
        offenders = [
            line
            for line in _summarizerLines(text)
            if "last_error" in line and f'agent="{agent.agent_id}"' in line
        ]
        assert not offenders, (
            "点名串被落进了 gauge（读数字段不该承载异常消息）：\n  "
            + "\n  ".join(offenders)
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in PROTECTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
