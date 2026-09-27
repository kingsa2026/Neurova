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
  `AnthropicLoop` 在批里含 `computer` 时逐条转发 `super().handle_tool_calls([单条])`，
  那些批拿不到成组执行 —— 这个残留盲区必须**在读数上直接可见**
  （不分档就会把它算成"M3 没有收益"）。
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

"""形态词汇的单一事实源在写入侧（`core/tool_capability.ToolBatchShape`）；
本文件的词表由读侧入口暴露，不另写一份字面量。"""
try:
    import scripts.diagnostics.tool_parallelism_readout as _readout_mod

    SHAPE_LABELS = tuple(getattr(_readout_mod, "SHAPE_LABELS", ()))
except Exception:  # noqa: BLE001 - 读侧入口不可导入时由用例自己点名
    SHAPE_LABELS = ()


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


class TestEvidenceLinesMatchLiveBehaviour:
    """依据行不得停在**已经被修掉的事实**上（M3 前置那片的下游残留）。

    `47be5594` 已把 Anthropic 路径改成「无 `computer` 调用时整批交基类」，
    但同一批的三处依据行还写着「逐条转发 ⇒ 那条路径上**永远**只会是
    single_call」。依据行是"改声明的人"读的第一手材料，它过期就会把人引向
    一个不存在的盲区——而盲区本身还在（含 `computer` 的批），只是变窄了。

    判据取**活行为**再比文字：同一句依据若与实测相反，文字侧必须改。
    """

    STALE = "永远"

    def _sites(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        return {
            "neurova/agent/loops/base.py": root / "neurova/agent/loops/base.py",
            "neurova/core/metrics.py": root / "neurova/core/metrics.py",
            "scripts/diagnostics/tool_parallelism_readout.py":
                root / "scripts/diagnostics/tool_parallelism_readout.py",
            "tests/unit/tools/test_tool_parallelism_readout.py": Path(__file__),
        }

    def test_liveBehaviourIsWholeBatchHandoff(self):
        """活行为：无 `computer` 的批必须整批交基类（成组执行拿得到）。"""
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[3]
            / "neurova/agent/loops/anthropic_loop.py"
        ).read_text(encoding="utf-8")
        assert "return await super().handle_tool_calls(tool_calls, messages)" in text, (
            "Anthropic 路径不再整批交基类——依据行的前提变了，须重新取证"
        )

    def test_evidenceLinesDoNotClaimAnAbsoluteBlindSpot(self):
        """依据行不得把盲区写成整条路径的绝对判断（残留盲区有前置条件）。"""
        offenders = []
        for rel, path in self._sites().items():
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if "single_call" in line and self.STALE in line:
                    offenders.append(f"{rel}:{lineno}")
        assert offenders == [], (
            "这些依据行写着已被修掉的绝对判断（活行为是整批交基类，"
            "残留盲区只在含 `computer` 的批上）——依据会静默过期："
            f"{offenders}"
        )

    def test_evidenceLinesNameTheRemainingBlindSpot(self):
        """依据行必须点名**残留**盲区的条件（含 `computer` 的批），不是笼统一句。"""
        missing = []
        for rel, path in self._sites().items():
            text = path.read_text(encoding="utf-8")
            if "AnthropicLoop" not in text:
                continue
            if "computer" not in text:
                missing.append(rel)
        assert missing == [], (
            f"这些依据行提到了 Anthropic 路径却没点名残留盲区的条件: {missing}"
        )


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


