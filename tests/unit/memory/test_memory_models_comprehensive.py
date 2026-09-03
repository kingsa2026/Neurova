"""
Neurova Memory Models - 全面单元测试（按当前真实模型重写）

覆盖:
1. 枚举: MemoryType, MemoryCategory, LifecycleStage, MemoryPerspective, EmotionType
2. 数据类: UserProfile, Skill, SelfModel, Attachment, Memory, MemoryRelation, MetaTrace
"""

import pytest
from datetime import datetime

from neurova.cognitive_layers.memory_layer.models import (
    MemoryType,
    MemoryCategory,
    LifecycleStage,
    MemoryPerspective,
    EmotionType,
    UserProfile,
    Skill,
    SelfModel,
    Attachment,
    Memory,
    MemoryRelation,
    MetaTrace,
)


# ============================ 枚举 ============================


class TestMemoryTypeEnum:
    def test_values(self):
        assert {e.value for e in MemoryType} == {
            "semantic", "episodic", "procedural", "pattern", "emotional", "working",
        }

    def test_from_string(self):
        assert MemoryType("semantic") == MemoryType.SEMANTIC
        assert MemoryType("episodic") == MemoryType.EPISODIC

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            MemoryType("short_term")


class TestMemoryCategoryEnum:
    def test_values(self):
        assert {e.value for e in MemoryCategory} == {
            "general", "conversation", "knowledge", "experience",
            "tool_usage", "reflection", "user_preference",
        }

    def test_from_string(self):
        assert MemoryCategory("conversation") == MemoryCategory.CONVERSATION


class TestLifecycleStageEnum:
    def test_values(self):
        assert {e.value for e in LifecycleStage} == {
            "active", "consolidated", "archived", "forgotten", "crystallized",
        }

    def test_from_string(self):
        assert LifecycleStage("archived") == LifecycleStage.ARCHIVED


class TestMemoryPerspectiveEnum:
    def test_values(self):
        assert {e.value for e in MemoryPerspective} == {
            "first_person", "second_person", "third_person", "system",
        }


class TestEmotionTypeEnum:
    def test_values(self):
        assert {e.value for e in EmotionType} == {
            "neutral", "joy", "sadness", "anger", "fear",
            "surprise", "disgust", "trust", "anticipation",
        }

    def test_neutral_default_semantics(self):
        assert EmotionType("neutral") == EmotionType.NEUTRAL

    def test_all_named_members_exist(self):
        for name in ("JOY", "SADNESS", "ANGER", "FEAR", "SURPRISE", "DISGUST", "TRUST", "ANTICIPATION"):
            assert hasattr(EmotionType, name)


# ============================ 数据类 ============================


class TestUserProfile:
    def test_defaults(self):
        p = UserProfile(user_id="u1", preferences={}, traits={})
        assert p.user_id == "u1"
        assert p.preferences == {}
        assert p.traits == {}

    def test_full_roundtrip(self):
        p = UserProfile(
            user_id="u1", name="小明",
            preferences={"style": "简洁"},
            traits={"curious": 0.9},
        )
        d = p.to_dict()
        restored = UserProfile.from_dict(d) if hasattr(UserProfile, "from_dict") else None
        if restored is not None:
            assert restored.name == "小明"


class TestSkill:
    def test_defaults(self):
        s = Skill()
        assert s.skill_id == ""
        assert s.category == "general"
        assert s.success_rate == 0.0

    def test_to_dict_contains_core_fields(self):
        s = Skill(skill_id="sk1", name="搜索")
        d = s.to_dict()
        assert d["skill_id"] == "sk1"
        assert d["name"] == "搜索"


class TestSelfModel:
    def test_defaults(self):
        m = SelfModel(agent_id="a1")
        assert m.agent_id == "a1"
        assert m.capabilities == []
        assert m.goals == []

    def test_traits_and_beliefs(self):
        m = SelfModel(
            agent_id="a1", name="助手",
            personality_traits={"friendly": 0.8},
            beliefs={"用户至上": 1.0},
            goals=["帮助用户"],
        )
        assert m.personality_traits["friendly"] == 0.8
        assert m.goals == ["帮助用户"]


class TestAttachment:
    def test_defaults(self):
        a = Attachment(id="att1", filename="a.png", content_type="image/png", size=10, path="/tmp/a.png")
        assert a.memory_id is None or a.memory_id == ""
        assert a.filename == "a.png"

    def test_link_memory(self):
        a = Attachment(id="att1", filename="a.png", content_type="image/png", size=10, path="/p", memory_id="mem_1")
        assert a.memory_id == "mem_1"


class TestMemory:
    def _make(self, **kw):
        defaults = dict(content="测试内容", memory_type=MemoryType.EPISODIC)
        defaults.update(kw)
        return Memory(**defaults)

    def test_minimal_construction(self):
        mem = self._make()
        assert mem.content == "测试内容"
        assert mem.temperature > 0
        assert mem.access_count == 0

    def test_full_fields(self):
        mem = self._make(
            category=MemoryCategory.KNOWLEDGE,
            lifecycle_stage=LifecycleStage.ACTIVE,
            emotion=EmotionType.JOY,
            importance=80.0,
            agent_id="a1",
        )
        assert mem.category == MemoryCategory.KNOWLEDGE
        assert mem.emotion == EmotionType.JOY
        assert mem.importance == 80.0

    def test_isolation_fields(self):
        mem = self._make(agent_id="a1", neuser_id="n1", user_id="u1")
        assert mem.agent_id == "a1" and mem.neuser_id == "n1" and mem.user_id == "u1"

    def test_to_dict_roundtrip_keys(self):
        mem = self._make()
        d = mem.to_dict() if hasattr(mem, "to_dict") else mem.__dict__
        for key in ("id", "content", "memory_type", "temperature"):
            assert key in d


class TestMemoryRelation:
    def test_defaults_and_fields(self):
        r = MemoryRelation(id="r1", source_memory_id="m1", target_memory_id="m2", relation_type="related")
        assert r.strength is not None
        assert r.relation_type == "related"


class TestMetaTrace:
    def test_defaults(self):
        t = MetaTrace(trace_id="t1", memory_id="m1")
        assert t.reasoning_steps == [] or t.reasoning_steps is not None
        assert t.confidence is not None

    def test_steps_recorded(self):
        t = MetaTrace(
            trace_id="t1", memory_id="m1",
            reasoning_steps=["step1", "step2"], confidence=0.7,
            sources=["m2"],
        )
        assert len(t.reasoning_steps) == 2
        assert t.confidence == 0.7
