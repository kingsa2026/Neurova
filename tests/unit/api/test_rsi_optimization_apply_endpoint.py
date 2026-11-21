"""R1 人工批准应用端点：POST /v1/governance/rsi/optimizations/apply。

phase 1（手动档）语义是"生成优化建议，人工审批"——本端点就是那个"人工审批"：
把最近一轮 run_iteration 产出的参数优化提案经管理员批准后，走与自动档同一份
"应用→前后实测→回滚判定"实现落地。守卫：
- 权限：治理管理员门（非 admin 403）；
- RSI 未装配 503；无待批提案/重复应用/观察期 409；越界 optimization_id 422；
- 批准体缺 approved_by 422（pydantic）。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.auth_headers import overrideIdentity


def _write_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: int) -> None:
    path = tmp_path / "governance_settings.json"
    path.write_text(
        json.dumps({"rsi_phase": phase, "conversation_rules_enabled": False}),
        encoding="utf-8",
    )
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))


def _build_orchestrator(tmp_path, monkeypatch, phase: int = 1):
    from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation
    from neurova.cognitive_layers.memory_layer.tool_memory_integration import ToolMemoryIntegration
    from neurova.evolution.experience_feedback import ExperienceFeedback
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    _write_phase(tmp_path, monkeypatch, phase)
    return RSIOrchestrator(
        sleep_system=SleepConsolidation(),
        emotion_system=EmotionModule(),
        experience_system=ExperienceFeedback(),
        tool_memory_system=ToolMemoryIntegration(
            memory_layer=None, muscle_memory=None,
            confidence_threshold=0.8, temperature_threshold=30.0,
            muscle_memory_threshold=0.85,
        ),
        agent_id="r1-endpoint-test",
    )


def _client_with_orchestrator(orch):
    app = FastAPI()
    from neurova.api.endpoints.governance import router

    app.include_router(router, prefix="/v1/governance")
    overrideIdentity(app, {"user_id": "admin1", "role": "admin"})
    patcher = patch(
        "neurova.api.endpoints.governance._get_rsi_orchestrator",
        return_value=orch,
    )
    patcher.start()
    client = TestClient(app)
    client._patcher = patcher  # 让调用方在用例结束时停掉 patch
    return client


def _stop_client(client) -> None:
    client._patcher.stop()
    client.close()


class TestRsiOptimizationApplyEndpoint:
    def test_apply_approved_optimizations_end_to_end(self, tmp_path, monkeypatch):
        """run_iteration 产出提案 → POST 批准应用 → applied≥1 且前后均 measured。"""
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        round_result = orch.run_iteration()
        assert round_result["applied_count"] == 0, "前置：phase 1 不自动应用"

        client = _client_with_orchestrator(orch)
        try:
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply",
                json={"approved_by": "admin1"},
            )
        finally:
            _stop_client(client)

        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["applied_count"] >= 1, data
        assert data["approved_by"] == "admin1"
        assert data["eval"]["before"]["state"] == "measured", data["eval"]
        assert data["eval"]["after"]["state"] == "measured", data["eval"]
        assert data["gain_evidenced"] is True
        # 落地后的状态面要能看见"提案已消费"
        assert orch.pendingManualOptimizations() == []

    def test_apply_with_unknown_optimization_id_is_422(self, tmp_path, monkeypatch):
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        client = _client_with_orchestrator(orch)
        try:
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply",
                json={"approved_by": "admin1", "optimization_ids": ["opt-nope"]},
            )
        finally:
            _stop_client(client)

        assert resp.status_code == 422, resp.text
        assert orch.pendingManualOptimizations(), "越界请求不得消费待批提案"

    def test_apply_without_pending_round_is_409(self, tmp_path, monkeypatch):
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        client = _client_with_orchestrator(orch)
        try:
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply",
                json={"approved_by": "admin1"},
            )
        finally:
            _stop_client(client)

        assert resp.status_code == 409, resp.text

    def test_apply_twice_is_409(self, tmp_path, monkeypatch):
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        client = _client_with_orchestrator(orch)
        try:
            first = client.post(
                "/v1/governance/rsi/optimizations/apply", json={"approved_by": "admin1"}
            )
            second = client.post(
                "/v1/governance/rsi/optimizations/apply", json={"approved_by": "admin2"}
            )
        finally:
            _stop_client(client)

        assert first.status_code == 200, first.text
        assert second.status_code == 409, second.text

    def test_missing_approved_by_is_422(self, tmp_path, monkeypatch):
        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        client = _client_with_orchestrator(orch)
        try:
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply", json={}
            )
        finally:
            _stop_client(client)

        assert resp.status_code == 422, resp.text

    def test_non_admin_is_403(self, tmp_path, monkeypatch):
        from neurova.api.endpoints.governance import router

        orch = _build_orchestrator(tmp_path, monkeypatch, phase=1)
        orch.run_iteration()
        app = FastAPI()
        app.include_router(router, prefix="/v1/governance")
        overrideIdentity(app, {"user_id": "plain1", "role": "user"})
        patcher = patch(
            "neurova.api.endpoints.governance._get_rsi_orchestrator",
            return_value=orch,
        )
        patcher.start()
        try:
            client = TestClient(app)
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply", json={"approved_by": "plain1"}
            )
        finally:
            patcher.stop()

        assert resp.status_code == 403, resp.text

    def test_rsi_not_assembled_is_503(self, tmp_path, monkeypatch):
        from fastapi import FastAPI as _App
        from fastapi.testclient import TestClient as _Client

        from neurova.api.endpoints.governance import router

        _write_phase(tmp_path, monkeypatch, phase=1)
        app = _App()
        app.include_router(router, prefix="/v1/governance")
        overrideIdentity(app, {"user_id": "admin1", "role": "admin"})
        patcher = patch(
            "neurova.api.endpoints.governance._get_rsi_orchestrator",
            return_value=None,
        )
        patcher.start()
        try:
            client = _Client(app)
            resp = client.post(
                "/v1/governance/rsi/optimizations/apply", json={"approved_by": "admin1"}
            )
        finally:
            patcher.stop()

        assert resp.status_code == 503, resp.text
