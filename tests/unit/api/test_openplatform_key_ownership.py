"""开放平台密钥的归属真实来自那道门，不是 request.state

缺陷：`openplatform_keys.py:128-129` 的 `_get_uid(request)` 读
`getattr(request.state, "user_id", "anonymous")`，而 **全仓没有任何地方写
`request.state.user_id`**（grep `state.user_id =` 零命中）。该路由已经挂了
`APIRouter(dependencies=[Depends(get_current_user)])`，身份拿得到，只是端点没去拿。

后果不是"降级成 anonymous"这么简单：所有用户的密钥都落在同一个 `anonymous` 桶里，
于是列表、详情、改名、撤销、删除**跨用户全部互相可见可操作**——按 key_id 就能撤别人的键。

这与本会话已修的 memory 域 `get_memory_manager` 身份注入、`memory_enhancement.py`
的 `request.state.user` 是同一根因（身份来源旁落 / 无人写入的字段被当事实源）。
修法照旧：身份只从那道门的返回值取。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import openplatform_keys as opk

BASE = "/api/v1/openplatform"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """按用例切换身份的门：override 打在真实依赖对象上"""
    monkeypatch.setenv("NEUROVA_OPENPLATFORM_KEYS_DB", str(tmp_path / "keys.json"))
    opk.reset_openplatform_keys_store()

    holder = {"who": {"user_id": "alice", "username": "alice", "role": "user", "neuser_id": "alice"}}

    app = FastAPI()
    app.include_router(opk.router, prefix=BASE)
    app.dependency_overrides[auth_mod.get_current_user] = lambda: holder["who"]
    c = TestClient(app)
    c.as_user = lambda uid: holder.__setitem__("who", {
        "user_id": uid, "username": uid, "role": "user", "neuser_id": uid
    })
    return c


def _create(client, name="ci-key"):
    r = client.post(f"{BASE}/", json={"name": name, "scopes": ["read"], "expires_in_days": 30})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_otherUserCannotSeeMyKeyInList(client):
    created = _create(client)

    client.as_user("bob")
    items = client.get(f"{BASE}/").json()["data"]["items"]

    ids = [k["id"] for k in items]
    assert created["id"] not in ids, f"bob 的列表里看见了 alice 的密钥：{ids}"


def test_otherUserCannotReadMyKey(client):
    created = _create(client)

    client.as_user("bob")
    assert client.get(f"{BASE}/{created['id']}").status_code == 404


def test_otherUserCannotRevokeMyKey(client):
    """撤销是破坏性操作——按别人的 key_id 就能撤，是最该拦的一条"""
    created = _create(client)

    client.as_user("bob")
    assert client.post(f"{BASE}/{created['id']}/revoke").status_code == 404

    client.as_user("alice")
    assert client.get(f"{BASE}/{created['id']}").status_code == 200, "alice 的密钥已被他人撤销"


def test_ownerStillManagesOwnKey(client):
    """收紧归属不得把正常owner自己的管理挡掉"""
    created = _create(client)

    assert client.put(f"{BASE}/{created['id']}", json={"name": "renamed"}).status_code == 200
    assert client.post(f"{BASE}/{created['id']}/revoke").status_code == 200


def test_stateUserIdReaderIsRetired(client):
    """身份不得再从 `request.state.user_id` 取——那个字段全仓无人写入。
    （反证要钉在符号本身上：字面量 `state.user_id` 抓不到
    `getattr(request.state, "user_id", ...)` 这种写法，会假绿。）"""
    assert not hasattr(opk, "_get_uid"), "仍在用那个无人写入的字段当身份来源"
