"""推理链持久化门控回归测试

事故（2026-09-05）：finish_trace 每轮对话无条件将整条推理链（含"晚上好→晚上好呀"
这类寒暄）作为 EPISODIC/reasoning_trace 记忆持久化，且：
- 无任何消费方（get_recent_traces 全仓零调用）
- unified_retriever.retrieve 不带 category 过滤 → 寒暄链会被当相关记忆
  捞回上下文，形成回声污染

契约（本测试锁死，遵循"新扩展点默认关"项目约定）：
- 默认（未设 env）：finish_trace 只清理 _active_traces，不调用 engine.store
- NEUROVA_TRACE_PERSIST=1 时：恢复持久化行为
- 无论开关，trace 都从活跃表移除（不泄漏）
"""

import json
import re
from pathlib import Path

import pytest
from unittest.mock import MagicMock

#: 扫描根单点，必须写在模块级：绑在函数里的名字，面自证棘轮的取数口认不出，整档会静默掉出它的面。
NEUROVA = Path(__file__).resolve().parents[3] / "neurova"


@pytest.fixture(autouse=True)
def _emptyGovernanceSettings(tmp_path, monkeypatch):
    """整个文件把治理设置面钉到每用例一个空文件。

    门改走 `resolve_flag` 后，取值次序是「env 显式 > 治理设置 > DEFAULTS」；而治理设置
    落在数据根，同一轮跑测里别的用例写进去的 `trace_persistence_enabled: true` 会让
    `test_default_no_persist` 变成"看谁先跑"——那正是本文件要防的幻影形态之一。
    """
    settingsFile = tmp_path / "governance_settings.json"
    monkeypatch.setattr(
        "neurova.security.governance_settings.settings_path", lambda: settingsFile)
    monkeypatch.delenv("NEUROVA_TRACE_PERSIST", raising=False)
    monkeypatch.delenv("NEUROVA_GOVERNANCE_SETTINGS", raising=False)
    return settingsFile


@pytest.fixture
def engine():
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
    return MagicMock(spec=CognitiveStorageEngine)


@pytest.fixture
def manager(engine):
    from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager
    return ReasoningTraceManager(engine=engine)


def _run_trace(manager):
    tid = manager.start_trace("晚上好")
    manager.add_step(tid, "retrieve", "q", "找到 0 条记忆")
    manager.finish_trace(tid, "晚上好呀！😊", total_tokens=42)
    return tid


class TestTracePersistGate:
    def test_default_no_persist(self, manager, engine, monkeypatch):
        """默认不持久化：engine.store 不被调用"""
        monkeypatch.delenv("NEUROVA_TRACE_PERSIST", raising=False)
        tid = _run_trace(manager)
        engine.store.assert_not_called()
        assert tid not in manager._active_traces

    def test_env_on_persists(self, manager, engine, monkeypatch):
        """NEUROVA_TRACE_PERSIST=1 时恢复持久化"""
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        tid = _run_trace(manager)
        engine.store.assert_called_once()
        node = engine.store.call_args[0][0]
        assert node.category == "reasoning_trace"
        assert node.trace_id == tid

    def test_invalid_env_treated_as_off(self, manager, engine, monkeypatch):
        """env 值非 "1" 一律视为关（与 NEUROVA_METACOG_GATE 同口径）"""
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "true")
        _run_trace(manager)
        engine.store.assert_not_called()

    def test_trace_always_removed(self, manager, engine, monkeypatch):
        """开关两种状态下 trace 都从活跃表移除，不泄漏"""
        monkeypatch.delenv("NEUROVA_TRACE_PERSIST", raising=False)
        t1 = _run_trace(manager)
        assert t1 not in manager._active_traces
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "1")
        t2 = _run_trace(manager)
        assert t2 not in manager._active_traces


class TestGateTakesPowerFromGovernance:
    """§6-206：这个门此前**只有 env 能拨**——全仓无生产赋值点，等于"定义了没人能开"。

    本批把它接进治理面（与工单 015 的 `metacog_gate_enabled` / `crystallization_llm_gate_enabled`
    同一条优先级口径），**默认值保持关**：收口只扩"谁能拨"，不改现网行为。
    回声污染那道防线（零消费方 + 检索不带 category 过滤）一字未动。
    """

    def _write(self, settingsFile, payload):
        settingsFile.write_text(json.dumps(payload), encoding="utf-8")

    def test_governanceOnPersistsWithoutEnv(self, manager, engine, _emptyGovernanceSettings):
        self._write(_emptyGovernanceSettings, {"trace_persistence_enabled": True})
        tid = _run_trace(manager)
        engine.store.assert_called_once()
        assert engine.store.call_args[0][0].category == "reasoning_trace"
        assert tid not in manager._active_traces

    def test_envZeroForcesOffEvenWhenGovernanceOn(self, manager, engine, monkeypatch,
                                                  _emptyGovernanceSettings):
        """方向要锁全：只断"治理能开"不断"env 0 能压住"，等于把逃生门漏掉。"""
        self._write(_emptyGovernanceSettings, {"trace_persistence_enabled": True})
        monkeypatch.setenv("NEUROVA_TRACE_PERSIST", "0")
        _run_trace(manager)
        engine.store.assert_not_called()

    def test_defaultStaysOffAfterWiring(self, manager, engine, _emptyGovernanceSettings):
        """反向锁：收口不得翻转现网默认——两侧都不设时必须仍不写盘。"""
        assert _emptyGovernanceSettings.exists() is False
        _run_trace(manager)
        engine.store.assert_not_called()

    def test_gateIsReadAtDecisionTimeNotAtConstruction(self, engine, _emptyGovernanceSettings):
        """同一个 manager 实例存续期间改治理设置，下一轮必须跟着变。

        构造期快照＝"治理页能改、运行时不认"的幻影旋钮（015 收口前的老毛病）。
        """
        from neurova.cognitive_layers.memory_layer.reasoning_trace_manager import ReasoningTraceManager

        mgr = ReasoningTraceManager(engine=engine)
        _run_trace(mgr)
        engine.store.assert_not_called()
        self._write(_emptyGovernanceSettings, {"trace_persistence_enabled": True})
        _run_trace(mgr)
        engine.store.assert_called_once()

    def test_noBareEnvReadIsLeftInConsumers(self):
        """消费方不得再自行读环境：留一处裸读就是第二个事实源。"""
        readForm = re.compile(
            r"""os\s*\.\s*(?:environ\s*\[|environ\.get\(|getenv\()\s*["']"""
            r"""NEUROVA_TRACE_PERSIST["']""")
        offenders = []
        sources = sorted(NEUROVA.rglob("*.py"))
        assert len(sources) > 500, (
            f"扫描面现读 {len(sources)} 档（根＝{NEUROVA}）——量级对不上生产源码总数＝根被改窄")
        for py in sources:
            if "__pycache__" in str(py):
                continue
            if readForm.search(py.read_text(encoding="utf-8", errors="replace")):
                offenders.append(py.relative_to(NEUROVA).as_posix())
        assert offenders == [], "裸 env 读点复现，治理面的值会被无声旁路：%s" % offenders

    def test_theKeyIsDeclaredInDefaults(self):
        """不在 DEFAULTS 声明的键 `resolve_flag` 直接抛 KeyError——声明面必须先登记。"""
        from neurova.security.governance_settings import DEFAULTS

        assert "trace_persistence_enabled" in DEFAULTS
        assert DEFAULTS["trace_persistence_enabled"] is False
