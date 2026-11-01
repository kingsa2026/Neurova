# -*- coding: utf-8 -*-
"""W1/W2/W4 的 live-verify（specs/2026-10-30 §7；探针即用即删）。

跑的真生产对象：真 `create_app()`/lifespan（真仓储 + 真底座库，数据根走
`isolatedDataRoot()` 单点）、真知识条目/本体实例/候选别名审批三个 HTTP 面
（`X-Service-Token` 管理员通道）、真默认 Agent（app 装配的同一个）上的真
`ChatPipeline._step_retrieve_and_build_context`（真 MemoryRetrievalChain → 真
KnowledgeRetrieverAdapter → 真 hybrid），真 context orchestrator（只包一层
记录壳，不换实现）。

时序为什么是这样：0 命中捕获只认"真检索脱靶"，而语料非空时向量路会把唯一
条目顶进结果——所以两条候选全部在空库阶段捕获，再走审批/否决与建条目。

如实记一句：本探针证「真检索脱靶 → 候选捕获 → 真审批端点 → 复测命中 →
同名多口径载荷与注入指引」这段真链在路上；**不证** LLM 生成段（那要真模型
凭据，与本升级判据无关），也不证 SSE 传输层（与 batch D / W5 探针同形）。

一条命令复现：
  PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/liveVerify_kbW1W2W4.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()


def applyVerifyEnv() -> dict:
    """注入本探针需要的 env；由 main() 在任何 neurova 导入之前调用。

    不在模块顶层直接写 `os.environ`：被 pytest 导入时会把变量带进整个跑测
    进程（`tests/unit/ci/test_manualScriptsEnvMutationRatchet.py` 的冻结基线
    就是钉这件事）。
    """
    os.environ["NEUROVA_SERVICE_TOKEN"] = "liveverify-kb-w124-token"
    os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "liveverify_kb_w124_secret_0123456789")
    # 三个升级开关全开（真链取 on 档行为；off/shadow 档的行为由单测钉住）
    os.environ["NEUROVA_KB_QUERY_NORMALIZE"] = "on"
    os.environ["NEUROVA_KB_MISS_CAPTURE"] = "on"
    os.environ["NEUROVA_KB_AMBIGUITY_CLARIFY"] = "on"
    return {"X-Service-Token": os.environ["NEUROVA_SERVICE_TOKEN"]}


AGENT = "default"
KB = "/api/v1/knowledge"

failures: list = []


def check(name: str, condition: bool, detail: str = "") -> None:
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
    if not condition:
        failures.append(name)


def metricsDelta(before: dict, after: dict) -> dict:
    out = {}
    for key in ("requests", "hits", "empty"):
        out[key] = after.get(key, 0) - before.get(key, 0)
    qn_after = after.get("query_normalization") or {}
    qn_before = before.get("query_normalization") or {}
    out["qn_retrievals"] = qn_after.get("retrievals", 0) - qn_before.get("retrievals", 0)
    out["qn_with_matches"] = qn_after.get("with_matches", 0) - qn_before.get("with_matches", 0)
    return out


def main() -> int:
    token = applyVerifyEnv()
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.knowledge.retrieval_metrics import get_retrieval_metrics

    with TestClient(create_app()) as client:
        # ── 真生产 agent：app lifespan 装配的同一位 ──────────────────
        from neurova.agent.chat_pipeline import ChatPipeline
        from neurova.api import endpoints as ep
        from neurova.api.endpoints import DEFAULT_AGENT_ID

        state = ep.get_app_state()
        agent = (state.get("agents") or {}).get(DEFAULT_AGENT_ID)
        check("真默认 agent 已由 lifespan 装配", agent is not None)
        pipeline = ChatPipeline(agent)

        # 真 orchestrator + 记录壳（挂 agent 侧——pipeline 的 property 无 setter）
        recordedBuilds: list = []
        orch = agent.context_orchestrator
        originalBuild = orch.build_context

        def spyingBuild(*args, **kwargs):
            recordedBuilds.append(kwargs)
            return originalBuild(*args, **kwargs)

        orch.build_context = spyingBuild

        def retrievalTurn(query: str) -> dict:
            """真检索步（真链第 2 步，LLM 之前的全部生产对象）。"""
            from neurova.agent.chat_pipeline import ChatContext

            before = get_retrieval_metrics().snapshot()
            recordedBuilds.clear()
            ctx = ChatContext(
                user_input=query, session_id="liveverify-kb-w124",
                metadata={"user_id": "system", "role": "admin", "tenant_id": "default"},
                save_memory=False,
            )
            asyncio.run(pipeline._step_retrieve_and_build_context(ctx))
            delta = metricsDelta(before, get_retrieval_metrics().snapshot())
            return {
                "delta": delta,
                "memories": list(ctx.relevant_memories or []),
                "ambiguity": (ctx.metadata or {}).get("knowledge_ambiguity"),
                "guidance_kwargs": dict(recordedBuilds[-1]) if recordedBuilds else {},
            }

        def pendingCandidates() -> list:
            resp = client.get(f"{KB}/alias-candidates?status=pending", headers=token)
            return (resp.json().get("data") or {}).get("items") or []

        # ── [1] 空库阶段：真检索脱靶 → 两条候选捕获（真链 0 命中分支）──
        turn0 = retrievalTurn("跑量")
        check("空库检索真脱靶（跑量）", turn0["delta"]["hits"] == 0, str(turn0["delta"]))
        retrievalTurn("没人认领的黑话查询")
        rows = pendingCandidates()
        candRun = next((r for r in rows if r.get("raw_query") == "跑量"), None)
        candRej = next((r for r in rows if r.get("raw_query") == "没人认领的黑话查询"), None)
        check("脱靶查询被真捕获为 pending 候选（两条）",
              candRun is not None and candRej is not None,
              json.dumps(rows, ensure_ascii=False)[:220])

        # ── [2] 真本体写面：登记两个主体（真 admission 咽喉）─────────────
        # 消解是宁合勿分：别名「跑量」一旦挂在甲主体上，再经咽喉建同名主体会被
        # 消解进甲主体（exact 命中即归并）——所以两个主体都必须在审批之前建好。
        schema = client.get(f"{KB}/ontology/schema", headers=token)
        check("本体 schema 读面 200", schema.status_code == 200, str(schema.status_code))
        terms = (schema.json().get("data") or {}).get("terms") or []
        relTerms = [t for t in terms if str(t.get("kind")) == "relation"]
        predicate = str(relTerms[0]["term_id"]) if relTerms else ""
        check("schema 关系谓词可读", bool(predicate), f"{len(relTerms)} 个")

        def createSubject(label: str) -> dict:
            r = client.post(f"{KB}/graph/instances", headers=token, json={
                "agent_id": AGENT, "subject_label": label,
                "predicate_term_id": predicate, "object_term": "口径说明",
                "content": f"{label} 口径说明", "evidence_text": f"{label} 口径说明",
            })
            check(f"主体「{label}」经真咽喉建边", r.status_code == 200, r.text[:150])
            return r.json().get("data") or {}

        subj1 = createSubject("客户流失率")
        subj2 = createSubject("跑量")

        from neurova.knowledge.foundation.knowledge_facts import get_knowledge_fact_store

        def subjectKeyOf(label: str) -> str:
            for row in get_knowledge_fact_store().listSubjects(AGENT, tenantId="default"):
                if row.get("canonical_label") == label:
                    return str(row["subject_key"])
            return ""

        key1 = subjectKeyOf("客户流失率")
        key2 = subjectKeyOf("跑量")
        check("两个主体键可读且互异", bool(key1) and bool(key2) and key1 != key2,
              f"{key1} / {key2}")

        # ── [3] W2 判据 B：真审批端点把别名「跑量」并入主体 ─────────────
        approved = client.post(
            f"{KB}/alias-candidates/{candRun['candidate_id']}/approve",
            headers=token, json={"subject_key": key1, "reason": "live-verify 审批"},
        )
        check("审批端点 200 且别名「跑量」已挂", approved.status_code == 200
              and "跑量" in str((approved.json().get("data") or {}).get("aliases")),
              approved.text[:180])

        # ── [4] 真条目 + W1 判据：同一查询复测命中（归一展开→召回）──────
        # 1 条命中即入上下文——链采纳门修后（重合按实跑查询计 + 词面重合通道
        # 独立达标，specs/2026-10-30 §11.4 根修），小语料不再被整包丢弃。
        entry = client.post(KB, headers=token, json={
            "title": "客户流失率口径说明",
            "content": "客户流失率按月统计，当前口径为百分之八，归属留存域。",
        })
        check("知识条目真建 200", entry.status_code == 200, entry.text[:120])
        data = entry.json().get("data") or entry.json()
        kid = str(data.get("knowledge_id") or "")

        turn1 = retrievalTurn("跑量")
        hitKids = [
            str(m.get("knowledge_id") or m.get("memory_id") or m.get("id") or "")
            for m in turn1["memories"]
        ]
        check("归一后同查询真命中条目", kid in hitKids,
              f"hits={hitKids} 首条载荷键={sorted((turn1['memories'][0] or {}).keys()) if turn1['memories'] else '[]'}")
        check("归一读数记 with_matches", turn1["delta"]["qn_with_matches"] == 1,
              str(turn1["delta"]))

        # ── [5] W4 判据：同一短词既是甲主体别名又是乙主体本名 → multi_subject ──
        turn3 = retrievalTurn("跑量")
        # 计算层直证：触发器与载荷在本环境的真实产出（与链路透传分开归因）
        from neurova.knowledge.ambiguity_clarification import buildAmbiguityBlock, subjectsMatchingQuery

        _store = get_knowledge_fact_store()
        _groups = subjectsMatchingQuery(_store, "跑量", AGENT, "default")
        print("  [diag] subjectsMatchingQuery:",
              [(t, [m.subjectKey for m in ms]) for t, ms in _groups])
        _direct = buildAmbiguityBlock(_store, "跑量", [], AGENT, "default")
        print("  [diag] buildAmbiguityBlock 直调:",
              json.dumps(_direct.toMetadata(), ensure_ascii=False)[:200] if _direct else None)
        amb = turn3["ambiguity"] or {}
        check("歧义载荷 multi_subject 两候选",
              amb.get("source") == "multi_subject" and len(amb.get("candidates") or []) == 2,
              json.dumps(amb, ensure_ascii=False)[:280])
        guidance = str((turn3["guidance_kwargs"] or {}).get("retrieval_guidance") or "")
        check("on 档真 build_context 收到受控指引",
              "[检索歧义]" in guidance and "2 个口径" in guidance, guidance[:180])

        # ── [6] W2 判据 C：真 reject 端点只结行不动主体 ──────────────────
        rejected = client.post(
            f"{KB}/alias-candidates/{candRej['candidate_id']}/reject",
            headers=token, json={"reason": "live-verify 否决"},
        )
        check("否决端点 200", rejected.status_code == 200, rejected.text[:150])
        stillPending = [r["raw_query"] for r in pendingCandidates()]
        check("否决后 pending 不含被拒行", "没人认领的黑话查询" not in stillPending,
              str(stillPending))

    print()
    if failures:
        print(f"live-verify 未全绿：{len(failures)} 格红 -> {failures}")
        return 1
    print("live-verify 全绿：W1 归一召回 / W2 捕获-审批-复测闭环与否决 / W4 同名多口径载荷与指引，真链在路。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
