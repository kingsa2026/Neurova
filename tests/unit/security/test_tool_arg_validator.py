"""T2 执行前参数校验单测 — docs/Neurova_工具调用链升级计划_2026-09-13.md。"""
import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.security.tool_arg_validator import validation_enabled, validate_tool_args


@pytest.fixture(autouse=True)
def _env_on(monkeypatch):
    monkeypatch.delenv("NEUROVA_TOOL_ARG_VALIDATION", raising=False)


def test_disabled_env_returns_passthrough(monkeypatch):
    monkeypatch.setenv("NEUROVA_TOOL_ARG_VALIDATION", "0")
    assert not validation_enabled()
    params, errors = validate_tool_args("weather", {"city": {"not": "a string"}})
    assert errors == [] and params == {"city": {"not": "a string"}}


def test_unknown_tool_no_schema_passes():
    params, errors = validate_tool_args("no_such_tool_xyz", {"anything": 1})
    assert errors == []


def test_string_number_coerced_then_passes():
    # recall_history.limit 是 integer，模型常以 "5" 字符串回传 → 宽容归一
    params, errors = validate_tool_args("recall_history", {"query": "x", "limit": "5"})
    assert errors == [] and params["limit"] == 5


def test_type_mismatch_rejected_with_field_path():
    params, errors = validate_tool_args("recall_history", {"query": "x", "limit": {"bad": 1}})
    assert errors and errors[0].startswith("limit:")


def test_missing_required_rejected():
    params, errors = validate_tool_args("memory_search", {"limit": 3})
    assert any("query" in e or "required" in e.lower() for e in errors)


def test_unknown_key_not_fatal():
    # 存量工具普遍多收参数（上游注入/模型冗余），未知键 jsonschema 默认放行
    params, errors = validate_tool_args("recall_history", {"query": "x", "typo_key": 1})
    assert errors == []


def test_enum_violation_rejected():
    # run_code 的 runtime_type enum 声明（T1 裁决补入）
    params, errors = validate_tool_args("run_code", {"code": "x", "runtime_type": "k8s"})
    assert any("runtime_type" in e for e in errors)


def test_alias_anyof_accepts_alternate_name():
    # weather/web_search 三别名 anyOf（T2 上线抓出的存量 required 矛盾修复）
    _, errors = validate_tool_args("weather", {"city": "北京"})
    assert errors == []
    _, errors = validate_tool_args("web_search", {"keywords": "AI 新闻"})
    assert errors == []


def test_alias_anyof_still_rejects_empty():
    _, errors = validate_tool_args("weather", {"unit": "c"})
    assert errors, "三别名全无时 anyOf 必须仍拒（空参不是合法天气查询）"


# ── 接线：执行器在核心执行前拒收非法参数 ──────────────────────────────


def test_executor_rejects_bad_args_before_core_execution(monkeypatch):
    from neurova.tool_executor import ToolExecutor

    ex = ToolExecutor(MagicMock())
    reached = {"core": False}

    async def _spy_core(tool_name, params):
        reached["core"] = True
        return ({"ok": True}, True, "spy")

    monkeypatch.setattr(ex, "_execute_tool_core", _spy_core)
    result = asyncio.run(
        ex._execute_single_tool("recall_history", {"query": "x", "limit": {"bad": 1}})
    )
    assert not reached["core"], "校验失败仍打到了执行核心"
    assert result["success"] is False and any("limit" in e for e in result["param_errors"])


def test_executor_env_off_skips_validation(monkeypatch):
    from neurova.tool_executor import ToolExecutor

    monkeypatch.setenv("NEUROVA_TOOL_ARG_VALIDATION", "0")
    ex = ToolExecutor(MagicMock())
    called = {"core": False}

    async def _core(tool_name, params):
        called["core"] = True
        return ({"ok": True}, True, "spy")

    monkeypatch.setattr(ex, "_execute_tool_core", _core)
    asyncio.run(ex._execute_single_tool("recall_history", {"query": "x", "limit": {"bad": 1}}))
    assert called["core"]
