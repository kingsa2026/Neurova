# -*- coding: utf-8 -*-
"""批次 K2 活体验证：条目擦除喉在真 HTTP 栈 + 真落点上是否真的把副本清干净。

跑的真生产对象：`create_app()` + `TestClient`（带真 lifespan）、真 JWT
（`neurova.api.auth.create_access_token`，与浏览器那条凭证链同一个签法）、真写咽喉
（`productionAdmissionGate`）、真投影图单例与真向量单例。数据根走仓内唯一隔离落点
`isolatedDataRoot()`，不碰仓库 `data/`。

判据拿**读数**，不拿"跑完了没报错"：擦除前后各自把隔离根里的 SQLite 文本列、
向量分片、投影 JSON 全文扫一遍，逐个报"正文还在不在"；并把审计链的巡检读数一并打出来
——合规删除若把 `/foundation/integrity` 弄红，就是修错了。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.entryErasureLive

反证形态（证明这套读数真的会红）：把 `foundation/erasure.py` 里 `refs` 那一行的
`"%s%s" % (p, knowledgeId)` 退回成只拼一份的写法再跑同一份脚本，
副本扫描必须报 `FOUND`——那才是本批根修被咬住的证据。
"""

from __future__ import annotations

import json
import sys

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

_MARKER = "青梧擦除活体中转站"
_BODY = "%s的对账周期是每七日一次，超时阈值取 45 秒" % _MARKER
_TRIPLE = "%s的容量上限取 12 万条" % _MARKER

_READINGS: dict = {}


def _record(name: str, value) -> None:
    _READINGS[name] = value
    print("%-34s %s" % (name, value))


def main() -> int:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.cognitive_layers.knowledge_graph.manager import (
        get_knowledge_graph_manager,
    )
    from neurova.knowledge.foundation.digest_chain import ActivityDigestChain
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store
    from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
    from neurova.knowledge.hybrid import hybrid_search_knowledge
    from neurova.knowledge.repository import get_knowledge_repository
    from neurova.knowledge.vector_index import get_knowledge_vector_index

    store = get_knowledge_fact_store()
    repo = get_knowledge_repository()
    graph = get_knowledge_graph_manager()
    vectors = get_knowledge_vector_index()

    app = create_app()
    token = create_access_token({"user_id": "live-admin", "username": "live-admin",
                                 "role": "admin", "sub": "live-admin"})
    headers = {"Authorization": "Bearer %s" % token}

    with TestClient(app) as client:
        resp = client.post("/api/v1/knowledge", headers=headers,
                           json={"title": "擦除活体条目", "content": _BODY,
                                 "category": "general"})
        assert resp.status_code in (200, 201), resp.text
        kid = resp.json()["knowledge_id"]
        item = repo.get_item("default", kid)
        seeker = {"user_id": "live-admin", "role": "admin"}
        _record("POST /v1/knowledge", kid)

        # 抽取面走真装配点（llm_call 是 graph_bridge 唯一的可注入参数，不是替身）
        nodeIds = extract_knowledge_to_graph(
            item, repo=repo,
            llm_call=lambda _p: json.dumps(
                {"entities": [{"label": _MARKER, "type": "entity"}], "relations": []}),
            graph_manager=graph, factStore=store, agentId="default")
        _record("graph_bridge 落点数", len(nodeIds))
        _record("向量索引条目数", vectors.ensure_indexed(repo, seeker)["entry_count"])

        # ── 擦除前：正文必须各处都读得到（读不到说明装配没成，后面的绿是假的）
        before = _sweep(store, vectors, graph)
        for face, found in before.items():
            _record("擦除前 %s" % face, "FOUND" if found else "absent")
        hitBefore = [r for r in hybrid_search_knowledge(repo, seeker, _MARKER, limit=5)
                     if _MARKER in json.dumps(r, ensure_ascii=False)]
        _record("擦除前检索命中", len(hitBefore))
        if not any(before.values()) or not hitBefore:
            print("!! 前提不成立：正文根本没落到那些面上，本次验证不证明任何事")
            return 2

        # ── 走真端点
        resp = client.delete("/api/v1/knowledge/%s" % kid, headers=headers,
                             params={"purge": "true"})
        _record("DELETE ?purge=true", resp.status_code)
        assert resp.status_code == 200, resp.text
        erasure = resp.json()["data"]["erasure"]
        _record("回执 complete", erasure["complete"])
        _record("回执逐面", {k: v["state"] for k, v in erasure["faces"].items()})

    # ── 擦除后
    after = _sweep(store, vectors, graph)
    for face, found in after.items():
        _record("擦除后 %s" % face, "FOUND" if found else "gone")
    hitAfter = [r for r in hybrid_search_knowledge(repo, seeker, _MARKER, limit=5)
                if _MARKER in json.dumps(r, ensure_ascii=False)]
    _record("擦除后检索命中", len(hitAfter))

    verdict = ActivityDigestChain(store).verify()
    _record("审计链 ok / 行数 / 断言留档数",
            (verdict["ok"], verdict["rows"], _erasedAssertionCount(store)))

    leaked = [f for f, found in after.items() if found]
    if leaked:
        print("FAIL 这些面仍留着正文副本: %s" % leaked)
        return 1
    if hitAfter:
        print("FAIL 检索面仍能命中已擦除内容")
        return 1
    if not verdict["ok"]:
        print("FAIL 擦除弄红了审计链: %s" % verdict.get("break"))
        return 1
    if _erasedAssertionCount(store) == 0:
        print("FAIL 没有任何断言被标记擦除——链上跳没被声明过，等于没走擦除")
        return 1
    print("LIVE-PASS 条目正文在权威库/活动账/向量分片/投影四处均不可取回，"
          "断言行与链位哈希原样保留，审计链仍绿")
    return 0


def _sweep(store, vectors, graph) -> dict:
    """逐面扫"正文还能不能取回"——面名与回执里的面名对齐。"""
    out = {"facts": False, "assertions": False, "activities": False,
           "entry": False, "vectors": False, "projection": False}
    conn = store._conn
    with store._lock:
        if any(_MARKER in str(r[0] or "") + str(r[1] or "") for r in conn.execute(
                "SELECT content, object_term FROM knowledge_facts")):
            out["facts"] = True
        if any(_MARKER in str(r[0] or "") for r in conn.execute(
                "SELECT statement_text FROM knowledge_assertions")):
            out["assertions"] = True
        if any(_MARKER in str(r[0] or "") + str(r[1] or "") for r in conn.execute(
                "SELECT inputs_json, outputs_json FROM knowledge_activities")):
            out["activities"] = True
        if any(_MARKER in str(r[0] or "") for r in conn.execute(
                "SELECT payload_json FROM knowledge_narratives")):
            out["entry"] = True
    for path in vectors._dir.glob("knowledge_vectors_*.json"):
        if _MARKER in path.read_text(encoding="utf-8"):
            out["vectors"] = True
    with graph._lock:
        for node in graph._nodes.values():
            if _MARKER in json.dumps(node.to_dict(), ensure_ascii=False):
                out["projection"] = True
    return out


def _erasedAssertionCount(store) -> int:
    with store._lock:
        return int(store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_assertions WHERE erased_at <> ''"
        ).fetchone()[0])


if __name__ == "__main__":
    sys.exit(main())
