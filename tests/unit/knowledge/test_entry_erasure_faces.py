"""条目擦除链路（跨仓对比抓出的断点 N2 / 候选 K2）。

缺陷：`DELETE /v1/knowledge/{id}?purge=true` 对外承诺"物理删除整条（清除违规内容的
显式通道）"（`knowledge_core.py:418`），实测只清条目行——`repository.purge_knowledge`
动的是叙述层与墓碑，而全仓 `DELETE FROM knowledge_facts|knowledge_assertions|
knowledge_subjects` **零命中**。于是同一条内容的正文还留在四处：

1. `knowledge_facts.content` / `object_term`——被四路检索与多跳走查读的那张权威图
2. `knowledge_assertions.statement_text`
3. `knowledge_activities.inputs_json`（实测 import 那批把归一化正文整段写了进去）
4. `knowledge_vectors_<uid>.json` 的 `content[:2000]`，与 JSON 属性图节点的
   `properties.description`（`graph_bridge.py:397` 写的是 `content[:200]`）

端点还**不读** `purge_knowledge` 的返回值就无条件回 `"deleted"`。

装配口径（写这批用例时踩到的两条，留给后来人）：条目正文经 `_syncEntryGovernance`
投影成 `record_kind='narrative'` 的事实行，而该行的正文**有意不存**（工单 019b-1，
唯一副本在叙述层）；三元组若与条目正文同内容会被 `ux_fact_agent_content` 折到那一行上，
`searchableFacts()` 又默认排除 narrative——于是"装配成功了"看起来像失败。所以用例里
三元组一律用**与条目正文不同**的说法。

判据两类都要有：
- **主判据是行为**——擦除后各处副本取不回正文；派生结论随前提一起走；孤儿主体清掉。
- **防过修守卫**：断言链与 `statement_hash` 必须原样保留。链摘要
  （`digest_chain._DIGEST_FIELDS`）不吃正文，所以擦正文不动链；若顺手硬删断言行，
  `ActivityDigestChain.verify` 会判"链被削过"，`/foundation/integrity` 从此常红。
  另有来源在主张的同内容事实必须存活——擦一个条目不等于审查别人说的话。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.vector_index import KnowledgeVectorIndex

_MARKER = "青梧中转站"
_BODY = "%s的对账周期是每七日一次" % _MARKER
_TRIPLE = "%s的超时阈值取 45 秒" % _MARKER
_TRIPLE_B = "%s的容量上限取 12 万条" % _MARKER
_STATES = ("erased", "redacted", "absent", "unavailable", "failed")


def _store(tmp_path) -> KnowledgeFactStore:
    """底座库与叙述层同库同文件：擦除跨两张表一起算，分开算就是两份真源。"""
    return KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))


def _admit(store, kid, *, subject, predicate, obj, content, actorId="unit"):
    """走真咽喉：不手工传阈值、不直插 SQL，否则测的不是生产那条写路径。"""
    gate = productionAdmissionGate(store, toolVersion="unit")
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, sourceTurnId="entry:%s" % kid,
        activityKind="extract", activityBasis="unit:erasure-face",
        assertions=[{"actorType": "pipeline", "actorId": actorId,
                     "mediumRef": "entry:%s" % kid, "statementText": content}],
    )).factId


def _authorityText(store) -> str:
    """权威库里还能取到的全部文本——判"副本取不回"要扫表，不能只扫读面。"""
    with store._lock:
        facts = store._conn.execute(
            "SELECT content, object_term FROM knowledge_facts").fetchall()
        assertions = store._conn.execute(
            "SELECT statement_text FROM knowledge_assertions").fetchall()
    return "|".join([str(r[0] or "") + str(r[1] or "") for r in facts]
                    + [str(r[0] or "") for r in assertions])


class _StubEngine:
    """注入引擎：`KnowledgeVectorIndex` 契约写明注入实例可直接返回 list。"""

    def encode(self, text):
        return [0.1, 0.2, 0.3]

    def encode_batch(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest.fixture()
def kb(tmp_path):
    store = _store(tmp_path)
    yield tmp_path, store, KnowledgeRepository(str(tmp_path / "kb"))
    store.close()


def _stubVector(tmp_path, monkeypatch) -> KnowledgeVectorIndex:
    """把向量缓存与投影图的生产单例访问器换成 tmp 实例。

    擦除喉默认就取这两个访问器，所以用例不往被测对象塞私有句柄、也不给它开后门——
    那样红会落在"签名不对"而不是"副本还在"。
    """
    index = KnowledgeVectorIndex(str(tmp_path / "kb" / "vec"), engine=_StubEngine())
    monkeypatch.setattr("neurova.knowledge.vector_index.get_knowledge_vector_index",
                        lambda: index)
    return index


def _stubGraph(tmp_path, monkeypatch) -> KnowledgeGraphManager:
    graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kb" / "graph"))
    monkeypatch.setattr("neurova.cognitive_layers.knowledge_graph.manager."
                        "get_knowledge_graph_manager", lambda *a, **kw: graph)
    return graph


class TestAuthorityCopiesAreErased:
    def test_entryOwnedFactRowsAreGone(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "中转站对账", _BODY)["knowledge_id"]
        _admit(store, kid, subject=_MARKER, predicate="governs", obj="超时阈值",
               content=_TRIPLE)
        assert store.searchableFacts(), "装配没成——前提不成立，下面的断言是在演空转"

        repo.purge_knowledge("default", kid)

        assert _MARKER not in _authorityText(store), (
            "条目已 purge，权威事实行与断言里的正文仍可取回——违规内容换个表就回来了")

    def test_factsOthersStillAssertSurvive(self, kb):
        """同内容即同一知识：另一个条目还在主张它，就不能因为这一个被擦而连坐。"""
        _tmp, store, repo = kb
        kidA = repo.create_knowledge("default", "甲份", _BODY,
                                     knowledge_id="entry-a")["knowledge_id"]
        kidB = repo.create_knowledge("default", "乙份", "青梧中转站的日清口径",
                                     knowledge_id="entry-b")["knowledge_id"]
        factA = _admit(store, kidA, subject=_MARKER, predicate="governs",
                       obj="超时阈值", content=_TRIPLE, actorId="a")
        factB = _admit(store, kidB, subject=_MARKER, predicate="governs",
                       obj="超时阈值", content=_TRIPLE, actorId="b")
        assert factA == factB, "同内容应折回同一事实行，否则本用例测不到共享"

        repo.purge_knowledge("default", kidA)

        kept = store.fact(factA)
        assert kept is not None, "乙份还在主张它，事实行不该被连坐删掉"
        # 「链上跳」与「还在主张」是两个读法：前者留给溯源，后者留给置信度聚合。
        remaining = [a["medium_ref"] for a in store.liveAssertions(factA)]
        assert remaining == ["entry:%s" % kidB], "甲份仍在被算作独立来源"
        assert all(a["statement_text"] == "" for a in store.assertions(factA)
                   if a["medium_ref"] == "entry:%s" % kidA)

    def test_derivedConclusionsGoWithTheirPremise(self, kb):
        """推导结论不带 entry: 溯源，只能顺派生边走 closure——按 medium_ref 删必漏它。"""
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "索引规范", _BODY)["knowledge_id"]
        _admit(store, kid, subject="青梧中转站甲", predicate="is_a", obj="文档集合",
               content="青梧中转站甲 is_a 文档集合")
        _admit(store, kid, subject="文档集合", predicate="is_a", obj="实体",
               content="文档集合 is_a 实体")
        derived = [f for f in store.searchableFacts() if "由规则" in str(f.get("content", ""))]
        assert derived, "前向链没推出传递闭包——前提不成立，本用例什么都不曾证明"

        repo.purge_knowledge("default", kid)

        left = [f for f in store.searchableFacts() if "青梧中转站" in str(f.get("content", ""))]
        assert not left, "前提被擦而结论留在读面：派生事实成了无主的说辞"

    def test_orphanSubjectIsCleared(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "孤儿主体", _BODY)["knowledge_id"]
        _admit(store, kid, subject=_MARKER, predicate="governs", obj="超时阈值",
               content=_TRIPLE)
        before = store.subjectCount()

        repo.purge_knowledge("default", kid)

        assert store.subjectCount() < before, "主体行的 canonical_label 也是条目派生文本"

    def test_activityEnvelopeLosesEntryText(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "活动信封", _BODY)["knowledge_id"]
        _admit(store, kid, subject=_MARKER, predicate="governs", obj="超时阈值",
               content=_TRIPLE)
        with store._lock:
            before = [r["inputs_json"] for r in store._conn.execute(
                "SELECT inputs_json FROM knowledge_activities").fetchall()]
        assert any(_MARKER in (e or "") for e in before), (
            "活动信封里根本没有正文，这条守卫测不到任何真实副本")

        repo.purge_knowledge("default", kid)

        with store._lock:
            after = [r["inputs_json"] for r in store._conn.execute(
                "SELECT inputs_json FROM knowledge_activities").fetchall()]
        assert not any(_MARKER in (e or "") for e in after), (
            "活动账还留着条目正文——它是第四处副本，也最容易被忽略")


class TestChainAndHashAreKept:
    """防过修：选定语义是「擦正文、留链与哈希」。硬删断言行会让链出空洞并红给巡检。"""

    def test_assertion_rows_keep_chain_position_and_hash(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "链不被削", _BODY)["knowledge_id"]
        factId = _admit(store, kid, subject=_MARKER, predicate="governs",
                        obj="超时阈值", content=_TRIPLE)
        before = store.assertions(factId)
        assert before and before[0]["digest"], "断言没上链，「留链」就无从谈起"

        repo.purge_knowledge("default", kid)

        after = store.assertions(factId)
        assert len(after) == len(before), "断言行被删了——链上跳数一变，巡检即判链被削过"
        assert after[0]["digest"] == before[0]["digest"]
        assert after[0]["seq"] == before[0]["seq"]
        assert after[0]["statement_hash"] == before[0]["statement_hash"]
        assert after[0]["statement_text"] == "", "链保住了但正文没擦——等于没修"

    def test_digestChainStillVerifiesAfterErasure(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "巡检不红", _BODY)["knowledge_id"]
        _admit(store, kid, subject=_MARKER, predicate="governs", obj="超时阈值",
               content=_TRIPLE)

        repo.purge_knowledge("default", kid)

        verdict = ActivityDigestChain(store).verify()
        assert verdict.get("ok", True) is True, (
            "擦除把 /foundation/integrity 弄红了：合规删除不该以毁掉审计面为代价")

    def test_erasedFlagCannotHideNewText(self, kb):
        """擦除标记不是"正文免检"通行证：带着标记却塞回正文，巡检必须点名。

        这条是上一条守卫的反证——`_breakReason` 放行的只是**声明过的缺失**，
        不是"凡是标了擦除就不再看"。摘要吃不到 `statement_text`，所以夹带新正文
        不会让哈希对不上，只能靠这一咬合兜住。
        """
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "夹带", _BODY)["knowledge_id"]
        factId = _admit(store, kid, subject=_MARKER, predicate="governs",
                        obj="超时阈值", content=_TRIPLE)
        repo.purge_knowledge("default", kid)
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ? WHERE fact_id = ?",
                ("有人借擦除夹带的新正文", factId))

        verdict = ActivityDigestChain(store).verify()
        assert verdict["ok"] is False and verdict["break"]["reason"] == (
            "已标记擦除的断言仍带着正文"), "放行条件写宽了：擦除标记变成了正文免检牌"

    def test_conflictRowsLoseErasedMembers(self, kb):
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "冲突成员", _BODY)["knowledge_id"]
        erasedFact = _admit(store, kid, subject=_MARKER, predicate="governs",
                            obj="超时阈值", content=_TRIPLE)
        otherKid = repo.create_knowledge("default", "另一份", _TRIPLE_B)["knowledge_id"]
        keptFact = _admit(store, otherKid, subject=_MARKER, predicate="governs",
                          obj="容量上限", content=_TRIPLE_B)
        with store._lock, store._conn:
            store._conn.execute(
                "INSERT INTO knowledge_conflicts (conflict_id, kind, subject_key,"
                " predicate_term_id, member_fact_ids_json, member_signature, detected_at)"
                " VALUES ('conf_u1','value','subj','governs',?,?,?)",
                (json.dumps([erasedFact, keptFact]), "sig_u1", "2026-10-09T00:00:00+00:00"))

        repo.purge_knowledge("default", kid)

        with store._lock:
            row = store._conn.execute(
                "SELECT member_fact_ids_json FROM knowledge_conflicts"
                " WHERE conflict_id='conf_u1'").fetchone()
        assert row is None or erasedFact not in json.loads(row["member_fact_ids_json"]), (
            "冲突账里还挂着已删事实的 id，conflictMembers 会把它读成查无此行的空洞")


class TestCacheAndProjectionCopies:
    def test_vectorCacheLosesTheBody(self, tmp_path, monkeypatch):
        store = _store(tmp_path)
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        index = _stubVector(tmp_path, monkeypatch)
        try:
            kid = repo.create_knowledge("default", "向量副本", _BODY,
                                        owner_user_id="u1")["knowledge_id"]
            user = {"user_id": "u1"}
            assert index.ensure_indexed(repo, user)["entry_count"] == 1, "向量面没铺起来"
            shard = tmp_path / "kb" / "vec" / "knowledge_vectors_u1.json"
            assert _MARKER in shard.read_text(encoding="utf-8")

            repo.purge_knowledge("default", kid)

            assert _MARKER not in shard.read_text(encoding="utf-8"), (
                "条目删了，向量缓存里的正文副本还在——下一次检索前它一直可读")
        finally:
            store.close()

    def test_projectionNodeBodyIsScrubbed(self, tmp_path, monkeypatch):
        store = _store(tmp_path)
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        graph = _stubGraph(tmp_path, monkeypatch)
        try:
            item = repo.create_knowledge("default", "投影副本", _BODY)
            kid = item["knowledge_id"]

            def llm(_prompt):
                return json.dumps({"entities": [{"label": _MARKER, "type": "entity"}],
                                   "relations": []})

            nodeIds = extract_knowledge_to_graph(
                item, repo=repo, llm_call=llm, graph_manager=graph,
                factStore=store, agentId="default")
            assert nodeIds, "投影节点没建出来，本用例只是在演空转"
            built = [graph.get_node(n) for n in nodeIds if graph.get_node(n)]
            assert any(_MARKER in json.dumps(n.to_dict(), ensure_ascii=False) for n in built), (
                "投影节点没带上正文——那就没什么可擦的，先把装配修好再谈这条判据")

            repo.purge_knowledge("default", kid)

            left = [graph.get_node(n) for n in nodeIds if graph.get_node(n)]
            assert not any(_MARKER in json.dumps(n.to_dict(), ensure_ascii=False) for n in left), (
                "JSON 属性图的 description 仍是条目正文")
        finally:
            store.close()


class TestReceiptNamesEveryFace:
    def test_receiptReportsPerFaceStates(self, kb):
        """回执不能折成一个 bool——端点正是靠它把"只删了一处"报成"已删除"。"""
        _tmp, store, repo = kb
        kid = repo.create_knowledge("default", "回执形状", _BODY)["knowledge_id"]
        _admit(store, kid, subject=_MARKER, predicate="governs", obj="超时阈值",
               content=_TRIPLE)

        receipt = repo.purge_knowledge("default", kid)

        assert isinstance(receipt, dict), "回执仍是一个 bool，端点无法据此区分删净与删漏"
        assert receipt.get("faces"), receipt
        for face in ("facts", "assertions", "activities", "vectors", "projection", "entry"):
            assert face in receipt["faces"], "回执少一栏，那一处副本就没人负责"
            assert receipt["faces"][face]["state"] in _STATES
        assert receipt["complete"] is True
        assert receipt["faces"]["facts"]["state"] == "erased"
        assert receipt["faces"]["assertions"]["state"] == "redacted"

    def test_missingEntryReportsAbsentInsteadOfSuccess(self, kb):
        _tmp, _store_, repo = kb
        receipt = repo.purge_knowledge("default", "never-existed")
        assert isinstance(receipt, dict), (
            "回执形态仍是一个 bool——端点拿到它无法区分「删净了」「只删了一处」「查无此条目」")
        assert receipt["complete"] is True
        assert receipt["faces"]["entry"]["state"] == "absent", (
            "查无此条目却报删除成功，是假交付")
