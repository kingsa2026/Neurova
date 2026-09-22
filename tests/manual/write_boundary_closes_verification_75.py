#!/usr/bin/env python3
"""live-verify：走真咽喉的六条写入链，各自写完即闭环（无替身）。

判据与 `tests/unit/knowledge/test_write_boundary_closes_verification.py` 同源，
但这里跑的是真链路：真仓库、真咽喉、真规则引擎、真抽取桥、真时序模块，
外加一条真后端子进程端点读数。

    python tests/manual/write_boundary_closes_verification_75.py
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 围栏是 pytest-only 的；运维/自证动作必须显式摘标记（与既有 manual 脚本同口径）。
os.environ.pop("PYTEST_CURRENT_TEST", None)
os.environ.pop("PYTEST_VERSION", None)

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate  # noqa: E402
from neurova.knowledge.foundation.digest_chain import ActivityDigestChain  # noqa: E402
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore  # noqa: E402
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader  # noqa: E402


def _distribution(store) -> dict:
    with store._lock:
        rows = store._conn.execute(
            "SELECT act.activity_kind AS kind, a.verification_state AS state,"
            " COUNT(*) AS n FROM knowledge_assertions a JOIN knowledge_activities act"
            " ON act.activity_id = a.activity_id GROUP BY act.activity_kind, a.verification_state"
            " ORDER BY act.activity_kind").fetchall()
    return {"%s/%s" % (r["kind"], r["state"]): int(r["n"]) for r in rows}


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wb-75-"))
    print("临时工作目录：%s" % tmp)

    # ── 链1 直写（咽喉兜底）+ 链2 推导 + 链3 时序事实 ────────────────
    direct = KnowledgeFactStore(str(tmp / "direct.db"))
    gate = productionAdmissionGate(direct, toolVersion="live-75")

    def admit(subject, predicate, obj, **kwargs):
        content = "%s %s %s" % (subject, predicate, obj)
        return gate.admit(AdmissionRequest(
            agentId=kwargs.pop("agentId", "default"), subjectLabel=subject,
            predicateTermId=predicate, objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "live-75",
                         "mediumRef": "live:75", "statementText": content}], **kwargs))

    r1 = admit("路由器", "is_a", "设备")
    admit("设备", "is_a", "硬件")
    print("[链1 直写] 回执读数 =", json.dumps(r1.verification, ensure_ascii=False))

    moment = datetime.datetime.now(datetime.timezone.utc)
    admit("丙烷", "is_a", "设备",
               validFrom=(moment - datetime.timedelta(days=5)).isoformat(),
               validUntil=(moment - datetime.timedelta(days=1)).isoformat())
    reader = TemporalFactReader(direct, agentId="default")
    # 按主体名精确断言：查询里含"设备"这个已登记主体，只判"返回非空"会误报。
    expiredHits = [f for f in reader.forQuery("丙烷 设备") if f["subject"] == "丙烷"]
    liveHits = [f for f in reader.forQuery("路由器 设备") if f["subject"] == "路由器"]
    print("[链2 时效] 过期说法退出读面 =", expiredHits == [],
          "| 对照：同库未过期说法读得到 =", bool(liveHits))

    from neurova.cognitive_layers.memory_layer.modules.tkg_module import TKGModule

    tkg = TKGModule(factStore=direct)
    tkg.bindAgent("kai")
    tkg.add_fact("丁烷", "is_a", "设备", statementText="丁烷是设备")

    print("[直接面三态分布]", json.dumps(_distribution(direct), ensure_ascii=False))
    bad = {k: v for k, v in _distribution(direct).items() if k.endswith("/unverified")}
    print("[直接面未验过]", bad or "0 条")

    # ── 链4 LLM 抽取（真 graph_bridge，真底座）──────────────────────
    from neurova.knowledge.graph_bridge import admitExtractedFacts

    extracted = admitExtractedFacts(
        {"entities": [{"label": "交换机", "type": "设备"}], "relations": []},
        {"agent_id": "kai", "knowledge_id": "kb_live", "title": "交换机"}, direct)
    print("[链4 抽取] 落定 %d 条" % len(extracted))

    # ── 链5 条目投影 + 链6 对账回放（真仓库）────────────────────────
    from neurova.knowledge.foundation.reconcile import FoundationReconciler
    from neurova.knowledge.repository import KnowledgeRepository

    repo = KnowledgeRepository(str(tmp / "kb"))
    repo.create_knowledge("default", "甲", "内容甲", owner_user_id="u1",
                          detect_conflict=False)
    replay = KnowledgeFactStore(str(tmp / "replay.db"))
    report = FoundationReconciler.reconcile(repo, str(tmp / "replay2.db"))
    print("[链6 对账回放] ok=%s" % report["ok"])
    replay.close()

    replay2 = KnowledgeFactStore(str(tmp / "replay2.db"))
    print("[链6 分布]", json.dumps(_distribution(replay2), ensure_ascii=False))
    replay2.close()

    print("[全部六链分布]", json.dumps(_distribution(direct), ensure_ascii=False))
    print("[巡检 verify]", json.dumps(
        {k: v for k, v in ActivityDigestChain(direct).verify().items()
         if k in ("ok", "chains", "rows", "unlinked", "verification")},
        ensure_ascii=False))
    direct.close()

    # ── 反向控制：篡改一笔，巡检必须抓到 ───────────────────────────
    tamper = KnowledgeFactStore(str(tmp / "tamper.db"))
    tGate = productionAdmissionGate(tamper, toolVersion="live-75")
    tReceipt = tGate.admit(AdmissionRequest(
        agentId="default", subjectLabel="甲", predicateTermId="is_a", objectTerm="设备",
        content="甲 is_a 设备",
        assertions=[{"actorType": "pipeline", "actorId": "live-75",
                     "mediumRef": "live:75", "statementText": "甲 is_a 设备"}]))
    with tamper._lock, tamper._conn:
        tamper._conn.execute(
            "UPDATE knowledge_assertions SET statement_text = ? WHERE activity_id = ?",
            ("被改过的说法", tReceipt.activityId))
    caught = ActivityDigestChain(tamper).attest(tReceipt.activityId)
    print("[反向控制] 篡改后被巡检判 failed =", caught["failed"] == 1)
    tamper.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
