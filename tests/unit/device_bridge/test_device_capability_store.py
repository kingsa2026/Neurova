# -*- coding: utf-8 -*-
"""B1 设备能力注册（mobile_devices v3 迁移 + recordHello + 投影）红灯判据。

计划卡 B1（docs/04-plans/2026-11-23-mobile-execution-end-plan.md §5 批一）：
- v3 迁移给 mobile_devices 加 platform / protocol_version / capabilities_json /
  app_state / last_hello_at 五列；
- recordHello 是能力快照的唯一写口（device:hello 帧处理层调用）；
- project()/listForUser() 投影出 platform/capabilities/app_state，供 REST
  读面与 device_bridge 路由选设备。
"""
import sqlite3

import pytest

from neurova.core.mobile_device_store import MobileDeviceStore


@pytest.fixture()
def store(tmp_path):
    s = MobileDeviceStore(dbPath=str(tmp_path / "mobile_devices.db"))
    yield s
    s.close()


def _register(store: MobileDeviceStore, pairingId: str = "pair-cap-1",
              userId: str = "u-cap", deviceId: str = "dev-1") -> None:
    store.register(pairingId=pairingId, userId=userId, deviceName="测试机",
                   deviceType="mobile", deviceId=deviceId, deviceSecret="sec-1")


class TestV3Migration:
    def test_v3_adds_capability_columns(self, store):
        cols = {row[1] for row in
                sqlite3.connect(store.dbPath).execute("PRAGMA table_info(mobile_devices)")}
        assert {"platform", "protocol_version", "capabilities_json",
                "app_state", "last_hello_at"} <= cols

    def test_fresh_store_has_empty_capability_projection(self, store):
        _register(store)
        row = store.get("pair-cap-1")
        assert row["platform"] == ""
        assert row["capabilities_json"] == "[]"
        assert row["app_state"] == ""
        assert row["last_hello_at"] is None


class TestRecordHello:
    def test_hello_roundtrip_persists_capabilities(self, store):
        _register(store)
        updated = store.recordHello(
            "pair-cap-1", platform="android", protocolVersion=1,
            capabilities=["open_url", "device_env", "clipboard_read"],
            appState="foreground")
        assert updated is not None
        assert updated["platform"] == "android"
        assert updated["protocol_version"] == 1
        assert updated["capabilities_json"] == '["open_url", "device_env", "clipboard_read"]'
        assert updated["app_state"] == "foreground"
        assert updated["last_hello_at"] and updated["last_hello_at"] > 0

    def test_second_hello_replaces_capabilities(self, store):
        _register(store)
        store.recordHello("pair-cap-1", platform="android", protocolVersion=1,
                          capabilities=["open_url"], appState="foreground")
        updated = store.recordHello("pair-cap-1", platform="android", protocolVersion=1,
                                    capabilities=["open_url", "app_list"],
                                    appState="background")
        assert updated["capabilities_json"] == '["open_url", "app_list"]'
        assert updated["app_state"] == "background"

    def test_hello_on_missing_device_returns_none(self, store):
        assert store.recordHello("pair-not-registered", platform="android",
                                 protocolVersion=1, capabilities=["open_url"],
                                 appState="foreground") is None

    def test_hello_persists_across_reopen(self, store, tmp_path):
        _register(store)
        store.recordHello("pair-cap-1", platform="harmony", protocolVersion=1,
                          capabilities=["clipboard_read"], appState="foreground")
        store.close()
        reopened = MobileDeviceStore(dbPath=str(tmp_path / "mobile_devices.db"))
        try:
            assert reopened.capabilitiesOf("pair-cap-1") == ["clipboard_read"]
        finally:
            reopened.close()

    def test_capabilities_of_missing_device_is_empty(self, store):
        assert store.capabilitiesOf("pair-none") == []


class TestProjection:
    def test_project_exposes_platform_capabilities_app_state(self, store):
        _register(store)
        store.recordHello("pair-cap-1", platform="android", protocolVersion=1,
                          capabilities=["open_url", "device_env"],
                          appState="foreground")
        listed = store.listForUser("u-cap", livePairingIds={"pair-cap-1"})
        assert len(listed) == 1
        projected = listed[0]
        assert projected["platform"] == "android"
        assert projected["capabilities"] == ["open_url", "device_env"]
        assert projected["app_state"] == "foreground"
        assert projected["protocol_version"] == 1

    def test_project_without_hello_keeps_empty_capabilities(self, store):
        _register(store)
        projected = store.listForUser("u-cap")[0]
        assert projected["platform"] == ""
        assert projected["capabilities"] == []
        assert projected["app_state"] == ""
