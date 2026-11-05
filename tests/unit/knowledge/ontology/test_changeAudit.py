# -*- coding: utf-8 -*-
"""B12 L8 变更审计（升级计划 §12.9）：本体写面落 change_log，只追加。"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.change_log import ChangeLog


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


class TestChangeAudit:
    def test_appendIsOnlyGrowing(self, store):
        log = ChangeLog(store)
        log.append(tenantId="default", actor="admin", action="create",
                   targetType="term", targetId="part_of",
                   beforeJson={}, afterJson={"kind": "relation"})
        log.append(tenantId="default", actor="admin", action="update",
                   targetType="term", targetId="part_of",
                   beforeJson={"label": "属于"}, afterJson={"label": "属于关系"})

        entries = log.list(tenantId="default")
        assert len(entries) == 2
        assert entries[0]["created_at"] <= entries[1]["created_at"]

    def test_noDeleteApiExists(self):
        assert not hasattr(ChangeLog, "delete"), "审计账不提供删除"
        assert not hasattr(ChangeLog, "purge"), "审计账不提供清空"
