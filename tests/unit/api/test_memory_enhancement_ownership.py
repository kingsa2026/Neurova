# -*- coding: utf-8 -*-
"""记忆增强端点必须按归属拒绝跨用户变更

两条缺陷，同根因（身份来源旁落到无人维护的字段）：

1. `_require_memory_manager` 取 `getattr(request.state, "user", None)`，而
   `request.state.user` **全仓无人写入**（中间件只写 `state.request_id`）
   → 作用域恒回落 default，于是 `forget` / `strengthen` / `batch` 这些**变更**
   操作全部带 `agent_wide=True` 执行，任何人按 memory_id 都能改别人的记忆。
2. 既有 `test_memory_enhancement_real_manager.py` 的 fixture 用
   `@app.middleware("http")` **自己伪造** `request.state.user`——测试替生产把那个
   没人写的字段补上了，洞因此长期不现形。本文件刻意不伪造：身份只走真实依赖。

判据与 memory 域上一批同规则：管理页的**可见性**理由（列表/导出/统计走 agent-wide）
不外溢成销毁与改写权限；变更类调用一律回到归属校验。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import memory_enhancement
from neurova.cognitive_layers.memory_layer.manager import MemoryManager

BASE = "/v1/memory-enhancement"
ALICE = {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "ne-alice"}
BOB = {"user_id": "bob", "username": "bob", "role": "user", "neuser_id": "ne-bob"}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    """真 MemoryManager + 可切换身份的门；不伪造 request.state.user。"""
    manager = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="agent-under-test",
        enable_buffer=False,
    )

    class _Agent:
        pass

    agent = _Agent()
    agent.memory_manager = manager

    class _State:
        agents = {"agent-under-test": agent}

        def get_agent(self, agent_id=None):
            return self.agents.get(agent_id or "agent-under-test")

    import neurova.api.app as app_module

    monkeypatch.setattr(app_module, "get_app_state", lambda: _State())

    holder = {"who": ALICE}
    app = FastAPI()
    app.include_router(memory_enhancement.router, prefix=BASE)
    app.dependency_overrides[get_current_user] = lambda: holder["who"]
    client = TestClient(app)
    client.as_user = lambda identity: holder.__setitem__("who", identity)
    client.manager = manager
    return client


def _seedAlice(client, content="alice 的私密记忆"):
    """在 alice 作用域落一条记忆，返回其 id"""
    manager = client.manager
    manager.set_request_scope(neuser_id="ne-alice", user_id="alice")
    return manager.remember(content=content, importance=50.0)


def _readAsAlice(client, memoryId):
    manager = client.manager
    manager.set_request_scope(neuser_id="ne-alice", user_id="alice")
    return manager.get_memory(memoryId)


def test_otherUserCannotForgetMyMemory(harness):
    memoryId = _seedAlice(harness)

    harness.as_user(BOB)
    resp = harness.post(f"{BASE}/{memoryId}/forget", json={"reason": "cross-user"})

    assert resp.status_code == 404, f"他人 forget 竟被接受：{resp.status_code} {resp.text[:140]}"
    rec = _readAsAlice(harness, memoryId)
    assert rec and rec["lifecycle_stage"] != "forgotten", "alice 的记忆已被他人软删"


def test_otherUserCannotStrengthenMyMemory(harness):
    memoryId = _seedAlice(harness)

    harness.as_user(BOB)
    resp = harness.post(f"{BASE}/{memoryId}/strengthen", json={"importance_boost": 0.9})

    assert resp.status_code == 404, f"他人 strengthen 竟被接受：{resp.status_code} {resp.text[:140]}"
    assert _readAsAlice(harness, memoryId)["importance"] == pytest.approx(50.0), "alice 的记忆重要性被他人改动"


def test_batchCannotMutateOtherUsersMemories(harness):
    """批量端点同规则：一次调用里也不能夹带别人的 id 就改"""
    mine = _seedAlice(harness, "第一条")

    harness.as_user(BOB)
    resp = harness.post(
        f"{BASE}/batch",
        json={"memory_ids": [mine], "operation": "strengthen", "params": {"importance_boost": 0.8}},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["results"] == [], f"批量操作把他人记忆改掉了：{data}"
    assert data["errors"] and data["errors"][0]["memory_id"] == mine, data
    assert _readAsAlice(harness, mine)["importance"] == pytest.approx(50.0)


def test_ownerCanStillManageOwnMemory(harness):
    """收紧不得把归属者自己的正常操作挡掉"""
    memoryId = _seedAlice(harness)

    resp = harness.post(f"{BASE}/{memoryId}/strengthen", json={"importance_boost": 0.5})
    assert resp.status_code == 200, resp.text
    assert _readAsAlice(harness, memoryId)["importance"] > 50.0

    resp = harness.post(f"{BASE}/{memoryId}/forget", json={"reason": "own"})
    assert resp.status_code == 200, resp.text
    assert _readAsAlice(harness, memoryId)["lifecycle_stage"] == "forgotten"


def test_identityDoesNotComeFromRequestState(harness):
    """`request.state.user` 全仓无人写入；身份只能来自那道门的返回值。

    反证钉在**代码形态**上而不是词：这个模块与测试的注释里都会提到那个字段名
    （为了说明它为什么不能用），按字面量匹配会自己把自己钉红。
    """
    import inspect

    src = inspect.getsource(memory_enhancement._require_memory_manager)
    assert 'getattr(request.state, "user"' not in src, "仍在读无人写入的 request.state.user"


def test_existingFixtureForgeryIsGone():
    """既有那份 fixture 不得再用中间件伪造身份——那正是这个洞长期不现形的原因"""
    import pathlib

    text = pathlib.Path("tests/unit/api/test_memory_enhancement_real_manager.py").read_text(
        encoding="utf-8"
    )
    assert "request.state.user =" not in text, (
        "测试替生产伪造了没人写的字段：请改为只 override 真实依赖"
    )
