# -*- coding: utf-8 -*-
"""Phase 0 — agent_core 尺寸棘轮（只降不升）。

背景（docs/04-plans/agent-core-decomposition-plan.md §1.4）：上一轮重构把
agent_core.py 做到 1621 行，随后功能持续回填至 2182 行——拆分是单向动作、
没有棘轮，历史成果被逐步吃掉。本守卫就是那道棘轮：

1. 七项尺寸指标（AST 实测）不得超过基线 history 最后一条的记录值；
   仅 agent_class_methods 可带 waiver 上调（新增公开行为须留痕）。
2. history 条目自身单调不升——防止"改基线而不是改代码"的绕过。
3. 基线文件存在性 + schema 兼容（文件被删/改结构时红灯给出恢复指引）。

维护协议（每完成一个 Phase）：
  a. 追加一条 history 条目：phase、date、description、七项 metric 实测值；
  b. 所有 metric 必须 <= 上一条（方法数豁免见 METHOD_COUNT_WAIVERS）；
  c. goal.agent_core_lines / goal.agent_class_lines 只许在达标时下调。
"""
import ast
import io
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AGENT_CORE = PROJECT_ROOT / "neurova" / "agent_core.py"
BASELINE = Path(__file__).resolve().parent / "agent_core_size_baseline.json"

METRIC_KEYS = (
    "agent_core_lines",
    "subsystem_container_lines",
    "subsystem_container_methods",
    "agent_class_lines",
    "agent_class_methods",
    "agent_class_property_accessors",
    "agent_class_non_property_methods",
)

# 允许带 waiver 回升的指标（只限"转发面新增"这类结构性增长）：
# 方法/property 数可因门面转发层新增而 +1，但必须在 history 条目写 waiver 理由。
METHOD_COUNT_KEYS = {"agent_class_methods", "agent_class_property_accessors",
                     "agent_class_non_property_methods"}

# 方法数上调豁免：phase 名 -> 理由（新增公开行为须在此留痕）
METHOD_COUNT_WAIVERS = {"Phase 1": "turn_state 门面 property 新增（转发面，非逻辑回填）"}

# 例外：agent_core_lines 允许因本守卫文件的 header 注释维护而 +2 容差？
# 不允许。守卫只盯生产文件 agent_core.py，与测试文件无关，无需容差。


def _load_baseline():
    assert BASELINE.exists(), (
        f"尺寸基线文件丢失: {BASELINE.relative_to(PROJECT_ROOT)}\n"
        "恢复方式：git checkout 该文件，或重跑拆分方案 Phase 0 的基线生成脚本后提交。"
    )
    return json.loads(io.open(BASELINE, encoding="utf-8").read())


def _measure():
    src = io.open(AGENT_CORE, encoding="utf-8").read()
    tree = ast.parse(src)
    metrics = {"agent_core_lines": len(src.splitlines())}
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        funcs = [n for n in node.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        props = [n for n in funcs if any(
            (isinstance(d, ast.Name) and d.id == "property")
            or (isinstance(d, ast.Attribute) and d.attr in ("setter", "deleter"))
            for d in n.decorator_list
        )]
        span = node.end_lineno - node.lineno + 1
        if node.name == "Agent":
            found.add("Agent")
            metrics["agent_class_lines"] = span
            metrics["agent_class_methods"] = len(funcs)
            metrics["agent_class_property_accessors"] = len(props)
            metrics["agent_class_non_property_methods"] = len(funcs) - len(props)
        elif node.name == "SubSystemContainer":
            found.add("SubSystemContainer")
            metrics["subsystem_container_lines"] = span
            metrics["subsystem_container_methods"] = len(funcs)
    assert found == {"Agent", "SubSystemContainer"}, (
        f"agent_core.py 缺少预期类: 缺 {found ^ {'Agent', 'SubSystemContainer'}}——"
        "若类被重命名/搬迁，本守卫需随 Phase 验收同步更新"
    )
    return metrics


class TestSizeRatchet:
    def test_baseline_exists_with_schema(self):
        data = _load_baseline()
        assert data.get("schema") == 1
        assert isinstance(data.get("history"), list) and data["history"]
        assert isinstance(data.get("goal"), dict)

    @pytest.mark.parametrize("key", METRIC_KEYS)
    def test_metric_not_above_last_recorded(self, key):
        data = _load_baseline()
        last = data["history"][-1]
        assert key in last, f"基线 history 末条缺 metric: {key}"
        actual = _measure()[key]
        recorded = last[key]
        assert actual <= recorded, (
            f"{key} 回涨: 实测 {actual} > 基线 {recorded} (+{actual - recorded})。\n"
            "拆分成果不可回填：新逻辑请落 neurova/agent/ 深模块；"
            "若属拆分 Phase 收尾，按维护协议追加 history 条目（只降不升）。"
        )

    @pytest.mark.parametrize("key", METRIC_KEYS)
    def test_history_monotonic_non_increasing(self, key):
        data = _load_baseline()
        hist = data["history"]
        for prev, nxt in zip(hist, hist[1:]):
            if key in METHOD_COUNT_WAIVERS:
                continue  # 方法数豁免由 test_method_count_increase_requires_waiver 单独盯
            waiver = nxt.get("waiver") if nxt.get(key, 0) > prev.get(key, 0) else None
            assert nxt[key] <= prev[key] or (waiver and key in METHOD_COUNT_KEYS), (
                f"history 中 {key} 出现回升: {prev.get('phase')}={prev[key]} -> "
                f"{nxt.get('phase')}={nxt[key]}。基线只许改小；"
                "改基线绕过棘轮 = 未完成拆分。"
            )

    def test_method_count_increase_requires_waiver(self):
        """agent_class_methods 若上调，必须在 METHOD_COUNT_WAIVERS 留痕。"""
        data = _load_baseline()
        hist = data["history"]
        actual = _measure()["agent_class_methods"]
        last = hist[-1]["agent_class_methods"]
        if actual <= last:
            return
        waiver = METHOD_COUNT_WAIVERS.get(str(hist[-1].get("phase")))
        assert waiver, (
            f"agent_class_methods 上调 {last} -> {actual} 但无 waiver 登记。"
            "在 METHOD_COUNT_WAIVERS 以 history 末条 phase 为键登记理由，"
            "并确认新增的是不可回避的公开行为而非可下沉的逻辑。"
        )

    def test_goal_not_looser_than_achieved(self):
        """goal（拆分终点）不得高于当前实测值形成假目标。"""
        data = _load_baseline()
        m = _measure()
        for gkey, mkey in (("agent_core_lines", "agent_core_lines"),
                           ("agent_class_lines", "agent_class_lines")):
            assert data["goal"][gkey] < m[mkey], (
                f"goal.{gkey}({data['goal'][gkey]}) >= 当前实测({m[mkey]})——"
                "目标已达成即失去驱动；Phase 验收时应下调到更紧的下一档"
            )
