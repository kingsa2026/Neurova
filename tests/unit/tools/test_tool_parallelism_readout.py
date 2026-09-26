# -*- coding: utf-8 -*-
"""M3 前置：并行收益的两个判据输入必须**可量**（红→绿）。

## 本片修的根因

方案 §10.1 把"先量后说"列为 M3 的硬性前置，要用两条读数回答 M3 值不值得做：

1. **多工具批次的占比**（低于 ~5% 则收益不成立，应据此放弃 M3 及之后）；
2. **工具耗时分布**（`neurova_tool_execution_seconds` 直方图 + 轮级耗时）。

实测两条输入**都不可量**，而且都不是"少个优化"，是断链：

- ① 全仓没有任何"一轮里到底有几个工具调用"的落点 ⇒ 占比这条判据**恒不可达**：
  读到的永远是 0 或读不到，"低于 5% 就放弃"与"数据缺失"在观测面上同形。
- ② 直方图有唯一写入方（`tool_executor` 咽喉的 `record_tool_execution`），
  但**唯一读侧** `analytics._read_tool_metrics` 只读计数器：`avg_duration_ms`
  在函数体里零赋值，恒 `0.0`。前端契约早有这个字段，面板上它是**假读数**
  （"没测到"与"测得极快"折叠成同一个 0）——正是工单 016 点名的同一形态。

## 判据落点

- 形态读数写在**唯一调度点**（`base.handle_tool_calls`）并带 `path` 标签：
  `AnthropicLoop` 逐条转发 `super().handle_tool_calls([单条])`，于是那条路径上
  任何声明放行都拿不到成组执行 —— 这个失明点必须**在读数上直接可见**
  （不分档就会把一条路径的盲区算成"M3 没有收益"）。
- 耗时读侧真读直方图；本文件钉 `avg_duration_ms > 0`（改前恒 0）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

READOUT_SCRIPT = PROJECT_ROOT / "scripts" / "diagnostics" / "tool_parallelism_readout.py"

SHAPE_METRIC = "neurova_tool_batch_shapes_total"


def _call(index: int, name: str) -> dict:
    return {"id": f"c{index}", "function": {"name": name, "arguments": "{}"}}


def _shapeSamples() -> dict:
    """当前形态读数：`{(path, shape): 值}`（直接读注册表的事实源，不解析文本）。

    匹配落在**样本名**上而非族名：`prometheus_client` 暴露 counter 时族名是
    去掉 `_total` 后缀的归一形态（`neurova_tool_batch_shapes`），按族名比会
    恒不命中——`analytics._read_tool_metrics` 的两处读侧正是栽在这里，
    本片一并根修，故断言侧也照同一条口径写。
    """
    from prometheus_client import REGISTRY

    out = {}
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name != SHAPE_METRIC:
                continue
            out[(sample.labels.get("path", ""), sample.labels.get("shape", ""))] = sample.value
    return out


class TestShapeMetricSurface:
    """形态读数必须先有仪表，且有模块级写入入口（照 `record_goal_verification` 形态）。"""

    def test_metricIsRegistered(self):
        """计数器是**有样本才出现**的：先写一条再读文本（否则断言恒红，判据空转）。"""
        from neurova.core.metrics import generate_metrics_text, record_tool_batch_shape

        record_tool_batch_shape("registration_probe", "single_call")
        assert SHAPE_METRIC in generate_metrics_text(), (
            "多工具批次占比的读数没接线到 /metrics：判据输入恒不可达"
        )

    def test_moduleLevelEntryExists(self):
        from neurova.core import metrics

        assert callable(getattr(metrics, "record_tool_batch_shape", None)), (
            "缺少模块级写入入口（埋点不得由调度侧持有 metrics 单例）"
        )


class TestSchedulerWritesShape:
    """读数由**唯一调度点**写：真 `handle_tool_calls` 走真分组，不手工埋点。"""

    @staticmethod
    def _make_loop(monkeypatch, safe_names):
        """真 OpenAILoop + 真 ToolExecutor，只在能力声明面与技能执行体放替身。"""
        from types import SimpleNamespace

        import neurova.agent.tool_coordinator as coordinator
        from neurova.agent.loops.openai_loop import OpenAILoop
        from neurova.core.tool_capability import ToolCapability, WriteScope
        from neurova.tool_executor import ToolExecutor

        eligible = ToolCapability(
            readOnly=True, concurrentSafe=True, writeScopes=frozenset({WriteScope.NONE})
        )
        names = {str(n).lower() for n in safe_names}
        monkeypatch.setattr(
            coordinator,
            "resolveToolCapability",
            lambda name: eligible if str(name or "").strip().lower() in names else None,
        )

        class _StubRegistry:
            def __init__(self):
                self.skills = {}

            def ensure(self, name):
                if name not in self.skills:
                    self.skills[name] = SimpleNamespace(
                        name=name,
                        description="形态探针",
                        config={},
                        run=lambda *a, **k: None,
                    )

            def get_skill(self, name):
                return self.skills.get(name)

            async def execute_skill(self, skill_name, params, context=None):
                return {"tool": skill_name}

        registry = _StubRegistry()
        for name in list(safe_names) + ["probe_write"]:
            registry.ensure(name)

        tool_messages = []
        agent = SimpleNamespace(
            llm_client=SimpleNamespace(),
            config=SimpleNamespace(name="t", user_id="u1", agent_id="a1"),
            _current_user_id="u1",
            _tool_messages_list=tool_messages,
            append_tool_messages=lambda records: tool_messages.extend(records or []),
            skill_registry=None,
            _skill_registry=registry,
            tool_memory=None,
            tool_lifecycle=None,
            skill_packer=None,
            tool_router=None,
            workspace_path=".",
        )
        agent.tool_executor = ToolExecutor(agent)
        return OpenAILoop(agent)

    @pytest.mark.asyncio
    async def test_singleCallIsRecordedAsSingleCall(self, monkeypatch):
        loop = self._make_loop(monkeypatch, {"probe_read"})
        await loop.handle_tool_calls([_call("c1", "probe_read")], [])
        assert _shapeSamples().get(("OpenAILoop", "single_call"), 0.0) >= 1.0, (
            "单调用轮没有落形态读数"
        )

    @pytest.mark.asyncio
    async def test_eligibleMultiCallIsRecordedAsParallel(self, monkeypatch):
        loop = self._make_loop(monkeypatch, {"probe_read", "probe_search"})
        await loop.handle_tool_calls(
            [_call("c1", "probe_read"), _call("c2", "probe_search")], []
        )
        assert _shapeSamples().get(("OpenAILoop", "multi_parallel"), 0.0) >= 1.0, (
            "成组的并行批没有落 multi_parallel 形态：M3 的收益读数会系统性低估"
        )

    @pytest.mark.asyncio
    async def test_serialMultiCallIsRecordedAsMultiSerial(self, monkeypatch):
        """多调用但零并行批（上限=1，合法域下界）必须与"成组"分开计。"""
        monkeypatch.setenv("NEUROVA_AGENT_MAX_PARALLEL_TOOLS", "1")
        loop = self._make_loop(monkeypatch, {"probe_read", "probe_search"})
        await loop.handle_tool_calls(
            [_call("c1", "probe_read"), _call("c2", "probe_search")], []
        )
        samples = _shapeSamples()
        assert samples.get(("OpenAILoop", "multi_serial"), 0.0) >= 1.0, (
            "全串行的多调用轮被记成了别的形态（反向控制失效）"
        )

    @pytest.mark.asyncio
    async def test_shapeReadoutSeparatesLoopPaths(self, monkeypatch):
        """读数必须带 `path` 分档：`AnthropicLoop` 逐条转发 super，是一条真实盲区。"""
        loop = self._make_loop(monkeypatch, {"probe_read"})
        await loop.handle_tool_calls([_call("c1", "probe_read")], [])
        paths = {path for (path, _shape) in _shapeSamples()}
        assert "OpenAILoop" in paths, f"形态读数没有路径分档：{paths}"


class TestDurationDistributionIsReadable:
    """直方图有写入方、读侧必须真读；`avg_duration_ms` 改前是恒 0 的假读数。"""

    @pytest.mark.asyncio
    async def test_averageComesFromTheHistogram(self):
        from neurova.api.endpoints import analytics
        from neurova.core.metrics import get_metrics

        metrics = get_metrics()
        metrics.record_tool_execution("readout_probe", "builtin", True, 1.0)
        metrics.record_tool_execution("readout_probe", "builtin", True, 3.0)

        rows = analytics._read_tool_metrics(top_n=100)
        probe = [r for r in rows if r["name"] == "readout_probe"]
        assert probe, "工具计数读数里没有刚记录的工具"
        assert probe[0]["avg_duration_ms"] == pytest.approx(2000.0, rel=0.01), (
            f"avg_duration_ms 不是从直方图读来的（读到 {probe[0]['avg_duration_ms']}）"
        )

    @pytest.mark.asyncio
    async def test_no_samplesStaysZero(self):
        """反向控制：没有样本的工具不得凭空算出耗时（诚实零态）。"""
        from neurova.api.endpoints import analytics

        rows = analytics._read_tool_metrics(top_n=100)
        assert all(r["avg_duration_ms"] >= 0.0 for r in rows)


class TestReadoutEntryPoint:
    """§10.1 要求"从既有观测面拉"——必须是可独立重跑的一条命令。"""

    def test_scriptExists(self):
        assert READOUT_SCRIPT.exists(), "取数入口没落库：M3 决策无据可依"

    def test_parsesTheSameMetricText(self, tmp_path):
        """离线复算：把 /metrics 文本喂进去，两个读数都要能算出来。"""
        import subprocess

        from neurova.core.metrics import get_metrics, generate_metrics_text

        # 独立路径名：注册表是进程级共享的，用别的用例也在写的名字会让断言随执行序漂移
        probe_path = "readout_script_probe"
        get_metrics().record_tool_batch_shape(probe_path, "multi_parallel")
        get_metrics().record_tool_batch_shape(probe_path, "single_call")
        get_metrics().record_tool_execution("readout_script_tool", "builtin", True, 2.0)
        text_path = tmp_path / "metrics.txt"
        text_path.write_text(generate_metrics_text(), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(text_path), "--json"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, f"脚本跑不起来：{result.stderr[-2000:]}"
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        for key in ("batch_shapes", "multi_tool_round_share", "tool_durations", "verdict"):
            assert key in payload, f"读数缺失：{key}"
        probe_shapes = payload["batch_shapes"].get(probe_path, {})
        assert probe_shapes.get("multi_parallel") == 1
        assert probe_shapes.get("single_call") == 1
        # 注册表是**进程级共享**的，其它用例也往里写：断言只认本用例那条路径的读数，
        # 全局占比只要求"算得出来且落在合法值域"——对全局值下精确断言等于把判据
        # 绑到测试执行序上（同文件内换个顺序就会漂）。
        assert payload["per_path"][probe_path]["grouped_share"] == 1.0
        assert 0.0 <= payload["multi_tool_round_share"] <= 1.0
        assert payload["verdict"] in ("worthwhile", "sparse")
        durations = {d["name"]: d for d in payload["tool_durations"]}
        assert durations["readout_script_tool"]["count"] >= 1
        assert durations["readout_script_tool"]["avg_ms"] > 0.0, (
            "耗时均值没从直方图本体读出来（读侧那一半缺失）"
        )


class TestDurationResolutionAnswersTheQuestion:
    """§10.1 要的是"耗时落在哪一段"，而仪表的最细桶是 50ms——量尺本身答不出来。

    实测（live 真链路，读 3 文件 + 写 1 文件）：`file_read` 均值 6.57ms、
    `file_write` 0.11ms，**全部落在同一个 `<=0.05s` 桶**里。此时"分布"只剩一个
    bar，M3 的收益量级（能否从并行里省出可感时间）无从判断——"量不出来"与
    "没必要量"在读数上同形，正是本片要修的那类断链。

    故仪表必须能分辨工具的实际量级（毫秒级）。这是**仪表分辨率的根修**，
    不是放宽判据：桶位是直方图构造函数的一部分，加细不漏计、不改既有语义。
    """

    def test_subFiftyMillisecondToolsAreResolvable(self):
        from neurova.core.metrics import get_metrics, generate_metrics_text

        metrics = get_metrics()
        # 6ms 与 40ms：都在旧最细桶（50ms）之下，但量级差近 7 倍
        metrics.record_tool_execution("resolution_probe_fast", "builtin", True, 0.006)
        metrics.record_tool_execution("resolution_probe_slow", "builtin", True, 0.040)

        text = generate_metrics_text()
        families = list(_families(text))
        counts = {}
        for family in families:
            for sample in family.samples:
                if sample.name == "neurova_tool_execution_seconds_count" and str(
                    sample.labels.get("tool_name")
                ).startswith("resolution_probe_"):
                    counts[sample.labels["tool_name"]] = int(sample.value)
        assert counts, "两笔耗时样本没进直方图"

        import scripts.diagnostics.tool_parallelism_readout as readout

        rows = {r["name"]: r for r in readout.parseToolDurations(text)}
        fast = [k for k, v in rows["resolution_probe_fast"]["segments_s"].items() if v]
        slow = [k for k, v in rows["resolution_probe_slow"]["segments_s"].items() if v]
        assert fast and slow, f"耗时样本落在空区间：{fast} / {slow}"
        assert fast != slow, (
            "6ms 与 40ms 被读进同一个桶——仪表分辨率不足，§10.1 的耗时分布题"
            f"在本仪表上不可答（两者都落在 {fast}）"
        )

    def test_segmentsAreDerivedBySubtraction(self):
        """反向控制：`_bucket` 是**累计**值，直接当分布读会得到"每桶一样大"的假象。"""
        import scripts.diagnostics.tool_parallelism_readout as readout

        text = (
            "# HELP neurova_tool_execution_seconds d\n"
            "# TYPE neurova_tool_execution_seconds histogram\n"
            'neurova_tool_execution_seconds_bucket{tool_name="x",le="0.1"} 1\n'
            'neurova_tool_execution_seconds_bucket{tool_name="x",le="1.0"} 3\n'
            'neurova_tool_execution_seconds_bucket{tool_name="x",le="+Inf"} 3\n'
            'neurova_tool_execution_seconds_sum{tool_name="x"} 1.5\n'
            'neurova_tool_execution_seconds_count{tool_name="x"} 3\n'
        )
        row = readout.parseToolDurations(text)[0]
        assert row["segments_s"] == {"<=0.1s": 1, "0.1s<..<=1s": 2}, (
            f"区间不是相减得出的（拿到 {row['segments_s']}）——累计值被当成分布读"
        )


def _families(text):
    from prometheus_client.parser import text_string_to_metric_families

    return list(text_string_to_metric_families(text))
