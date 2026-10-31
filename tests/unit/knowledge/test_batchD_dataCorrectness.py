# -*- coding: utf-8 -*-
"""批 D 数据正确性（specs/2026-10-31-full-repo-defect-sweep-fixplan.md 批 D）。

D1：supersede_old 漏 `_save()`——重启水合后人工裁决被静默反转。
D2：admission 内容去重漏传 tenantId——跨租户折叠。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.repository import KnowledgeRepository


def test_d1_supersede_old_survives_restart(tmp_path):
    """裁决 supersede_old 后重新水合：旧条目不得再出现在检索/清单里。"""
    repo1 = KnowledgeRepository(tmp_path)
    old = repo1.create_knowledge("default", title="旧版知识", content="旧内容甲")
    repo1.create_knowledge("default", title="旧版知识", content="新内容乙")
    conflict = repo1.list_conflicts()[0]
    assert repo1.resolve_conflict(
        conflict["conflict_id"], "supersede_old", resolved_by="admin"
    ) is True

    repo2 = KnowledgeRepository(tmp_path)  # 重启水合
    visible_ids = [
        it.get("knowledge_id") for it in repo2.list_knowledge("default", limit=100)
    ]
    assert old["knowledge_id"] not in visible_ids, (
        "重启后已被裁决出列的旧条目不得复活（修前 _save 漏调，水合反转裁决）"
    )


def test_d2_admission_content_dedup_is_tenant_scoped(tmp_path):
    """同内容跨租户各建各的行：B 租户可见自己的事实，A/B 互不串。"""
    from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    ledger = productionAdmissionGate(store)

    def _admit(tenant: str, content: str) -> str:
        return ledger.admit(AdmissionRequest(
            agentId="a1", subjectLabel="口径条目", predicateTermId="describes",
            objectTerm=content, content=content,
            assertions=[{"actorType": "user", "actorId": "u1",
                         "mediumRef": "manual:t", "statementText": content}],
            tenantId=tenant,
        )).factId

    fact_t1 = _admit("t1", "同内容事实")
    fact_t2 = _admit("t2", "同内容事实")
    assert fact_t1 != fact_t2, "跨租户同内容必须各建各的行（修前折回 default 租户的行）"

    t1_ids = {f["fact_id"] for f in store.searchableFacts("a1", tenantId="t1")}
    t2_ids = {f["fact_id"] for f in store.searchableFacts("a1", tenantId="t2")}
    assert fact_t1 in t1_ids and fact_t2 in t2_ids
    assert fact_t1 not in t2_ids and fact_t2 not in t1_ids
