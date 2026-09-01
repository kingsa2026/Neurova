# -*- coding: utf-8 -*-
"""审批 API remember 透传测试（补课 3.2：前端 EXACT/SIMILAR 双档对齐）。

approval_manager.approve_request 的 remember 参数（v4 P1-c）此前无 API
透出——本测试锁定 governance 端点把 remember 传到管理器。
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from neurova.api.endpoints import governance as gov_mod

    am = gov_mod.ApprovalManager() if hasattr(gov_mod, "ApprovalManager") else None
    if am is None:
        # 管理器经 _get_governance/_get_approval_manager 等取——直接 patch
        am = MagicMock()

    # 构造一个真实 pending 请求对象（属性访问形状对齐 ApprovalRequest）
    request_obj = SimpleNamespace(
        id="req-1",
        status="pending",
        metadata={"tool_name": None, "params": {}},
        approved_by=None,
        note=None,
        remember=None,
    )

    captured = {}

    def fake_approve(request_id, approved_by="", note="", remember=None):
        captured["args"] = (request_id, approved_by, note, remember)
        request_obj.status = "approved"
        return True

    am.approve_request = fake_approve
    am.get_request = lambda rid: request_obj if rid == "req-1" else None

    monkeypatch.setattr(gov_mod, "_get_approvals", lambda: am)
    monkeypatch.setattr(gov_mod, "_pending_status", lambda: "pending")

    app = FastAPI()
    app.include_router(gov_mod.router, prefix="/v1/governance")
    return TestClient(app), captured


@pytest.mark.parametrize("remember", [None, "exact", "similar"])
def test_approve_passes_remember_through(client, remember):
    tc, captured = client
    body = {"approved_by": "user", "note": "ok"}
    if remember is not None:
        body["remember"] = remember
    resp = tc.post("/v1/governance/approvals/req-1/approve", json=body)
    assert resp.status_code == 200, resp.text
    assert captured["args"][3] == remember


def test_approve_rejects_invalid_remember(client):
    tc, _ = client
    resp = tc.post(
        "/v1/governance/approvals/req-1/approve",
        json={"approved_by": "user", "remember": "bogus"},
    )
    assert resp.status_code == 422  # pydantic 枚举校验拒绝
