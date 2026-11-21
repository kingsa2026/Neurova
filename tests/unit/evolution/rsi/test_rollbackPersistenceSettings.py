"""R5（拍板 2026-11-21，详案 §6-R5）：回滚持久化参数化 — 三级解析契约。

此前 `resolve_rollback_state_path()` 只认 env `NEUROVA_EVOLUTION_ROLLBACK`：
未配置返回 None = 零 IO。生产默认不配置 ⇒ 晋升判据"距上次回滚天数"的
数据源（回滚历史 + 装配时刻）默认缺席（详案 §1.4 实测 rsi_rollback.json
history 0 条、1018 次迭代 0 应用）。

本卡把门控升级为三级解析（默认值翻转为**开**——审计数据源不应默认缺席）：

    env `NEUROVA_EVOLUTION_ROLLBACK` 显式路径（兼容既有部署）
    > 设置键 `rsi_rollback_persistence_enabled`（EvolutionSettings.rsi_* 族）
      开 → data_root 派生默认路径 `data/evolution/rsi_rollback.json`
    > 关 → None（显式关闭仍零 IO）

落盘路径经 `core/data_root` 派生：本文件各档显式注入临时 `NEUROVA_DATA_DIR`，
不写仓库根（`test_repo_root_pollution_guard` 判据不变）。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from neurova.evolution.rsi.rollback_manager import (
    RSIRollbackManager,
    resolve_rollback_state_path,
)

ROLLBACK_ENV = "NEUROVA_EVOLUTION_ROLLBACK"
SETTINGS_ENV = "NEUROVA_EVOLUTION_SETTINGS"
DATA_ROOT_ENV = "NEUROVA_DATA_DIR"

#: 关闭开关的最小设置文件内容
DISABLED_SETTINGS = {"rsi_rollback_persistence_enabled": False}


def _write_settings(tmp_path: Path, patch: dict) -> None:
    (tmp_path / "evolution_settings.json").write_text(
        json.dumps(patch), encoding="utf-8")


@pytest.fixture
def noEnvRollback(monkeypatch):
    """摘掉 conftest 注入的 env，露出"设置键决定默认路径"的那一级。"""
    monkeypatch.delenv(ROLLBACK_ENV, raising=False)


@pytest.fixture
def isolatedSettings(tmp_path, monkeypatch):
    """进化设置文件指到本用例临时目录（与 test_evolution_settings_rsi_knobs 同形）。"""
    monkeypatch.setenv(SETTINGS_ENV, str(tmp_path / "evolution_settings.json"))


@pytest.fixture
def isolatedDataRoot(tmp_path, monkeypatch) -> Path:
    """数据根指到本用例临时目录：派生默认路径可断言、零仓库污染。"""
    root = tmp_path / "dataRoot"
    monkeypatch.setenv(DATA_ROOT_ENV, str(root))
    return root


def _derived_path(data_root: Path) -> Path:
    return data_root / "evolution" / "rsi_rollback.json"


class TestResolveRollbackStatePath:
    """resolve_rollback_state_path 的三级解析契约。"""

    def test_defaultEnabledDerivesDataRootPath(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot
    ):
        """默认（设置键开、无 env）→ 数据根派生路径，不再是 None。"""
        assert resolve_rollback_state_path() == _derived_path(isolatedDataRoot)

    def test_explicitEnvPathStillWins(self, monkeypatch, isolatedSettings, isolatedDataRoot):
        """env 显式路径优先于设置键（既有部署零漂移）。"""
        explicit = isolatedDataRoot / "elsewhere" / "rollback.json"
        monkeypatch.setenv(ROLLBACK_ENV, str(explicit))
        assert resolve_rollback_state_path() == explicit

    def test_disabledSwitchReturnsNone(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot, tmp_path
    ):
        """显式关闭 → None（零 IO 仍是受支持形态，不是被删掉的能力）。"""
        _write_settings(tmp_path, DISABLED_SETTINGS)
        assert resolve_rollback_state_path() is None

    def test_envPathWinsEvenWhenSwitchDisabled(
        self, monkeypatch, isolatedSettings, isolatedDataRoot, tmp_path
    ):
        """env 与开关同设时 env 赢——显式部署配置不被设置面默认值覆盖。"""
        _write_settings(tmp_path, DISABLED_SETTINGS)
        explicit = tmp_path / "explicit.json"
        monkeypatch.setenv(ROLLBACK_ENV, str(explicit))
        assert resolve_rollback_state_path() == explicit

    def test_missingSettingsFileFallsBackToEnabledDefault(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot, tmp_path
    ):
        """设置文件缺失 → 默认开 → 派生路径（默认翻转的正面断言）。"""
        assert not (tmp_path / "evolution_settings.json").exists(), (
            "前置：本档必须不落任何设置文件，考的才是'缺文件回默认'")
        assert resolve_rollback_state_path() == _derived_path(isolatedDataRoot)


class TestSettingsKeyContract:
    """`rsi_rollback_persistence_enabled` 作为 EvolutionSettings 键的读写契约。"""

    def test_defaultIsTrue(self, isolatedSettings):
        from neurova.evolution.evolution_settings import EvolutionSettings, load_settings

        assert EvolutionSettings().rsi_rollback_persistence_enabled is True
        assert load_settings().rsi_rollback_persistence_enabled is True

    def test_updatePersistsAndLoads(self, isolatedSettings, tmp_path):
        from neurova.evolution.evolution_settings import load_settings, update_settings

        update_settings(rsi_rollback_persistence_enabled=False)
        assert load_settings().rsi_rollback_persistence_enabled is False
        stored = json.loads(
            (tmp_path / "evolution_settings.json").read_text(encoding="utf-8"))
        assert stored["rsi_rollback_persistence_enabled"] is False

    def test_oldConfigWithoutNewKeyStillLoads(self, isolatedSettings, tmp_path):
        """存量配置文件（无新键）照常加载，新键回默认开——升级零漂移。"""
        _write_settings(tmp_path, {"text_evolution": True, "lifecycle_sweep": True})
        from neurova.evolution.evolution_settings import load_settings

        loaded = load_settings()
        assert loaded.text_evolution is True
        assert loaded.rsi_rollback_persistence_enabled is True

    def test_evolutionSettingsApiExposesTheKey(self, tmp_path, monkeypatch):
        """管理端 `/v1/evolution/settings` 必须能读写该键——否则"设置面暴露"
        只到后端配置单源为止，前端面板无从落笔。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import text_evolution_api as api

        monkeypatch.setenv(SETTINGS_ENV, str(tmp_path / "evolution_settings.json"))
        admin = {"user_id": "u1", "username": "admin", "role": "admin", "neuser_id": "u1"}
        app = FastAPI()
        app.include_router(api.router, prefix="/api/v1/evolution")
        with TestClient(app, raise_server_exceptions=False) as client:
            client.app.dependency_overrides[get_current_user] = lambda: admin
            client.app.dependency_overrides[api._admin_dep] = lambda: admin

            resp = client.put(
                "/api/v1/evolution/settings",
                json={"rsi_rollback_persistence_enabled": False},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["data"]["rsi_rollback_persistence_enabled"] is False
            readback = client.get("/api/v1/evolution/settings")
            assert readback.json()["data"]["rsi_rollback_persistence_enabled"] is False


class TestOrchestratorAttach:
    """编排器装配侧：开启即自挂载派生路径并落盘；关闭即零 IO。"""

    @staticmethod
    def _build_orchestrator() -> "object":
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        class _SignalOnlySystem:
            def get_feedback(self):
                return {"success_rate": 0.5}

        stubs = {name: _SignalOnlySystem() for name in
                 ("sleep", "emotion", "experience", "tool_memory")}
        return RSIOrchestrator(**{f"{name}_system": s for name, s in stubs.items()})

    def test_orchestratorAttachesDerivedPathWhenEnabled(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot
    ):
        """开启（默认）时编排器自挂载派生路径，且首次构造即钉装配时刻。"""
        orch = self._build_orchestrator()
        manager = orch.rollback_manager
        assert manager._persist_path == _derived_path(isolatedDataRoot)
        assert _derived_path(isolatedDataRoot).exists(), (
            "首次构造未落盘——装配时刻会在重启后丢失")

    def test_enabledManagerPersistsRollbackAndReadsBack(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot
    ):
        """开启时 create_snapshot/execute_rollback 落盘、可读回。"""
        path = _derived_path(isolatedDataRoot)
        first = RSIRollbackManager()
        first.attach_persistence(path)
        snapshot_id = first.create_snapshot(
            {"muscle_memory_threshold": {"system": "tool_memory", "value": 0.85}})
        assert first.execute_rollback(snapshot_id) is True
        assert path.exists(), "回滚留痕未落盘"

        restarted = RSIRollbackManager()
        restarted.attach_persistence(path)
        assert restarted.load(path) is True
        history = restarted.get_rollback_history()
        assert len(history) == 1, "回滚历史落盘后读不回"
        assert restarted.days_since_last_rollback() == pytest.approx(0, abs=0.2)

    def test_disabledManagerStaysZeroIo(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot, tmp_path
    ):
        """关闭时编排器不挂载持久化，回滚动作零 IO。"""
        _write_settings(tmp_path, DISABLED_SETTINGS)
        orch = self._build_orchestrator()
        manager = orch.rollback_manager
        assert manager._persist_path is None, "关闭开关后编排器仍挂载了持久化"
        assert manager.save() is False

        manager.execute_rollback(manager.create_snapshot({"x": {"system": "sleep", "value": 0.7}}))
        assert not _derived_path(isolatedDataRoot).exists(), (
            "关闭开关后回滚留痕仍写了盘")
        assert manager.get_rollback_history(), "零 IO 指不落盘，内存留痕语义不变"

    def test_persistenceSurvivesRestartAcrossDays(
        self, noEnvRollback, isolatedSettings, isolatedDataRoot
    ):
        """端到端：落盘 → 改写装配时刻 → 按重启语义读回，判据天数可算。"""
        path = _derived_path(isolatedDataRoot)
        first = self._build_orchestrator()
        assert first.rollback_manager._persist_path == path

        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["installed_at"] = (
            datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        path.write_text(json.dumps(stored), encoding="utf-8")

        restarted = self._build_orchestrator()
        days = restarted.rollback_manager.days_since_last_rollback()
        assert days == pytest.approx(8, abs=0.3), (
            f"重启后装配时刻应从盘上恢复（8 天前），实际 {days}")
