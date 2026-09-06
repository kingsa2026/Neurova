"""认知三链路巡检 P0-3 防回归：EKB 经验的 agent 级隔离贯通。

根因：主写入路径（post_chat_pipeline._step_record_experience）不传
agent_id，检索路径（chat_pipeline._retrieve_ekb_experience /
context.injector）也不传——3913 行存量 agent_id 全 NULL，API 按 agent
过滤恒空，且 A agent 经验注入 B agent prompt（跨 agent 互串）。
"""
import pytest

from neurova.skills.experience_knowledge_base import (
    ExperienceKnowledgeBase,
    ExperienceRecord,
)


@pytest.fixture
def ekb(tmp_path):
    return ExperienceKnowledgeBase(db_path=str(tmp_path / "ekb.db"))


def _add(ekb, text, agent_id=None):
    rec = ExperienceRecord(
        skill_name="chat",
        context={"user_input": text},
        result={"reply_excerpt": "r"},
        success=True,
    )
    return ekb.add_experience_record(skill_name="chat", exp=rec, agent_id=agent_id)


def test_write_with_agent_id_is_row_visible_to_same_agent_only(ekb):
    _add(ekb, "北京天气查询", agent_id="agent-a")
    _add(ekb, "上海天气查询", agent_id="agent-b")

    hits_a = ekb.find_similar_experiences(context={"user_input": "北京天气"}, limit=5, agent_id="agent-a")
    hits_b = ekb.find_similar_experiences(context={"user_input": "上海天气"}, limit=5, agent_id="agent-b")
    assert any("北京" in str(h.get("context", {}).get("user_input", "")) for h in hits_a)
    assert all("北京" not in str(h.get("context", {}).get("user_input", "")) for h in hits_b), (
        "agent-b 的隔离检索不得命中 agent-a 的经验（跨 agent 互串）"
    )


def test_stats_scoped_by_agent(ekb):
    _add(ekb, "t1", agent_id="agent-a")
    stats_a = ekb.get_experience_stats(agent_id="agent-a")
    stats_b = ekb.get_experience_stats(agent_id="agent-b")
    assert stats_a.get("total", stats_a.get("total_records", 1)) >= 1
    assert stats_b.get("total", stats_b.get("total_records", 0)) == 0


def test_pipeline_writers_pass_agent_identity(tmp_path, monkeypatch):
    """调用方契约：写入侧必须携带 agent_id/session_id（P0-3+B5 断点在调用方）。"""
    import asyncio
    from types import SimpleNamespace

    captured = {}

    class FakeEKB:
        def add_experience_record(self, **kw):
            captured.update(kw)

    import neurova.skills.experience_knowledge_base as ekb_mod

    monkeypatch.setattr(ekb_mod, "get_experience_knowledge_base", lambda: FakeEKB())

    from neurova.post_chat_pipeline import PostChatPipeline

    pipe = PostChatPipeline.__new__(PostChatPipeline)
    pipe._step_results = []
    pipe._agent = SimpleNamespace(
        _collect_tool_messages=lambda: [],
        agent_id="audit-agent",
        session_id="sess-1",  # 真 Agent 上是 property（见 test_agent_turn_session_contract）
        _current_session_id="sess-1",
    )

    evolution = type("Evo", (), {"on_experience_recorded": lambda self, *a, **k: None})()
    monkeypatch.setattr(
        PostChatPipeline, "_get_dependency", lambda self, name: evolution if name == "evolution" else None
    )
    import neurova.evolution.evolution_facade as facade_mod

    monkeypatch.setattr(facade_mod.EvolutionFacade, "record_experience", lambda self, *a, **k: None)

    asyncio.run(pipe._step_record_experience("hello", "world", True))
    assert captured.get("agent_id") == "audit-agent", "EKB 写入必须携带 agent_id（否则前端按 agent 查恒空）"
    assert captured.get("session_id") == "sess-1", "session_id 须取 _current_session_id（B5）"
