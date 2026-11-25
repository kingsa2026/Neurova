# -*- coding: utf-8 -*-
"""KNOW-09 统一事务边界判据：事实/断言/治理/叙述同库一次提交，失败整体回滚。

全部走真装配：真 SQLite（tmp_path）、真 NarrativeStore / KnowledgeFactStore /
真准入咽喉，不打桩业务对象。故障注入用系统的**真实失败源**——条目缺
knowledge_id 时叙述层 `_projectRows` 拒写（ValueError）。治理投影先于叙述
保存执行，旧代码在保存失败时必然留下已提交的事实/断言/活动半成品
（跨连接分次提交），本文件钉住"失败整体回滚、不留半成品"。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.narratives import NarrativeStore
from neurova.knowledge.repository import KnowledgeRepository

AGENT = "agent-tx"


def _activeFactCount(db_path: str) -> int:
    store = KnowledgeFactStore(db_path)
    try:
        return store.queryReadOnly(
            "SELECT COUNT(*) AS n FROM knowledge_facts WHERE status = 'active'"
        )[0]["n"]
    finally:
        store.close()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("NEUROVA_KB_NARRATIVE_STORE", raising=False)
    r = KnowledgeRepository(str(tmp_path / "kb"))
    yield r


class TestUnifiedFoundationTransaction:
    def test_create_failure_rolls_back_facts_and_narratives_together(self, repo):
        db_path = repo._narrative_db_path
        # 故障注入：坏行（缺 knowledge_id）让叙述层 _projectRows 真实拒写
        repo._items.setdefault(AGENT, []).append({"title": "坏行", "content": "x"})

        with pytest.raises(ValueError):
            repo.create_knowledge(
                agent_id=AGENT, title="新知识", content="统一事务边界判据内容",
                owner_user_id="u1",
            )

        assert NarrativeStore(db_path).count() == 0, "叙述层零落盘"
        assert _activeFactCount(db_path) == 0, \
            "治理投影不得先于叙述保存提交——失败必须整体回滚，不留半截事实"
        assert not repo._items.get(AGENT), "内存权威不得残留幽灵条目"

    def test_delete_failure_keeps_fact_and_entry_together(self, repo):
        db_path = repo._narrative_db_path
        item = repo.create_knowledge(
            agent_id=AGENT, title="待删知识", content="内容甲", owner_user_id="u1"
        )
        kid = item["knowledge_id"]
        assert _activeFactCount(db_path) == 1, "前置：条目投影出的治理行是 active"

        repo._items.setdefault(AGENT, []).append({"title": "坏行", "content": "y"})

        with pytest.raises(ValueError):
            repo.delete_knowledge(AGENT, kid)

        assert repo.get_item(AGENT, kid) is not None, "条目必须随事务回滚而保留"
        assert kid not in repo._tombstones, "墓碑不得先于叙述保存落定"
        assert _activeFactCount(db_path) == 1, "治理行不得先于叙述保存退场"
