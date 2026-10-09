# -*- coding: utf-8 -*-
"""风险 1-3 活体验证：落盘诚实、探针节点维度、启动只报不修。

跑的真生产对象：真 `create_app()` + `TestClient`（带真 lifespan，启动读数就长在那）、
真 HTTP 端点（`authority-drift` / `projection/rebuild`）、真写咽喉、真 per-agent 投影目录。
数据根与 agent 工作区都走隔离根（`isolatedDataRoot()` + `NEUROVA_AGENT_WORKSPACES_DIR`），
**不 patch `get_knowledge_fact_store`**——单测那几格是被围栏逼着注隔离实例的，
本脚本要证的正是生产默认路径上读数与回执都成立。

判据取读数：rebuild 的 `persist` 回执、drift 的四个计数、启动日志里那一行 WARN 的原文。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.projectionHonestyLive

反证：把 `app.py` 里那句 `for _d in _drift:` 改成 `for _d in []:` 再跑同一份脚本，
启动必须不再报"无据节点"——否则那行 WARN 是被别的日志蒙出来的。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.manual._liveVerifyIsolation import isolatedDataRoot

_ISOLATED_ROOT = isolatedDataRoot()   # 数据根与 agent 工作区都落在它下面，不碰仓内真库

_GHOST = "青梧无据节点"


def _record(name, value):
    print("%-30s %s" % (name, value))


def main() -> int:
    import os

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.core import agent_workspaces
    from neurova.knowledge.foundation.admission import (
        AdmissionRequest,
        productionAdmissionGate,
    )
    from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

    # agent 工作区单独指一处：`get_agent_workspaces_root()` 是调用时解析，
    # 这里注入才对到 per-agent 投影目录（与数据根同源，都在隔离根下）
    wsRoot = _ISOLATED_ROOT / "agent_workspaces"
    os.environ[agent_workspaces.AGENT_WORKSPACES_ENV] = str(wsRoot)
    graphDir = wsRoot / "default" / "knowledge_graph"
    graphDir.mkdir(parents=True, exist_ok=True)

    store = get_knowledge_fact_store()
    gate = productionAdmissionGate(store, toolVersion="live")
    for subject, predicate, obj in (("青梧乙", "is_a", "文档集合"),
                                    ("青梧甲", "part_of", "青梧乙")):
        gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=predicate,
            objectTerm=obj, content="%s %s %s" % (subject, predicate, obj),
            activityKind="extract", activityBasis="projectionHonestyLive",
            assertions=[{"actorType": "pipeline", "actorId": "live",
                         "mediumRef": "live:projection", "statementText": obj}]))

    # 手工摆一份投影：两端有据 + 3 个无据孤立节点（各带正文摘要）
    def node(nid, label, body=None):
        props = {"description": body} if body else {}
        return {"node_id": nid, "label": label, "node_type": "concept",
                "properties": props, "aliases": [], "tags": [], "weight": 1.0,
                "created_at": 0, "updated_at": 0, "metadata": {}}

    (graphDir / "nodes.json").write_text(json.dumps(
        [node("n1", "青梧甲"), node("n2", "青梧乙"),
         node("g1", _GHOST + "1", "条目正文摘要一"),
         node("g2", _GHOST + "2", "条目正文摘要二"),
         node("g3", _GHOST + "3", "条目正文摘要三")], ensure_ascii=False), encoding="utf-8")
    (graphDir / "edges.json").write_text(json.dumps(
        [{"edge_id": "e1", "source_id": "n1", "target_id": "n2",
          "relation_type": "part_of", "weight": 1.0, "properties": {}, "metadata": {},
          "created_at": 0, "updated_at": 0}], ensure_ascii=False), encoding="utf-8")

    token = create_access_token({"user_id": "root", "username": "root",
                                 "role": "admin", "sub": "root"})
    headers = {"Authorization": "Bearer %s" % token}
    base = "/api/v1/knowledge-graph/default/knowledge-graph"

    with TestClient(create_app(), headers=headers) as client:
        drifted = client.get(base + "/authority-drift").json()["data"]
        _record("漂移读数（清账前）", {k: (len(v) if isinstance(v, list) else v) for k, v in drifted.items()})
        rebuilt = client.post(base + "/projection/rebuild")
        data = rebuilt.json().get("data") or {}
        _record("POST rebuild", (rebuilt.status_code, "persist.ok=", data.get("persist", {}).get("ok"),
                                 "nodes=", data.get("nodes"), "projection_nodes=",
                                 data.get("projection_nodes")))
        after = client.get(base + "/authority-drift").json()["data"]
        _record("漂移读数（清账后）", {k: (len(v) if isinstance(v, list) else v) for k, v in after.items()})

    # 启动只报不修：全新进程再跑一次 lifespan，看 WARN 是否点名，且文件字节不变
    snapshot = {p: p.read_bytes() for p in (graphDir / "nodes.json", graphDir / "edges.json")}
    logs = []

    class _Capture:
        def __enter__(self):
            import logging

            self._handler = logging.Handler()
            self._handler.emit = lambda record: logs.append(record.getMessage())
            logging.getLogger("neurova.api.app").addHandler(self._handler)
            return self

        def __exit__(self, *exc):
            import logging

            logging.getLogger("neurova.api.app").removeHandler(self._handler)

    from neurova.api.app import create_app as _second
    with _Capture():
        with TestClient(_second()):
            pass
    warn = [m for m in logs if "投影" in m and "分叉" in m]
    _record("启动 WARN", warn[:1] or "（无）")
    for p, before in snapshot.items():
        assert p.read_bytes() == before, "启动阶段动了投影文件：只报不修被违反"
    _record("投影文件字节", "未变（只报不修成立）")

    problems = []
    if rebuilt.status_code != 200 or data.get("persist", {}).get("ok") is not True:
        problems.append("rebuild 的落盘回执不成立")
    if len(after.get("unbacked_nodes", [])) != 3:
        problems.append("清账后无据节点应为 3（rebuild 不清它们），实得 %s"
                        % len(after.get("unbacked_nodes", [])))
    if after.get("unbacked_nodes_with_body") != 3:
        problems.append("探针没数出带正文摘要的无据节点")
    if not warn:
        problems.append("启动没报分叉 WARN：那一行日志不存在，读数是空的")
    if problems:
        print("FAIL " + "；".join(problems))
        return 1
    print("LIVE-PASS 落盘有回执、探针报得出 3 个无据节点（且如实说明 rebuild 不清它们）、"
          "启动一次性点名且不动数据")
    return 0


if __name__ == "__main__":
    sys.exit(main())
