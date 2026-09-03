"""
知识库隔离 API 测试

覆盖批次 1 的 API 契约：
- 知识条目 7 个路由强制鉴权（无 JWT → 401）
- list/search 走可见性视图（scope: all/public/private/shared）
- create visibility=public 仅 admin
- 共享只读（被共享者 PUT/DELETE → 403）
- 提交公共库 → admin 审批（approve→public / reject→维持 private）
- 不可见条目返回 404（不泄露存在性）

测试范式：裸 FastAPI + include_router + dependency_overrides。
注意 override 的是 neurova.api.auth.get_current_user（knowledge.py 的 import 来源），
不是 neurova.api.deps 里的同名函数。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
BOB = {"user_id": "2", "username": "bob", "role": "user", "neuser_id": "2"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """返回 (client, holder, app)。holder["user"] 可在测试中切换当前用户。"""
    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr(
        "neurova.knowledge.repository.get_knowledge_repository", lambda: r
    )

    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, app


def _create(client, title, **overrides):
    payload = {"title": title, "content": "content of " + title}
    payload.update(overrides)
    resp = client.post(PREFIX, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ================================================================
# 鉴权
# ================================================================


class TestAuthRequired:
    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("get", PREFIX, None),
            ("post", PREFIX + "/search", {"query": "q"}),
            ("post", PREFIX, {"title": "t", "content": "c"}),
            ("get", PREFIX + "/configs", None),
            ("post", PREFIX + "/import-url", None),
        ],
    )
    def test_anonymous_gets_401(self, api, monkeypatch, method, path, body):
        client, _holder, app = api
        app.dependency_overrides.clear()
        monkeypatch.setattr(
            knowledge_module, "_fetch_url", lambda url: b"<html>ok</html>"
        )
        kwargs = {"json": body} if body is not None else {}
        if path.endswith("import-url"):
            kwargs["params"] = {"url": "https://example.com/x"}
        resp = getattr(client, method)(path, **kwargs)
        assert resp.status_code == 401


# ================================================================
# 可见性视图
# ================================================================


class TestVisibilityView:
    def test_private_invisible_to_others_visible_to_admin(self, api):
        client, holder, _app = api
        item = _create(client, "alice-secret")

        holder["user"] = dict(BOB)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "alice-secret" not in titles
        # 不可见条目 404，不泄露存在性
        assert client.get(PREFIX + "/" + item["knowledge_id"]).status_code == 404

        holder["user"] = dict(ADMIN)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "alice-secret" in titles

    def test_create_public_requires_admin(self, api):
        client, holder, _app = api
        resp = client.post(PREFIX, json={"title": "p", "content": "c", "visibility": "public"})
        assert resp.status_code == 403

        holder["user"] = dict(ADMIN)
        resp = client.post(PREFIX, json={"title": "p", "content": "c", "visibility": "public"})
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

        holder["user"] = dict(BOB)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "p" in titles

    def test_scope_param(self, api):
        client, holder, _app = api
        _create(client, "mine")
        holder["user"] = dict(ADMIN)
        _create(client, "pub", visibility="public")

        holder["user"] = dict(BOB)
        assert [i["title"] for i in client.get(PREFIX, params={"scope": "public"}).json()] == ["pub"]
        assert client.get(PREFIX, params={"scope": "private"}).json() == []
        assert client.get(PREFIX, params={"scope": "all"}).json() != []

    def test_search_within_visible_view(self, api):
        client, holder, _app = api
        _create(client, "alpha-note", content="unique haystack alpha")

        holder["user"] = dict(BOB)
        resp = client.post(PREFIX + "/search", json={"query": "alpha"})
        assert resp.json() == []

        holder["user"] = dict(ALICE)
        resp = client.post(PREFIX + "/search", json={"query": "alpha"})
        assert len(resp.json()) == 1


# ================================================================
# 修改守卫
# ================================================================


class TestModifyGuards:
    def test_shared_user_readonly(self, api, monkeypatch):
        client, holder, _app = api
        item = _create(client, "shared-doc")
        monkeypatch.setattr(
            knowledge_module, "_resolve_usernames", lambda names: {"bob": "2"}
        )
        resp = client.post(PREFIX + "/%s/share" % item["knowledge_id"], json={"usernames": ["bob"]})
        assert resp.status_code == 200

        holder["user"] = dict(BOB)
        # 可见可查
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "shared-doc" in titles
        # 只读：改/删被拒
        resp = client.put(
            PREFIX + "/" + item["knowledge_id"], json={"title": "hijack"}
        )
        assert resp.status_code == 403
        resp = client.delete(PREFIX + "/" + item["knowledge_id"])
        assert resp.status_code == 403

    def test_share_unknown_username_400(self, api, monkeypatch):
        client, _holder, _app = api
        item = _create(client, "doc")
        monkeypatch.setattr(
            knowledge_module,
            "_resolve_usernames",
            lambda names: (_ for _ in ()).throw(ValueError("unknown user: ghost")),
        )
        resp = client.post(PREFIX + "/%s/share" % item["knowledge_id"], json={"usernames": ["ghost"]})
        assert resp.status_code == 400

    def test_share_requires_owner(self, api, monkeypatch):
        client, holder, _app = api
        item = _create(client, "mine")
        monkeypatch.setattr(
            knowledge_module, "_resolve_usernames", lambda names: {"bob": "2"}
        )
        holder["user"] = dict(BOB)
        resp = client.post(PREFIX + "/%s/share" % item["knowledge_id"], json={"usernames": ["bob"]})
        # bob 对 alice 的私有条目不可见 → 404（不泄露存在性）
        assert resp.status_code == 404


# ================================================================
# 公共库审批
# ================================================================


class TestPublicSubmission:
    def test_submit_approve_flow(self, api):
        client, holder, _app = api
        item = _create(client, "to-public")
        kid = item["knowledge_id"]

        resp = client.post(PREFIX + "/%s/submit-public" % kid)
        assert resp.status_code == 200
        assert resp.json()["submission"]["status"] == "pending"

        holder["user"] = dict(ADMIN)
        resp = client.get(PREFIX + "/public-submissions")
        assert [p["knowledge_id"] for p in resp.json()] == [kid]

        resp = client.post(PREFIX + "/%s/review-public" % kid, json={"approve": True, "note": "ok"})
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "public"

        holder["user"] = dict(BOB)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "to-public" in titles

    def test_reject_keeps_private(self, api):
        client, holder, _app = api
        item = _create(client, "rejected-doc")
        kid = item["knowledge_id"]
        client.post(PREFIX + "/%s/submit-public" % kid)

        holder["user"] = dict(ADMIN)
        resp = client.post(
            PREFIX + "/%s/review-public" % kid, json={"approve": False, "note": "不适合"}
        )
        assert resp.status_code == 200
        assert resp.json()["visibility"] == "private"
        assert resp.json()["submission"]["status"] == "rejected"

        holder["user"] = dict(BOB)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert "rejected-doc" not in titles

    def test_review_requires_admin(self, api):
        client, holder, _app = api
        item = _create(client, "doc")
        client.post(PREFIX + "/%s/submit-public" % item["knowledge_id"])

        holder["user"] = dict(BOB)
        resp = client.post(
            PREFIX + "/%s/review-public" % item["knowledge_id"], json={"approve": True}
        )
        assert resp.status_code == 403

    def test_non_admin_cannot_list_submissions(self, api):
        client, holder, _app = api
        holder["user"] = dict(BOB)
        resp = client.get(PREFIX + "/public-submissions")
        assert resp.status_code == 403


# ================================================================
# 导入归属
# ================================================================


class TestImportAttribution:
    def test_import_creates_private_entry_for_caller(self, api):
        client, holder, _app = api
        resp = client.post(
            PREFIX + "/import",
            files={"file": ("note.txt", b"imported body text", "text/plain")},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["visibility"] == "private"
        assert items[0]["owner_user_id"] == "1"

        holder["user"] = dict(BOB)
        titles = [i["title"] for i in client.get(PREFIX).json()]
        assert items[0]["title"] not in titles
