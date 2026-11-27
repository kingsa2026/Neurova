"""DEAD-14/DEAD-15：插件停机单源与零消费 API 退役判据。"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from neurova.plugins.plugin_manager import PluginManager
from neurova.skill_system.core import SkillRegistry
from neurova.skills import models
from neurova.skills.task_decomposer import TaskDecomposer


_PLUGIN_SOURCE = '''
from pathlib import Path
from neurova.plugins.base_plugin import BasePlugin


class LifecycleProbe(BasePlugin):
    async def on_initialize(self):
        self._mark("initialize")

    async def on_start(self):
        self._mark("start")

    async def on_stop(self):
        self._mark("stop")

    async def on_destroy(self):
        self._mark("destroy")

    @staticmethod
    def _mark(value):
        log = Path(__file__).with_name("lifecycle.log")
        with log.open("a", encoding="utf-8") as stream:
            stream.write(value + "\\n")
'''


def _install_started_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[PluginManager, Path]:
    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "probe"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps({
            "name": "probe",
            "version": "1.0.0",
            "entry_point": "main.py",
            "permissions": {},
            "framework_surfaces": [],
            "api_endpoints": [],
        }),
        encoding="utf-8",
    )
    (plugin_dir / "main.py").write_text(_PLUGIN_SOURCE, encoding="utf-8")

    manager = PluginManager(plugin_dir=str(plugin_root))
    manager.install_plugin(plugin_dir)
    assert manager.enable_plugin("probe") is True
    manager.load_plugin("probe")
    import asyncio

    asyncio.run(manager.startPlugin("probe"))
    return manager, plugin_dir / "lifecycle.log"


def _events(log_path: Path) -> list[str]:
    return log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []


def test_sync_disable_stops_and_destroys_loaded_plugin(tmp_path, monkeypatch):
    manager, log_path = _install_started_plugin(tmp_path, monkeypatch)

    assert manager.disable_plugin("probe") is True

    assert _events(log_path)[-2:] == ["stop", "destroy"]
    assert manager.get_plugin("probe").enabled is False


def test_sync_unload_stops_and_destroys_loaded_plugin(tmp_path, monkeypatch):
    manager, log_path = _install_started_plugin(tmp_path, monkeypatch)

    assert manager.unload_plugin("probe") is True

    assert _events(log_path)[-2:] == ["stop", "destroy"]
    assert manager.moduleInfo("probe") is None
    assert manager.get_plugin("probe").loaded is False


def test_uninstall_uses_the_same_real_stop_path_once(tmp_path, monkeypatch):
    manager, log_path = _install_started_plugin(tmp_path, monkeypatch)

    assert manager.uninstall_plugin("probe") is True

    assert _events(log_path).count("stop") == 1
    assert _events(log_path).count("destroy") == 1
    assert manager.get_plugin("probe") is None


def test_isolated_skill_execution_surface_is_retired():
    assert not hasattr(SkillRegistry, "execute_skill_isolated")
    assert not hasattr(SkillRegistry, "runtime_manager")
    assert "runtime_manager" not in inspect.signature(SkillRegistry).parameters


@pytest.mark.parametrize(
    "methodName",
    [
        "plan_skill_chain",
        "optimize_chain",
        "estimate_chain_cost",
        "_map_subtask_to_skill",
        "_topological_sort",
        "_prioritize_steps",
        "_estimate_chain_complexity",
        "_check_parallelizable",
    ],
)
def test_task_chain_surface_is_retired(methodName):
    assert not hasattr(TaskDecomposer, methodName)


@pytest.mark.parametrize(
    "modelName",
    [
        "ChainStatus",
        "StepStatus",
        "SkillChainStep",
        "SkillChain",
        "StepExecutionResult",
        "ChainExecutionResult",
        "ChainStatusInfo",
    ],
)
def test_task_chain_models_are_retired(modelName):
    assert not hasattr(models, modelName)


def test_agent_skill_catalog_provider_surface_is_retired():
    import neurova.agent_core as agent_core

    assert not hasattr(agent_core, "AgentSkillCatalogProvider")
    assert not hasattr(agent_core, "AgentSkillCatalogSource")
