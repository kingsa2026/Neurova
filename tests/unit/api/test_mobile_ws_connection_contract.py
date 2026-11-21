# -*- coding: utf-8 -*-
"""D-5 移动端排产·服务端先行：连接契约随心跳 pong 下发（G4 消费接线）。

G4 的 describeForClients 此前零消费点（断点）——三端只能手抄数值。本卡把
契约接到移动 WS 的心跳应答：``pong`` 帧携带 ``connection_runtime`` 契约
（describeForClients 现算），安卓/鸿蒙首次 ping/pong 即取到心跳/退避/重放
窗口取值，不再手抄。不发独立首帧——不破坏既有 WS 帧序契约。
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import mobile_pairing as mobile_ep

PAIRING_CODE = "CONTRACT-CODE-1"
OWNER = "u-contract"


@pytest.fixture()
def wsClient():
    mobile_ep._pairing_codes.clear()
    mobile_ep._ws_connections.clear()
    mobile_ep._pairing_codes[PAIRING_CODE] = {
        "status": "confirmed", "user_id": OWNER, "pairing_id": "pair-contract-1",
    }
    app = FastAPI()
    app.include_router(mobile_ep.router, prefix="/api/v1/mobile")
    return TestClient(app)


def _pingAndReadPong(ws) -> dict:
    ws.send_text(json.dumps({"type": "ping"}))
    while True:
        frame = json.loads(ws.receive_text())
        if frame.get("type") == "pong":
            return frame


class TestConnectionRuntimeContract:
    def test_pongCarriesConnectionRuntimeContract(self, wsClient):
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            pong = _pingAndReadPong(ws)
        contract = pong["connection_runtime"]
        assert contract["version"] >= 1
        assert contract["heartbeat"]["interval_s"] == 15.0
        assert contract["reconnect"]["backoff_base_s"] == 0.5
        assert contract["reconnect"]["backoff_cap_s"] == 30.0
        assert contract["replay"]["window_s"] == 86400.0
        assert contract["subscription"]["scopes"] == ["session", "thread", "global"]

    def test_contractFollowsEnvOverride(self, wsClient, monkeypatch):
        monkeypatch.setenv("NEUROVA_HEARTBEAT_INTERVAL_S", "7.5")
        with wsClient.websocket_connect(f"/api/v1/mobile/ws?code={PAIRING_CODE}") as ws:
            pong = _pingAndReadPong(ws)
        assert pong["connection_runtime"]["heartbeat"]["interval_s"] == 7.5
