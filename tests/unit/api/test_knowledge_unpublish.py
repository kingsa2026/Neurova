"""
管理员删除公共库条目 → 下架而非连坐删除 私人原始数据 测试（2026-09-01 TDD）

Bug（用户报告）：私人知识库提交到公共库的文档，管理员从公共库删除后，
私人库也一并被删除。

根因：公共库不是独立存储——submit_to_public 只把属主那条记录的
visibility 置为 public（公共库与私人库是同一份物理数据）；而
delete_knowledge 是物理删除整条记录，admin 全可改 → 管理员在公共库
视角的删除把属主的原始数据连带物理删除。

契约（语义级修复）：
1. 管理员删除「他人提交的公共条目」→ 默认为下架（unpublish）：
   条目保留，visibility 回 private，submission.status=rejected
   （reviewed_by=管理员、note 注明下架）。公共库立即消失，私人库保留。
2. 显式 ?purge=true → 物理删除整条（管理员清除违规内容的通道）。
3. 管理员删除自己创建的条目、属主删除自己的条目（public/private）→
   物理删除（现状不变，自己的数据自己删）。
4. 下架后条目仍可被属主再次 submit-public 重新走审批。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "neuser_id": "9"}

PREFIX = "/v1/knowledge"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": dict(ALICE)}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    client = TestClient(app)
    return client, holder, r


def _create_submitted_public(client, holder, title="公共文档"):
    """alice 建私有条目 → 提交公库 → admin 审批通过（public）。返回 knowledge_id。"""
    holder["user"] = dict(ALICE)
    resp = client.post(PREFIX, json={"title": title, "content": "内容"})
    kid = resp.json()["knowledge_id"]
    client.post(f"{PREFIX}/{kid}/submit-public")
    holder["user"] = dict(ADMIN)
    resp = client.post(f"{PREFIX}/{kid}/review-public", json={"approve": True})
    assert resp.status_code == 200
    return kid


class TestAdminDeletePublicSubmission:
    def test_admin_delete_unpublishes_keeps_owner_data(self, api):
        """核心回归：管理员从公共库删除 ≠ 删掉属主原始数据。"""
        client, holder, repo = api
        kid = _create_submitted_public(client, holder)

        holder["user"] = dict(ADMIN)
        resp = client.delete(f"{PREFIX}/{kid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "unpublished", "响应须如实说明动作=下架"

        # 条目仍在（私人库保住）：visibility 回 private，submission=rejected
        item = repo.get_item("default", kid)
        assert item is not None, "私人库的原始条目必须保留"
        assert item["visibility"] == "private"
        assert item["submission"]["status"] == "rejected"
        assert item["submission"]["reviewed_by"] == "9"
        assert "下架" in (item["submission"]["note"] or "")

        # 公共库视角立即消失
        holder["user"] = dict(ADMIN)
        public_titles = [
            i["title"] for i in client.get(PREFIX, params={"scope": "public"}).json()["data"]["items"]
        ]
        assert "公共文档" not in public_titles

        # 属主私人视角仍可见
        holder["user"] = dict(ALICE)
        resp = client.get(f"{PREFIX}/{kid}")
        assert resp.status_code == 200

    def test_purge_true_physically_deletes(self, api):
        """显式 purge=true 才物理删除。"""
        client, holder, repo = api
        kid = _create_submitted_public(client, holder)

        holder["user"] = dict(ADMIN)
        resp = client.delete(f"{PREFIX}/{kid}", params={"purge": "true"})
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "deleted"
        assert repo.get_item("default", kid) is None

    def test_admin_deletes_own_entry_purges(self, api):
        """管理员删除自己创建的条目 → 物理删除（自己的数据）。"""
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        resp = client.post(PREFIX, json={"title": "管理员自建", "content": "c", "visibility": "public"})
        kid = resp.json()["knowledge_id"]

        resp = client.delete(f"{PREFIX}/{kid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "deleted"
        assert repo.get_item("default", kid) is None

    def test_owner_delete_own_public_entry_purges(self, api):
        """属主删除自己的条目（含已公共化）→ 物理删除，语义不变。"""
        client, holder, repo = api
        kid = _create_submitted_public(client, holder)

        holder["user"] = dict(ALICE)
        resp = client.delete(f"{PREFIX}/{kid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "deleted"
        assert repo.get_item("default", kid) is None

    def test_unpublished_entry_can_resubmit(self, api):
        """下架后属主可重新提交公库再走审批。"""
        client, holder, _repo = api
        kid = _create_submitted_public(client, holder)

        holder["user"] = dict(ADMIN)
        client.delete(f"{PREFIX}/{kid}")

        holder["user"] = dict(ALICE)
        resp = client.post(f"{PREFIX}/{kid}/submit-public")
        assert resp.status_code == 200, "下架（rejected）不应阻止重新提交"
        holder["user"] = dict(ADMIN)
        assert client.get(PREFIX + "/public-submissions").json()[0]["knowledge_id"] == kid
