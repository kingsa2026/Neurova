# -*- coding: utf-8 -*-
"""审批账本必须是单源落点，且落点由数据根决定（不再由调用顺序决定）

事实：`get_approval_manager(workspace_path=".")` 是进程级单例，却收一个"由第一个
到达的调用方钉死"的路径参数。仓内 10 个调用点里有 9 个不传（吃 CWD 默认 → 仓根
`./.approval/`），只有 `agent_core.py:736` 传 agent 工作区。于是同一份审批状态有两处
物理存储，用哪一处取决于谁先初始化——`agent_core.py:732-735` 的注释警告过这件事，
但它只保证了"实例唯一"，没保证"落点唯一"。

收口：账本落点唯一，且从数据根解析（可经 NEUROVA_DATA_DIR 注入隔离）；工厂不再收
workspace_path —— 参数留着就一定会被第二次传成别的值。类构造器仍收路径，供测试注入
临时目录。
"""

import inspect
from pathlib import Path

import pytest

from neurova.security import approval_manager as am


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """数据根与 CWD 都隔离到 tmp，并清掉进程级单例。"""
    data_root = tmp_path / "data"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(data_root))
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(am, "_approval_manager", None)
    yield data_root, cwd
    monkeypatch.setattr(am, "_approval_manager", None)


def test_factory_no_longer_accepts_a_workspace_path():
    """路径参数是这次分裂的入口，必须从工厂签名里消失。"""
    params = inspect.signature(am.get_approval_manager).parameters
    assert "workspace_path" not in params, list(params)


def test_store_lands_under_data_root_isolated_by_env(isolated):
    data_root, _cwd = isolated

    manager = am.get_approval_manager()

    assert manager._db_path.exists()
    assert data_root in manager._db_path.parents, manager._db_path


def test_cwd_is_never_a_landing_point(isolated):
    """CWD 落点是"换个启动目录就换个账本"的入口，收口后不得再出现。"""
    _data_root, cwd = isolated

    am.get_approval_manager()

    assert not (cwd / ".approval").exists(), "仍在 CWD 建账本 = 换启动目录即换库"


def test_agent_core_stops_passing_a_per_agent_workspace():
    """调用点同步收口：源级守卫，防止参数被"顺手"加回去。"""
    source = Path("neurova/agent_core.py").read_text(encoding="utf-8")
    start = source.index("get_approval_manager(")
    call_site = source[start:start + 200]

    assert "workspace_path" not in call_site, call_site
