# -*- coding: utf-8 -*-
"""B4/B5 设备桥治理判据（风险分级门 / 审批扣住 / 熔断 / 审计留痕）。

计划卡 B4/B5（docs/04-plans/2026-11-23-mobile-execution-end-plan.md §5 批二）：
- D4 拍板：screen_*/notification_read/clipboard_read 一律 require_approval；
  open_url/device_env 等低风险 auto；review/sandbox 档全部须审批；
- 审批走既有 ApprovalManager 单源，手机端经 chat:approval_required 帧呈现
  审批卡，超时即拒（默认 60s）；
- 熔断：步数/时长双上限（D5：默认 50 步 / 600s），超限结构化拒绝
  device_budget_exhausted（新拒绝码，retry=never）；
- B5 留痕：设备动作进 desktop_audit 审计库；处于蜂群 run 上下文时落 H-4
  （appendRunEvent，事件型 device_action）。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.computer_use.runtime_policy import DesktopRuntimeMode
from neurova.device_bridge.governance import (
    ALWAYS_APPROVAL_ACTIONS,
    decide_device,
    enforce_approval_gate,
    resetBudgetState,
)
from neurova.device_bridge.registry import (
    DeviceConnectionRegistry,
    resetDeviceBridgeRegistry,
)


class FakeRawWs:
    def __init__(self) -> None:
        self.sent: list = []

    async def send_json(self, frame) -> None:
        self.sent.append(frame)


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    from neurova.device_bridge.registry import resetDeviceBridgeRegistry
    from neurova.device_bridge.router import resetDeviceBridgeRouter

    monkeypatch.setenv("NEUROVA_MOBILE_WS_LEDGER_DB", str(tmp_path / "ws_ledger.db"))
    monkeypatch.setenv("NEUROVA_DEVICE_BRIDGE_ENABLED", "1")
    monkeypatch.delenv("NEUROVA_DEVICE_MAX_STEPS", raising=False)
    monkeypatch.delenv("NEUROVA_DEVICE_MAX_DURATION_S", raising=False)
    monkeypatch.delenv("NEUROVA_DEVICE_APPROVAL_TIMEOUT_S", raising=False)
    resetDeviceBridgeRegistry()
    resetBudgetState()
    yield
    resetDeviceBridgeRegistry()
    resetBudgetState()


@pytest.fixture()
def approvalManager(tmp_path):
    from neurova.security.approval_manager import ApprovalManager

    manager = ApprovalManager(str(tmp_path / "workspace"))
    yield manager


@pytest.fixture()
def onlineDevice():
    from neurova.device_bridge.registry import getDeviceBridgeRegistry

    registry = getDeviceBridgeRegistry()
    raw = FakeRawWs()

    class _Ledger:
        async def send_json(self, frame):
            await raw.send_json(frame)

    registry.register("pair-gov-1", "u-gov", _Ledger())
    return raw


# ── 策略纯函数 ────────────────────────────────────────────────────────


class TestDevicePolicy:
    def test_always_approval_set_matches_d4(self):
        assert ALWAYS_APPROVAL_ACTIONS == frozenset({
            "screen_observe", "screen_gesture", "notification_read", "clipboard_read",
        })

    def test_high_sensitive_actions_require_approval_even_in_full(self):
        # screen_*/notification_read = high；clipboard_read 隐私敏感 = medium，
        # 但同在 D4 一律审批集——决策都是 require_approval，风险档按词表各归各
        for action, risk in (("screen_observe", "high"), ("screen_gesture", "high"),
                             ("notification_read", "high"), ("clipboard_read", "medium")):
            decision = decide_device(action, DesktopRuntimeMode.FULL.value)
            assert decision["action"] == "require_approval", action
            assert decision["risk"] == risk, action

    def test_low_risk_auto_executes_in_full(self):
        for action in ("open_url", "device_env", "open_app", "clipboard_write", "app_list"):
            decision = decide_device(action, DesktopRuntimeMode.FULL.value)
            assert decision["action"] == "proceed", action

    def test_review_mode_requires_approval_for_everything(self):
        for action in ("open_url", "device_env", "screen_gesture"):
            decision = decide_device(action, DesktopRuntimeMode.REVIEW.value)
            assert decision["action"] == "require_approval", action

    def test_unknown_action_defaults_to_approval(self):
        decision = decide_device("some_new_action", DesktopRuntimeMode.FULL.value)
        assert decision["action"] == "require_approval"


# ── 审批扣住流程 ──────────────────────────────────────────────────────


class TestApprovalGate:
    def test_low_risk_proceeds_without_approval(self, approvalManager, onlineDevice, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )
        gate = asyncio.run(enforce_approval_gate(
            "device_open_url", {"url": "https://example.com"},
            agent_id="ag-1", user_id="u-gov", session_id="sess-1"))
        assert gate is None
        assert onlineDevice.sent == []

    @pytest.mark.parametrize("tool", ["device_screen_gesture", "device_clipboard_read"])
    def test_high_sensitive_is_held_for_approval(self, approvalManager, onlineDevice, monkeypatch, tool):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )
        holder: dict = {}

        async def flow():
            task = asyncio.create_task(enforce_approval_gate(
                tool, {}, agent_id="ag-1", user_id="u-gov", session_id="sess-1"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if onlineDevice.sent:
                    break
            approvalFrame = onlineDevice.sent[0]
            holder["frame"] = approvalFrame
            request_id = approvalFrame["data"]["approval_id"]
            assert approvalManager.approve_request(request_id, approved_by="u-gov")
            return await task

        gate = asyncio.run(flow())
        assert gate is None  # 批准后放行
        frame = holder["frame"]
        assert frame["type"] == "chat:approval_required"
        assert frame["data"]["tool_name"] == tool

    def test_rejection_refuses_with_permission_required(self, approvalManager, onlineDevice, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )

        async def flow():
            task = asyncio.create_task(enforce_approval_gate(
                "device_screen_gesture", {}, agent_id="ag-1", user_id="u-gov",
                session_id="sess-1"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if onlineDevice.sent:
                    break
            request_id = onlineDevice.sent[0]["data"]["approval_id"]
            assert approvalManager.reject_request(request_id, rejected_by="u-gov")
            return await task

        gate = asyncio.run(flow())
        assert gate is not None
        assert gate["success"] is False
        assert gate["action_result"]["refusal_code"] == "permission_required"
        assert gate["action_result"]["escalation"]["reason"] == "approval_rejected"

    def test_timeout_refuses(self, approvalManager, onlineDevice, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )
        monkeypatch.setenv("NEUROVA_DEVICE_APPROVAL_TIMEOUT_S", "0.2")

        async def flow():
            task = asyncio.create_task(enforce_approval_gate(
                "device_screen_gesture", {}, agent_id="ag-1", user_id="u-gov",
                session_id="sess-1"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if onlineDevice.sent:
                    break
            return await task

        gate = asyncio.run(flow())
        assert gate is not None
        assert gate["success"] is False
        assert gate["action_result"]["escalation"]["reason"] == "approval_timeout"


# ── 熔断 ─────────────────────────────────────────────────────────────


class TestBudgetBreaker:
    def test_step_limit_trips_budget_refusal(self, approvalManager, onlineDevice, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )
        monkeypatch.setenv("NEUROVA_DEVICE_MAX_STEPS", "2")

        async def flow():
            outcomes = []
            for i in range(3):
                outcomes.append(await enforce_approval_gate(
                    "device_open_url", {"url": "https://example.com"},
                    agent_id="ag-1", user_id="u-gov", session_id="sess-budget"))
            return outcomes

        outcomes = asyncio.run(flow())
        assert outcomes[0] is None and outcomes[1] is None
        assert outcomes[2] is not None
        assert outcomes[2]["error"]["code"] == "device_budget_exhausted"
        assert outcomes[2]["action_result"]["refusal_code"] == "device_budget_exhausted"

    def test_budget_is_per_session(self, approvalManager, onlineDevice, monkeypatch):
        monkeypatch.setattr(
            "neurova.security.approval_manager.get_approval_manager",
            lambda **kwargs: approvalManager,
        )
        monkeypatch.setenv("NEUROVA_DEVICE_MAX_STEPS", "1")

        async def flow():
            first = await enforce_approval_gate(
                "device_open_url", {"url": "https://example.com"},
                agent_id="ag-1", user_id="u-gov", session_id="sess-a")
            other = await enforce_approval_gate(
                "device_open_url", {"url": "https://example.com"},
                agent_id="ag-1", user_id="u-other", session_id="sess-b")
            return first, other

        first, other = asyncio.run(flow())
        assert first is None
        assert other is None  # 另一会话不受波及


# ── B5 审计留痕 ───────────────────────────────────────────────────────


class TestDeviceAudit:
    def test_audit_records_into_desktop_audit(self, tmp_path, monkeypatch):
        from neurova.device_bridge.governance import auditDeviceAction
        from neurova.security import desktop_audit

        store = desktop_audit.DesktopAuditStore(db_path=str(tmp_path / "audit.db"))
        monkeypatch.setattr(
            "neurova.security.desktop_audit.get_desktop_audit_store",
            lambda db_path=None: store,
        )
        auditDeviceAction(
            "device_open_url", {"url": "https://example.com"},
            {"success": True}, 12.0,
            user_id="u-gov", agent_id="ag-1", session_id="sess-1")
        records = store.query_actions(tool="device_open_url", limit=10)
        assert len(records) == 1
        assert records[0]["session_id"] == "sess-1"

    def test_audit_writes_h4_event_inside_swarm_run(self, tmp_path, monkeypatch):
        from neurova.agent import swarm
        from neurova.agent.swarm_event_log import readRunEvents
        from neurova.device_bridge.governance import auditDeviceAction

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        token = swarm._currentSubagentIdVar.set("run-gov-1")
        try:
            auditDeviceAction(
                "device_tap", {"x": 1, "y": 2},
                {"success": True}, 5.0,
                user_id="u-gov", agent_id="ag-1", session_id="sess-1")
        finally:
            swarm._currentSubagentIdVar.reset(token)
        events = readRunEvents("run-gov-1")
        assert any(e["type"] == "device_action" for e in events)
        event = next(e for e in events if e["type"] == "device_action")
        assert event["payload"]["tool"] == "device_tap"
        assert event["payload"]["risk"] in ("low", "medium", "high")
