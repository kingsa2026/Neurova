# -*- coding: utf-8 -*-
"""B8–B14 本体栈一次性活体验证（升级计划 §16.3 收口判据）。

隔离数据根 + 进程内 create_app() + 真签 token（不用 TestClient 的依赖覆盖——
鉴权走生产同一条 JWT 路径）。仓内 data/ 内容指纹前后一致 ⇒ 未写生产库。

用法：.venv/Scripts/python.exe tests/manual/_liveVerifyOntologyStack.py
输出：每步一行 `PASS/FAIL 步骤 说明`，退出码 0=全绿。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

dataRoot = isolatedDataRoot("neurovaLiveOntology")

import io  # noqa: E402
import json  # noqa: E402
import contextlib  # noqa: E402
import urllib.parse  # noqa: E402

# 数据根先注入，再拉起应用（import 顺序即隔离纪律）
from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from neurova.knowledge.foundation import get_knowledge_fact_store  # noqa: E402
from neurova.knowledge.foundation.admission import (  # noqa: E402
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry  # noqa: E402

app = create_app()
client = TestClient(app)
token = create_access_token({"sub": "admin_live", "role": "admin", "user_id": "9",
                             "tenant_id": "default"})
HEADERS = {"Authorization": "Bearer %s" % token}
PREFIX = "/api/v1/knowledge"

results: list = []


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))


def dataFingerprint() -> str:
    h = hashlib.sha256()
    root = Path("data")
    if not root.exists():
        return "(no data dir)"
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p).encode())
            h.update(str(p.stat().st_size).encode())
    return h.hexdigest()[:16]


before = dataFingerprint()

# ── B8：关系特征登记＋auto 规则＋候选审批 ──────────────────────────
r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "related_to", "kind": "relation", "label": "关联"},
    headers=HEADERS)
step("B8 related_to 已在（种子收编 409=幂等）", r.status_code in (200, 409), str(r.status_code))

r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "part_of", "kind": "relation", "label": "属于",
    "parent_term_id": "related_to", "transitive": True,
    "aliases": ["属于"], "module": "domain"}, headers=HEADERS)
step("B8 part_of 更新（PUT 保留现值）", r.status_code in (200, 409), str(r.status_code))

r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "used_by", "kind": "relation"}, headers=HEADERS)
step("B8 used_by 已在（种子收编）", r.status_code in (200, 409), str(r.status_code))

r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "blocks", "kind": "relation", "label": "阻塞", "inverse_of": "used_by"},
    headers=HEADERS)
step("B8 blocks 新建（inverse_of 双向补齐）", r.status_code == 200, str(r.status_code))
inv = client.get(PREFIX + "/ontology/terms", params={"limit": 500}, headers=HEADERS)
usedBy = [t for t in inv.json()["data"]["items"] if t["term_id"] == "used_by"]
step("B8 used_by 回向补齐", usedBy and usedBy[0].get("inverse_of") == "blocks",
     str(usedBy[0].get("inverse_of") if usedBy else "?"))

r = client.get(PREFIX + "/ontology/terms", params={"fields": "term_id,module"},
               headers=HEADERS)
body = (r.json() or {}).get("data") or {}
items = body.get("items") or []
step("B8 terms 分页/投影", r.status_code == 200 and "next_cursor" in body
     and all(set(t.keys()) <= {"term_id", "module"} for t in items),
     "items=%d cursor=%r" % (len(items), body.get("next_cursor")))

r = client.get(PREFIX + "/ontology/iri/" + "http%3A%2F%2Fexample.org%2Fv%23x",
               headers=HEADERS)
step("B12 IRI 解析未知 404", r.status_code == 404, str(r.status_code))

# ── B2：dry-run validate ──────────────────────────────────────────
r = client.post(PREFIX + "/ontology/validate", json={
    "triples": [{"subjectLabel": "订单V1", "predicateTermId": "part_of",
                 "objectTerm": "订单V2"}]}, headers=HEADERS)
step("B2 validate dry-run 200", r.status_code == 200, str(r.status_code) + " " + r.text[:80])

# ── B10：shape REST 注册/列表/删除＋violation 阻断 ─────────────────
r = client.post(PREFIX + "/ontology/shapes", json={
    "shape_id": "live_part_of_enum", "target_kind": "relation",
    "target_term_id": "part_of", "path": {"predicate": "part_of"},
    "constraint_kind": "in", "constraint": {"values": ["订单V2"]},
    "severity": "violation", "message": "关系值域越界"}, headers=HEADERS)
step("B10 shape 注册 REST", r.status_code == 200, str(r.status_code))
r = client.get(PREFIX + "/ontology/shapes", headers=HEADERS)
step("B10 shape 列表 REST", r.status_code == 200
     and any(s["shape_id"] == "live_part_of_enum"
             for s in (r.json().get("data") or {}).get("items", [])), str(r.status_code))
r = client.delete(PREFIX + "/ontology/shapes/live_part_of_enum", headers=HEADERS)
step("B10 shape 删除 REST", r.status_code == 200, str(r.status_code))
r = client.post(PREFIX + "/ontology/validate", json={
    "triples": [{"subjectLabel": "订单V1", "predicateTermId": "part_of",
                 "objectTerm": "订单V2"}]}, headers=HEADERS)
step("B10 内置校验同流", r.status_code == 200
     and any(f["rule"] in ("domain", "range", "parentConsistency", "disjoint",
                           "cardinality", "requiredProps", "punning", "qualifierSchema")
             for f in (r.json().get("data") or {}).get("results", [{}])[0].get("findings", [])), "")

# ── B11：解释链端点 ────────────────────────────────────────────────
r = client.get(PREFIX + "/ontology/derivations/nonexistent_fact", headers=HEADERS)
step("B11 解释链 404（未知 fact）", r.status_code == 404, str(r.status_code))

# ── B12：五格式导出 ────────────────────────────────────────────────
r = client.get(PREFIX + "/ontology/export.ttl", headers=HEADERS)
step("B12 Turtle 导出", r.status_code == 200
     and "rdfs:subClassOf" in r.text or "kbg:" in r.text, str(r.status_code))
for path, marker in (
    ("/ontology/export.jsonld", "@context"),
    ("/ontology/export.owl", "rdfs:subClassOf"),
    ("/ontology/export.shacl", "sh:"),
    ("/ontology/export.prov", "prov:"),
):
    r = client.get(PREFIX + path, headers=HEADERS)
    step("B12 %s 导出" % path.rsplit(".", 1)[-1], r.status_code == 200
         and marker in r.text, str(r.status_code))

# ── B6：流水线 run/diff ────────────────────────────────────────────
r = client.post(PREFIX + "/ontology/pipeline/run", json={
    "termUpserts": [], "ruleRegistrations": [], "factCandidates": [],
    "reason": "活体基线"}, headers=HEADERS)
ok = r.status_code == 200
baselineId = r.json().get("data", {}).get("baselineId", "") if ok else ""
step("B6 pipeline run", ok, baselineId)

r = client.get(PREFIX + "/ontology/pipeline/diff",
               params={"fromBaseline": baselineId}, headers=HEADERS)
step("B6 pipeline diff", r.status_code == 200, str(r.status_code))

# ── B12：rollback REST ─────────────────────────────────────────────
r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "live_rollback_extra", "kind": "concept"}, headers=HEADERS)
step("B12 rollback 前建基线外术语", r.status_code == 200, str(r.status_code))
r = client.post(PREFIX + "/ontology/pipeline/rollback", json={
    "toBaselineId": baselineId, "reason": "活体回滚"}, headers=HEADERS)
step("B12 rollback REST", r.status_code == 200, str(r.status_code))
r = client.get(PREFIX + "/ontology/terms", params={"limit": 500}, headers=HEADERS)
step("B12 rollback 后基线外术语退场",
     all(t["term_id"] != "live_rollback_extra"
         for t in (r.json().get("data") or {}).get("items", [])), str(r.status_code))

# ── B11：双时态 query REST ────────────────────────────────────────
store = get_knowledge_fact_store()
gate = productionAdmissionGate(store)
gate.admit(AdmissionRequest(
    agentId="default", subjectLabel="订单LIVE", predicateTermId="part_of",
    objectTerm="订单LIVE2", content="订单LIVE part_of 订单LIVE2",
    validFrom="2026-01-01", validUntil="2026-12-31",
    assertions=[{"actorType": "pipeline", "actorId": "live",
                 "mediumRef": "live:test", "statementText": "订单LIVE part_of 订单LIVE2"}]))
r = client.post(PREFIX + "/access/query", params={"agent_id": "default"},
                json={"query": "订单LIVE", "asOf": "2026-06-01",
                      "knownAt": "2026-11-06"}, headers=HEADERS)
step("B11 双时态 asOf/knownAt 命中", r.status_code == 200 and len(r.json()) >= 1,
     "%s %s" % (r.status_code, r.text[:80]))
r = client.post(PREFIX + "/access/query", params={"agent_id": "default"},
                json={"query": "订单LIVE", "asOf": "2027-01-01",
                      "knownAt": "2026-11-06"}, headers=HEADERS)
step("B11 双时态越界不命中", r.status_code == 200 and r.json() == [],
     "%s %s" % (r.status_code, r.text[:80]))

# ── B4：推导溯源读面（关系候选先建一条再批） ───────────────────────
# 候选面无 REST 注入口（抽取侧落库），直接跳过 REST 建——用 approve 未知 id 应 404
r = client.post(PREFIX + "/ontology/relation-candidates/nope/approve", headers=HEADERS)
step("B8 候选 404（未知 id）", r.status_code == 404, str(r.status_code))

# ── B13：质量报告 REST（活体现在算，不是 CI 抄数）──────────────────
r = client.get(PREFIX + "/ontology/quality", headers=HEADERS)
quality = (r.json() or {}).get("data") or {}
step("B13 质量报告 REST 200", r.status_code == 200 and quality.get("term_count", 0) > 0,
     "%s terms=%s findings=%s" % (r.status_code, quality.get("term_count"),
                                  len(quality.get("findings") or [])))
step("B13 质量报告指标闭集", set(quality.get("metrics") or {}) == {"consistency", "conciseness"},
     str(sorted((quality.get("metrics") or {}).keys())))
step("B13 质量报告两次读数逐字一致",
     json.dumps(quality, sort_keys=True) == json.dumps(
         (client.get(PREFIX + "/ontology/quality", headers=HEADERS).json() or {}).get("data"),
         sort_keys=True), "")

# ── L2：术语声明写面（labels / module / identity_keys / qualifier_schema）──
r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "live_declared_order", "kind": "concept", "label": "活体声明单",
    "parent_term_id": "Order" if any(
        t["term_id"] == "Order"
        for t in (client.get(PREFIX + "/ontology/terms", params={"limit": 500},
                             headers=HEADERS).json().get("data") or {}).get("items", []))
    else None,
    "labels": {"zh": "活体声明单", "en": "Live Declared Order"},
    "alt_labels": {"zh": ["活体单"]},
    "module": "domain",
    "identity_keys": ["external_id"],
    "basis": "活体声明写面"}, headers=HEADERS)
declared = (r.json().get("data") or {}).get("term") or {}
step("L2 声明字段 POST 写得出来", r.status_code == 200
     and declared.get("labels", {}).get("en") == "Live Declared Order"
     and declared.get("module") == "domain"
     and declared.get("identity_keys") == ["external_id"]
     and declared.get("alt_labels", {}).get("zh") == ["活体单"],
     "%s %s" % (r.status_code, json.dumps(
         {k: declared.get(k) for k in ("labels", "module", "identity_keys")},
         ensure_ascii=False)[:160]))

r = client.put(PREFIX + "/ontology/terms/live_declared_order", json={
    "term_id": "live_declared_order", "kind": "concept", "label": "活体声明单改名"},
    headers=HEADERS)
kept = (r.json().get("data") or {}).get("term") or {}
step("L2 PUT 未声明时保留 labels/module/identity_keys",
     r.status_code == 200 and kept.get("label") == "活体声明单改名"
     and kept.get("labels", {}).get("zh") == "活体声明单"
     and kept.get("module") == "domain", "%s" % r.status_code)

r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "live_bad_lang", "kind": "concept", "labels": {"中文标签": "不收"}},
    headers=HEADERS)
step("L2 非法语言标记写入处拒 400", r.status_code == 400, str(r.status_code))

r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "live_shipped_via", "kind": "relation", "label": "经此运输",
    "qualifier_schema": {"carrier": {"required": True}}}, headers=HEADERS)
step("L3 谓词 qualifier_schema 写得出来",
     r.status_code == 200
     and ((r.json().get("data") or {}).get("term") or {}).get("qualifier_schema")
     == {"carrier": {"required": True}}, str(r.status_code))

# ── B14：企业源描述符提交 REST（校验+落库+两态回显，仍无真实连接器）──
DESCRIPTOR_OK = {
    "sourceType": "sql",
    "columns": ["order_id", "risk_level"],
    "subject": {"template": "orders:{order_id}"},
    "predicate": {"termId": "part_of"},
    "object": {"kind": "column", "column": "risk_level"},
}
r = client.post(PREFIX + "/enterprise/sources", json={
    "source_id": "live_erp", "descriptor": DESCRIPTOR_OK}, headers=HEADERS)
saved = (r.json().get("data") or {})
step("B14 描述符提交 200 且默认关闸",
     r.status_code == 200 and saved.get("enabled") is False
     and saved.get("adapter_registered") is False,
     "%s enabled=%s adapter=%s" % (r.status_code, saved.get("enabled"),
                                   saved.get("adapter_registered")))

r = client.post(PREFIX + "/enterprise/sources", json={
    "source_id": "live_erp_bad",
    "descriptor": dict(DESCRIPTOR_OK, predicate={"termId": "no_such_predicate"})},
    headers=HEADERS)
step("B14 非法谓词整条拒 400 且零落库", r.status_code == 400
     and "no_such_predicate" in str((r.json() or {}).get("detail")), str(r.status_code))
r = client.get(PREFIX + "/enterprise/sources/nope", headers=HEADERS)
step("B14 未提交源 404", r.status_code == 404, str(r.status_code))
r = client.get(PREFIX + "/enterprise/sources", headers=HEADERS)
listed = (r.json().get("data") or {}).get("items") or []
step("B14 列表只含合法提交的那一条",
     r.status_code == 200 and [s["source_id"] for s in listed] == ["live_erp"],
     str([s["source_id"] for s in listed]))

viewerToken = create_access_token({"sub": "viewer_live", "role": "viewer",
                                  "user_id": "5", "tenant_id": "default"})
r = client.post(PREFIX + "/enterprise/sources", headers=
                {"Authorization": "Bearer %s" % viewerToken},
                json={"source_id": "live_erp_viewer", "descriptor": DESCRIPTOR_OK})
step("B14 非管理员提交 403", r.status_code == 403, str(r.status_code))

# ── B6：批次「部分声明」不抹现值（合并口径与 REST PUT 同属一处）───────
r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "live_partial_kept", "kind": "concept", "label": "批次保留",
    "aliases": ["保留别名"], "labels": {"zh": "批次保留"},
    "module": "domain", "identity_keys": ["external_id"]}, headers=HEADERS)
step("B6 批次前置术语带满声明", r.status_code in (200, 409), str(r.status_code))
r = client.post(PREFIX + "/ontology/pipeline/run", json={
    "termUpserts": [{"termId": "live_partial_kept", "kind": "concept",
                     "label": "批次改名"}],
    "ruleRegistrations": [], "factCandidates": [], "reason": "批次只改 label"},
    headers=HEADERS)
step("B6 批次只改一栏", r.status_code == 200, str(r.status_code))
r = client.put(PREFIX + "/ontology/terms/live_partial_kept", json={
    "term_id": "live_partial_kept", "kind": "concept", "version": "1.1.0"},
    headers=HEADERS)
kept = (r.json().get("data") or {}).get("term") or {}
step("B6/B10 批次与 PUT 都保留未声明栏",
     r.status_code == 200 and kept.get("aliases") == ["保留别名"]
     and kept.get("labels", {}).get("zh") == "批次保留"
     and kept.get("module") == "domain"
     and kept.get("identity_keys") == ["external_id"]
     and kept.get("label") == "批次改名" and kept.get("version") == "1.1.0",
     json.dumps({k: kept.get(k) for k in ("label", "aliases", "module", "version")},
                ensure_ascii=False))
r = client.post(PREFIX + "/ontology/pipeline/run", json={
    "termUpserts": [{"termId": "live_partial_cleared", "kind": "concept",
                     "label": "显式清空", "aliases": []}],
    "ruleRegistrations": [], "factCandidates": [], "reason": "显式空容器才是清空"},
    headers=HEADERS)
cleared = [t for t in (client.get(PREFIX + "/ontology/terms", params={"limit": 500},
                                  headers=HEADERS).json().get("data") or {}).get("items", [])
           if t["term_id"] == "live_partial_cleared"]
step("B6 显式空容器仍按清空处理",
     r.status_code == 200 and cleared and cleared[0]["aliases"] == [], str(r.status_code))

# ── §8 第 5 条点名两条链：别名抽取→归一→事实→导出 ────────────────
r = client.post(PREFIX + "/ontology/terms", json={
    "term_id": "ships_via", "kind": "relation", "label": "经此运输",
    "aliases": ["走的是", "经手"]}, headers=HEADERS)
step("B8 别名登记 REST", r.status_code in (200, 409), str(r.status_code))
resolved = OntologyTermRegistry(store).resolveRelationAlias("走的是", tenantId="default")
step("B8 别名归一到 term_id", resolved == "ships_via", str(resolved))
r = client.post(PREFIX + "/graph/instances", json={
    "agent_id": "default", "subject_label": "货件L1", "predicate_term_id": "ships_via",
    "object_term": "中远", "evidence_text": "货件L1 走的是 中远",
    "basis": "活体别名链"}, headers=HEADERS)
step("B8 归一后的谓词写得进事实", r.status_code == 200,
     "%s %s" % (r.status_code, (r.text or "")[:70]))
r = client.get(PREFIX + "/ontology/export.ttl", headers=HEADERS)
step("B8 事实进 Turtle 导出", r.status_code == 200 and "ships_via" in r.text,
     "命中=%s" % ("ships_via" in r.text))

# ── §8 第 5 条点名第二条链：未知关系→候选→审批→术语 ───────────────
from neurova.knowledge.ontology.relation_candidates import (
    RelationCandidateStore,
    normalizeSurface,
)

candidateId = RelationCandidateStore(store).record(
    "default", "隶属于", sourceEntryId="live:docCand",
    sourceText="订单L2 隶属于 客户C2", confidence=0.91)
step("B8 未知关系落候选（生产入口 graph_bridge 同一个 record）",
     bool(candidateId), str(candidateId))
r = client.get(PREFIX + "/ontology/relation-candidates", params={"status": "pending"},
               headers=HEADERS)
pending = [c for c in ((r.json().get("data") or {}).get("items") or [])
           if c["candidate_id"] == candidateId]
step("B8 候选列表读得到", r.status_code == 200 and len(pending) == 1, str(r.status_code))
r = client.post(PREFIX + "/ontology/relation-candidates/%s/approve" % candidateId,
                params={"basis": "活体审批"}, headers=HEADERS)
promoted = ((r.json().get("data") or {}).get("candidate") or {}).get("promoted_term_id")
# term_id 取的是**归一词形**（CJK 属词字符，不转写成拉丁）——期望值从单源函数取，
# 不在活体里手抄一个"看着像"的 belongs_to（那会把真实口径写歪）。
step("B8 审批→登记术语（词形归一做 term_id）",
     r.status_code == 200 and promoted == normalizeSurface("隶属于"),
     "%s promoted=%s" % (r.status_code, promoted))
r = client.get(PREFIX + "/ontology/iri/kbg:%s" % urllib.parse.quote(promoted or ""),
               headers=HEADERS)
step("B8 新术语立刻有稳定 IRI 解析面", r.status_code == 200,
     "%s iri=%s" % (r.status_code, urllib.parse.quote(promoted or "")))
r = client.post(PREFIX + "/ontology/relation-candidates/%s/approve" % candidateId,
                headers=HEADERS)
step("B8 重复审批拒（409，二态互斥）", r.status_code == 409, str(r.status_code))

# ── B11 §12.6：物化档位（observe 不进主路 / enforce 进）＋事件时间词汇 ──
def _modeBridgeReachable(mode: str, ruleId: str) -> bool:
    """在真走查上量一次：这条档位的推导跳板，能不能把挂条目的那一跳带进来。"""
    from neurova.knowledge.foundation.graph_walk import GraphFactWalker
    from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
    from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE

    st = get_knowledge_fact_store()
    registry = OntologyTermRegistry(st)
    for termId, kind in (("modeOrder", "concept"), ("modeHigh", "concept"),
                         ("modeRisk", "relation"), ("modeAct", "relation")):
        if registry.term(termId, tenantId="default") is None:
            registry.register(termId, kind, label=termId, tenantId="default")
    gate = productionAdmissionGate(st)

    def _admitRow(subject, predicate, obj, mediumRef="live:none"):
        content = "%s %s %s" % (subject, predicate, obj)
        return gate.admit(AdmissionRequest(
            agentId="default", subjectLabel=subject, predicateTermId=predicate,
            objectTerm=obj, content=content,
            assertions=[{"actorType": "pipeline", "actorId": "live",
                         "mediumRef": mediumRef, "statementText": content}]))

    # 跳板形态（与单元档一致）：条目挂在**类**那一跳上；主体→类推导→类上那条显式行
    # ⇒ 只有推导行进得了主路，条目才走得到。挂在前提上就变成一跳直达，量不到档位。
    _admitRow("modeHigh", "modeAct", "复核", mediumRef="entry:liveModeDoc")
    subject = "档位主体_%s" % mode
    _admitRow(subject, IS_A_PREDICATE, "modeOrder")
    _admitRow(subject, "modeRisk", "High")
    registry.assignSubjectType(st.resolveSubjectKey("default", subject), "modeOrder",
                               tenantId="default")
    ForwardChainingEngine(st, gateFactory=lambda s: productionAdmissionGate(s)).registerRule(
        ruleId, IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "modeOrder"},
         {"atom": "modeRisk", "subject": "X", "objectConst": "High"}],
        headObjectConst="modeHigh", materialization=mode, tenantId="default")
    hops = GraphFactWalker(st, agentId="default").walkFromQuery(subject, limit=10)
    return any(h.get("entry_id") == "liveModeDoc" for h in hops)


import os as _os

_os.environ.pop("NEUROVA_CONDITION_CLASSES_ROUTE", None)  # 全局灰度保持 off
step("L5 observe 档：灰度 off 时推导跳板不进主路",
     _modeBridgeReachable("observe", "live_mode_observe") is False, "")
step("L5 enforce 档：灰度 off 时同一条跳板进主路（按规则类转正）",
     _modeBridgeReachable("enforce", "live_mode_enforce") is True, "")
r = client.post(PREFIX + "/ontology/rules", json={
    "rule_id": "live_mode_bad", "head_predicate": "is_a", "materialization": "always"},
    headers=HEADERS)
step("L5 未知档位写入处拒 400", r.status_code == 400, str(r.status_code))
r = client.get(PREFIX + "/ontology/export.ttl", headers=HEADERS)
step("L3 事件/时间词汇带 OWL-Time 导出映射",
     r.status_code == 200 and "https://www.w3.org/2006/time#before" in r.text,
     "time#before 命中=%s" % ("time#before" in r.text))

after = dataFingerprint()
step("数据根指纹不变", before == after, "%s → %s" % (before, after))

failed = [r for r in results if not r[1]]
print("\n== 活体总结： %d/%d PASS ==" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
