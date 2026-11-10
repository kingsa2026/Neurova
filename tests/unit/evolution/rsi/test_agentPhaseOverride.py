# -*- coding: utf-8 -*-
"""G2 agent 级 phase 覆写（survey §10.2，拍板：覆写路线）。

口径升级：`_persist_rsi_phase` 旧注记明文"多 agent 共享一个 phase、隔离属明确
不做"——本批把最小灰度维度（agent 级覆写）接进来：
- 解析单源 `resolveRsiPhaseFor`：overrides 命中即用覆写值，否则全局 rsi_phase；
- 两 agent 异相位时判据按各自相位读（本批红灯判据）；
- 写回分域：有覆写条目的 agent 晋升写覆写条目（不污染全局），无覆写的
  agent 沿旧语义写全局。
"""

import json

import pytest

from neurova.security.governance_settings import (
    load_governance_settings,
    resolveRsiPhaseFor,
)


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "governance_settings.json"
    path.write_text(json.dumps({
        "rsi_phase": 1,
        "rsi_phase_overrides": {"agent-a": 3},
    }), encoding="utf-8")
    monkeypatch.setenv("NEUROVA_GOVERNANCE_SETTINGS", str(path))
    return path


def test_override_hit_wins_global_falls_through(settings_file):
    """解析单源：命中覆写条目即用覆写值；未命中的 agent 读全局。"""
    assert resolveRsiPhaseFor("agent-a") == 3, "覆写条目被忽略——异相位灰度失效"
    assert resolveRsiPhaseFor("agent-b") == 1, "未命中 agent 应读全局相位"
    assert resolveRsiPhaseFor("") == 1, "空 agent_id 按全局读（探针/装配路径）"


def test_invalid_override_entry_falls_back_to_global(settings_file, tmp_path):
    """非法覆写条目（越界/非整数）不炸装配：该 agent 回落全局相位。"""
    path = settings_file
    path.write_text(json.dumps({
        "rsi_phase": 2,
        "rsi_phase_overrides": {"agent-a": 9, "agent-b": "x"},
    }), encoding="utf-8")
    assert resolveRsiPhaseFor("agent-a") == 2, "越界覆写值必须回落全局"
    assert resolveRsiPhaseFor("agent-b") == 2, "非整数覆写值必须回落全局"


def test_two_agents_read_their_own_phases(settings_file):
    """红灯判据本体：两 agent 异相位时，判据按各自相位读。

    同一进程装配两个编排器（a=覆写 3，b=全局 1），部署控制器的阶段读数
    必须逐 agent 分域——灰度口径从"全量同相位"升级为"按 agent 覆写"。
    """
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from unittest.mock import MagicMock

    def _orch(agent_id):
        return RSIOrchestrator(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=MagicMock(),
            agent_id=agent_id,
        )

    orch_a = _orch("agent-a")
    orch_b = _orch("agent-b")

    assert orch_a.deployment_controller.get_current_phase() == 3, (
        "覆写条目的 agent 仍读全局相位——异相位灰度失效")
    assert orch_b.deployment_controller.get_current_phase() == 1, (
        "无覆写 agent 的相位被别人家的覆写污染")


def test_persist_writes_override_entry_not_global(settings_file):
    """写回分域：有覆写条目的 agent 晋升写覆写条目，全局相位不动。

    旧语义"按后写者胜共享全局"在覆写域内必须失效——否则 a 晋升会把 b 拖着走。
    """
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from unittest.mock import MagicMock

    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
        agent_id="agent-a",
    )
    assert orch._persist_rsi_phase(4) is True

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["rsi_phase"] == 1, "有覆写 agent 的晋升污染了全局相位"
    assert data["rsi_phase_overrides"]["agent-a"] == 4, "晋升未写回覆写条目"


def test_persist_without_override_keeps_global_semantics(settings_file):
    """无覆写条目的 agent 沿旧语义写全局（现网行为零漂移）。"""
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from unittest.mock import MagicMock

    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
        agent_id="agent-b",
    )
    assert orch._persist_rsi_phase(2) is True

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["rsi_phase"] == 2, "无覆写 agent 的晋升应写全局（旧语义）"
    assert data["rsi_phase_overrides"] == {"agent-a": 3}, "全局写回动了别人的覆写条目"


def test_phase_source_surfaces_in_status(settings_file):
    """状态面呈报相位来源（override/global）——管理员看得见这 agent 在吃哪份相位。"""
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator
    from unittest.mock import MagicMock

    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
        agent_id="agent-a",
    )
    assert orch.get_status()["phase_source"] == "override"
    assert orch.get_status()["deployment_phase"] == 3
