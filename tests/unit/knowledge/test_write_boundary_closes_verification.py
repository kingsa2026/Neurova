"""咽喉写入的每一笔都要自陈来路、自验结论——不许只收「记得调 attest 的那两条链」。

病灶（Issue #75 复核，2026-09-21 第六批）：§6.3 把校验闭环的调用点登记为
「条目投影与历史回填两条真实写入链」，可事实上经咽喉落库的真实写入链有六条：
条目投影、历史回填、对账回放、规则推导、LLM 抽取、时序事实。后四条写完就走，
没有任何人回写 `verification_state` —— 它们的断言从落库那一刻起恒为 `unverified`，
与审计点名的「92/92 恒 unverified」是同一形状，只是换了四条链。

修法不在四条链上各补一次 `attest()`（那就是"记住了的才闭环"的原地复活），
而在**唯一写咽喉**收口：`admit()` 落完账即对本笔活动裁决并回写，回执带上结论。
谁走咽喉谁闭环，没有第二条纪律。

第 4 条判据钉的是同族第二处：规则推导的事实此前不声明来路，于是落进咽喉兜底的
`admit` / 「直写」，`ACTIVITY_KINDS` 里那个 `derive` 从无使用者——推导在溯源账上
读起来像"有人直插了一条"。
"""

from __future__ import annotations

import pathlib

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject="甲", predicate="is_a", obj="设备", **kwargs):
    content = kwargs.pop("content", "%s %s %s" % (subject, predicate, obj))
    return productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
        agentId=kwargs.pop("agentId", "default"), subjectLabel=subject,
        predicateTermId=predicate, objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}], **kwargs))


def _statesOf(store, activityKind=None):
    sql = ("SELECT a.verification_state AS state, act.activity_kind AS kind"
           " FROM knowledge_assertions a JOIN knowledge_activities act"
           " ON act.activity_id = a.activity_id")
    params = ()
    if activityKind:
        sql += " WHERE act.activity_kind = ?"
        params = (activityKind,)
    with store._lock:
        rows = store._conn.execute(sql, params).fetchall()
    return [r["state"] for r in rows], [r["kind"] for r in rows]


class TestEveryWriteChainClosesItsOwnLoop:
    def test_llmExtractionChainLeavesNoUnverifiedRow(self, store):
        from neurova.knowledge.graph_bridge import admitExtractedFacts

        admitExtractedFacts(
            {"entities": [{"label": "路由器", "type": "设备"}], "relations": []},
            {"agent_id": "kai", "knowledge_id": "kb_1", "title": "路由器"}, store)

        states, kinds = _statesOf(store, activityKind="extract")

        assert kinds, "前提：抽取链确实落了断言"
        assert set(states) == {"verified"}, "抽取链写完不回写结论，读数就永远停在未验过"

    def test_temporalFactChainLeavesNoUnverifiedRow(self, store):
        from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule

        module = TKGModule(factStore=store)
        module.bindAgent("kai")
        module.add_fact("丙", "is_a", "设备", statementText="丙是设备")

        states, kinds = _statesOf(store, activityKind="admit")

        assert kinds, "前提：时序事实链确实落了断言"
        assert set(states) == {"verified"}, "时序事实链写完不回写结论，读数就永远停在未验过"

    def test_derivationChainLeavesNoUnverifiedRow(self, store):
        _admit(store, "路由器", "is_a", "设备")
        _admit(store, "设备", "is_a", "硬件")

        states, kinds = _statesOf(store)

        assert "derive" in kinds, "前提：种子规则确实推出了结论"
        assert set(states) == {"verified"}, "推导链写完不回写结论，读数就永远停在未验过"

    def test_reconcileReplayLeavesNoUnverifiedRow(self, store, tmp_path):
        from neurova.knowledge.foundation.reconcile import FoundationReconciler
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge("default", "甲", "内容甲", owner_user_id="u1",
                              detect_conflict=False)
        report = FoundationReconciler.reconcile(repo, str(tmp_path / "replay.db"))
        replay = KnowledgeFactStore(str(tmp_path / "replay.db"))
        try:
            states, kinds = _statesOf(replay, activityKind="import")
        finally:
            replay.close()

        assert report["ok"] is True
        assert kinds, "前提：对账回放确实落了断言"
        assert set(states) == {"verified"}, "对账回放写完不回写结论，读数就永远停在未验过"


