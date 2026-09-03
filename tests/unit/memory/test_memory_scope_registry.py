"""记忆口径根因测试：get_memory_manager 必须按 (agent, neuser, user, db_path) 作用域解析，
且默认 db_path 指向 agent 工作区标准路径——否则 API 统计永远读到全局单例而看不到
Agent 实例写入的真实记忆（dashboard 记忆恒 0 的根因）。"""
import os
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[3]  # tests/unit/memory -> 项目根


@pytest.fixture(autouse=True)
def reset_factory(monkeypatch):
    """每个测试重置工厂注册表，避免单例/注册表跨测试残留。"""
    import neurova.cognitive_layers.memory_layer.manager as mgr

    monkeypatch.setattr(mgr, "_default_manager", None)
    monkeypatch.setattr(mgr, "_managers", {})
    yield


def _call_factory(*args, **kwargs):
    import neurova.cognitive_layers.memory_layer.manager as mgr

    return mgr.get_memory_manager(*args, **kwargs)


def test_default_db_path_points_to_agent_workspace(monkeypatch):
    """无参工厂默认落到 agent_workspaces/default/memory/memory.db（与 AgentConfig 一致）。"""
    mgr = _call_factory()
    p = Path(mgr._db_path)
    assert p.as_posix().endswith("agent_workspaces/default/memory/memory.db"), p
    # 目录必须已创建（persist DB 与 db_path 同目录）
    assert p.parent.is_dir(), p.parent


def test_user_dict_extends_scope_fields(monkeypatch):
    """端点传 user 字典（get_current_user 结果）时按 user_id/neuser_id 落地，而非把 dict 当 user_id。"""
    mgr = _call_factory("default", {"user_id": "u7", "neuser_id": "n7"})
    assert mgr._user_id == "u7"
    assert mgr._neuser_id == "n7"


def test_same_scope_reuses_and_diff_scope_isolated(monkeypatch):
    mgr1 = _call_factory("default", "default")
    mgr2 = _call_factory("default", "default")
    assert mgr1 is mgr2, "同作用域必须复用实例（bus 统计连续）"

    mgr3 = _call_factory("kai", "default")
    assert mgr3 is not mgr1, "不同 agent 必须独立实例（三层隔离）"

    mgr4 = _call_factory("default", {"user_id": "u9", "neuser_id": "n9"})
    assert mgr4 is not mgr1, "不同用户必须独立实例（三层隔离）"


def test_explicit_db_path_still_respected(monkeypatch, tmp_path):
    """显式传入 db_path 时不得被默认路径解析覆盖。"""
    db = tmp_path / "custom.db"
    mgr = _call_factory("default", "default", db_path=str(db))
    assert mgr._db_path == str(db)