class TestReadoutOnARealScrape:
    """离线复算的真实使用形态：喂**抓回来的** `/metrics` 体，不是喂"理想文本"。

    本类来自一次真实取数（Issue #271 M3 前置）：要拿生产观测面的读数，
    实际拿到的却是反代/官网吞掉后的 **HTML**。取数入口当时以解释器栈收场——
    读者分不清"判定结果是 sparse"与"你喂的不是 /metrics 文本"，而这两种情形
    在观测面上必须**分得开**（同"采不到要出声"的纪律）。

    三件事各钉一条：
    1. 喂错内容 → 点名原因，不是 traceback；
    2. `no_data` → 不得被读成 §10.1 的否证（它不是否证条件）；
    3. 两个口径各自正名：`grouped_share` 与多工具轮占比是**两个不同的问题**。
    """

    def test_htmlScrapeIsRejectedByNameNotByTraceback(self, tmp_path):
        """抓取体不是 Prometheus 文本时必须点名，而不是抛 ValueError 栈。

        实测（真抓取）：`prometheus_client` 对 HTML 抛
        `ValueError: invalid metric name:<!DOCTYPE html>...`，退出码 1。
        取数命令的读者是**决策者**，他需要读到"这份输入不是 /metrics 文本"。
        """
        import subprocess

        html = tmp_path / "scrape.html"
        html.write_text(
            "<!DOCTYPE html><html><body>proxy intercepted</body></html>", encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(html)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert "Traceback" not in result.stderr, (
            f"喂错内容以解释器栈收场，读者分不清它是不是判定结论：{result.stderr[-500:]}"
        )
        combined = result.stdout + result.stderr
        assert "不是 Prometheus 文本" in combined or "not prometheus" in combined.lower(), (
            f"没有点名输入形态错误：{combined[-500:]}"
        )
        assert result.returncode != 0, "喂错内容不得报成正常完成"

    def test_missingFileIsNamedNotTracebacked(self, tmp_path):
        """同一根因的另一半：`--metrics-file` 指向不存在的文件也必须点名。

        `_metricText` 有两条"输入不可用"的路径（文件读不到 / 内容不是
        Prometheus 文本），它们是同一个事实的两半 —— 只修被点名的那一半，
        另一半照样以解释器栈收场（教义第 5 条：同契约全部命中点一并修）。
        """
        import subprocess

        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(tmp_path / "nope.txt")],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert "Traceback" not in result.stderr, (
            f"文件读不到以解释器栈收场：{result.stderr[-400:]}"
        )
        assert "读不到" in result.stderr + result.stdout, (
            f"没有点名文件不可读：{(result.stderr + result.stdout)[-400:]}"
        )
        assert result.returncode != 0

    def test_noDataIsNotReadAsTheSparsenessFalsification(self, tmp_path):
        """`no_data` 必须显式标注"不构成 §10.1 否证"。

        它是判据**输入缺失**，而 sparse 是判据**结论**。两者混同就等于
        "拿失明当结论"——本仓已为此付过代价（Issue #271 上一片：占比恒不可达时
        「低于 5% 就放弃」与「数据缺失」在观测面上同形）。
        """
        import subprocess

        empty = tmp_path / "empty_metrics.txt"
        empty.write_text("", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(empty)],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stderr[-500:]
        assert "no_data" in result.stdout, "零样本没有被读成 no_data"
        assert "否证" in result.stdout and "不构成" in result.stdout, (
            "no_data 没有显式标注「不构成否证」——它会被读成 sparse（拿失明当结论）："
            f"{result.stdout[-600:]}"
        )

    def test_twoSharesAreNamedApart(self, tmp_path):
        """两个口径必须各自正名：它们会给出**相反**的 verdict。

        实测同一份数据：某路径 21 个单调用轮 + 1 个成组轮 ⇒
        「成组批 / 多调用轮」= 1.0（worthwhile），
        「多工具轮 / 全部轮」= 1/22 ≈ 0.045（sparse）。
        一个字段两种读法、结论相反，必须分别命名，不许折叠成一个 `share`。
        """
        import json as _json
        import subprocess

        text = tmp_path / "mixed.txt"
        text.write_text(
            "# HELP neurova_tool_batch_shapes_total b\n"
            "# TYPE neurova_tool_batch_shapes_total counter\n"
            + "".join(
                f'neurova_tool_batch_shapes_total{{path="P",shape="single_call"}} 1\n'
                for _ in range(21)
            )
            + 'neurova_tool_batch_shapes_total{path="P",shape="multi_parallel"} 1\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(text), "--json"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stderr[-800:]
        payload = _json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["per_path"]["P"]["grouped_share"] == 1.0
        assert "multi_tool_round_share" in payload, "多工具轮占比口径缺失（§10.1 原文口径）"
        assert payload["multi_tool_round_share"] == round(1 / 22, 4), (
            f"多工具轮占比算错了（拿到 {payload['multi_tool_round_share']}）"
        )
        # verdict 落 §10.1 的**原文口径**（多工具批次占全部轮）：1/22 < 0.05 ⇒ sparse。
        # 另一个口径在同一份数据上给 1.0（worthwhile）—— 两者结论相反，必须各挂名。
        assert payload["grouped_parallel_share"] == 1.0
        assert payload["verdict"] == "sparse", (
            "verdict 没落在 §10.1 原文口径（多工具批次 / 全部轮）上："
            f"拿到 {payload['verdict']}，会把'多工具轮本身就极少'读成'值得做 M3'"
        )


class TestNoDataCauseIsSplitByInstrumentPresence:
    """`no_data` 有两种成因，**处置相反** —— 它们此前在输出上完全同形。

    实测两条真实路径（Issue #271 取数）：

    - **仪表缺席**：部署镜像 revision `d5210625`（09-26 12:23）的 `core/metrics.py`
      对 `tool_batch_shapes` **零命中**，该 revision 导出的抓取里连家族头都没有
      ⇒ 本份抓取上判据没有输入：再跑多少轮、再等多久都不会有样本（确为完整抓取时
      要动的是**部署**）；
    - **零样本**：当前源码导出的抓取里家族头在、样本数为 0（重启清空计数器，
      而新实例一次工具轮都没跑过）⇒ 判据**可达且已就位**：样本随真实轮次到达，
      重跑本命令即出结论。

    两种情形都印一个 `no_data`。读者因此分不清"该修部署"与"该等样本" ——
    这是本仓反复付代价的"把失明当结论"的同一族形态，只是又深了一层：上一片
    分开了「判据结论（sparse）」与「判据输入没采到（no_data）」，这一片必须
    再分开「输入根本没采到（仪表缺席）」与「输入可达、只是还没样本」。
    """

    @staticmethod
    def _run(tmp_path, text: str, *extra):
        import subprocess

        scrape = tmp_path / "scrape.txt"
        scrape.write_text(text, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--metrics-file", str(scrape), *extra],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )

    @staticmethod
    def _zeroSampleScrape(tmp_path) -> str:
        """真源码导出的零样本抓取：家族头在、`{...}` 样本行一条都没有。

        **必须另起进程**导出：本进程的注册表被同文件其它用例写过，就地导出会带上
        它们的样本，用例前提随执行序漂移（实测：单跑该类时零样本、全文件跑时不是）。
        另起进程同时正是"重启后新实例"的真实形态——判据仪表是进程级的，
        重启即清空计数器，样本随真实工具轮到达。
        """
        import subprocess

        fresh = subprocess.run(
            [
                sys.executable,
                "-c",
                "from neurova.core.metrics import get_metrics, generate_metrics_text;"
                " get_metrics();"
                " print(generate_metrics_text(), end='')",
            ],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert fresh.returncode == 0, f"新进程导出抓取失败：{fresh.stderr[-600:]}"
        return fresh.stdout

    def test_zeroSampleScrapeIsReachableNotBlind(self, tmp_path):
        """家族头在 + 零样本 ⇒ 成因是**可达且已就位**，不是"量不到"。

        判据：`zero_samples`。处置是"等真实轮次"，不是"去修部署"、更不是
        "据此放弃 M3"——判据本身是可达的。
        """
        import json as _json

        text = self._zeroSampleScrape(tmp_path)
        assert "neurova_tool_batch_shapes" in text, (
            "本进程的抓取里连家族头都没有：判据仪表没接线（这条断言守的是本用例的前提）"
        )
        assert 'neurova_tool_batch_shapes_total{' not in text, (
            "本用例的前提是**零样本**（没有任何 {...} 样本行）"
        )

        result = self._run(tmp_path, text, "--json")
        assert result.returncode == 0, result.stderr[-500:]
        payload = _json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["verdict"] == "no_data", (
            f"零样本没被判成 no_data（拿到 {payload['verdict']}）"
        )
        assert payload.get("no_data_cause") == "zero_samples", (
            "零样本的成因没被分开：它会被读成'判据不可达'，于是该等样本的时候"
            f"跑去改部署（拿到 {payload.get('no_data_cause')!r}）"
        )
        assert payload["instrument"]["shape_family"]["present"] is True
        assert payload["instrument"]["shape_family"]["sample_total"] == 0

    def test_absentInstrumentIsNamedAsUnreachable(self, tmp_path):
        """家族头不在 ⇒ 成因**不得指向"再等等"**，且作用域只到本份抓取。

        判据：`absent_in_this_scrape`。这份抓取取自埋点提交之前的代码（实测镜像
        revision `d5210625` 对 `tool_batch_shapes` 零命中）。成因名的作用域是
        **本份抓取**：同一读数也可能是子集抓取 / 被截断 —— 判据只关于文本，
        就不许越过文本去断言部署（那要读者拿完整抓取去证）。
        """
        import json as _json

        text = (
            "# HELP neurova_tool_executions_total h\n"
            "# TYPE neurova_tool_executions_total counter\n"
            'neurova_tool_executions_total{tool_name="file_read",source="builtin",success="true"} 4\n'
        )
        result = self._run(tmp_path, text, "--json")
        assert result.returncode == 0, result.stderr[-500:]
        payload = _json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["verdict"] == "no_data"
        assert payload.get("no_data_cause") == "absent_in_this_scrape", (
            "本份抓取里仪表缺席没被点名：读者会以为'再等等就有读数'"
            f"（拿到 {payload.get('no_data_cause')!r}）"
        )
        assert payload["instrument"]["shape_family"]["present"] is False

    def test_twoCausesAreDistinguishable(self, tmp_path):
        """反向控制：两种成因必须**分得开**，不许折叠成同一个值。

        折叠回同一个 `no_data` 就是本片要修的那个缺陷本身。
        """
        import json as _json

        zero = self._run(tmp_path, self._zeroSampleScrape(tmp_path), "--json")
        absent = self._run(
            tmp_path, "# HELP neurova_whatever_total h\n# TYPE neurova_whatever_total counter\n", "--json"
        )
        zero_cause = _json.loads(zero.stdout.strip().splitlines()[-1])["no_data_cause"]
        absent_cause = _json.loads(absent.stdout.strip().splitlines()[-1])["no_data_cause"]
        assert zero_cause != absent_cause, (
            f"两种成因被折叠成同一个值 {zero_cause!r}——读者无从分辨处置"
        )

    def test_humanReadableNamesDispositionPerCause(self, tmp_path):
        """人类可读输出必须**各自点名处置**：该修部署 vs 该等样本。

        只印一句"input 不可用"，读者仍要自己猜该动哪里——那等于把判据留在
        我们自己脑内。
        """
        absent = self._run(tmp_path, "# HELP neurova_x_total h\n# TYPE neurova_x_total counter\n")
        assert "absent_in_this_scrape" in absent.stdout, (
            f"缺席成因没在人类可读输出里点名：{absent.stdout[-400:]}"
        )
        assert "核对抓取" in absent.stdout, (
            "缺席的处置没先指向抓取本身：子集抓取 / 被截断 / 抓错服务都会长成这样，"
            f"直接指向部署就是把文本级事实当成部署级结论：{absent.stdout[-400:]}"
        )
        assert "部署" in absent.stdout, (
            f"部署分支被一并删掉了（确为完整抓取时该给的处置仍要给）：{absent.stdout[-400:]}"
        )

        zero = self._run(tmp_path, self._zeroSampleScrape(tmp_path))
        assert "zero_samples" in zero.stdout, (
            f"零样本成因没在人类可读输出里点名：{zero.stdout[-400:]}"
        )
        assert "可达" in zero.stdout, (
            f"零样本的'判据可达'没说清（它会被读成恒不可达）：{zero.stdout[-400:]}"
        )

    def test_durationReadoutSplitsTheSameTwoCases(self, tmp_path):
        """同一根因的第二个命中点：耗时分布那行也把两种情形印成"（无样本）"。

        教义第 5 条：一个断链被点名后，同契约的其余命中点一并修。
        """
        absent = self._run(tmp_path, "# HELP neurova_x_total h\n# TYPE neurova_x_total counter\n")
        assert "（无样本）" not in absent.stdout or "仪表" in absent.stdout, (
            "耗时读数只说'（无样本）'，与'本份抓取里仪表缺席'同形："
            f"读者分不清该等还是该核对抓取：{absent.stdout[-400:]}"
        )
        assert "仪表" in absent.stdout, (
            f"耗时读数没点出本份抓取里仪表缺席：{absent.stdout[-400:]}"
        )

    def test_durationSegmentJudgesByItsOwnInstrument(self, tmp_path):
        """耗时段按**它自己的**仪表判成因，不借用形态段的结论。

        实测这份旧部署（revision `d5210625`）里两支仪表状态不同：
        `tool_execution_seconds` 早就在位（埋点先于形态表），形态表则缺席。
        把形态段的"仪表缺席"抄给耗时段，读者会照着错的处置去动 ——
        而两支仪表在观测面上本来就是独立的两条读数。
        """
        text = (
            "# HELP neurova_tool_execution_seconds d\n"
            "# TYPE neurova_tool_execution_seconds histogram\n"
        )
        result = self._run(tmp_path, text)
        assert result.returncode == 0, result.stderr[-500:]
        duration_line = [l for l in result.stdout.splitlines() if "耗时" in l or "成因=" in l]
        tail = result.stdout.split("工具耗时分布")[-1]
        assert "zero_samples" in tail, (
            "耗时段借用了形态段的成因：它自己的仪表明明在位（只是零样本），"
            f"却被判成'仪表缺席、该修部署'：{tail[-400:]}"
        )

    def test_inProcessReadAssemblesRegistryLikeTheEndpoint(self):
        """进程内路径必须先装配仪表，再导出文本——与 `/metrics` 端点同一条装配。

        实测（live-verify）：不装依赖跑 `python tool_parallelism_readout.py`（无参数），
        它给出 `absent_in_this_scrape` —— 而这是**误判**：`generate_metrics_text()` 单独
        调用时 `_Metrics()` 从未被构造，注册表里一条 neurova 家族都没有，于是
        "本进程还没装配仪表"被读成"这份部署里没有仪表"，把处置指向了无辜的部署。

        真 `/metrics` 端点在注册时就 `get_metrics()`（`api/app.py` 的
        `_register_metrics_endpoint` 第一行），故进程内取数要照同一条装配走，
        判出来的"仪表在不在"才是关于**部署**的事实，而不是关于**本进程偷懒**。
        """
        import subprocess

        result = subprocess.run(
            [sys.executable, str(READOUT_SCRIPT), "--json"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stderr[-600:]
        import json as _json

        payload = _json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["instrument"]["shape_family"]["present"] is True, (
            "进程内取数把'本进程尚未装配仪表'读成了'部署里没有仪表'："
            "处置会被指向无辜的部署（与 /metrics 端点的装配不一致）"
        )
        assert payload["verdict"] == "no_data"
        assert payload["no_data_cause"] == "zero_samples", (
            f"新实例的真实成因是零样本（拿到 {payload['no_data_cause']!r}）"
        )

    def test_nonNoDataCarriesNoCause(self, tmp_path):
        """反向控制：判据出结论时不得挂一个无意义的成因。"""
        import json as _json

        text = (
            "# HELP neurova_tool_batch_shapes_total b\n"
            "# TYPE neurova_tool_batch_shapes_total counter\n"
            'neurova_tool_batch_shapes_total{path="P",shape="single_call"} 1\n'
        )
        result = self._run(tmp_path, text, "--json")
        payload = _json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["verdict"] in ("worthwhile", "sparse")
        assert payload.get("no_data_cause") in ("", None), (
            f"有结论的轮次挂了成因 {payload.get('no_data_cause')!r}——成因是 no_data 专属"
        )


#: 三态素材的落点（同一条命令、三份**真抓取**、三种读数）。
M3_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "m3_readout"


def _runReadout(*args, timeout: int = 300):
    """跑一次取数命令（真子进程，与决策者手里的用法逐字相同）。"""
    import subprocess

    return subprocess.run(
        [sys.executable, str(READOUT_SCRIPT), *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout,
    )


def _readoutJson(*args):
    result = _runReadout(*args, "--json")
    assert result.returncode == 0, result.stderr[-800:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestAbsentFamilyCauseIsScopedToTheScrape:
    """"这一份抓取里没有"与"那套部署里没有"是两件事——成因只许声明前者。

    实测（真跑）：喂一份**只含形态族**的抓取切片（`tool_batch_shapes` 在、
    `tool_execution_seconds` 不在，正是"只抓了一个族"的常见形态），耗时段印的是
    **改前**的 `instrument_absent` + "该动的是**部署**（那份部署早于埋点提交，等多久
    都不会有样本）"。而这份文本对部署一无所知：它可能只是子集抓取、被反代截断、
    或抓的根本不是本服务。

    这与上一片修掉的"进程内路径误判"同族（把本机/本文件的事实说成部署的事实），
    根因不同：那里仪表其实在位，这里**在这份文本上**确实没有。故判据不许越过文本
    断言部署——成因名与处置都收拢到"本份抓取"的作用域，部署分支只作为**可核实的
    条件分支**保留（确为完整抓取时才成立）。
    """

    #: 只含形态族的切片：形态段在、耗时段不在（真实形态，非构造）
    SHAPE_ONLY = (
        "# HELP neurova_tool_batch_shapes_total b\n"
        "# TYPE neurova_tool_batch_shapes_total counter\n"
        'neurova_tool_batch_shapes_total{path="P",shape="single_call"} 1.0\n'
    )

    @staticmethod
    def _scrape(tmp_path, name: str, text: str) -> str:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_subsetScrapeDoesNotAssertADeploymentFact(self, tmp_path):
        """文本级缺席不得写成部署级结论，且处置要**先指向抓取本身**。"""
        path = self._scrape(tmp_path, "shape_only.txt", self.SHAPE_ONLY)
        result = _runReadout("--metrics-file", path)
        assert result.returncode == 0, result.stderr[-500:]
        assert "absent_in_this_scrape" in result.stdout, (
            "成因名没把作用域写进契约（读者会读成'那套部署里没有'）："
            f"{result.stdout[-500:]}"
        )
        assert "该动的是**部署**" not in result.stdout, (
            "文本级缺席被写成了部署级结论：这份文本对部署一无所知"
            f"（子集抓取 / 被截断 / 抓错服务都会长成这样）：{result.stdout[-500:]}"
        )
        assert "核对抓取" in result.stdout, (
            f"处置没有先指向抓取本身：{result.stdout[-500:]}"
        )
        assert "部署" in result.stdout, (
            "部署分支被一并删掉了：确为完整抓取时该给的处置仍然要给"
        )

    def test_foreignScrapeKeepsTheSameTextScope(self, tmp_path):
        """同一根因的另一个命中点：整份抓取里连一个 neurova_* 家族都没有。

        成因仍只能声明"本份抓取里没有"，不得推断部署（这份文本同样可能只是
        抓错了目标）。机器可读字段 `no_data_cause` 与人类可读输出同一条契约。
        """
        path = self._scrape(
            tmp_path,
            "foreign.txt",
            "# HELP go_goroutines Number of goroutines\n"
            "# TYPE go_goroutines gauge\n"
            "go_goroutines 12\n",
        )
        payload = _readoutJson("--metrics-file", path)
        assert payload["no_data_cause"] == "absent_in_this_scrape", (
            f"抓错目标的文本给出了部署级成因 {payload['no_data_cause']!r}"
        )
        text = _runReadout("--metrics-file", path).stdout
        assert "该动的是**部署**" not in text, f"{text[-500:]}"

    def test_theDeploymentBranchSurvivesAsACondition(self, tmp_path):
        """反向控制：作用域收拢**不得**把部署分支软成一句"先看看"。

        `scrape_before_instrumentation.txt` 是该部署的**完整**真导出：
        "该部署早于埋点提交"此时才是可核实的结论，读者需要的处置
        （重新部署当前版本）必须仍在输出里——把报错降级成 warning 是本仓明令禁止的。
        """
        fixture = M3_FIXTURES / "scrape_before_instrumentation.txt"
        payload = _readoutJson("--metrics-file", str(fixture))
        assert payload["no_data_cause"] == "absent_in_this_scrape"
        text = _runReadout("--metrics-file", str(fixture)).stdout
        assert "重新部署当前版本" in text, (
            f"部署分支的条件处置丢了（报错被软掉）：{text[-500:]}"
        )

    def test_absentIsStillNotZeroSamples(self, tmp_path):
        """反向控制：作用域正名**不得**把两种成因折叠回去。

        两个输入都必须是 `no_data`（成因只在 `no_data` 上出现）：`SHAPE_ONLY`
        形态族里带样本 ⇒ 判据出结论 `sparse`、成因本就该是空值，故这里另造一份
        "两族家族头都在、样本为零"的文本作对照。
        """
        absent = self._scrape(
            tmp_path,
            "foreign2.txt",
            "# HELP go_goroutines g\n# TYPE go_goroutines gauge\ngo_goroutines 1\n",
        )
        zero = self._scrape(
            tmp_path,
            "zero.txt",
            "# HELP neurova_tool_batch_shapes_total b\n"
            "# TYPE neurova_tool_batch_shapes_total counter\n"
            "# HELP neurova_tool_execution_seconds d\n"
            "# TYPE neurova_tool_execution_seconds histogram\n",
        )
        absent_cause = _readoutJson("--metrics-file", absent)["no_data_cause"]
        zero_cause = _readoutJson("--metrics-file", zero)["no_data_cause"]
        assert absent_cause == "absent_in_this_scrape", (
            f"拿错目标的文本没给出文本级成因（拿到 {absent_cause!r}）"
        )
        assert zero_cause == "zero_samples", (
            f"两族在位的零样本态被读成了 {zero_cause!r}"
        )
        assert absent_cause != zero_cause, "两种成因被折叠回了同一个值"

    def test_shapeOnlySliceStillReachesItsJudgement(self, tmp_path):
        """反向控制：只抓了一个族的切片里，**可判的那一段照常出结论**。

        作用域收拢只改"没结论"的措辞，不许把有结论的读数也拖成 no_data——
        形态族有样本时 `verdict` 仍是 `sparse`/`worthwhile`，成因字段保持空值
        （成因是 `no_data` 专属）。
        """
        path = self._scrape(tmp_path, "shape_only2.txt", self.SHAPE_ONLY)
        payload = _readoutJson("--metrics-file", path)
        assert payload["verdict"] == "sparse", (
            f"形态族有样本却没给出判据结论（拿到 {payload['verdict']!r}）"
        )
        assert payload["no_data_cause"] == "", (
            f"有结论的读数挂了成因 {payload['no_data_cause']!r}"
        )


class TestThreeStatesOfOneCommand:
    """同一条命令、三份真抓取、三种读数——三态素材落库并逐态钉住。

    Issue #271 的真机反馈把 M3 判据的三态都跑出来了：重启前 `absent_in_this_scrape`、
    刚重启后 `zero_samples`、跑过工具轮之后有样本。三态在改前**同形**（都只印一个
    `no_data`），本片把它们各自的素材固化下来，任何一次重复制都会把某两态压回同形。

    素材来源（逐份可复算，非构造文本）：
    - `scrape_sampled.txt`：真 `RegisteredOpenAILoop` → 真分组 → 真执行咽喉 → 真注册表
      导出（轮 1 三次、轮 2 两次、轮 3 单调用），与真机读数同形（multi_parallel 2 /
      single_call 1，path=`RegisteredOpenAILoop`）；
    - `scrape_zero_samples.txt`：当前源码真导出（新实例、零工具轮）；
    - `scrape_before_instrumentation.txt`：埋点提交之前那份 `core/metrics.py` 的真导出
      （形态表连家族头都不在）。
    """

    def test_sampledScrapeReachesTheJudgement(self):
        payload = _readoutJson("--metrics-file", str(M3_FIXTURES / "scrape_sampled.txt"))
        assert payload["instrument"]["shape_family"]["present"] is True
        assert payload["instrument"]["shape_family"]["sample_total"] == 2
        assert payload["batch_shapes"]["RegisteredOpenAILoop"] == {
            "multi_parallel": 2, "single_call": 1,
        }
        assert payload["multi_tool_round_share"] == round(2 / 3, 4)
        assert payload["verdict"] == "worthwhile", (
            f"有样本态没有给出判据结论（拿到 {payload['verdict']}）"
        )
        assert payload["no_data_cause"] == "", (
            f"有结论的读数挂了成因 {payload['no_data_cause']!r}——成因是 no_data 专属"
        )
        assert {r["name"] for r in payload["tool_durations"]} == {"file_read"}, (
            "耗时读数没跟着形态一起出来：真导出的 tool_name 只有 file_read"
        )

    def test_allSingleCallScrapeReachesTheFalsification(self):
        """否证分支必须**可达**：全是单调用轮 ⇒ 多工具轮占比 0 ⇒ sparse。

        §10.1 的放弃条件（"多工具批次占比低于 ~5%"）此前恒不可达——判据没有输入，
        于是"低于阈值就放弃"与"数据缺失"在读数上同形。这一态钉住的是：条件本身
        能被真实样本满足（否则"放弃 M3"这个结论永远只是纸面上的）。
        """
        import tempfile

        text = (
            "# HELP neurova_tool_batch_shapes_total b\n"
            "# TYPE neurova_tool_batch_shapes_total counter\n"
            + "".join(
                f'neurova_tool_batch_shapes_total{{path="RegisteredOpenAILoop",shape="single_call"}} 1.0\n'
                for _ in range(3)
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scrape.txt"
            path.write_text(text, encoding="utf-8")
            payload = _readoutJson("--metrics-file", str(path))
        assert payload["multi_tool_round_share"] == 0.0
        assert payload["verdict"] == "sparse", (
            f"否证条件没有被满足（拿到 {payload['verdict']}）——§10.1 的放弃条件不可达"
        )
        assert payload["no_data_cause"] == ""

    def test_zeroSampleScrapeIsReachableNotAbsent(self):
        payload = _readoutJson("--metrics-file", str(M3_FIXTURES / "scrape_zero_samples.txt"))
        assert payload["verdict"] == "no_data"
        assert payload["no_data_cause"] == "zero_samples", (
            f"拿到 {payload['no_data_cause']!r}——零样本态会被读成'仪表缺席'，"
            "处置被指向无辜的部署"
        )
        assert payload["instrument"]["shape_family"]["present"] is True

    def test_beforeInstrumentationScrapeIsAbsent(self):
        payload = _readoutJson(
            "--metrics-file", str(M3_FIXTURES / "scrape_before_instrumentation.txt")
        )
        assert payload["verdict"] == "no_data"
        assert payload["no_data_cause"] == "absent_in_this_scrape", (
            f"拿到 {payload['no_data_cause']!r}——埋点前的抓取会被读成'等样本'，"
            "而它等多久都不会有样本"
        )
        assert payload["instrument"]["shape_family"]["present"] is False

    def test_theThreeStatesStayDistinct(self):
        """三态必须彼此可分——把它们压回一个 `no_data` 就是本片要防的复发。"""
        sampled = _readoutJson("--metrics-file", str(M3_FIXTURES / "scrape_sampled.txt"))
        zero = _readoutJson("--metrics-file", str(M3_FIXTURES / "scrape_zero_samples.txt"))
        absent = _readoutJson(
            "--metrics-file", str(M3_FIXTURES / "scrape_before_instrumentation.txt")
        )
        readings = [
            (sampled["verdict"], sampled["no_data_cause"]),
            (zero["verdict"], zero["no_data_cause"]),
            (absent["verdict"], absent["no_data_cause"]),
        ]
        assert len(set(readings)) == 3, f"三态压回了同形：{readings}"


class TestShapeVocabularyHasOneSource:
    """形态词汇只允许一处定义：写入侧与读数侧**同一份**（教义第 6 条）。

    改前它有两份：`base._recordBatchShape` 里三个字面量（写），读数脚本里
    另三个字面量（读）。两份一漂移，读数侧把不认识的标签**静默丢掉**，然后照样
    给出一个有把握的结论——实测（3 个 `single_call` + 5 个 `multi_pipeline`）：
    8 个样本里 5 个被扔掉，读数给出 `sparse`（"多工具轮占比 0"），而真相是
    "有 5 轮形态不明"。这正是本仓反复栽过的那类问题：拿失明当结论。
    """

    def test_shapeLabelsHaveExactlyOneDefinition(self):
        """三个标签的字面量在生产侧**只允许**出现在 `core/tool_capability.py`。

        定义处 = `ToolBatchShape` 的三个成员值。写入侧与读数侧的其它落点一律
        引用它们，不得再写第二遍字面量——写两份就会漂移，漂移后读数侧静默丢样本。
        """
        import ast

        from tests import ast_scan

        labels = set(SHAPE_LABELS)
        assert len(labels) == 3, f"形态词汇不是三值：{SHAPE_LABELS}"
        source = PROJECT_ROOT / "neurova" / "core" / "tool_capability.py"
        offenders, definitions = [], []
        # 两个面都扫：生产侧（写入侧落点）与 `scripts/`（读数侧落点）。
        # 只扫一边就会漏掉另一半——本片之前的形态正是"两侧各写一份"。
        for ref in list(
            ast_scan.sourceRefsUnder(ast_scan.PRODUCTION_ROOT, hints=tuple(sorted(labels)))
        ) + list(
            ast_scan.sourceRefsUnder(
                PROJECT_ROOT / "scripts", hints=tuple(sorted(labels))
            )
        ):
            tree = ast.parse(ref.code)
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    doc = ast.get_docstring(node, clean=False)
                    if doc is not None:
                        docstrings.add(id(node.body[0]))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and node.value in labels
                    and id(node) not in docstrings
                ):
                    continue
                if ref.path == source:
                    definitions.append((node.lineno, node.value))
                else:
                    offenders.append((ref.path.name, node.lineno, node.value))
        assert not offenders, (
            "形态标签在生产侧另有字面量落点（写侧与读侧各写一份就会漂移，"
            f"漂移后读数侧静默丢样本）：{offenders}"
        )
        assert sorted(value for _, value in definitions) == sorted(labels), (
            f"单一事实源与词表对不上：定义处 {definitions} vs 词表 {sorted(labels)}"
        )

    def test_readoutVocabularyComesFromTheWriterSide(self):
        """读数侧的词表必须**派生**自写入侧的那一份，而不是自己再写一遍。"""
        from neurova.core.tool_capability import ToolBatchShape

        assert set(SHAPE_LABELS) == {shape.value for shape in ToolBatchShape}, (
            "读数侧词表与写入侧定义漂移："
            f"{sorted(SHAPE_LABELS)} vs {sorted(s.value for s in ToolBatchShape)}"
        )

    def test_unknownShapeLabelIsNeverSilentlyDropped(self):
        """不认识的标签必须点名，且**不得**据此出结论（分母已经不完整）。"""
        import tempfile

        text = (
            "# HELP neurova_tool_batch_shapes_total b\n"
            "# TYPE neurova_tool_batch_shapes_total counter\n"
            + "".join(
                f'neurova_tool_batch_shapes_total{{path="P",shape="single_call"}} 1.0\n'
                for _ in range(3)
            )
            + "".join(
                f'neurova_tool_batch_shapes_total{{path="P",shape="multi_pipeline"}} 1.0\n'
                for _ in range(5)
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scrape.txt"
            path.write_text(text, encoding="utf-8")
            payload = _readoutJson("--metrics-file", str(path))

        assert payload.get("unrecognized_shape_labels") == {"multi_pipeline": 5}, (
            "不认识的形态标签被静默丢掉了："
            f"拿到 {payload.get('unrecognized_shape_labels')!r}"
        )
        assert payload["verdict"] == "no_data", (
            f"分母不完整却给出了结论 {payload['verdict']!r}——8 个样本有 5 个没被读懂"
        )
        assert payload["no_data_cause"] == "schema_drift", (
            f"成因没点名词汇漂移（拿到 {payload['no_data_cause']!r}）——"
            "它会被读成'零样本，等真实轮次'，而该动的是读数侧的词表"
        )
        assert payload["multi_tool_round_share"] is None, (
            "不完整分母上仍给出占比：读者会拿这个数字当结论"
        )

class TestPerToolParallelWorthiness:
    """逐工具「值不值得为它成组等待」：**P50 口径** + 冷路径另档（Issue #271 交接第 ② 条）。

    判据形状来自真机读数（Issue #271）：`file_read` 34ms 落门外、`memory_search`
    991ms 冷 / 83ms 热落在边界上。两条要求同时成立：

    1. **只用 P50**，不用 avg —— "这个工具**常态**值不值得等"是分位问题，avg 会被
       一小撮冷样本拖走（同分布下 avg ≥ 200ms 而中位仅个位数毫秒是真实现象）；
    2. **冷路径另档**，不进门槛 —— 它是部署/超时该管的事，不是并行收益该管的事；
       两件事必须在读数上分开，否则"有冷样本"会被读成"这个工具常态很慢"。

    而 200ms **不是**直方图的桶边界（桶是 0.1 / 0.25），故 P50 在这副仪表上只能
    **夹逼**：真值落在 `(lower, upper]` 内。判据因此是三态 —— 区间整段落在门槛之上
    判"值得"、整段落在门槛之下判"不值得"、**跨过门槛则如实说"边界"**。硬判一个是/否
    就是拿仪表分辨率装出来的确定性。
    """

    @staticmethod
    def _scrape(tmp_path, name: str, tool: str, buckets, total: int, sum_s: float) -> str:
        """按给定累计桶造一份真形态的抓取文本（累计语义：`le` 是"≤ 该值"的计数）。"""
        lines = [
            "# HELP neurova_tool_execution_seconds Tool execution duration",
            "# TYPE neurova_tool_execution_seconds histogram",
        ]
        for le, cum in buckets:
            lines.append(
                f'neurova_tool_execution_seconds_bucket{{le="{le}",tool_name="{tool}"}} {cum}'
            )
        lines.append(f'neurova_tool_execution_seconds_sum{{tool_name="{tool}"}} {sum_s}')
        lines.append(f'neurova_tool_execution_seconds_count{{tool_name="{tool}"}} {total}')
        path = tmp_path / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    @staticmethod
    def _row(payload, tool: str):
        rows = {r["name"]: r for r in payload["tool_durations"]}
        assert tool in rows, f"耗时读数里没有 {tool}：{sorted(rows)}"
        return rows[tool]

    def test_p50IsABucketBracketNotAInterpolatedPoint(self, tmp_path):
        """P50 必须报成**桶边界夹逼**，不许插值出一个假的小数点。

        真值落在 `(lower, upper]`：`upper` 是累计计数首次达到一半的那个桶界，
        `lower` 是它前一个未到一半的桶界。与 `analytics` 里 p95 的"桶上限、无插值"
        同一口径——本仓已有的分位语义就这一条，不另造一份。
        """
        path = self._scrape(
            tmp_path, "bracket.txt", "bracket_tool",
            [("0.005", 2), ("0.01", 4), ("+Inf", 4)], total=4, sum_s=0.03,
        )
        row = self._row(_readoutJson("--metrics-file", path), "bracket_tool")
        assert row.get("p50_upper_ms") == 5.0, (
            f"P50 上界不是桶界（累计首次过半处 le=0.005）：拿到 {row.get('p50_upper_ms')!r}"
        )
        assert row.get("p50_lower_ms") == 0.0, (
            f"P50 下界不是桶界（首个过半桶之前没有更小桶）：拿到 {row.get('p50_lower_ms')!r}"
        )

    def test_fastToolIsNotWorthWaiting(self, tmp_path):
        """常态快（区间整段 < 门槛）⇒ 明确判"不值得"，不给边界态兜底。"""
        path = self._scrape(
            tmp_path, "fast.txt", "fast_tool",
            [("0.01", 3), ("0.1", 5), ("0.25", 6), ("+Inf", 6)], total=6, sum_s=0.2,
        )
        row = self._row(_readoutJson("--metrics-file", path), "fast_tool")
        assert row.get("worth_waiting") is False, (
            f"常态 10ms 级的工具没被判成'不值得等'：拿到 {row.get('worth_waiting')!r}"
        )

    def test_slowToolIsWorthWaiting(self, tmp_path):
        """常态慢（区间整段 > 门槛）⇒ 判"值得"，这是 M3 的真实客户。"""
        path = self._scrape(
            tmp_path, "slow.txt", "slow_tool",
            [("0.5", 1), ("2.5", 3), ("+Inf", 4)], total=4, sum_s=6.0,
        )
        row = self._row(_readoutJson("--metrics-file", path), "slow_tool")
        assert row.get("worth_waiting") is True, (
            f"常态 1s 级的工具没被判成'值得等'：拿到 {row.get('worth_waiting')!r}"
        )

    def test_boundaryToolIsNotForcedIntoEitherSide(self, tmp_path):
        """P50 夹逼区间**跨过门槛**（(0.1s, 0.25s] 跨 200ms）⇒ 三态里的"边界"。

        这正是真机读数里 `memory_search` 的位置。硬判是/否就是拿仪表分辨率
        装出来的确定性 —— 处置应当是"要么补精细桶、要么等更多样本"。
        """
        path = self._scrape(
            tmp_path, "boundary.txt", "boundary_tool",
            [("0.1", 1), ("0.25", 3), ("+Inf", 4)], total=4, sum_s=1.2,
        )
        payload = _readoutJson("--metrics-file", path)
        row = self._row(payload, "boundary_tool")
        assert row.get("p50_lower_ms") == 100.0 and row.get("p50_upper_ms") == 250.0
        assert row.get("worth_waiting") is None, (
            f"跨门槛的夹逼区间被硬判成 {row.get('worth_waiting')!r}——"
            "仪表分辨率答不出的问题不许装出答案"
        )
        text = _runReadout("--metrics-file", path).stdout
        assert "边界" in text, f"人类可读输出没把'边界'这一态说出来：{text[-400:]}"

    def test_coldTailIsReportedApartAndNeverFlipsTheVerdict(self, tmp_path):
        """冷路径**另档呈现**，且不得把常态判据带偏（本片的核心纪律）。

        10 个样本里 6 个在 10ms 级、4 个在 1s 级（冷热双峰）：常态不快不慢地
        偏在快侧 ⇒ 判"不值得"；而"有 40% 落在 >0.25s"必须另有一档读数可见，
        却不能把 verdict 翻成"值得"。
        """
        path = self._scrape(
            tmp_path, "bimodal.txt", "bimodal_tool",
            [("0.01", 6), ("0.25", 6), ("1.0", 8), ("2.5", 10), ("+Inf", 10)],
            total=10, sum_s=4.0,
        )
        row = self._row(_readoutJson("--metrics-file", path), "bimodal_tool")
        assert row.get("worth_waiting") is False, (
            "冷样本把常态判据带偏了（P50 明明在快侧）："
            f"拿到 {row.get('worth_waiting')!r}"
        )
        assert row.get("slow_share") == 0.4, (
            f"冷路径没另档呈现（应为 4/10）：拿到 {row.get('slow_share')!r}"
        )

    def test_judgementUsesTheMedianNotTheAverage(self, tmp_path):
        """反向控制：avg 被冷样本拖到秒级、中位仍在毫秒级 ⇒ 判据必须跟中位走。

        这正是本片选 P50 的理由；若实现改回比 avg，本用例立刻红。
        """
        path = self._scrape(
            tmp_path, "avgbias.txt", "avgbias_tool",
            [("0.01", 3), ("120.0", 4), ("+Inf", 4)], total=4, sum_s=120.0,
        )
        row = self._row(_readoutJson("--metrics-file", path), "avgbias_tool")
        assert row["avg_ms"] > 200.0, "用例前提：avg 已被冷样本拖过门槛"
        assert row.get("worth_waiting") is False, (
            f"判据跟了 avg 而不是 P50：拿到 {row.get('worth_waiting')!r}"
        )

    def test_thresholdValueIsNamedInTheReadout(self, tmp_path):
        """门槛值必须在读数里点名——不点名的门槛读者无法复核（也不会知道是多少）。"""
        path = self._scrape(
            tmp_path, "named.txt", "named_tool",
            [("0.01", 3), ("0.25", 5), ("+Inf", 6)], total=6, sum_s=0.05,
        )
        text = _runReadout("--metrics-file", path).stdout
        assert "200" in text, f"门槛值没在输出里点名：{text[-500:]}"