class TestReceiptCarriesItsOwnVerdict:
    def test_receiptReportsTheVerdictOfTheWriteItJustMade(self, store):
        receipt = _admit(store)

        assert receipt.verification.get("graded") == 1, "回执要带上本笔的校验结论"
        assert receipt.verification.get("verified") == 1
        assert receipt.verification.get("failed") == 0

    def test_theVerdictIsScopedToThisActivityOnly(self, store):
        """写路径只裁决本笔活动：不做全库重扫，也不许把别人那笔的结论当成自己的读数。"""
        first = _admit(store, "甲", "is_a", "设备")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ? WHERE activity_id = ?",
                ("被改过的说法", first.activityId))

        second = _admit(store, "乙", "is_a", "设备")

        assert second.verification["graded"] == 1, (
            "读数只数本笔：全库扫描会让它不再等于本笔写入的条数")
        assert second.verification["failed"] == 0, "别人那笔的结论不该算进本笔读数"

    def test_theInspectorStillCatchesTheTamperedRow(self, store):
        """反向控制：不在写路径重扫，不等于判据被放宽——巡检照样要抓到。"""
        first = _admit(store, "甲", "is_a", "设备")
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE knowledge_assertions SET statement_text = ? WHERE activity_id = ?",
                ("被改过的说法", first.activityId))

        report = ActivityDigestChain(store).attest(first.activityId)

        assert report["failed"] == 1


class TestDerivedFactsDeclareTheirOrigin:
    def test_derivationIsNotFiledAsADirectWriteFallback(self, store):
        _admit(store, "路由器", "is_a", "设备")
        _admit(store, "设备", "is_a", "硬件")

        rows = store._conn.execute(
            "SELECT activity_kind, basis FROM knowledge_activities"
            " WHERE activity_kind <> 'admit'").fetchall()

        assert [r["activity_kind"] for r in rows] == ["derive"], (
            "推导有自己的来路种类，落成兜底「直写」会让溯源账读不出是谁推的")
        assert "推导" in rows[0]["basis"]


class TestValidityWindowIsStillReadableAfterTheBoundaryMoves:
    def test_expiredClaimStaysOutOfTheReadSurface(self, store):
        """本笔写入收口的同一条链上，写→读的咬合不许被改动碰坏。"""
        import datetime

        moment = datetime.datetime.now(datetime.timezone.utc)
        _admit(store, "丙烷", "is_a", "设备",
               validFrom=(moment - datetime.timedelta(days=5)).isoformat(),
               validUntil=(moment - datetime.timedelta(days=1)).isoformat())
        reader = TemporalFactReader(store, agentId="default")

        # 对照必须一并断言：只断言"读不到"的话，主体名压根没被认出来也算过
        assert reader.forQuery("丙烷 设备") == []
        _admit(store, "甲烷", "is_a", "设备")
        assert reader.forQuery("甲烷 设备"), "对照：未过期的说法必须读得到，否则上一行是假绿"


class TestThereIsOnlyOneClosurePoint:
    """闭环只准有一份实现：第二条「我记得要调 attest」的路就是下一次漏掉的种子。"""

    def test_matrixHasNoSecondClosurePoint(self):
        """扫**代码**不扫注释：注释里提一句"这里再跑一次 attest 就是第二份实现"
        本身不是调用；按文本扫会把解释性文字误判成违规，判据一被误伤就没人再看。"""
        import ast

        root = pathlib.Path(__file__).resolve().parents[3]
        offenders = []
        for path in (root / "neurova").rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            calls = {node.func.attr for node in ast.walk(tree)
                     if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
            if not calls & {"attest"}:
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            # 咽喉（收口点）与 digest_chain（定义处 + 巡检入口）。
            if rel in ("neurova/knowledge/foundation/admission.py",
                       "neurova/knowledge/foundation/digest_chain.py"):
                continue
            offenders.append(rel)

        assert offenders == [], (
            "写路径上出现了第二份闭环实现（%s）——应收口到 `admit()` 的收尾，"
            "「谁记得谁闭环」撑不住下一次新增写入链" % offenders)

    def test_closingIsScopedPerWriteNotWholeLibrary(self):
        """写路径只裁决本笔：全库重扫会让每一次写入的成本随库增长。"""
        from neurova.knowledge.foundation.digest_chain import ActivityDigestChain

        assert hasattr(ActivityDigestChain, "closeWrite"), "写路径收尾入口必须存在"

        module = pathlib.Path(__file__).resolve().parents[3].joinpath(
            *ActivityDigestChain.__module__.split(".")).with_suffix(".py")
        body = module.read_text(encoding="utf-8").split(
            "def closeWrite", 1)[1].split("def attest", 1)[0]
        assert "_gradeAll(str(activityId))" in body, "closeWrite 必须传活动 id 收窄裁决面"
        assert "assertionVerificationCounts" not in body, (
            "写路径不许读全库分布——那是巡检入口 `attest()` 的读数，不是本笔的")
