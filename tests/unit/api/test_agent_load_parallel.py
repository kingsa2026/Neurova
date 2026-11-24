# -*- coding: utf-8 -*-
"""启动期 agent 并行装载（2026-11-24 启动性能批·用户拍板方案 1）。

红灯依据：_load_saved_agents 原为逐个串行构造，随 agent 数量线性变慢
（本机 10 agent ≈ 9s）。改为线程池并行后，N 个 agent 的装载耗时≈最慢
一个而非总和；用 4 个各睡 0.4s 的桩 Agent 锁定判据：串行 ≥1.6s（红），
并行应显著低于 1.2s（绿）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from neurova.api.app import AppState, _agent_load_workers, _load_saved_agents


def _seed_agent(root: Path, agent_id: str, *, corrupt: bool = False) -> None:
    d = root / agent_id
    d.mkdir(parents=True, exist_ok=True)
    if corrupt:
        (d / "agent_config.json").write_text("{not-json", encoding="utf-8")
    else:
        (d / "agent_config.json").write_text(
            json.dumps({"name": agent_id, "model": "gpt-4", "provider": "openai"}),
            encoding="utf-8",
        )


@pytest.fixture()
def load_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from neurova.agent_config import reset_config_manager
    from neurova.api.endpoints import set_app_state

    reset_config_manager()
    set_app_state({"agents": {}})
    yield Path(os.environ["NEUROVA_AGENT_WORKSPACES_DIR"])
    set_app_state(None)
    reset_config_manager()


def _install_slow_agent(monkeypatch, seconds: float):
    """桩 Agent：构造睡指定时长，并记录执行线程名（证明并行）。"""
    threads_seen: set[str] = set()

    class _SlowAgent:
        def __init__(self, config=None, **kwargs):
            time.sleep(seconds)
            threads_seen.add(threading.current_thread().name)
            self.config = config

    monkeypatch.setattr("neurova.agent_core.Agent", _SlowAgent)
    return threads_seen


def test_agents_load_in_parallel(load_env, monkeypatch):
    root = load_env
    ids = ["la1", "la2", "la3", "la4"]
    for aid in ids:
        _seed_agent(root, aid)
    threads_seen = _install_slow_agent(monkeypatch, 0.4)

    state = AppState()
    t0 = time.perf_counter()
    _load_saved_agents(state)
    elapsed = time.perf_counter() - t0

    assert sorted(state.agents.keys()) == ids, "4 个 agent 必须全部装载注册"
    assert elapsed < 1.2, (
        f"装载耗时 {elapsed:.2f}s——仍接近串行总和（4×0.4s=1.6s），并行未生效"
    )
    assert len(threads_seen) >= 2, f"应有多线程参与构造，实际线程 {threads_seen}"


def test_single_agent_failure_does_not_block_others(load_env, monkeypatch):
    root = load_env
    for aid in ["lb1", "lb2", "lb3"]:
        _seed_agent(root, aid)
    _seed_agent(root, "lb_bad", corrupt=True)
    _install_slow_agent(monkeypatch, 0.05)

    state = AppState()
    _load_saved_agents(state)

    assert sorted(state.agents.keys()) == ["lb1", "lb2", "lb3"], (
        "坏配置 agent 必须被跳过且不拖累其余 agent 装载"
    )


def test_worker_count_from_env(monkeypatch):
    monkeypatch.setenv("NEUROVA_AGENT_LOAD_WORKERS", "2")
    assert _agent_load_workers() == 2
    monkeypatch.setenv("NEUROVA_AGENT_LOAD_WORKERS", "not-a-number")
    assert _agent_load_workers() == 4, "非法值回退默认 4"
    monkeypatch.setenv("NEUROVA_AGENT_LOAD_WORKERS", "99")
    assert _agent_load_workers() == 16, "上限钳制 16，防误配打爆线程"
    monkeypatch.setenv("NEUROVA_AGENT_LOAD_WORKERS", "1")
    assert _agent_load_workers() == 1, "1 = 保留串行路径（A/B 对照用）"
    monkeypatch.delenv("NEUROVA_AGENT_LOAD_WORKERS")
    assert _agent_load_workers() == 4
