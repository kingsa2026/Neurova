"""P0-2/P0-3 API 契约测试。

端点契约：
- GET  /v1/knowledge/conflicts            → 冲突清单（仅管理员；非 admin 403）
- POST /v1/knowledge/conflicts/{id}/resolve → 裁决（仅管理员；resolution 非法 400）
- GET  /v1/knowledge/deleted              → 墓碑清单（仅管理员；非 admin 403）
- POST /v1/knowledge/{id}/restore         → 复活（属主/管理员；他人 403；未删 404）
- GET  /v1/knowledge/{id}/revisions       → revision 账本（仅可见条目）
- DELETE /v1/knowledge/{id}               → tombstone（条目从所有视图消失，可在 /deleted 审计）
- DELETE /v1/knowledge/{id}?purge=true    → 物理删除（原 purge 通道语义保留）
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


class TestConflictApi:
    def test_list_conflicts_admin_only(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "同名A", "content": "a"})
        client.post(PREFIX, json={"title": "同名A", "content": "b"})

        holder["user"] = dict(ALICE)
        assert client.get(f"{PREFIX}/conflicts").status_code == 403

        holder["user"] = dict(ADMIN)
        resp = client.get(f"{PREFIX}/conflicts")
        assert resp.status_code == 200
        conflicts = resp.json()
        assert len(conflicts) == 1
        assert conflicts[0]["status"] == "pending"
        assert conflicts[0]["similarity"] >= 0.9

    def test_resolve_supersede_hides_old(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "裁决条目", "content": "a"})
        client.post(PREFIX, json={"title": "裁决条目", "content": "b"})
        cid = client.get(f"{PREFIX}/conflicts").json()[0]["conflict_id"]

        resp = client.post(
            f"{PREFIX}/conflicts/{cid}/resolve", json={"resolution": "supersede_old"}
        )
        assert resp.status_code == 200
        assert client.get(f"{PREFIX}/conflicts").json() == []

        deleted_ids = {d["knowledge_id"] for d in client.get(f"{PREFIX}/deleted").json()}
        conflicts_resolved = client.get(f"{PREFIX}/conflicts?status=resolved").json()
        assert len(conflicts_resolved) == 1
        # 被取代的旧条目在墓碑里
        assert repo.list_deleted()[0]["superseded_by"] is not None

    def test_resolve_invalid_resolution_400(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "非法", "content": "a"})
        client.post(PREFIX, json={"title": "非法", "content": "b"})
        cid = client.get(f"{PREFIX}/conflicts").json()[0]["conflict_id"]
        resp = client.post(f"{PREFIX}/conflicts/{cid}/resolve", json={"resolution": "nuke"})
        assert resp.status_code == 400


class TestTombstoneApi:
    def test_delete_then_admin_sees_tombstone_and_owner_restores(self, api):
        client, holder, repo = api
        holder["user"] = dict(ALICE)
        kid = client.post(PREFIX, json={"title": "可复活的", "content": "c"}).json()["knowledge_id"]
        resp = client.delete(f"{PREFIX}/{kid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "deleted"
        assert client.get(f"{PREFIX}/{kid}").status_code == 404

        # 墓碑清单仅管理员
        holder["user"] = dict(ALICE)
        assert client.get(f"{PREFIX}/deleted").status_code == 403
        holder["user"] = dict(ADMIN)
        deleted = client.get(f"{PREFIX}/deleted").json()
        assert len(deleted) == 1
        assert deleted[0]["knowledge_id"] == kid
        assert deleted[0]["deleted_by"] == "1"

        # 他人不可复活
        bob = {"user_id": "2", "username": "bob", "role": "user", "neuser_id": "2"}
        holder["user"] = dict(bob)
        assert client.post(f"{PREFIX}/{kid}/restore").status_code == 403

        # 属主复活成功，条目回到视图
        holder["user"] = dict(ALICE)
        resp = client.post(f"{PREFIX}/{kid}/restore")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "restored"
        assert client.get(f"{PREFIX}/{kid}").status_code == 200

    def test_restore_not_deleted_404(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        kid = client.post(PREFIX, json={"title": "活着", "content": "c"}).json()["knowledge_id"]
        assert client.post(f"{PREFIX}/{kid}/restore").status_code == 404

    def test_purge_keeps_physical_channel(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        kid = client.post(PREFIX, json={"title": "违规", "content": "c"}).json()["knowledge_id"]
        resp = client.delete(f"{PREFIX}/{kid}?purge=true")
        assert resp.status_code == 200
        # 契约沿用旧值（test_knowledge_unpublish 锁定 action == "deleted"）
        assert resp.json()["data"]["action"] == "deleted"
        assert repo.get_item("default", kid) is None
        assert client.get(f"{PREFIX}/deleted").json() == []


class TestRevisionsApi:
    def test_revisions_visible_and_ordered(self, api):
        client, holder, repo = api
        holder["user"] = dict(ALICE)
        kid = client.post(PREFIX, json={"title": "v0", "content": "c0"}).json()["knowledge_id"]
        client.put(f"{PREFIX}/{kid}", json={"title": "v1"})
        client.put(f"{PREFIX}/{kid}", json={"title": "v2", "content": "c2"})

        holder["user"] = dict(ADMIN)
        revs = client.get(f"{PREFIX}/{kid}/revisions").json()
        assert len(revs) == 2
        assert revs[0]["old"]["title"] == "v1"  # 最新在前
        assert revs[1]["old"]["title"] == "v0"

    def test_revisions_unknown_entry_404(self, api):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        assert client.get(f"{PREFIX}/no-such/revisions").status_code == 404


class TestFactAxisConflictApi:
    """016：治理层分歧（007 的 knowledge_conflicts）与条目同值冲突共用一个队列端点。

    两条轴的对象不同（一边是条目、一边是事实行），所以响应靠 `axis` 判别而不是混成一种形状：
    条目侧的旧字段一字不改（契约不破），事实侧带 kind / severity / recommended_policy /
    policy_basis / members。
    """

    @pytest.fixture()
    def factStore(self, tmp_path, monkeypatch):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "kb" / "knowledge_facts.db"))
        monkeypatch.setattr("neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
                            lambda *a, **k: store)
        yield store
        store.close()

    def _seedFactConflict(self, store):
        """造一条**待人工裁决**的分歧：新近/置信/断言支持三项都无差异，裁决器才不自动取代。

        两条事实若时间戳不同，`most_recent` 会当场分出胜负并 auto_resolved——那是
        007 的正常路径，但队列（status=pending）里就没有行了。
        """
        from neurova.knowledge.foundation.conflict_judge import KnowledgeConflictJudge

        sameStamp = "2026-09-20T00:00:00+00:00"
        key = store.upsertSubject("default", "神经瓦")
        older = store.upsertFact("default", key, "version", "1.0", "1.0 的正文",
                                 recordedAt=sameStamp)
        newer = store.upsertFact("default", key, "version", "2.0", "2.0 的正文",
                                 recordedAt=sameStamp)
        for fid in (older, newer):
            store.setEvidenceState(fid, "evidenced")
        recorded = KnowledgeConflictJudge(store).record("神经瓦", "version")
        return recorded[0]["conflict_id"], older, newer

    def test_queue_carries_both_axes_with_discriminator(self, api, factStore):
        client, holder, repo = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "同名A", "content": "a"})
        client.post(PREFIX, json={"title": "同名A", "content": "b"})
        conflictId, older, newer = self._seedFactConflict(factStore)

        rows = client.get(f"{PREFIX}/conflicts?axis=all").json()

        byAxis = {r["axis"] for r in rows}
        assert byAxis == {"entry", "fact"}
        entry = [r for r in rows if r["axis"] == "entry"][0]
        assert {"old_id", "new_id", "similarity", "reason", "title"} <= set(entry)
        fact = [r for r in rows if r["axis"] == "fact"][0]
        assert fact["conflict_id"] == conflictId
        assert fact["kind"] == "value" and fact["severity"] > 0
        assert fact["policy_basis"], "有依据的自动裁决必须把依据带到队列上"
        assert fact["recommended_policy"] in ("most_recent", "credibility_weighted",
                                             "highest_confidence", "keep_both", "manual")
        assert set(fact["member_fact_ids"]) == {older, newer}
        assert fact["subject_label"] == "神经瓦", "队列上只给主体键等于让人去查数据库"
        assert sorted(fact["members_summary"]) == ["version → 1.0", "version → 2.0"]

    def test_axis_filter_narrows_the_queue(self, api, factStore):
        client, holder, _ = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "同名A", "content": "a"})
        client.post(PREFIX, json={"title": "同名A", "content": "b"})
        self._seedFactConflict(factStore)

        assert {r["axis"] for r in client.get(f"{PREFIX}/conflicts?axis=fact").json()} == {"fact"}
        assert {r["axis"] for r in client.get(f"{PREFIX}/conflicts?axis=entry").json()} == {"entry"}

    def test_resolve_routes_to_the_owning_ledger(self, api, factStore):
        client, holder, _ = api
        holder["user"] = dict(ADMIN)
        client.post(PREFIX, json={"title": "同名A", "content": "a"})
        client.post(PREFIX, json={"title": "同名A", "content": "b"})
        conflictId, _, _ = self._seedFactConflict(factStore)

        resp = client.post(f"{PREFIX}/conflicts/{conflictId}/resolve", json={"resolution": "dismiss"})

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["axis"] == "fact"
        assert factStore.conflicts("pending") == []
        assert len([r for r in client.get(f"{PREFIX}/conflicts").json() if r["axis"] == "entry"]) == 1, \
            "裁决事实侧不许顺手关掉条目侧的账"

    def test_admin_only_and_unknown_id(self, api, factStore):
        client, holder, _ = api
        conflictId, _, _ = self._seedFactConflict(factStore)

        holder["user"] = dict(ALICE)
        assert client.post(f"{PREFIX}/conflicts/{conflictId}/resolve",
                           json={"resolution": "dismiss"}).status_code == 403
        holder["user"] = dict(ADMIN)
        assert client.post(f"{PREFIX}/conflicts/nope/resolve",
                           json={"resolution": "dismiss"}).status_code == 404

    def test_resolved_history_excludes_the_other_axis_automatically(self, api, factStore):
        """resolved 是状态词，不是轴：两侧都按 status 查，各自只回自己的历史。"""
        client, holder, _ = api
        holder["user"] = dict(ADMIN)
        conflictId, _, _ = self._seedFactConflict(factStore)
        client.post(f"{PREFIX}/conflicts/{conflictId}/resolve", json={"resolution": "dismiss"})

        history = client.get(f"{PREFIX}/conflicts?status=resolved&axis=all").json()

        assert [r["conflict_id"] for r in history] == [conflictId]
        assert history[0]["axis"] == "fact" and history[0]["resolution"] == "dismiss"

    def test_manualSupersedeNeedsAWinner_thenRetiresTheLosingFact(self, api, factStore):
        """人工裁决必须真落地：只写一个 resolution 字符串而不取代败方，
        队列清了而两条矛盾事实还在同时进上下文——那是假干净。"""
        client, holder, _ = api
        holder["user"] = dict(ADMIN)
        conflictId, older, newer = self._seedFactConflict(factStore)

        bad = client.post(f"{PREFIX}/conflicts/{conflictId}/resolve",
                          json={"resolution": "supersede_old"})
        assert bad.status_code == 400, bad.text
        assert "winner" in bad.text

        wrongWinner = client.post(f"{PREFIX}/conflicts/{conflictId}/resolve",
                                 json={"resolution": "supersede_old", "winner_fact_id": "fact_ghost"})
        assert wrongWinner.status_code == 400, wrongWinner.text

        ok = client.post(f"{PREFIX}/conflicts/{conflictId}/resolve",
                         json={"resolution": "supersede_old", "winner_fact_id": newer})
        assert ok.status_code == 200, ok.text
        assert factStore.fact(newer)["status"] == "active"
        assert factStore.fact(older)["status"] == "superseded"
        assert factStore.conflicts("pending") == []
