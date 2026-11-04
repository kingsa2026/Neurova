"""带外审批执行后的续跑轮判据（候选 C3 批次 1，spec: docs/specs/2026-11-05-审批带外执行后自动续跑轮设计.md）

红灯判据：带外重放完成后无续跑——晚到终态沉在 _pending_hints（下一轮才被
读到），用户批准后拿不到任何主动汇报。
"""

import pytest
from types import SimpleNamespace

TOOL = "exec_command"
REQUEST_ID = "req-c3-1"


class _StubAgent:
    def __init__(self):
        self.calls = []

    async def chat(self, user_input, session_id, metadata=None):
        self.calls.append(
            {"user_input": user_input, "session_id": session_id, "metadata": dict(metadata or {})}
        )
        return {"text": "已收到晚到结果并汇报"}


@pytest.fixture
def stub_agent(monkeypatch):
    import neurova.security.approval_continuation as cont

    agent = _StubAgent()
    monkeypatch.setattr(cont, "_defaultAgentProvider", lambda agent_id: agent)
    return agent


def test_gate_default_off_is_current_semantics():
    """口径判据：默认值＝现网语义（不拉起），行为变更显式开启（工单 015）。"""
    from neurova.security.governance_settings import DEFAULTS

    assert DEFAULTS.get("approval_continuation_enabled") is False


@pytest.mark.asyncio
async def test_continuation_calls_agent_chat_with_structured_prompt(stub_agent, monkeypatch):
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: True)
    out = await cont.runApprovalContinuation(
        request_id=REQUEST_ID,
        agent_id="agt",
        user_id="u1",
        session_id="s1",
        tool_name=TOOL,
        success=True,
    )
    assert out["started"] is True and out["status"] == "completed"
    assert len(stub_agent.calls) == 1, "续跑轮必须恰好拉起一次"
    call = stub_agent.calls[0]
    assert call["session_id"] == "s1"
    assert TOOL in call["user_input"] and REQUEST_ID in call["user_input"]
    assert "执行成功" in call["user_input"]
    assert call["metadata"].get("approval_continuation") is True


@pytest.mark.asyncio
async def test_continuation_prompt_carries_failure_error(stub_agent, monkeypatch):
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: True)
    await cont.runApprovalContinuation(
        request_id=REQUEST_ID,
        agent_id="agt",
        user_id="u1",
        session_id="s1",
        tool_name=TOOL,
        success=False,
        error="exit code 1",
    )
    prompt = stub_agent.calls[0]["user_input"]
    assert "执行失败" in prompt and "exit code 1" in prompt


@pytest.mark.asyncio
async def test_continuation_disabled_returns_not_started(stub_agent, monkeypatch):
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: False)
    out = await cont.runApprovalContinuation(
        request_id=REQUEST_ID, agent_id="agt", user_id="u1",
        session_id="s1", tool_name=TOOL, success=True,
    )
    assert out == {"started": False, "reason": "disabled"}
    assert stub_agent.calls == []


@pytest.mark.asyncio
async def test_continuation_agent_missing_reports_honestly(monkeypatch):
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: True)
    monkeypatch.setattr(cont, "_defaultAgentProvider", lambda agent_id: None)
    out = await cont.runApprovalContinuation(
        request_id=REQUEST_ID, agent_id="nope", user_id="u1",
        session_id="s1", tool_name=TOOL, success=True,
    )
    assert out["started"] is False and out["reason"] == "agent_not_ready"


@pytest.mark.asyncio
async def test_continuation_without_session_honest_refusal(monkeypatch):
    """无会话归属不拉起：晚到通路同款纪律（宁可点名拒绝，不塞进别人的上下文）。"""
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: True)

    async def _boom(*a, **k):
        raise AssertionError("无会话归属不得发起任何 chat")

    monkeypatch.setattr(cont, "_defaultAgentProvider", lambda agent_id: SimpleNamespace(chat=_boom))
    out = await cont.runApprovalContinuation(
        request_id=REQUEST_ID, agent_id="agt", user_id="u1",
        session_id="", tool_name=TOOL, success=True,
    )
    assert out["started"] is False and out["reason"] == "no_session"


