# -*- coding: utf-8 -*-
"""工具定义三投影·第一步（盘点投影 + 快照门）守卫。

实施计划：docs/04-plans/2026-11-20-reference-aa-borrowable-mechanisms-plan.md 项 3。

钉住四件事：
1. catalog 的 ToolDef 名册与 `get_registered_tool_names()` 完全一致
   （不多不少、顺序稳定）——盘点投影的覆盖面判据；
2. 每个工具都有 external_write 判定，且非只读 ⇒ external_write=True
   （项 2 journal 消费口径：非只读即记账；不新造名单）；
3. `contracts/tool_catalog.json` 快照与当前推导一致；篡改即门红
   （对齐项 5 的 verify-diff 纪律）；
4. 迁移样例：`context_status` 的 help 行由 catalog 渲染，与既有 OpenAI
   出口渲染逐字节一致（证明 help 投影可行且零漂移）。
"""

from __future__ import annotations

import json
from pathlib import Path

from neurova.builtin_tools import (
    BuiltinToolRegistry,
    get_builtin_tool_params,
    get_registered_tool_names,
)
from neurova.tools.catalog import (
    HELP_PROJECTION_SAMPLE_TOOL,
    ToolDef,
    all_tool_defs,
    build_snapshot,
    dump_snapshot,
    get_tool_def,
    render_help_line,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = PROJECT_ROOT / "contracts" / "tool_catalog.json"


def _legacyLine(fn: dict, with_params: bool = True, desc_limit=None) -> str:
    """按既有 render_tools_description._line 的格式规则**独立**重建 help 行。

    这是迁移零漂移的对照基准：catalog 渲染结果必须与它逐字节一致。
    """
    desc = fn.get("description", "") or ""
    if desc_limit is not None and len(desc) > desc_limit:
        desc = desc[:desc_limit] + "…"
    params_desc = ""
    if with_params:
        params = fn.get("parameters", {}).get("properties", {})
        required = fn.get("parameters", {}).get("required", [])
        if params:
            param_list = [f"{k}{'(必填)' if k in required else ''}" for k in params]
            params_desc = f" — 参数: {', '.join(param_list)}"
    return f"- **{fn['name']}**: {desc}{params_desc}"


class TestCatalogCoversRegisteredTools:
    """判据 a：catalog 与 get_registered_tool_names() 完全一致（不多不少）。"""

    def test_names_exactly_match_registry(self):
        registered = get_registered_tool_names()
        catalogNames = [d.name for d in all_tool_defs()]
        assert registered, "注册名册为空（装配面断了）"
        assert len(catalogNames) == len(set(catalogNames)), "catalog 出现重复工具名"
        assert set(catalogNames) == set(registered), "catalog 与注册名册不一致"
        assert catalogNames == registered, "catalog 顺序应与注册名册一致（按名排序）"

    def test_tooldef_carries_declared_fields(self):
        for field in (
            "name",
            "description",
            "args_schema",
            "read_only",
            "external_write",
            "min_role",
            "agent_scope",
        ):
            assert all(hasattr(d, field) for d in all_tool_defs()), f"ToolDef 缺字段 {field}"

    def test_args_schema_is_a_copy_not_the_live_source(self):
        """args_schema 必须是声明位的副本——调用方改动不得污染事实源。"""
        defn = get_tool_def("file_read")
        assert defn is not None
        liveParams = get_builtin_tool_params("file_read")["parameters"]
        assert defn.args_schema == liveParams
        assert defn.args_schema is not liveParams

    def test_main_agent_only_tools_projected_to_agent_scope(self):
        byName = {d.name: d for d in all_tool_defs()}
        assert byName["spawn_subagent"].agent_scope == "main_only"
        assert byName["file_read"].agent_scope == "all"

    def test_get_tool_def_roundtrip_and_unknown(self):
        assert get_tool_def("file_read") is not None
        assert get_tool_def("__no_such_tool__") is None
        assert isinstance(get_tool_def("file_read"), ToolDef)


class TestExternalWriteDetermination:
    """判据 b：每个非只读工具都有 external_write 判定（非只读即记账口径）。"""

    def test_every_tool_has_boolean_determination(self):
        for defn in all_tool_defs():
            assert isinstance(defn.read_only, bool), defn.name
            assert isinstance(defn.external_write, bool), defn.name

    def test_non_readonly_implies_external_write(self):
        offenders = [d.name for d in all_tool_defs() if not d.read_only and not d.external_write]
        assert offenders == [], f"非只读工具未判 external_write：{offenders}"

    def test_readonly_implies_not_external_write(self):
        offenders = [d.name for d in all_tool_defs() if d.read_only and d.external_write]
        assert offenders == [], f"只读工具被误判 external_write：{offenders}"

    def test_spot_check_readonly_and_write(self):
        byName = {d.name: d for d in all_tool_defs()}
        assert byName["file_read"].read_only is True
        assert byName["file_read"].external_write is False
        assert byName["file_write"].read_only is False
        assert byName["file_write"].external_write is True


class TestSnapshotGate:
    """判据 c：快照可重复生成；篡改红 / 一致绿。"""

    def test_snapshot_is_reproducible(self):
        assert dump_snapshot(build_snapshot()) == dump_snapshot(build_snapshot())

    def test_snapshot_is_sorted_and_counted(self):
        snapshot = build_snapshot()
        names = [t["name"] for t in snapshot["tools"]]
        assert names == sorted(names)
        assert snapshot["tool_count"] == len(names) == len(get_registered_tool_names())

    def test_committed_snapshot_matches_derivation(self):
        assert SNAPSHOT_PATH.is_file(), "contracts/tool_catalog.json 缺失"
        stored = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        assert stored == build_snapshot(), "仓库快照与当前推导不一致（快照没跟上代码）"

    def test_gate_green_on_committed_snapshot(self):
        from scripts.check_tool_catalog import main as gateMain

        assert gateMain([]) == 0

    def test_gate_green_on_fresh_derivation(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        snapshotFile = tmp_path / "tool_catalog.json"
        snapshotFile.write_text(dump_snapshot(build_snapshot()), encoding="utf-8")
        assert gateMain(["--snapshot", str(snapshotFile)]) == 0

    def test_gate_red_when_snapshot_missing(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        assert gateMain(["--snapshot", str(tmp_path / "nope.json")]) == 1

    def test_gate_red_when_tool_mutated(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        stored = build_snapshot()
        stored["tools"][0]["read_only"] = not stored["tools"][0]["read_only"]
        snapshotFile = tmp_path / "tool_catalog.json"
        snapshotFile.write_text(dump_snapshot(stored), encoding="utf-8")
        assert gateMain(["--snapshot", str(snapshotFile)]) == 1

    def test_gate_red_when_tool_removed(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        stored = build_snapshot()
        stored["tools"] = stored["tools"][1:]
        stored["tool_count"] = len(stored["tools"])
        snapshotFile = tmp_path / "tool_catalog.json"
        snapshotFile.write_text(dump_snapshot(stored), encoding="utf-8")
        assert gateMain(["--snapshot", str(snapshotFile)]) == 1

    def test_gate_red_when_phantom_tool_added(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        stored = build_snapshot()
        stored["tools"].append({**stored["tools"][0], "name": "phantom_tool"})
        stored["tool_count"] = len(stored["tools"])
        snapshotFile = tmp_path / "tool_catalog.json"
        snapshotFile.write_text(dump_snapshot(stored), encoding="utf-8")
        assert gateMain(["--snapshot", str(snapshotFile)]) == 1

    def test_gate_update_regenerates_identical_snapshot(self, tmp_path):
        from scripts.check_tool_catalog import main as gateMain

        snapshotFile = tmp_path / "tool_catalog.json"
        assert gateMain(["--update", "--snapshot", str(snapshotFile)]) == 0
        assert json.loads(snapshotFile.read_text(encoding="utf-8")) == build_snapshot()


class TestHelpProjectionMigration:
    """判据 d（迁移样例）：sample 工具的 help 行由 catalog 渲染且零漂移。

    orchestrator 的接线待按域迁移批次再接入；本类直接对 ``render_help_line``
    的输出做零漂移断言，证明 help 投影可行（同一 ToolDef 可渲染出与既有
    OpenAI 出口逐字节一致的提示词条目）。
    """

    def test_sample_tool_is_in_catalog(self):
        assert get_tool_def(HELP_PROJECTION_SAMPLE_TOOL) is not None

    def test_sample_help_line_matches_legacy_surface_byte_for_byte(self):
        tool = BuiltinToolRegistry().get_tool(HELP_PROJECTION_SAMPLE_TOOL)
        assert tool is not None
        expected = _legacyLine(tool.to_openai_format()["function"])
        actual = render_help_line(get_tool_def(HELP_PROJECTION_SAMPLE_TOOL))
        assert actual == expected

    def test_sample_help_line_degraded_forms_match_legacy(self):
        tool = BuiltinToolRegistry().get_tool(HELP_PROJECTION_SAMPLE_TOOL)
        fn = tool.to_openai_format()["function"]
        defn = get_tool_def(HELP_PROJECTION_SAMPLE_TOOL)
        for withParams, descLimit in ((False, None), (False, 400), (False, 40), (True, 160)):
            expected = _legacyLine(fn, with_params=withParams, desc_limit=descLimit)
            actual = render_help_line(defn, with_params=withParams, desc_limit=descLimit)
            assert actual == expected, f"with_params={withParams}, desc_limit={descLimit}"

    def test_help_line_is_prompt_ready(self):
        """渲染结果即提示词条目：含工具名、完整描述与参数段，可直接落『可用工具』段。"""
        defn = get_tool_def(HELP_PROJECTION_SAMPLE_TOOL)
        line = render_help_line(defn)
        assert line.startswith(f"- **{defn.name}**: ")
        assert defn.description in line
        assert " — 参数: " in line
