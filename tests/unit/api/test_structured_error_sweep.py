"""W3 工具执行结构化错误信封全端点透传扫荡（批四收尾卡，2026-11-22）。

同根因（工具/技能执行失败的结构化 dict 载荷被压扁成裸 error 串）在
/tools/execute（45a8c452c 已修：失败响应 data.result 携带原始载荷、顶层
error 串保留兼容）之外仍散布于：

- skill.py 技能执行咽喉支：``SkillExecuteResponse(success=False, error=str(...))``
  把 payload（含 error_code/phase/retryable/executed 等结构化字段）压扁成串；
- computer.py 五处浏览器端点：``HTTPException(502, detail=normalized.get("error"))``
  只留串，normalized 里其余结构化字段全丢。

本卡钉约（不破坏既有消费方）：
- 技能失败：顶层 error 串保留 + 新增 ``error_detail`` 携带原始结构化载荷；
- 浏览器失败：502 响应体 ``detail`` 串原样保留（前端按字符串判读的契约不动），
  结构化载荷随 ``result`` 透传。
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


# 咽喉层 U3 失联相位的结构化失败载荷形态（与 tool_executor 的
# _sshNotExecutedEnvelope 同构，字段取自真实契约）
SKILL_STRUCTURED_FAILURE = {
    "success": False,
    "error": "技能执行失败：下游连接超时",
    "error_code": "REMOTE_NOT_EXECUTED",
    "phase": "execute",
    "retryable": True,
    "executed": False,
}

# 浏览器后端失败的结构化载荷（success/error 之外还带可判读语义字段）
BROWSER_STRUCTURED_FAILURE = {
    "success": False,
    "error": "浏览器命令执行失败：无可用后端",
    "error_code": "BROWSER_BACKEND_UNAVAILABLE",
    "phase": "dispatch",
    "retryable": False,
    "route": "camofox",
}

_BROWSER_STRUCTURED_FIELDS = ("error_code", "phase", "retryable", "route")


# ── 技能执行失败面 ─────────────────────────────────────


def _runSkillExecute(monkeypatch, structuredFailure):
    """经生产咽喉支驱动 execute_skill：agent 可用、executor 回结构化失败。"""
    from neurova.api.endpoints import skill as skillModule

    manifest = MagicMock()
    manifest.id = "probe_skill"
    manifest.name = "Probe"
    manifest.description = ""
    manifest.version = "1.0.0"
    manifest.keywords = []
    manifest.enabled = True
    registry = MagicMock()
    registry.list_skills.return_value = [manifest]

    executor = Mock()
    executor.execute_skill_tool = AsyncMock(return_value=dict(structuredFailure))
    executor._result_is_success = Mock(return_value=False)
    agent = Mock()
    agent.tool_executor = executor

    monkeypatch.setattr("neurova.skills.get_skill_registry", lambda *a, **k: registry)
    monkeypatch.setattr(skillModule, "_get_agent", lambda *a, **k: agent)

    request = MagicMock(spec=Request)
    request.state.request_id = "w3-structured-error-sweep"
    body = skillModule.SkillExecuteRequest(parameters={"q": 1})
    return asyncio.run(skillModule.execute_skill(request, "probe_skill", body))


def test_skillFailureCarriesStructuredErrorDetail(monkeypatch):
    """技能执行失败：error_detail 必须携带原始结构化载荷，顶层 error 串保留。"""
    response = _runSkillExecute(monkeypatch, SKILL_STRUCTURED_FAILURE)

    assert response.success is False, "结构化失败载荷应仍判失败"
    assert "超时" in (response.error or ""), "顶层 error 串保留（既有消费方契约不动）"
    detail = getattr(response, "error_detail", None) or {}
    for fieldName in ("error_code", "phase", "retryable", "executed"):
        assert detail.get(fieldName) == SKILL_STRUCTURED_FAILURE[fieldName], (
            f"技能失败面丢了结构化字段 {fieldName!r}——被压扁成裸 error 串: "
            f"error={response.error!r} error_detail={detail!r}"
        )


def test_skillSuccessDoesNotSetErrorDetail(monkeypatch):
    """成功面不带 error_detail（None），避免给成功响应塞噪声字段。"""
    from neurova.api.endpoints import skill as skillModule

    manifest = MagicMock()
    manifest.id = "probe_skill"
    manifest.name = "Probe"
    manifest.description = ""
    manifest.version = "1.0.0"
    manifest.keywords = []
    manifest.enabled = True
    registry = MagicMock()
    registry.list_skills.return_value = [manifest]

    executor = Mock()
    executor.execute_skill_tool = AsyncMock(return_value={"success": True, "data": {"ok": 1}})
    executor._result_is_success = Mock(return_value=True)
    agent = Mock()
    agent.tool_executor = executor

    monkeypatch.setattr("neurova.skills.get_skill_registry", lambda *a, **k: registry)
    monkeypatch.setattr(skillModule, "_get_agent", lambda *a, **k: agent)

    request = MagicMock(spec=Request)
    request.state.request_id = "w3-structured-error-sweep"
    response = asyncio.run(
        skillModule.execute_skill(request, "probe_skill", skillModule.SkillExecuteRequest())
    )

    assert response.success is True
    assert getattr(response, "error_detail", "missing") is None


# ── 浏览器端点失败面（五处） ───────────────────────────


def _assertBrowserFailureEnvelope(response):
    """502 信封判据：detail 串保留 + result 携带全部结构化字段。"""
    assert isinstance(response, JSONResponse), (
        f"浏览器失败应回 JSONResponse 信封（HTTPException 会把结构化载荷压扁成 "
        f"detail 串），实际返回 {type(response).__name__}"
    )
    assert response.status_code == 502, response.status_code
    payload = json.loads(response.body)
    detail = payload.get("detail")
    assert isinstance(detail, str) and detail, (
        f"detail 串必须原样保留（前端按字符串判读的契约不动）: {payload}"
    )
    result = payload.get("result") or {}
    for fieldName in _BROWSER_STRUCTURED_FIELDS:
        assert result.get(fieldName) == BROWSER_STRUCTURED_FAILURE[fieldName], (
            f"502 响应体丢了结构化字段 {fieldName!r}——被压扁成裸 detail 串: {payload}"
        )


def _driveBrowserFailure(monkeypatch, handlerName, methodName):
    """mock _get_manager 让指定浏览器方法返回结构化失败 dict，返回处理函数。"""
    from neurova.api.endpoints import computer as computerModule

    manager = Mock()
    managerMethod = AsyncMock(return_value=dict(BROWSER_STRUCTURED_FAILURE))
    setattr(manager, methodName, managerMethod)
    monkeypatch.setattr(computerModule, "_get_manager", lambda: manager)
    return computerModule, getattr(computerModule, handlerName)


def test_browserNavigateFailureCarriesStructuredResult(monkeypatch):
    computerModule, handler = _driveBrowserFailure(monkeypatch, "browser_navigate", "browser_navigate")
    body = computerModule.BrowserNavigateRequest(url="https://example.com")
    try:
        response = asyncio.run(handler(body, {"user_id": "w3-probe"}))
    except HTTPException as exc:
        raise AssertionError(
            f"browser_navigate 失败面把结构化载荷压扁成裸 detail 串（W3 未修）: {exc.detail!r}"
        ) from exc
    _assertBrowserFailureEnvelope(response)


def test_browserSnapshotFailureCarriesStructuredResult(monkeypatch):
    computerModule, handler = _driveBrowserFailure(
        monkeypatch, "browser_snapshot", "browser_dom_snapshot")
    body = computerModule.BrowserSnapshotRequest()
    try:
        response = asyncio.run(handler(body, {"user_id": "w3-probe"}))
    except HTTPException as exc:
        raise AssertionError(
            f"browser_snapshot 失败面把结构化载荷压扁成裸 detail 串（W3 未修）: {exc.detail!r}"
        ) from exc
    _assertBrowserFailureEnvelope(response)


def test_browserClickRoleFailureCarriesStructuredResult(monkeypatch):
    computerModule, handler = _driveBrowserFailure(
        monkeypatch, "browser_click_role", "browser_click_role")
    body = computerModule.BrowserClickRoleRequest(role="button")
    try:
        response = asyncio.run(handler(body, {"user_id": "w3-probe"}))
    except HTTPException as exc:
        raise AssertionError(
            f"browser_click_role 失败面把结构化载荷压扁成裸 detail 串（W3 未修）: {exc.detail!r}"
        ) from exc
    _assertBrowserFailureEnvelope(response)


def test_browserFillRoleFailureCarriesStructuredResult(monkeypatch):
    computerModule, handler = _driveBrowserFailure(
        monkeypatch, "browser_fill_role", "browser_fill_role")
    body = computerModule.BrowserFillRoleRequest(role="textbox", text="hello")
    try:
        response = asyncio.run(handler(body, {"user_id": "w3-probe"}))
    except HTTPException as exc:
        raise AssertionError(
            f"browser_fill_role 失败面把结构化载荷压扁成裸 detail 串（W3 未修）: {exc.detail!r}"
        ) from exc
    _assertBrowserFailureEnvelope(response)


def test_browserExecuteFailureCarriesStructuredResult(monkeypatch):
    """命令总线入口 /browser/execute：失败 502 透传结构化载荷。"""
    from neurova.api.endpoints import computer as computerModule

    monkeypatch.setattr(
        computerModule, "_dispatch_browser_command",
        AsyncMock(return_value=dict(BROWSER_STRUCTURED_FAILURE)),
    )
    cmd = computerModule.NavigateCmd(url="https://example.com")
    try:
        response = asyncio.run(
            computerModule.browser_execute_route(cmd, {"user_id": "w3-probe"}))
    except HTTPException as exc:
        raise AssertionError(
            f"browser_execute 失败面把结构化载荷压扁成裸 detail 串（W3 未修）: {exc.detail!r}"
        ) from exc
    _assertBrowserFailureEnvelope(response)
