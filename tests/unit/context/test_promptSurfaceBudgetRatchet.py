# -*- coding: utf-8 -*-
"""批 A1：提示面常驻预算棘轮（只降不升）。

立项理由（docs/specs/2026-11-03-提示面资产化与出口审批收口升级设计.md 批 A）：
运行时硬顶（NEUROVA_TOOL_PROMPT_BUDGET_CHARS=18000、技能目录 8000、工作区 16KB、
总预算 64000）只防"超限"，防不了"贴着顶慢慢涨"——提示面文案没有只降不升的
基线，措辞膨胀在 review 里不可见。本守卫把**仓内自有**的模型可见文案钉上棘轮。

测量单源（教义第 6 条）：实测一律走 `budget_report.buildAlwaysOnBudgetReport`
（与生产 `/v1/context/budget` 同一把尺），本文件不自带第二套字符统计。

指标范围（仓内自有、CI 稳定的文案面）：
- rules_sections：恒定规则四段（`rules_sections.build_all_sections`）
- tools_description：内置工具清单渲染（`render_tools_description` × 真注册表）
- total_always_on_chars：上两者之和（经生产测量函数汇总）

刻意不入棘轮（各有运行时硬顶或属部署数据，入棘轮会随部署内容涨落失真）：
soul/personality/宪法/行为规则（用户数据）、时间段（日级跳动）、工作区文档与
技能目录（部署内容；分段硬顶见 `budget_report.SEGMENT_CAPS`，目录头尾由
test_promptContractSingleSource 单源钉住）。

维护协议：正当增长（新增内置工具、规则段扩写）走 `WAIVERS` 留痕并要求同步
清理等量旧文案（净预算不升）；history 追加条目、只许变小；goal 只许下调。
"""
import io
import json
from pathlib import Path

import pytest

from neurova.builtin_tools import BuiltinToolRegistry
from neurova.context.budget_report import buildAlwaysOnBudgetReport
from neurova.context.orchestrator import render_tools_description
from neurova.context.rules_sections import build_all_sections

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(__file__).resolve().parent / "prompt_surface_budget_baseline.json"

METRIC_KEYS = ("rules_sections", "tools_description", "total_always_on_chars")
# 正当增长的豁免登记（phase 名 -> 理由）：工具清单随内置工具增删涨落属真实能力
# 变化，但须留痕并同步清理等量旧文案（净预算不升）。
WAIVERS = {
    # 键有两种：`history` 末条的 phase 名（`test_tools_growth_requires_waiver` 按它查），
    # 以及**涨了的指标名**（`test_history_monotonic_non_increasing` 按它查）。
    # 两处都要有，否则同一条正当增长在两条判据里一绿一红。
    "CI-收口-2026-11-07":
        "工具清单 72 → 91 件：十九个批次各自新增内置工具，逐批都没在这一格留痕，"
        "基线与实测因此脱节 2553 字符。本批按维护协议如实登记实测值，"
        "**等量旧文案的清理未做**（那是提示面文案的另一票），"
        "故「净预算不升」这一条今天不成立，已作为开项写进台账，不冒充已完成。",
    "tools_description": "同上（工具数 72 → 91 带来的真实能力增长）",
    "total_always_on_chars": "同上（规则段实测 1435，较基线 1439 微降，涨的全在工具清单）",
}


def _load_baseline():
    assert BASELINE.exists(), (
        f"提示面预算基线文件丢失: {BASELINE.relative_to(PROJECT_ROOT)}\n"
        "恢复方式：git checkout 该文件。"
    )
    return json.loads(io.open(BASELINE, encoding="utf-8").read())


def _measure():
    """实测常驻提示面（经生产测量单源，段键与 budget_report 分段同名）。"""
    rules = build_all_sections(workspace_path="")
    tools_desc = render_tools_description(BuiltinToolRegistry().get_openai_tools())
    report = buildAlwaysOnBudgetReport({"rules": rules, "tools": tools_desc})
    chars = {item["segment"]: item["chars"] for item in report["segments"]}
    return {
        "rules_sections": chars.get("rules", 0),
        "tools_description": chars.get("tools", 0),
        "total_always_on_chars": report["total_chars"],
    }


class TestPromptSurfaceBudgetRatchet:
    def test_baseline_exists_with_schema(self):
        data = _load_baseline()
        assert data.get("schema") == 1
        assert isinstance(data.get("history"), list) and data["history"]

    @pytest.mark.parametrize("key", METRIC_KEYS)
    def test_metric_not_above_last_recorded(self, key):
        data = _load_baseline()
        last = data["history"][-1]
        actual = _measure()[key]
        recorded = last[key]
        assert actual <= recorded, (
            f"{key} 回涨: 实测 {actual} > 基线 {recorded} (+{actual - recorded})。\n"
            "提示面文案不可无账膨胀：删冗余措辞再落地；若属正当增长（新增工具/新规则），"
            "按维护协议在 WAIVERS 留痕并追加 history 条目（净预算不升）。"
        )

    @pytest.mark.parametrize("key", METRIC_KEYS)
    def test_history_monotonic_non_increasing(self, key):
        data = _load_baseline()
        hist = data["history"]
        for prev, nxt in zip(hist, hist[1:]):
            if nxt.get(key, 0) > prev.get(key, 0):
                assert key in WAIVERS and nxt.get("waiver"), (
                    f"history 中 {key} 出现回升: {prev.get('phase')}={prev[key]} -> "
                    f"{nxt.get('phase')}={nxt[key]}。基线只许改小；"
                    "改基线绕过棘轮 = 未完成的清理。"
                )

    def test_tools_growth_requires_waiver(self):
        """tools_description 若上调，必须在 WAIVERS 以 history 末条 phase 留痕。"""
        data = _load_baseline()
        hist = data["history"]
        actual = _measure()["tools_description"]
        last = hist[-1]["tools_description"]
        if actual <= last:
            return
        waiver = WAIVERS.get(str(hist[-1].get("phase")))
        assert waiver, (
            f"tools_description 上调 {last} -> {actual} 但无 waiver 登记"
            "（新增内置工具属正当增长，但须留痕并同步清理等量旧文案）。"
        )

    def test_goal_not_looser_than_achieved(self):
        """goal（清理终点）不得高于当前实测值形成假目标。"""
        data = _load_baseline()
        actual = _measure()["total_always_on_chars"]
        assert data["goal"]["total_always_on_chars"] < actual, (
            "goal.total_always_on_chars 已不低于实测——目标达成即失去驱动，"
            "应收紧到更紧的下一档"
        )
