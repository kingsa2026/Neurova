# -*- coding: utf-8 -*-
"""T2 治理批准端点（A5 元优化闭环的人工半）——409 无候选/已在账，200 带证据。"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints.governance import router


@contextmanager
def _client_with_orch(orch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/governance")
    from neurova.api.deps import get_current_user
    from tests.auth_headers import overrideIdentity

    overrideIdentity(app, {"user_id": "admin1", "role": "admin"})
    with patch(
        "neurova.api.endpoints.governance._get_rsi_orchestrator",
        return_value=orch,
    ):
        yield TestClient(app)


def _orch_with_result(result, error=None):
    orch = MagicMock()
    if error is not None:
        orch._applyApprovedImproverUpgrade.side_effect = error
    else:
        orch._applyApprovedImproverUpgrade.return_value = result
    return orch


def test_approve_returns_evidence_on_success():
    orch = _orch_with_result({
        "registered": True, "version": "I_drop20", "derived_from": "I_0",
        "probe_state": "measured", "probe_gamma": 0.05, "approved_by": "admin1",
    })
    with _client_with_orch(orch) as client:
        r = client.post("/api/v1/governance/rsi/improver-upgrade/approve",
                        json={"approved_by": "admin1"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["registered"] is True and data["probe_gamma"] == 0.05


def test_approve_maps_value_error_to_409():
    """红灯判据：无候选/已在账/无证据（ValueError 态）→ 409 点名理由。"""
    orch = _orch_with_result(None, error=ValueError("升级版本 I_drop20 已在账（无新变更）"))
    with _client_with_orch(orch) as client:
        r = client.post("/api/v1/governance/rsi/improver-upgrade/approve",
                        json={"approved_by": "admin1"})
    assert r.status_code == 409, r.text
    assert "已在账" in r.json()["detail"]


def test_approve_requires_named_approver():
    orch = _orch_with_result({"registered": True})
    with _client_with_orch(orch) as client:
        r = client.post("/api/v1/governance/rsi/improver-upgrade/approve",
                        json={"approved_by": ""})
    assert r.status_code == 422, r.text  # min_length=1 契约
