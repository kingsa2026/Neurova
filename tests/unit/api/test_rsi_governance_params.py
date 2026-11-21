"""R7（拍板 2026-11-21，详案 §6-R7 / §8-4/7/9）：RSI 面板运行参数键。

把演化运行参数做成治理设置键并出街到治理面：
- `rsi_canary_window_seconds`（金丝雀观测窗，保守默认 300 秒，§8-4 拍板）；
- `rsi_canary_rollback_thresholds`（回滚阈值族，默认
  {"max_error_rate": 0.2, "min_success_rate_drop": 0.1}，P1-4 金丝雀消费）；
- `rsi_phase_min_applied`（R6 已入 DEFAULTS，本卡补 PUT 写入口——
  治理页读得到改不到就是幻影旋钮）。

判据：GET 带默认值出街、PUT 落盘可读回、越界 422 点名、解析读法
（env > 设置 > 默认，夹紧合法域）单源在 governance_settings。
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


CANARY_DEFAULTS = {"max_error_rate": 0.2, "min_success_rate_drop": 0.1}


class _Client:
    """治理设置端点的最小挂载（与 test_governance_settings 同形）。"""

    def __init__(self, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import neurova.api.endpoints.governance as gov
        from neurova.api.endpoints.governance import router

        self.gov = gov
        self.settings_file = Path(tmp_path) / "governance_settings.json"
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        app.dependency_overrides[gov._governance_admin_dep] = lambda: {"id": 1}
        self.client = TestClient(app)

    def withSettingsFile(self):
        return patch.object(
            self.gov, "_governance_settings_path", return_value=self.settings_file)


def test_get_exposes_rsi_runtime_params_with_defaults(tmp_path):
    box = _Client(tmp_path)
    with box.withSettingsFile():
        resp = box.client.get("/api/v1/governance/settings")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["rsi_canary_window_seconds"] == 300
    assert data["rsi_canary_rollback_thresholds"] == CANARY_DEFAULTS
    # R6 已入 DEFAULTS 的键，本卡只钉它随治理面出街（面板读数）。
    assert data["rsi_phase_min_applied"] == {"2": 3, "3": 10}
    assert "metacog_gate_enabled" in data
    assert "rsi_phase_overrides" in data


def test_put_writes_canary_and_min_applied_keys_persistently(tmp_path):
    box = _Client(tmp_path)
    payload = {
        "rsi_canary_window_seconds": 120,
        "rsi_canary_rollback_thresholds": {"max_error_rate": 0.5,
                                           "min_success_rate_drop": 0.3},
        "rsi_phase_min_applied": {"2": 5, "3": 20},
        "metacog_gate_enabled": True,
    }
    with box.withSettingsFile():
        resp = box.client.put("/api/v1/governance/settings", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["rsi_canary_window_seconds"] == 120
        assert data["rsi_canary_rollback_thresholds"] == {
            "max_error_rate": 0.5, "min_success_rate_drop": 0.3}
        assert data["rsi_phase_min_applied"] == {"2": 5, "3": 20}
        assert data["metacog_gate_enabled"] is True
        # 新进程语义：从磁盘重读
        readback = box.client.get("/api/v1/governance/settings").json()["data"]
    assert readback["rsi_canary_window_seconds"] == 120
    assert readback["rsi_phase_min_applied"] == {"2": 5, "3": 20}
    stored = json.loads(box.settings_file.read_text(encoding="utf-8"))
    assert stored["rsi_canary_rollback_thresholds"]["max_error_rate"] == 0.5


def test_put_rejects_out_of_range_canary_window(tmp_path):
    box = _Client(tmp_path)
    with box.withSettingsFile():
        for bad in (0, 0.5, 86401):
            resp = box.client.put(
                "/api/v1/governance/settings",
                json={"rsi_canary_window_seconds": bad})
            assert resp.status_code == 422, f"window={bad} 应 422：{resp.text}"


def test_put_rejects_bad_canary_thresholds(tmp_path):
    box = _Client(tmp_path)
    with box.withSettingsFile():
        for bad in (
            {"max_error_rate": 1.5},                     # 越上界
            {"min_success_rate_drop": -0.1},             # 越下界
            {"max_error_rate": "high"},                  # 非数值
            {"unknown_threshold": 0.5},                  # 键集外的键（第二套键名即漂移）
        ):
            resp = box.client.put(
                "/api/v1/governance/settings",
                json={"rsi_canary_rollback_thresholds": bad})
            assert resp.status_code == 422, f"thresholds={bad} 应 422：{resp.text}"


def test_put_rejects_bad_phase_min_applied(tmp_path):
    box = _Client(tmp_path)
    with box.withSettingsFile():
        for bad in (
            {"9": 3},        # 相位越界
            {"2": -1},       # 负次数
            {"2": 1.5},      # 非整数
            {"": 3},         # 空相位键
        ):
            resp = box.client.put(
                "/api/v1/governance/settings",
                json={"rsi_phase_min_applied": bad})
            assert resp.status_code == 422, f"min_applied={bad} 应 422：{resp.text}"


class TestCanaryResolvers:
    """决策时刻读法：env > 治理设置 > 默认，夹紧到合法域（单源）。"""

    def test_window_default_and_env_override(self, monkeypatch, tmp_path):
        from neurova.security.governance_settings import resolveRsiCanaryWindowSeconds

        monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS",
                           str(tmp_path / "governance_settings.json"))
        monkeypatch.delenv("NEUROVA_RSI_CANARY_WINDOW", raising=False)
        assert resolveRsiCanaryWindowSeconds() == 300.0

        monkeypatch.setenv("NEUROVA_RSI_CANARY_WINDOW", "45")
        assert resolveRsiCanaryWindowSeconds() == 45.0
        # env 越界夹紧，不旁路合法域
        monkeypatch.setenv("NEUROVA_RSI_CANARY_WINDOW", "999999")
        assert resolveRsiCanaryWindowSeconds() == 86400.0

    def test_window_reads_settings_file(self, monkeypatch, tmp_path):
        from neurova.security.governance_settings import resolveRsiCanaryWindowSeconds

        settings_file = tmp_path / "governance_settings.json"
        settings_file.write_text(
            json.dumps({"rsi_canary_window_seconds": 600}), encoding="utf-8")
        monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(settings_file))
        monkeypatch.delenv("NEUROVA_RSI_CANARY_WINDOW", raising=False)
        assert resolveRsiCanaryWindowSeconds() == 600.0

    def test_thresholds_default_partial_and_bad_values(self, monkeypatch, tmp_path):
        from neurova.security.governance_settings import (
            resolveRsiCanaryRollbackThresholds,
        )

        settings_file = tmp_path / "governance_settings.json"
        monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(settings_file))

        # 缺文件 → 内置默认
        assert resolveRsiCanaryRollbackThresholds() == CANARY_DEFAULTS

        # 部分覆盖：未覆盖的键回默认对应键，不整组作废
        settings_file.write_text(
            json.dumps({"rsi_canary_rollback_thresholds": {"max_error_rate": 0.4}}),
            encoding="utf-8")
        assert resolveRsiCanaryRollbackThresholds() == {
            "max_error_rate": 0.4, "min_success_rate_drop": 0.1}

        # 坏值/越界逐键夹紧或回默认，绝不把垃圾值折算成可放行的读数
        settings_file.write_text(json.dumps({"rsi_canary_rollback_thresholds": {
            "max_error_rate": 2.5, "min_success_rate_drop": "oops",
        }}), encoding="utf-8")
        assert resolveRsiCanaryRollbackThresholds() == {
            "max_error_rate": 1.0, "min_success_rate_drop": 0.1}

    def test_thresholds_accept_explicit_settings_dict(self):
        """判据面可直接喂设置 dict（与 resolveRsiPhaseFor 同形的可测性）。"""
        from neurova.security.governance_settings import (
            resolveRsiCanaryRollbackThresholds,
        )

        resolved = resolveRsiCanaryRollbackThresholds(
            {"rsi_canary_rollback_thresholds": {"max_error_rate": 0.9}})
        assert resolved == {"max_error_rate": 0.9, "min_success_rate_drop": 0.1}
