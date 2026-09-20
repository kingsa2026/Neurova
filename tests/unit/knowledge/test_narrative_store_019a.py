"""叙述层换后端（工单 019a）。

019a 的唯一硬判据：`self._items` 逐字段等于 JSON 时代。分片索引（`_item_index_docs`
与 `_rebuild_indexes`）只读 `self._items`，是它的纯函数——喂进去的不变，索引输出
就不该动一个字。因此本文件不测"库里有没有分块表"，只测两件事：
搬进去不失真、搬出来不变形。

另一条同等重要：换后端不许留下"两份权威"。一次性搬完必须让旧 JSON 退出读路径，
否则"删空后重启"会拿快照把已删条目复活。
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import (
    FOUNDATION_DB_NAME,
    NarrativeStore,
)
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"

_LONG = "蜂群并发成本护栏需要限流与记账两段。" * 40


def _flatItems(repo) -> List[Dict[str, Any]]:
    return [it for items in repo._items.values() for it in items]


def _flatStore(store: NarrativeStore) -> List[Dict[str, Any]]:
    return [it for items in store.loadAll().values() for it in items]


def _seedJsonRepo(storageDir) -> KnowledgeRepository:
    """关闸态建库：写出 knowledge.json，含分块/父块/图节点/提交/修订各类子结构。"""
    repo = KnowledgeRepository(str(storageDir))
    first = repo.create_knowledge(
        "default", "蜂群并发成本护栏", _LONG, category="architecture",
        tags=["成本", "蜂群"], source="import:note.txt", confidence=0.72,
        owner_user_id="u1",
    )
    first["shared_with"] = ["u3"]
    first["graph_node_ids"] = ["n-a", "n-b"]
    first["submission"] = {"state": "pending", "by": "u1", "at": 1700000000.5}
    first["revisions"] = [{"title": "旧标题", "content": "旧正文", "at": 1690000000.0}]
    repo._rebuild_indexes()
    second = repo.create_knowledge(
        "kai", "公共看板说明", "全员可见，走审批", visibility="public",
        owner_user_id="u2", category="general", detect_conflict=False,
    )
    assert second["knowledge_id"] != first["knowledge_id"]
    return repo


@pytest.fixture
def seeded(tmp_path) -> KnowledgeRepository:
    return _seedJsonRepo(tmp_path / "kb")


class TestMigrationChain:
    def test_narrativesTableAppearsAfterMigrationChain(self, tmp_path):
        """v4 是新增结构——老底座库（v3）重开必须自动拿到它，否则线上永远缺表。"""
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        names = set()
        with store._conn() as conn:
            names = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            assert "knowledge_narratives" in names
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) >= 4

    def test_existingFactDbUpgradesInPlace(self, tmp_path):
        """生产底座库已是 v3 且已有事实数据，换后端不能要求重建。"""
        factDb = str(tmp_path / FOUNDATION_DB_NAME)
        KnowledgeFactStore(factDb).close()

        store = NarrativeStore(factDb)
        with store._conn() as conn:
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) >= 4
            assert conn.execute("SELECT COUNT(*) FROM knowledge_facts").fetchone()[0] == 0


class TestStoreFidelity:
    def test_replaceThenLoadIsDeepEqual(self, tmp_path, seeded):
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        store.replaceAll(seeded._items)
        assert store.loadAll() == copy.deepcopy(seeded._items)

    def test_groupOrderAndItemOrderPreserved(self, tmp_path, seeded):
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        store.replaceAll(seeded._items)
        loaded = store.loadAll()
        assert list(loaded) == list(seeded._items)
        assert [i["knowledge_id"] for i in loaded["default"]] == \
               [i["knowledge_id"] for i in seeded._items["default"]]

    def test_chunksAndSubstructuresSurvive(self, tmp_path, seeded):
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        store.replaceAll(seeded._items)
        original = _flatItems(seeded)[0]
        restored = _flatStore(store)[0]
        for field in ("chunks", "parents", "revisions", "graph_node_ids",
                      "submission", "shared_with", "owner_user_id", "visibility"):
            assert field in original, "%s 未被样本覆盖，这条判据是空的" % field
            assert restored[field] == original[field]

    def test_replaceAllRefusesItemWithoutKnowledgeId(self, tmp_path):
        """缺 id 的行一旦进了"先 DELETE 再写"的全量替换，就是静默删数据。"""
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        with pytest.raises(ValueError, match="knowledge_id"):
            store.replaceAll({"default": [{"title": "无 id 条目", "content": "x"}]})
        assert store.count() == 0

    def test_replaceAllIsTotalReplace(self, tmp_path):
        store = NarrativeStore(str(tmp_path / FOUNDATION_DB_NAME))
        store.replaceAll({"default": [{"knowledge_id": "k1", "content": "a"}]})
        store.replaceAll({"default": [{"knowledge_id": "k2", "content": "b"}]})
        assert store.count() == 1
        assert _flatStore(store)[0]["knowledge_id"] == "k2"

    def test_importKeepsIdsAndNeverOverwritesExisting(self, tmp_path, seeded):
        jsonPath = tmp_path / "kb" / "knowledge.json"
        store = NarrativeStore(str(tmp_path / "fresh" / FOUNDATION_DB_NAME))
        report = store.importFromJson(str(jsonPath))
        seededIds = {i["knowledge_id"] for i in _flatItems(seeded)}
        assert report["imported"] == len(seededIds)
        assert report["skipped_existing"] == 0
        assert {i["knowledge_id"] for i in _flatStore(store)} == seededIds

        again = store.importFromJson(str(jsonPath))
        assert again["imported"] == 0
        assert again["skipped_existing"] == len(seededIds)

    def test_importRefusesSnapshotWithoutIds(self, tmp_path):
        """旧库里若有缺 id 条目，搬入即静默丢行——必须停在脸上。"""
        path = tmp_path / "broken.json"
        path.write_text(json.dumps({"default": [{"title": "无 id"}]}), encoding="utf-8")
        store = NarrativeStore(str(tmp_path / "db.sqlite"))
        with pytest.raises(ValueError, match="knowledge_id"):
            store.importFromJson(str(path))


class TestRepositorySwitch:
    def test_gateOffWritesOnlyJson(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        _seedJsonRepo(tmp_path / "kb")
        assert (tmp_path / "kb" / "knowledge.json").exists()
        assert not (tmp_path / "kb" / FOUNDATION_DB_NAME).exists()

    def test_gateOnLoadsJsonEraItemsFieldByField(self, tmp_path, seeded, monkeypatch):
        before = copy.deepcopy(seeded._items)
        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        # 被有意改掉的只有 confidence 与 source：开闸即建治理行，条目上那两个数从此是
        # 派生值（019b-2 聚合置信、019b-4 从断言 medium_ref 派生来源），
        # 旧库里 126/130 恒 0.7 的硬编码在开闸那一刻就被归正。
        # 除此之外逐字段等于 JSON 时代——这条判据的范围因此收窄，不是放宽。
        assert _stripDerivedFields(reopened._items) == _stripDerivedFields(before)
        pairs = list(zip(_flatItems(reopened), _flatItemsFromDict(before)))
        assert any(i["confidence"] != b["confidence"] for i, b in pairs),             "开闸不回填置信度，这条豁免就只是给旧行为开后门"
        assert all("source" in i and i["source"] for i, _ in pairs),             "source 派生后必须仍非空，否则豁免变成藏缺陷"
        assert all(i["confidence"] in (0.45, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85)
                   for i, _ in pairs), "置信度必须落在聚合格点上，不是任意小数"


def _stripDerivedFields(itemsByAgent):
    out = {}
    for agentId, items in itemsByAgent.items():
        out[agentId] = [{k: v for k, v in item.items() if k not in ("confidence", "source")}
                        for item in items]
    return out


def _flatItemsFromDict(itemsByAgent):
    return [it for items in itemsByAgent.values() for it in items]

    def test_gateOnWritesGoToDatabase(self, tmp_path, seeded, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        reopened.create_knowledge("default", "换后端之后写入", "正文应该落在底座库里",
                                  owner_user_id="u1", detect_conflict=False)
        assert not (tmp_path / "kb" / "knowledge.json").exists()

        again = KnowledgeRepository(str(tmp_path / "kb"))
        titles = [i["title"] for i in _flatItems(again)]
        assert "换后端之后写入" in titles
        assert len(titles) == len(_flatItems(seeded)) + 1

    def test_sourceJsonArchivedAfterCutover(self, tmp_path, seeded, monkeypatch):
        """两份权威=迟早对不上；搬完必须让旧文件读不到，且原件留存可回退。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        KnowledgeRepository(str(tmp_path / "kb"))
        assert not (tmp_path / "kb" / "knowledge.json").exists()
        archived = NarrativeStore.findArchivedJson(str(tmp_path / "kb"))
        assert len(archived) == 1
        assert json.loads(open(archived[0], encoding="utf-8").read())

    def test_deletedAllDoesNotResurrectSnapshot(self, tmp_path, seeded, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "on")
        reopened = KnowledgeRepository(str(tmp_path / "kb"))
        for agentId, kids in [
            (a, [i["knowledge_id"] for i in items]) for a, items in reopened._items.items()
        ]:
            for kid in kids:
                reopened.delete_knowledge(agentId, kid, deleted_by="u1")

        again = KnowledgeRepository(str(tmp_path / "kb"))
        assert _flatItems(again) == []

    def test_gateOffAfterCutoverFailsLoud(self, tmp_path, seeded, monkeypatch):
        """回退到关闸态时旧文件已被搬走——静默开空库正是 B01 那类事故，必须拒绝。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        KnowledgeRepository(str(tmp_path / "kb"))
        monkeypatch.delenv(ENV_FLAG)
        with pytest.raises(RuntimeError, match="NEUROVA_KB_NARRATIVE_STORE"):
            KnowledgeRepository(str(tmp_path / "kb"))

    def test_indexDocsByteIdenticalAcrossBackends(self, tmp_path, seeded, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "on")
        sqliteRepo = KnowledgeRepository(str(tmp_path / "kb"))
        monkeypatch.delenv(ENV_FLAG)
        jsonRepo = KnowledgeRepository(str(tmp_path / "json"))
        jsonRepo._items = copy.deepcopy(seeded._items)

        expected = [
            json.dumps(jsonRepo._item_index_docs(it), ensure_ascii=False, sort_keys=True)
            for it in _flatItems(jsonRepo)
        ]
        actual = [
            json.dumps(sqliteRepo._item_index_docs(it), ensure_ascii=False, sort_keys=True)
            for it in _flatItems(sqliteRepo)
        ]
        assert actual == expected
        assert any("#" in doc.split('"id"')[-1] for doc in actual), \
            "样本应含分块条目，否则这条判据是空的"


class TestWriteSurfaceUnderGate:
    """闸内把端点真正用到的写方法走一遍——换后端不许在任何一条写路径上留断点。"""

    def test_fullWriteSurfacePersistsAcrossReopen(self, tmp_path, seeded, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "on")
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        admin = {"id": "root", "role": "admin"}
        kid = _flatItems(repo)[0]["knowledge_id"]
        doomed = _flatItems(repo)[1]["knowledge_id"]

        assert repo.update_knowledge("default", kid, {"title": "改过的标题", "confidence": 0.9})
        assert repo.list_chunks(kid), "样本条目必须已分块，否则块编辑没被覆盖"
        repo.update_chunk(kid, 0, "块正文被改写了", user=admin)
        repo.share_entry(admin, kid, ["u9"])
        repo.submit_to_public(admin, kid)
        repo.review_public_submission(admin, kid, True, reviewed_by="root")
        assert repo.delete_knowledge("kai", doomed, deleted_by="root")
        assert repo.list_deleted()

        again = KnowledgeRepository(str(tmp_path / "kb"))
        restored = again.get_item("default", kid)
        assert restored["title"] == "改过的标题"
        assert restored["visibility"] == "public"
        # 闸内 confidence 是聚合出来的（1 源 + 可回放现场 = 0.5），调用方传的 0.9 不再落账；
        # 关闸态仍然原样存 0.9——见 test_gateOffWritesOnlyJson 那条口径。
        assert restored["confidence"] == pytest.approx(0.5)
        assert "u9" in restored["shared_with"]
        assert restored["submission"]["status"] == "approved"
        assert restored["chunks"][0]["content"] == "块正文被改写了"
        assert restored["revisions"], "条目级修订账本不该在换后端后失效"
        assert again.find_item(doomed) is None
        hits = again.search_knowledge("default", "改过的标题")
        assert [h["knowledge_id"] for h in hits] == [kid]


class TestNoBreakpoint:
    def test_gateOnFromEmptyDirStartsClean(self, tmp_path, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "on")
        repo = KnowledgeRepository(str(tmp_path / "brand-new"))
        assert repo._items == {}
        repo.create_knowledge("default", "全新库第一条", "无旧文件可搬", owner_user_id="u1",
                              detect_conflict=False)
        assert len(_flatItems(KnowledgeRepository(str(tmp_path / "brand-new")))) == 1

    def test_corruptDatabaseFailsLoudInsteadOfEmptying(self, tmp_path, seeded, monkeypatch):
        """底座库读坏了不能当空库继续——下一次全量替换会抹掉整本叙述层。"""
        dbPath = tmp_path / "kb" / FOUNDATION_DB_NAME
        monkeypatch.setenv(ENV_FLAG, "on")
        NarrativeStore(str(dbPath)).replaceAll(seeded._items)
        dbPath.write_bytes(b"not a sqlite file at all")

        with pytest.raises(Exception):
            KnowledgeRepository(str(tmp_path / "kb"))
