"""对照批 B7：后台工具完成结果的限时查询面。

ToolCoordinator 的 `_completed` 是内存有界留存，此前**没有查询口**（代码注释
自述"留存本身没有查询口"）——转后台工具的完成通知走一次性 SSE，刷新/重启后
就查不到了。本组红灯钉两件事：

1. coordinator 层缺 `getCompletedEntry` 只读取数（归属 fail-closed）；
2. console 读面缺 `GET /chat/tools/{task_id}/result` 端点（真 create_app 路由）。

归属双层 fail-closed：entry 盖章 session_id 必须与查询 session_id 精确一致；
会话 owner 非空时必须与调用者一致（空=共享，与 /chat/runs 同一谓词）。
"""

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from neurova.api.app import create_app
from neurova.api.auth import create_access_token
from neurova.api.endpoints import set_app_state
from neurova.agent.tool_coordinator import ToolCoordinator

TOOL_BASE = "/api/v1/console/chat/tools"


def _token() -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': 'user-a', 'username': 'user-a', 'role': 'user', 'neuser_id': 'ne-user-a'})}"}


def _coordinator() -> ToolCoordinator:
    return ToolCoordinator()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    coordinator = _coordinator()
    # 完成态 entry（白盒种数：pump 线程的 finally 落位形态）
    coordinator._completed["bg_ok"] = {
        "task": None, "observer": None,
        "tool_name": "shell", "result": "ok-result", "error": None,
        "success": True, "session_id": "sess-1",
    }
    coordinator._completed["bg_other_session"] = {
        "task": None, "observer": None,
        "tool_name": "shell", "result": "secret-of-s1", "error": None,
        "success": True, "session_id": "sess-1",
    }
    stub_agent = SimpleNamespace(tool_executor=SimpleNamespace(tool_coordinator=coordinator))
    app = create_app()
    # create_app 装配时会重置 app_state——桩 agent 必须在其**之后**登记
    set_app_state({"agents": {"default": stub_agent}, "default_agent_id": "default"})
    yield TestClient(app)


class TestCoordinatorReadface:

    def test_get_completed_entry_returns_projection(self):
        coordinator = _coordinator()
        coordinator._completed["bg_x"] = {
            "task": "TASK-OBJ", "observer": "OBS-OBJ",
            "tool_name": "shell", "result": "r", "error": None,
            "success": True, "session_id": "s1",
        }
        entry = coordinator.getCompletedEntry("bg_x", session_id="s1")
        assert entry is not None and entry["result"] == "r"
        assert "task" not in entry and "observer" not in entry, "运行期引用不得外泄"

    def test_get_completed_entry_session_mismatch_is_none(self):
        coordinator = _coordinator()
        coordinator._completed["bg_x"] = {
            "tool_name": "shell", "result": "r", "error": None,
            "success": True, "session_id": "s1",
        }
        assert coordinator.getCompletedEntry("bg_x", session_id="s2") is None
        assert coordinator.getCompletedEntry("bg_x") is not None  # 不带会话=内部用途


class TestEndpoint:

    def test_query_returns_result(self, client):
        r = client.get(f"{TOOL_BASE}/bg_ok/result",
                       params={"session_id": "sess-1"}, headers=_token())
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["result"] == "ok-result"
        assert "task" not in data and "observer" not in data

    def test_query_404_for_unknown_task(self, client):
        r = client.get(f"{TOOL_BASE}/bg_nope/result",
                       params={"session_id": "sess-1"}, headers=_token())
        assert r.status_code == 404

    def test_query_404_for_session_mismatch(self, client):
        r = client.get(f"{TOOL_BASE}/bg_other_session/result",
                       params={"session_id": "sess-2"}, headers=_token())
        assert r.status_code == 404, "他席会话的任务不得泄露存在性"

    def test_query_403_for_other_owner(self, client, monkeypatch):
        from neurova.api.endpoints import console as console_mod

        class _StubRepo:
            def get_session(self, agent_id: str, session_id: str):
                return {"user_id": "user-b"}  # 会话属于别人

        monkeypatch.setattr(console_mod, "get_session_repository",
                            lambda: _StubRepo())
        r = client.get(f"{TOOL_BASE}/bg_ok/result",
                       params={"session_id": "sess-1"}, headers=_token())
        assert r.status_code == 403

    def test_query_ok_for_shared_session(self, client, monkeypatch):
        from neurova.api.endpoints import console as console_mod

        class _StubRepo:
            def get_session(self, agent_id: str, session_id: str):
                return {"user_id": ""}  # 共享会话（空 owner 视为共享）

        monkeypatch.setattr(console_mod, "get_session_repository",
                            lambda: _StubRepo())
        r = client.get(f"{TOOL_BASE}/bg_ok/result",
                       params={"session_id": "sess-1"}, headers=_token())
        assert r.status_code == 200
