# -*- coding: utf-8 -*-
"""P2-23/P2-24 后端契约：scope 即时生效、任务窗口互斥/到期/前台约束。"""
import time

import pytest

from neurova.api import mobile_ws_ledger as wsledger
from neurova.api.endpoints import mobile_pairing as mobile_ep


class _LedgerWsProbe:
    def __init__(self):
        self.sent = []

    async def send_json(self, frame):
        self.sent.append(frame)


@pytest.fixture()
def ledger(tmp_path):
    store = wsledger.MobileWsLedger(db_path=tmp_path / "reliability.db")
    yield store
    store.close()


@pytest.mark.asyncio
async def test_device_task_endpoint_wires_start_renew_end_and_cancel(ledger, monkeypatch):
    monkeypatch.setattr(wsledger, "getMobileWsLedger", lambda: ledger)
    probe = _LedgerWsProbe()
    await mobile_ep._handle_device_task("pair-1", {
        "action": "start", "task_id": "task-1", "app_state": "foreground",
    }, probe)
    await mobile_ep._handle_device_task("pair-1", {
        "action": "renew", "task_id": "task-1", "app_state": "foreground",
    }, probe)
    await mobile_ep._handle_device_task("pair-1", {
        "action": "end", "task_id": "task-1", "app_state": "foreground",
    }, probe)
    await mobile_ep._handle_device_task("pair-1", {
        "action": "start", "task_id": "task-2", "app_state": "foreground",
    }, probe)
    await mobile_ep._handle_device_task("pair-1", {
        "action": "cancel", "task_id": "task-2", "app_state": "foreground",
    }, probe)
    assert [frame["status"] for frame in probe.sent] == [
        "active", "active", "ended", "active", "ended",
    ]
    assert ledger.taskWindow("pair-1") is None


@pytest.mark.asyncio
async def test_device_task_endpoint_rejects_background_and_foreign_renew(ledger, monkeypatch):
    monkeypatch.setattr(wsledger, "getMobileWsLedger", lambda: ledger)
    probe = _LedgerWsProbe()
    await mobile_ep._handle_device_task("pair-1", {
        "action": "start", "task_id": "task-1", "app_state": "background",
    }, probe)
    assert probe.sent[-1]["code"] == "foreground_required"
    await mobile_ep._handle_device_task("pair-1", {
        "action": "start", "task_id": "task-1", "app_state": "foreground",
    }, probe)
    await mobile_ep._handle_device_task("pair-1", {
        "action": "renew", "task_id": "task-2", "app_state": "foreground",
    }, probe)
    assert probe.sent[-1]["code"] == "task_window_mismatch"
    assert ledger.taskWindow("pair-1", "task-1") is not None


@pytest.mark.asyncio
async def test_chat_validation_error_carries_requested_session_id():
    probe = _LedgerWsProbe()
    await mobile_ep._handle_chat_send(probe, {
        "content": "   ", "session_id": "s-err",
    }, "u-1")
    assert probe.sent[-1]["type"] == "error"
    assert probe.sent[-1]["code"] == "empty_content"
    assert probe.sent[-1]["session_id"] == "s-err"


@pytest.mark.asyncio
async def test_device_hello_settles_pending_command_without_task_window(ledger, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(wsledger, "getMobileWsLedger", lambda: ledger)
    monkeypatch.setattr(mobile_ep, "getDeviceRegistry", lambda: SimpleNamespace(
        recordHello=lambda *args, **kwargs: {},
    ))
    ledger.beginCommand("cmd-expired", "pair-1", "device:execute", {
        "command_id": "cmd-expired", "task_id": "task-1",
    })
    probe = _LedgerWsProbe()

    await mobile_ep._handle_device_hello("pair-1", {
        "platform": "android", "protocol_version": 1,
        "capabilities": [], "app_state": "foreground",
    }, probe)

    settled = ledger.beginCommand("cmd-expired", "pair-1", "device:execute", {})
    assert settled[1] and settled[1].get("error", {}).get("code") == "task_window_expired", settled


def test_scope_change_is_immediate_without_resume(ledger):
    ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s1"})
    ledger.appendEvent("pair-1", 1, {"type": "chat:chunk", "session_id": "s2"})
    ledger.subscribe("pair-1", "session", "s1")
    assert [row["frame"]["session_id"] for row in ledger.replaySince("pair-1", 0)] == ["s1"]
    ledger.subscribe("pair-1", "session", "s2")
    assert [row["frame"]["session_id"] for row in ledger.replaySince("pair-1", 0)] == ["s2"]


def test_task_window_old_connection_cannot_end_new_generation(ledger):
    ledger.startTaskWindow("pair-1", "task-new", epoch=2)
    assert ledger.endTaskWindow("pair-1", "task-new", epoch=1) is False
    assert ledger.taskWindow("pair-1", "task-new", epoch=2) is not None
    assert ledger.endTaskWindow("pair-1", "task-new", epoch=2) is True


def test_task_window_start_renew_end_and_single_task(ledger):
    started = ledger.startTaskWindow("pair-1", "task-1", app_state="foreground")
    assert started["task_id"] == "task-1"
    assert started["expires_at"] > time.time()
    with pytest.raises(ValueError, match="task_window_busy"):
        ledger.startTaskWindow("pair-1", "task-2", app_state="foreground")
    renewed = ledger.renewTaskWindow("pair-1", "task-1")
    assert renewed["expires_at"] >= started["expires_at"]
    assert ledger.endTaskWindow("pair-1", "task-1") is True
    assert ledger.taskWindow("pair-1", "task-1") is None


def test_task_window_background_renew_disarms_current_window(ledger):
    ledger.startTaskWindow("pair-1", "task-1", app_state="foreground")
    with pytest.raises(ValueError, match="foreground_required"):
        ledger.renewTaskWindow("pair-1", "task-1", app_state="background")
    assert ledger.taskWindow("pair-1", "task-1") is None


def test_task_window_rejects_background_foreign_renew_and_expiry(ledger):
    with pytest.raises(ValueError, match="foreground_required"):
        ledger.startTaskWindow("pair-1", "task-1", app_state="background")
    ledger.startTaskWindow("pair-1", "task-1", app_state="foreground")
    with pytest.raises(ValueError, match="task_window_mismatch"):
        ledger.renewTaskWindow("pair-1", "task-2")
    window = ledger.taskWindow("pair-1", "task-1")
    ledger._task_windows["pair-1"] = {**window, "expires_at": time.time() - 1}
    assert ledger.taskWindow("pair-1", "task-1") is None


def test_registry_unregister_requires_same_live_connection():
    from neurova.device_bridge.registry import DeviceConnectionRegistry

    registry = DeviceConnectionRegistry()
    registry.register("pair-1", "user-1", object())
    live = object()
    registry.register("pair-1", "user-1", live)
    registry.unregister("pair-1", expected=object())
    assert registry.get("pair-1").ledger_ws is live
    registry.unregister("pair-1", expected=live)
    assert registry.get("pair-1") is None
