# -*- coding: utf-8 -*-
"""P2-7 防回归：delete_agent 的目录树删除不得阻塞事件循环。

原缺陷（docs/资源型Bug扫描报告_2026-09-11.md P2 第7条）：
async delete_agent 内同步调用 ``_remove_tree_with_retry``（shutil.rmtree
+ time.sleep 重试），删大工作区（几百 MB）卡事件循环秒级~十秒级。

修复：两处调用改 ``await asyncio.to_thread(...)``。本测试以线程身份断言
删除函数运行在事件循环线程之外，且删除结果/响应契约不变（目录真实删除）。

隔离纪律：CWD 切 tmp_path（data/{agent_id} 为 CWD 相对路径），
app_state 用后重置，绝不触碰真实 data/ 与真实工作区。
"""

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request

from neurova.agent_config import reset_config_manager
from neurova.api.endpoints import agent as agent_module
from neurova.api.endpoints import set_app_state


@pytest.fixture()
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reset_config_manager()
    set_app_state(None)
    yield tmp_path
    set_app_state(None)
    reset_config_manager()


def _make_ghost(env: Path, agent_id: str):
    workspace = env / "agent_workspaces" / agent_id
    workspace.mkdir(parents=True)
    (workspace / "f.txt").write_text("x", encoding="utf-8")
    data_dir = env / "data" / agent_id
    data_dir.mkdir(parents=True)
    (data_dir / "memory.db").write_bytes(b"SQLite format 3")

    agent = SimpleNamespace(
        config=SimpleNamespace(workspace_path=str(workspace)), shutdown=lambda: None
    )
    set_app_state({"agents": {agent_id: agent}, "default_agent_id": "default"})
    return workspace, data_dir


def test_delete_agent_offloads_tree_removal_from_event_loop(isolated_env, monkeypatch):
    workspace, data_dir = _make_ghost(isolated_env, "loop1")
    main_thread = threading.get_ident()
    seen_threads = []
    real_remove = agent_module._remove_tree_with_retry

    def spy(path, *args, **kwargs):
        seen_threads.append(threading.get_ident())
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(agent_module, "_remove_tree_with_retry", spy)

    resp = asyncio.run(
        agent_module.delete_agent(request=Request(scope={"type": "http"}), agent_id="loop1")
    )

    assert len(seen_threads) == 2, "工作区与 data 目录两处删除都应执行"
    assert all(t != main_thread for t in seen_threads), (
        "rmtree+time.sleep 重试仍跑在事件循环线程上（P2-7 未修复），删大工作区卡全站"
    )
    assert resp["code"] == 0
    assert resp["data"] == {"workspace_removed": True, "agent_data_removed": True}
    assert not workspace.exists(), "删除结果契约破坏：工作区未删除"
    assert not data_dir.exists(), "删除结果契约破坏：data/{agent_id} 未删除"
