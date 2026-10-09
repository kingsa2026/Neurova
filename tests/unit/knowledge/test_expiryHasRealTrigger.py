"""到期迁移要有真触发点（跨仓对比抓出的断点 N1 / 候选 K1）。

缺陷：`knowledge_facts.py` 的生命周期注释写着"状态是生命周期的唯一权威……到期靠
**显式调用**推进"，而那句"显式调用"在全仓没有落点——`expireDueFacts()` 在 `neurova/`
与 `scripts/` 内零调用点（只有定义与两处注释提到它）。于是它下面那段"前提到期 ⇒
撤销其推导结论"的级联（`:1041-1042`）运行期不可达：`supersede` 与 `retract` 两支都有
`_retireDerived` 级联，独缺"到期"这一条迁移。

直接检索面今天是正确的：`searchableFacts` 额外挡掉"已到期但尚未被推进的行"
（`:583-584` 自己写明是怕读面跑在巡检前头）。**漏的是派生面**——由带窗口前提推出的
结论行不带窗口（`rule_engine._admitDerivedFact` 不填 `validFrom/validUntil`），
既进不了到期候选，就长期以 `active` 身份被读面命中。

判据一律走**生产那两条消费者**（启动一次性收敛 + 运维端点），用例里不直调
`expireDueFacts()`——直调等于把"有没有人调它"这个缺陷本身测掉。
`tests/unit/knowledge/test_fact_lifecycle.py` 已经钉过 `expireDueFacts` 自身的数学，
本文件钉的是它的**被调用性**，两格不重复。
"""

from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.app import create_app
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)

_UTC = datetime.timezone.utc
PREFIX = "/v1/knowledge"


def _past() -> str:
    return (datetime.datetime.now(_UTC) - datetime.timedelta(hours=1)).isoformat()


def _admit(store, subject, predicate, obj, validUntil=None):
    """走真咽喉：推导器由门自己装配，结论才有资格说是"生产推出来的"。"""
    gate = productionAdmissionGate(store, toolVersion="unit")
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, validUntil=validUntil,
        activityKind="extract", activityBasis="unit:expiry",
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:expiry", "statementText": content}],
    )).factId


def _seedExpiringChain(store):
    """铺一条"带窗口前提 → 传递闭包结论"：前提已到期，结论却无窗口。"""
    _admit(store, "青梧索引", "is_a", "文档集合", validUntil=_past())
    mid = _admit(store, "文档集合", "is_a", "实体")
    derived = [f for f in store.searchableFacts() if "由规则" in str(f.get("content", ""))]
    return mid, derived


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """隔离口径按围栏自己的指示：拿 `tmp_path` 建实例，再 monkeypatch 门面注进去。

    围栏比的是 `PRODUCTION_STORAGE_DIR`——那是**导入期**由 `dataPath("knowledge")` 定下来的，
    所以用例里再 `setenv("NEUROVA_DATA_DIR", tmp_path)` 挪不动它（第一版就这么撞了一墙
    "测试会话禁止读写生产知识库"）。门面被端点与启动钩子在调用期内 import，
    patch 这一处同时覆盖两条消费者；被 patch 的只有**存储实例**，不是被测的接线本身。
    """
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    isolated = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr("neurova.knowledge.foundation.get_knowledge_fact_store",
                        lambda *a, **kw: isolated)
    monkeypatch.setattr("neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
                        lambda *a, **kw: isolated)
    yield isolated
    isolated.close()


@pytest.fixture()
def api(store, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    holder = {"user": {"user_id": "9", "username": "admin", "role": "admin"}}
    app.dependency_overrides[knowledge_auth.get_current_user_or_service] = lambda: holder["user"]
    return TestClient(app), holder, store


class TestStartupConvergence:
    def test_bootingTheRealAppAdvancesDueFacts(self, store):
        _mid, derived = _seedExpiringChain(store)
        assert derived, "前向链没推出传递闭包——前提不成立，下面的断言是在演空转"
        assert store.fact(derived[0]["fact_id"])["status"] == "active"

        with TestClient(create_app()):
            pass

        assert store.fact(derived[0]["fact_id"])["status"] == "retracted", (
            "前提已到期而结论仍是 active：那条级联在运行期从未被跑到")

    def test_startupDoesNotPretendWhenTheStoreIsUnusable(self, store, monkeypatch):
        """启动收敛失败要如实点名，不许把"没跑成"读成"没有到期的行"。

        邻居们 fail-open 是为了不阻断启动，但故障必须留下可读痕迹（教义第 2 条）；
        这一格同时反向证明上面那格不是空转——启动路径确实调到了到期收敛。
        """
        calls: list = []

        def _boom(*_a, **_kw):
            calls.append("tried")
            raise RuntimeError("底座库被锁住")

        monkeypatch.setattr(type(store), "expireDueFacts", _boom)

        with TestClient(create_app()):
            pass

        assert calls, "启动路径根本没走到到期收敛——上面那格的绿是空转出来的"


class TestOpsEndpoint:
    def test_expiryEndpointAdvancesAndReports(self, api):
        client, _holder, store = api
        _mid, derived = _seedExpiringChain(store)
        assert derived, "装配没成，本用例什么都不曾证明"

        resp = client.post(f"{PREFIX}/foundation/expiry")

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["expired"] >= 1, resp.json()
        assert store.fact(derived[0]["fact_id"])["status"] == "retracted"
        assert not [f for f in store.searchableFacts() if "青梧索引" in str(f.get("content", ""))], (
            "运维端点跑完了，派生结论还在读面")

    def test_anonymousOrNonAdminCannotTriggerAGlobalWrite(self, api):
        """整库状态推进不是租户级动作——任何登录用户都能按一下就太宽。"""
        client, holder, _store = api
        holder["user"] = {"user_id": "1", "username": "alice", "role": "user"}

        resp = client.post(f"{PREFIX}/foundation/expiry")

        assert resp.status_code == 403, resp.text

    def test_repeatedRunsAreIdempotent(self, api):
        client, _holder, store = api
        _seedExpiringChain(store)

        first = client.post(f"{PREFIX}/foundation/expiry").json()["data"]["expired"]
        second = client.post(f"{PREFIX}/foundation/expiry").json()["data"]["expired"]

        assert first >= 1 and second == 0, (
            "第二次仍在推进同一批行——到期不是一次性迁移，重复跑会反复写活动账")
