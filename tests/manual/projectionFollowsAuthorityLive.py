# -*- coding: utf-8 -*-
"""§6-114 活体验证：投影只铺权威接纳的东西，rebuild 真的按权威换新。

两段，各证一件事：

A. **真库只读复核**——不带隔离根，只读 `agent_workspaces/default/knowledge_graph`
   与底座库，把更正后的四维读数打出来。这一段的用途是**复核上一批自己的结论**：
   §6-106 写"清账后仍留 33 个无据孤立节点"，而"无据"当时是按"是否参与关系"判的；
   改成按"主体在不在权威里"判之后，这 33 个到底还剩几个？如果归零，那就是我上一批
   的口径错，不是数据脏——这条必须自己抓出来，不然台账里留着一句假的"残留副本"。
   全程只读：不开写事务、不 POST 任何端点。

B. **隔离根上走真 HTTP**——真 `create_app()` + `TestClient` + 真 JWT + 真投影目录，
   先塞两条无据边与两个无据节点，再 `POST …/projection/rebuild`，
   验 `pruned_edges/pruned_nodes` 真报数、四维读数归零、且有据的那条边原样在。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.projectionFollowsAuthorityLive
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

_MARKER_EDGE = "telepathizes"
_GHOST_SUBJECT = "青梧无据残留主体"


def _record(name, value):
    print("%-32s %s" % (name, value))


def _readRealLibrary() -> dict:
    """A 段：只读。连库用 mode=ro，绝不让 sqlite 顺手把文件建出来。"""
    from neurova.core.agent_workspaces import get_agent_workspaces_root
    from neurova.core.data_root import dataPath
    from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
    from neurova.knowledge.graph_bridge import projectionDrift

    # 落点一律走单源解析器：`core/data_root.py` 与 `core/agent_workspaces.py`。
    # 脚本自己拼第二份 `data/knowledge/...`，读的就可能不是生产那张库（守卫：
    # `tests/unit/ci/test_manual_live_verify_contract.py::testManualScriptsDoNotReplicateDataRootLayout`）。
    db = Path(dataPath("knowledge", "knowledge_facts.db"))
    graphDir = get_agent_workspaces_root() / "default" / "knowledge_graph"
    if not db.exists() or not graphDir.exists():
        return {"available": False}
    conn = sqlite3.connect("file:%s?mode=ro" % db.resolve().as_posix(), uri=True)
    conn.row_factory = sqlite3.Row

    class _RoStore:
        """只读垫片：`projectionDrift` 只用 `listSubjects`/`searchableFacts` 两个读面，
        这里照原样提供，写方法一律不给——避免"只读取名、实则可以写"。"""

        _lock = None

        def listSubjects(self, agentId):
            return [dict(r) for r in conn.execute(
                "SELECT * FROM knowledge_subjects WHERE agent_id = ? AND merged_into IS NULL",
                (agentId,))]

        def searchableFacts(self, agentId=None, includeNarratives=False):
            # 读侧兜底口径照抄生产 `searchableFacts`（status 权威 + 时效兜底 +
            # 排除叙述行），少一条就是与生产不同的一份判据
            sql = ("SELECT f.*, s.canonical_label FROM knowledge_facts f"
                   " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
                   " WHERE f.status = 'active' AND s.status != 'merged'"
                   " AND (f.valid_until IS NULL OR f.valid_until > ?)"
                   " AND f.record_kind != 'narrative'")
            args = [__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat()]
            if agentId:
                sql += " AND f.agent_id = ?"
                args.append(agentId)
            return [dict(r) for r in conn.execute(sql + " ORDER BY f.fact_id", args)]

    graph = KnowledgeGraphManager(storage_dir=str(graphDir), auto_save=False)
    drift = projectionDrift("default", graph, _RoStore())
    return {"available": True,
            "orphan": len(drift["orphan_relations"]),
            "missing": len(drift["missing_relations"]),
            "unbacked_nodes": len(drift["unbacked_nodes"]),
            "unbacked_with_body": drift["unbacked_nodes_with_body"],
            "isolated_nodes": len(drift["isolated_nodes"]),
            "projection_nodes": drift["projection_nodes"],
            "authority_nodes": drift["authority_nodes"]}


def main() -> int:
    print("── A 段：真库只读复核 §6-106 那句\"33 个无据节点\" ──")
    real = _readRealLibrary()
    if not real.get("available"):
        _record("真库", "不可用（跳过 A 段，B 段照跑）")
    else:
        for k in ("orphan", "missing", "unbacked_nodes", "unbacked_with_body",
                  "isolated_nodes", "projection_nodes", "authority_nodes"):
            _record("真库 " + k, real[k])
        if real["unbacked_nodes"] == 0 and real["isolated_nodes"] > 0:
            print("  → 更正成立：上一批报的\"33 个无据节点\"里，按点据（主体在权威）判"
                  "无一个是无据的，它们是**有类型没连边**的合法实体。")
        elif real["unbacked_nodes"] > 0:
            print("  → 仍有真无据节点 %d 个，rebuild 该摘它们。" % real["unbacked_nodes"])

    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    # 单点一次隔干净两根（数据根 + agent 工作区根，台账 §6-308 的 D8）——
    # 这里不再 setdefault 第二份落点，取根一律走生产单源解析器。
    isolatedDataRoot()
    from neurova.core.agent_workspaces import get_agent_workspaces_root

    graphDir = get_agent_workspaces_root() / "default" / "knowledge_graph"
    graphDir.mkdir(parents=True, exist_ok=True)

    def node(nid, label, body=None):
        return {"node_id": nid, "label": label, "node_type": "concept",
                "properties": ({"description": body} if body else {}), "aliases": [],
                "tags": [], "weight": 1.0, "created_at": 0, "updated_at": 0,
                "metadata": {}}

    (graphDir / "nodes.json").write_text(json.dumps(
        [node("a", "青梧甲"), node("b", "青梧乙"),
         node("g1", _GHOST_SUBJECT, "条目正文摘要残留"),
         node("g2", _GHOST_SUBJECT + "2")], ensure_ascii=False), encoding="utf-8")
    (graphDir / "edges.json").write_text(json.dumps(
        [{"edge_id": "e1", "source_id": "a", "target_id": "b", "relation_type": "part_of",
          "weight": 1.0, "properties": {}, "metadata": {}, "created_at": 0, "updated_at": 0},
         {"edge_id": "e2", "source_id": "g1", "target_id": "g2",
          "relation_type": _MARKER_EDGE, "weight": 1.0, "properties": {}, "metadata": {},
          "created_at": 0, "updated_at": 0}], ensure_ascii=False), encoding="utf-8")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

    store = get_knowledge_fact_store()
    gate = productionAdmissionGate(store, toolVersion="live")
    for subject, predicate, obj in (("青梧甲", "is_a", "文档集合"),
                                    ("青梧乙", "is_a", "文档集合"),
                                    ("青梧甲", "part_of", "青梧乙")):
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=predicate,
            objectTerm=obj, content="%s %s %s" % (subject, predicate, obj),
            activityKind="extract", activityBasis="projectionFollowsAuthorityLive",
            assertions=[{"actorType": "pipeline", "actorId": "live",
                         "mediumRef": "live:pfa", "statementText": obj}]))

    from neurova.cognitive_layers.knowledge_graph.manager import (
        reset_agent_knowledge_graph_managers,
    )
    reset_agent_knowledge_graph_managers()

    base = "/api/v1/knowledge-graph/default/knowledge-graph"
    token = create_access_token({"user_id": "root", "username": "root",
                                 "role": "admin", "sub": "root"})
    print("── B 段：隔离根 + 真 HTTP ──")
    with TestClient(create_app(), headers={"Authorization": "Bearer %s" % token}) as client:
        before = client.get(base + "/authority-drift").json()["data"]
        _record("重建前 四维", {"orphan": len(before["orphan_relations"]),
                                "unbacked": len(before["unbacked_nodes"]),
                                "with_body": before["unbacked_nodes_with_body"],
                                "isolated": len(before["isolated_nodes"])})
        resp = client.post(base + "/projection/rebuild")
        data = resp.json().get("data") or {}
        _record("POST rebuild", (resp.status_code, "pruned_edges=", data.get("pruned_edges"),
                                 "pruned_nodes=", data.get("pruned_nodes")))
        after = client.get(base + "/authority-drift").json()["data"]
        _record("重建后 四维", {"orphan": len(after["orphan_relations"]),
                                "missing": len(after["missing_relations"]),
                                "unbacked": len(after["unbacked_nodes"]),
                                "isolated": len(after["isolated_nodes"])})
        labels = sorted(json.loads((graphDir / "nodes.json").read_text(encoding="utf-8"))
                        and [n["label"] for n in json.loads(
                            (graphDir / "nodes.json").read_text(encoding="utf-8"))])
        _record("磁盘上剩下的节点", labels)

    bad = []
    if len(before["orphan_relations"]) != 1 or len(before["unbacked_nodes"]) != 2:
        bad.append("重建前两维读数不对（无据边应 1、无据点应 2）：%s" % before)
    if resp.status_code != 200 or data.get("pruned_edges") != 1 or data.get("pruned_nodes") != 2:
        bad.append("rebuild 没按权威换新或没报 pruning 读数：%s" % data)
    if after["orphan_relations"] or after["missing_relations"] or after["unbacked_nodes"]:
        bad.append("重建后四维未归零：%s" % after)
    if _GHOST_SUBJECT not in "".join(labels) and "青梧甲" not in labels:
        bad.append("有据节点也被摘了（过修）：%s" % labels)
    if "青梧甲" not in labels or _GHOST_SUBJECT in labels:
        bad.append("该留的没留 / 该摘的没摘：%s" % labels)
    if bad:
        print("FAIL " + "；".join(bad))
        return 1
    print("LIVE-PASS 无据边与无据点被按权威摘净并有数可报，有据的那条边与两端原样留着")
    return 0


if __name__ == "__main__":
    sys.exit(main())
