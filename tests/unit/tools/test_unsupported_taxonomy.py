"""U12 结构化拒绝分类学（D4 升级计划）。

契约：能力未装配 / 端不支持所请求的输入域时，执行器返回**稳定形状**

    {success: False, error_code: "TOOL_UNSUPPORTED", reason: str, supported: [..], error: str}

而不是裸异常或无 error_code 的散装 error dict。

逐个清点的现存裸 raise / 不支持出口（本文件钉住）：
- _execute_create_skill：注入扫描器 ImportError 裸 raise（能力未装配，红=裸异常）；
- normalize_computer_params 的参数域拒绝（端不支持该参数，supported=放行表）；
- _execute_tool_core 的「未知工具」（supported=内置分派表）；
- _execute_git 的「不支持的 git 子命令」（supported=子命令白名单）。
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.tool_executor import ToolExecutor


def _makeExecutor(monkeypatch):
    agent = SimpleNamespace(
        config=SimpleNamespace(user_id="u1", agent_id="a1"),
        tool_memory=MagicMock(),
        tool_lifecycle=None,
        _skill_registry=None,
        tool_router=None,
        _current_user_input="x",
        _tool_messages_list=[],
        append_tool_messages=lambda records: None,
    )
    return ToolExecutor(agent)


@pytest.mark.asyncio
async def test_createSkillMissingScannerIsStructured(monkeypatch):
    """红：能力未装配（注入扫描器缺失）当前抛裸 ImportError；
    绿：执行边界翻译成 TOOL_UNSUPPORTED 结构化拒绝（仍 fail-closed）。"""
    executor = _makeExecutor(monkeypatch)
    monkeypatch.setitem(sys.modules, "neurova.security.skill_scanner", None)
    result = await executor._execute_single_tool("create_skill", {
        "name": "demo",
        "description": "测试技能",
        "steps": [{"name": "calculator", "params": {"expression": "1+1"}}],
    })
    assert isinstance(result, dict), "能力未装配必须回结构化 dict，不得裸异常逸出"
    assert result.get("error_code") == "TOOL_UNSUPPORTED", result
    assert result.get("success") is False
    assert "扫描器" in str(result.get("reason")), result
    assert isinstance(result.get("supported"), list)


@pytest.mark.asyncio
async def test_computerParamDomainRejectionIsStructured(monkeypatch):
    """端不支持该参数：error_code=TOOL_UNSUPPORTED，supported=该工具放行参数表。

    参数先过 T2 schema 校验（x/y 必填），再过 R1-3 放行表归一——
    故携带合法必填键 + 表外键来命中「未知参数」拒绝。"""
    executor = _makeExecutor(monkeypatch)
    result = await executor._execute_single_tool(
        "computer_click", {"x": 10, "y": 20, "bogus_param": 1})
    assert result.get("error_code") == "TOOL_UNSUPPORTED", result
    assert "bogus_param" in str(result.get("reason")), result
    supported = result.get("supported")
    assert isinstance(supported, list) and supported, "必须带该工具的放行参数表"
    assert "x" in supported and "button" in supported


@pytest.mark.asyncio
async def test_unknownToolIsStructuredWithSupportedList(monkeypatch):
    """未知工具（端不支持该工具名）：结构化拒绝 + supported=内置工具面。"""
    executor = _makeExecutor(monkeypatch)
    result = await executor._execute_single_tool("definitely_not_a_tool", {})
    assert result.get("error_code") == "TOOL_UNSUPPORTED", result
    assert "definitely_not_a_tool" in str(result.get("reason")), result
    supported = result.get("supported")
    assert isinstance(supported, list) and "calculator" in supported


@pytest.mark.asyncio
async def test_gitUnsupportedSubcommandIsStructured(monkeypatch):
    """不支持的 git 子命令：结构化拒绝 + supported=子命令白名单。"""
    executor = _makeExecutor(monkeypatch)
    result = await executor._execute_single_tool("git", {"command": "git frobnicate --all"})
    assert result.get("error_code") == "TOOL_UNSUPPORTED", result
    assert "frobnicate" in str(result.get("reason")), result
    supported = result.get("supported")
    assert isinstance(supported, list) and "status" in supported and "push" in supported


def test_toolUnsupportedResultShapeIsStable():
    """形状单源：toolUnsupportedResult 产出的键集恒定（消费方可安全按键判别）。"""
    from neurova.tool_executor import TOOL_UNSUPPORTED_CODE, toolUnsupportedResult

    result = toolUnsupportedResult("原因", supported=["a", "b"])
    assert result == {
        "success": False,
        "error_code": TOOL_UNSUPPORTED_CODE,
        "reason": "原因",
        "supported": ["a", "b"],
        "error": "原因",
    }
    assert toolUnsupportedResult("r")["supported"] == []
