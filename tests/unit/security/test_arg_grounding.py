"""T5 日期落地校验 — docs/Neurova_工具调用链升级计划_2026-09-13.md。

契约：schema 标了 format=date/date-time 的 string 参数，年份须在可见文本
有字面依据（Needle ungrounded 移植）。开关默认关；标记即生效开关。

实况修正（相对计划 Step 5）：当前 62 内置工具面无一收日历日期参数
（2026-09-13 grep 全仓实证，调度器为内部模块不进 LLM 面），故机制交付
为 inert-but-ready——无标记工具零影响，未来工具标 format 即自动生效。
"""
import pytest

from neurova.security.arg_grounding import (
    find_ungrounded_date_fields,
    get_conversation_source,
    grounding_enabled,
    set_conversation_source,
)

_SCHEMA = {"type": "object", "properties": {
    "date": {"type": "string", "format": "date"},
    "meeting_at": {"type": "string", "format": "date-time"},
    "note": {"type": "string"},
}}


def test_ungrounded_year_detected():
    bad = find_ungrounded_date_fields(_SCHEMA, {"date": "2027-03-01"},
                                      source_text="帮我记一下明天开会 2026年")
    assert bad == ["date: 值 2027-03-01 的年份 2027 在可见文本中无字面依据"]


def test_grounded_passes():
    assert find_ungrounded_date_fields(_SCHEMA, {"date": "2026-09-20"},
                                       source_text="2026 财年计划") == []


def test_date_time_format_checked_too():
    bad = find_ungrounded_date_fields(_SCHEMA, {"meeting_at": "2031-01-01T10:00"},
                                      source_text="今天 2026-09-13")
    assert bad and bad[0].startswith("meeting_at")


def test_non_date_field_ignored():
    assert find_ungrounded_date_fields(_SCHEMA, {"note": "2099"}, source_text="x") == []


def test_missing_or_empty_value_ignored():
    assert find_ungrounded_date_fields(_SCHEMA, {"date": ""}, source_text="2026") == []
    assert find_ungrounded_date_fields(_SCHEMA, {}, source_text="2026") == []


def test_garbage_prefix_not_treated_as_year():
    assert find_ungrounded_date_fields(_SCHEMA, {"date": "xxxx-01-01"}, source_text="") == []


def test_empty_source_rejects_declared_year():
    # 可见文本为纯空白时，带 format 的日期字段一律判臆造（Needle omission 语义）
    bad = find_ungrounded_date_fields(_SCHEMA, {"date": "2025-01-01"}, source_text="   ")
    assert len(bad) == 1


def test_default_off(monkeypatch):
    monkeypatch.delenv("NEUROVA_ARG_GROUNDING", raising=False)
    assert not grounding_enabled()
    monkeypatch.setenv("NEUROVA_ARG_GROUNDING", "1")
    assert grounding_enabled()


def test_contextvar_roundtrip():
    set_conversation_source("计划定在 2027 年")
    assert "2027" in get_conversation_source()


def test_mechanism_inert_without_markers():
    """无 format 标记的现有内置工具全部零影响（inert-but-ready 钉测）。"""
    from neurova.builtin_tools import _BUILTIN_SCHEMAS

    for name, entry in _BUILTIN_SCHEMAS.items():
        marked = [p for p in (entry["parameters"].get("properties") or {}).values()
                  if isinstance(p, dict) and p.get("format") in ("date", "date-time")]
        assert not marked, f"{name} 带日期标记但本测试前提是当前工具面无日历日期参数——请同步改写本测试与 T5 计划"


def test_executor_wiring_rejects_ungrounded(monkeypatch):
    """接线钉测：env 开 + 工具 schema 带日期标记 + 无依据年份 → 拒执行回传 ungrounded。"""
    import asyncio
    from unittest.mock import MagicMock

    from neurova.security import arg_grounding

    monkeypatch.setenv("NEUROVA_ARG_GROUNDING", "1")
    # 伪造一个带 format 标记的"工具"schema（当前真实工具面尚不存在，见模块 docstring）
    import neurova.builtin_tools as bt

    bt._BUILTIN_SCHEMAS["fake_dated_tool"] = {
        "description": "test",
        "parameters": {"type": "object", "properties": {"date": {"type": "string", "format": "date"}},
                       "required": ["date"]},
    }
    try:
        from neurova.tool_executor import ToolExecutor

        ex = ToolExecutor(MagicMock())
        reached = {"core": False}

        async def _spy_core(tool_name, params):
            reached["core"] = True
            return ({"ok": True}, True, "spy")

        monkeypatch.setattr(ex, "_execute_tool_core", _spy_core)
        arg_grounding.set_conversation_source("我们 2026 年再说")
        result = asyncio.run(ex._execute_single_tool("fake_dated_tool", {"date": "2030-01-01"}))
        assert not reached["core"], "ungrounded 日期仍打到了执行核心"
        assert result["success"] is False and result["validation"]["ungrounded"]

        # 有依据年份 → 放行
        result2 = asyncio.run(ex._execute_single_tool("fake_dated_tool", {"date": "2026-05-01"}))
        assert reached["core"], "grounded 日期应放行执行"
    finally:
        bt._BUILTIN_SCHEMAS.pop("fake_dated_tool", None)
