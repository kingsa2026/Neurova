"""条目投影的租户分区契约（交接文档 2026-10-31 §4）。

EntryLedger 构造 AdmissionRequest 时不带 tenantId，叙述事实行恒落 default：
租户 B 的条目在治理层被记成 default 的，且同内容条目会跨租户折回同一行。
判据读的是 `knowledge_facts.tenant_id`（治理行真身），不是内存读数。
"""

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import FOUNDATION_DB_NAME
from neurova.knowledge.repository import KnowledgeRepository

ENV_FLAG = "NEUROVA_KB_NARRATIVE_STORE"
_BODY = "租户分区必须贯穿条目投影与治理行。" * 4


@pytest.fixture()
def gated(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_FLAG, "on")
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    store = KnowledgeFactStore(str(tmp_path / "kb" / FOUNDATION_DB_NAME))
    yield repo, store
    store.close()


def test_nonDefaultTenantLandsOnItsOwnGovernanceRow(gated):
    repo, store = gated
    item = repo.create_knowledge("agent-1", "租户条目", _BODY,
                                 owner_user_id="u1", tenant_id="tenant-b")

    fact = store.activeNarrativeFact("agent-1", item["knowledge_id"], tenantId="tenant-b")

    assert fact is not None, "租户 B 的条目必须有治理行"
    assert fact["tenant_id"] == "tenant-b"


def test_sameContentAcrossTenantsDoesNotShareOneRow(gated):
    repo, store = gated
    itemA = repo.create_knowledge("agent-1", "同名条目", _BODY,
                                  owner_user_id="u1", tenant_id="tenant-a")
    itemB = repo.create_knowledge("agent-1", "同名条目", _BODY,
                                  owner_user_id="u2", tenant_id="tenant-b")

    factA = store.activeNarrativeFact("agent-1", itemA["knowledge_id"], tenantId="tenant-a")
    factB = store.activeNarrativeFact("agent-1", itemB["knowledge_id"], tenantId="tenant-b")

    assert factA is not None and factB is not None
    assert factB["tenant_id"] == "tenant-b"
    assert factA["fact_id"] != factB["fact_id"], "跨租户同内容不得折回同一治理行"
