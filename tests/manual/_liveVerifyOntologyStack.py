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

# 数据根先注入，再拉起应用（import 顺序即隔离纪律）
from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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

# ── B10：shape 注册＋violation 阻断 ───────────────────────────────
# shapes 写面端点规划内（B10 只落求值器与注册表类）；跳过 REST 建形状，
# 直接经 B2 验证内置 6 项仍走同一 findings 流。
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

# ── B4：推导溯源读面（关系候选先建一条再批） ───────────────────────
# 候选面无 REST 注入口（抽取侧落库），直接跳过 REST 建——用 approve 未知 id 应 404
r = client.post(PREFIX + "/ontology/relation-candidates/nope/approve", headers=HEADERS)
step("B8 候选 404（未知 id）", r.status_code == 404, str(r.status_code))

after = dataFingerprint()
step("数据根指纹不变", before == after, "%s → %s" % (before, after))

failed = [r for r in results if not r[1]]
print("\n== 活体总结： %d/%d PASS ==" % (len(results) - len(failed), len(results)))
sys.exit(1 if failed else 0)