@pytest.mark.asyncio
async def test_continuation_agent_error_reported_not_faked(stub_agent, monkeypatch):
    import neurova.security.approval_continuation as cont

    monkeypatch.setattr(cont, "_continuationEnabled", lambda: True)

    async def _boom(user_input, session_id, metadata=None):
        raise RuntimeError("llm down")

    stub_agent.chat = _boom
    out = await cont.runApprovalContinuation(
        request_id=REQUEST_ID, agent_id="agt", user_id="u1",
        session_id="s1", tool_name=TOOL, success=True,
    )
    assert out["started"] is True and out["status"] == "failed" and "llm down" in out["error"]


@pytest.mark.asyncio
async def test_approve_endpoint_triggers_continuation_after_out_of_band_replay(monkeypatch):
    """端点 wiring：带外重放（无 waiter）完成后必须拉起续跑轮。"""
    from neurova.api.endpoints import governance as gov

    req = SimpleNamespace(
        request_id=REQUEST_ID,
        agent_id="agt",
        user_id="u1",
        status="pending",
        metadata={
            "tool_name": TOOL,
            "params": {"command": "ls"},
            "session_id": "s1",
            "tool_call_id": "call-1",
        },
    )

    class _AM:
        def get_request(self, rid):
            return req

        def approve_request(self, *a, **k):
            return True

    class _Exec:
        def __init__(self, agent):
            pass

        def _result_is_success(self, result):
            return bool(isinstance(result, dict) and result.get("success"))

        async def _execute_single_tool(self, name, params, skip_governance=False):
            return {"success": True}

    monkeypatch.setattr(gov, "_get_approvals", lambda: _AM())
    monkeypatch.setattr(gov, "_get_agent", lambda aid: object())
    monkeypatch.setattr("neurova.tool_executor.ToolExecutor", _Exec)
    # governance 顶部已绑定 hasApprovalWaiter 名字——补丁必须打它的命名空间
    monkeypatch.setattr(gov, "hasApprovalWaiter", lambda rid: False)

    captured = {}

    def _fake_start(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr("neurova.security.approval_continuation.startApprovalContinuation", _fake_start)

    from neurova.api.endpoints.governance import ApprovalActionRequest, approve_and_execute

    body = ApprovalActionRequest(approved_by="tester")
    resp = await approve_and_execute(SimpleNamespace(), REQUEST_ID, body, None)

    assert resp["data"]["executed"] is True, "带外重放必须真执行"
    assert captured.get("request_id") == REQUEST_ID, "带外重放后必须拉起续跑轮"
    assert captured.get("session_id") == "s1"
    assert captured.get("tool_name") == TOOL
    assert captured.get("success") is True


@pytest.mark.asyncio
async def test_approve_endpoint_no_continuation_when_waiter_holds_replay(monkeypatch):
    """有人在等（原轮阻塞中）→ 端点不重放，也就**不拉起续跑**（原轮自己收尾）。"""
    from neurova.api.endpoints import governance as gov

    req = SimpleNamespace(
        request_id=REQUEST_ID,
        agent_id="agt",
        user_id="u1",
        status="pending",
        metadata={"tool_name": TOOL, "params": {}, "session_id": "s1", "tool_call_id": "c1"},
    )

    class _AM:
        def get_request(self, rid):
            return req

        def approve_request(self, *a, **k):
            return True

    monkeypatch.setattr(gov, "_get_approvals", lambda: _AM())
    monkeypatch.setattr(gov, "_get_agent", lambda aid: object())
    monkeypatch.setattr(gov, "hasApprovalWaiter", lambda rid: True)

    def _forbidden(**kwargs):
        raise AssertionError("waiter 路径不得拉起续跑（原轮在管线里自己执行）")

    monkeypatch.setattr("neurova.security.approval_continuation.startApprovalContinuation", _forbidden)

    from neurova.api.endpoints.governance import ApprovalActionRequest, approve_and_execute

    body = ApprovalActionRequest(approved_by="tester")
    resp = await approve_and_execute(SimpleNamespace(), REQUEST_ID, body, None)
    assert resp["data"].get("resumed_in_turn") is True
