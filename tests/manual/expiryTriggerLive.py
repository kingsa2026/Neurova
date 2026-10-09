# -*- coding: utf-8 -*-
"""批次 K1 活体验证：到期这条生命周期迁移是否真的有触发点。

跑的真生产对象：真 `create_app()` + `TestClient`（带真 lifespan，触发点就在启动钩子里）、
真写咽喉 `productionAdmissionGate`、真前向链推导、真四路检索读面与多跳走查。
数据根走仓内唯一隔离落点 `isolatedDataRoot()`，**不 patch 任何门面**——
单测那几格是被迫把存储注成隔离实例（围栏比的是导入期定死的 `PRODUCTION_STORAGE_DIR`），
本脚本要证的正是"生产默认路径上，没人调也能自己收敛"。

判据取**状态读数**，不取"跑完了没报错"：前提行的 `status`、派生结论行的 `status`、
读面里还剩几条、运维端点第二次的返回值。

反证跑法（仓库根）：把 `neurova/api/app.py` 里那段到期收敛的 `await asyncio.to_thread(...)`
单独退回注释，跑同一份脚本，前提行必须仍是 `active`——否则这套读数什么都没咬住。

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.expiryTriggerLive
"""

from __future__ import annotations

import datetime
import sys

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

_UTC = datetime.timezone.utc
_READINGS: dict = {}


def _record(name: str, value) -> None:
    _READINGS[name] = value
    print("%-30s %s" % (name, value))


def _admit(store, subject, predicate, obj, validUntil=None):
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )

    gate = productionAdmissionGate(store, toolVersion="live")
    content = "%s %s %s" % (subject, predicate, obj)
    return gate.admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content, validUntil=validUntil,
        activityKind="extract", activityBasis="expiryTriggerLive",
        assertions=[{"actorType": "pipeline", "actorId": "live",
                     "mediumRef": "live:expiry", "statementText": content}],
    )).factId


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.knowledge.foundation.graph_walk import GraphFactWalker
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

    store = get_knowledge_fact_store()
    past = (datetime.datetime.now(_UTC) - datetime.timedelta(hours=2)).isoformat()

    premise = _admit(store, "青梧活体索引", "is_a", "文档集合", validUntil=past)
    _admit(store, "文档集合", "is_a", "实体")
    derived = [f for f in store.searchableFacts() if "由规则" in str(f.get("content", ""))]
    _record("前提行", premise)
    _record("派生结论行数", len(derived))
    if not derived:
        print("FAIL 前向链没推出结论，本脚本没有任何东西可验")
        return 2

    beforePremise = store.fact(premise)["status"]
    beforeDerived = [f["status"] for f in store.searchableFacts()
                     if "青梧活体索引" in str(f.get("content", ""))]
    _record("启动前 前提 status", beforePremise)
    _record("启动前 读面含派生", bool(beforeDerived))
    if beforePremise != "active":
        print("FAIL 前提在启动前就不是 active，触发点的效果无法归因")
        return 2

    # ── 真 lifespan：触发点应当自己把到期行推进
    with TestClient(create_app()):
        pass

    afterPremise = store.fact(premise)["status"]
    stillReadable = [f["fact_id"] for f in store.searchableFacts()
                     if "青梧活体索引" in str(f.get("content", ""))]
    _record("启动后 前提 status", afterPremise)
    _record("启动后 读面残留", stillReadable)
    derivedStates = store._conn.execute(
        "SELECT fact_id, status, content FROM knowledge_facts"
        " WHERE content LIKE '%由规则%'").fetchall()
    derivedStates = [(r["fact_id"], r["status"], r["content"]) for r in derivedStates]
    _record("派生结论状态", [(f, s) for f, s, _c in derivedStates])
    walked = GraphFactWalker(store, agentId="default").walkFromQuery("青梧活体索引")
    _record("多跳走查条数", len(walked or []))

    # ── 运维端点：第二次必须是 0（幂等），且非管理员按不动
    token = create_access_token({"user_id": "root", "username": "root",
                                 "role": "admin", "sub": "root"})
    app = create_app()
    with TestClient(app, headers={"Authorization": "Bearer %s" % token}) as client:
        second = client.post("/api/v1/knowledge/foundation/expiry")
        _record("第二次运维端点", (second.status_code, second.json().get("data")))
    userToken = create_access_token({"user_id": "u1", "username": "u1",
                                     "role": "user", "sub": "u1"})
    with TestClient(create_app(), headers={"Authorization": "Bearer %s" % userToken}) as c2:
        refused = c2.post("/api/v1/knowledge/foundation/expiry")
        _record("非管理员触发", refused.status_code)

    bad = []
    if afterPremise != "expired":
        bad.append("前提没被推进（仍是 %s）——启动触发点没跑" % afterPremise)
    if stillReadable:
        bad.append("读面还留着派生结论：%s" % stillReadable)
    if any(s != "retracted" for _f, s, c in derivedStates if "青梧活体索引" in (c or "")):
        bad.append("派生结论状态未随前提退场：%s" % [(f, s) for f, s, _c in derivedStates])
    if second.status_code != 200 or second.json()["data"]["expired"] != 0:
        bad.append("运维端点第二次不回 0，幂等不成立")
    if refused.status_code != 403:
        bad.append("非管理员触发未回 403（%s）" % refused.status_code)
    if bad:
        print("FAIL " + "；".join(bad))
        return 1
    print("LIVE-PASS 启动一次性收敛把到期行推进为 expired、其推导结论退场，"
          "运维端点幂等且非管理员按不动")
    return 0


if __name__ == "__main__":
    sys.exit(main())
