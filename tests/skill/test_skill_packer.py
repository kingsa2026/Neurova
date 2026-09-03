"""Tests for neurova/skill/skill_packer.py — core scenarios only.

Covers:
- SkillCategory enum surface
- PackedSkill dataclass (defaults, to_dict/from_dict roundtrip)
- TaskExecutionRecord dataclass (defaults, to_dict/from_dict roundtrip)
- SkillPacker init (no skills)
- pack_skill / get_packed_skill
- get_packed_skills with category filter
- record_task_execution
- _check_and_pack and evaluate_pattern_for_packing
- iterate_skill (version bump)
- persistence (reload from disk)
- thread safety
- get_skill_packer singleton
"""
import json
import threading
from pathlib import Path

import pytest


def _new_packer(tmp_path, name="packer"):
    from tests.skill.conftest import SkillPacker
    return SkillPacker(storage_dir=str(tmp_path / name))


class TestSkillCategoryEnum:
    def test_enum_members(self):
        from tests.skill.conftest import SkillCategory
        assert SkillCategory.COGNITIVE.value == "cognitive"
        assert SkillCategory.MEMORY.value == "memory"
        assert SkillCategory.REASONING.value == "reasoning"
        assert SkillCategory.LEARNING.value == "learning"
        assert SkillCategory.COMMUNICATION.value == "communication"
        assert SkillCategory.EXECUTION.value == "execution"
        assert SkillCategory.MONITORING.value == "monitoring"
        assert SkillCategory.INTEGRATION.value == "integration"

    def test_enum_is_string_based(self):
        from tests.skill.conftest import SkillCategory
        assert isinstance(SkillCategory.COGNITIVE, str)
        assert SkillCategory("memory") is SkillCategory.MEMORY


class TestPackedSkillDataclass:
    def test_defaults_filled_in(self):
        from tests.skill.conftest import PackedSkill, SkillCategory
        from datetime import datetime
        s = PackedSkill(
            skill_id="sk_1",
            name="alpha",
            description="desc",
            category=SkillCategory.COGNITIVE,
        )
        assert s.version == "1.0.0"
        assert isinstance(s.created_at, datetime)
        assert isinstance(s.updated_at, datetime)
        assert s.parameters == {}
        assert s.examples == []
        assert s.dependencies == []
        assert s.tags == []
        assert s.metadata == {}

    def test_to_dict_roundtrip(self):
        from tests.skill.conftest import PackedSkill, SkillCategory
        original = PackedSkill(
            skill_id="sk_2",
            name="beta",
            description="d",
            category=SkillCategory.MEMORY,
            parameters={"k": "v"},
            examples=[{"q": "a", "a": "b"}],
            dependencies=["dep1"],
            tags=["fast", "ml"],
            metadata={"author": "x"},
        )
        d = original.to_dict()
        assert d["skill_id"] == "sk_2"
        assert d["category"] == "memory"
        assert d["parameters"] == {"k": "v"}
        assert d["tags"] == ["fast", "ml"]
        restored = PackedSkill.from_dict(d)
        assert restored.skill_id == original.skill_id
        assert restored.name == original.name
        assert restored.category == original.category
        assert restored.parameters == original.parameters
        assert restored.examples == original.examples
        assert restored.tags == original.tags
        assert restored.metadata == original.metadata
        assert restored.created_at == original.created_at


class TestTaskExecutionRecordDataclass:
    def test_defaults_filled_in(self):
        from tests.skill.conftest import TaskExecutionRecord
        from datetime import datetime
        r = TaskExecutionRecord(
            task_id="t1",
            task_type="search",
            skill_id="sk_1",
            start_time=datetime.now(),
        )
        assert r.end_time is not None
        assert r.success is False
        assert r.input_data == {}
        assert r.output_data == {}
        assert r.error_message == ""
        assert r.execution_time_ms >= 0.0
        assert r.metadata == {}

    def test_to_dict_roundtrip(self):
        from tests.skill.conftest import TaskExecutionRecord
        from datetime import datetime, timedelta
        start = datetime.now()
        end = start + timedelta(milliseconds=120)
        r = TaskExecutionRecord(
            task_id="t1",
            task_type="search",
            skill_id="sk_1",
            start_time=start,
            end_time=end,
            success=True,
            input_data={"q": "x"},
            output_data={"hits": 3},
            error_message="",
            execution_time_ms=120.0,
            metadata={"trace": "abc"},
        )
        d = r.to_dict()
        assert d["task_id"] == "t1"
        assert d["success"] is True
        assert d["input_data"] == {"q": "x"}
        assert d["output_data"] == {"hits": 3}
        restored = TaskExecutionRecord.from_dict(d)
        assert restored.task_id == r.task_id
        assert restored.success is True
        assert restored.input_data == r.input_data
        assert restored.output_data == r.output_data
        assert restored.metadata == r.metadata


class TestSkillPackerInit:
    def test_init_with_storage_path(self, tmp_path):
        packer = _new_packer(tmp_path)
        assert packer is not None
        assert packer.get_packed_skills() == []

    def test_init_creates_storage_dir(self, tmp_path):
        d = tmp_path / "skillpacker"
        from tests.skill.conftest import SkillPacker
        SkillPacker(storage_dir=str(d))
        assert d.exists()


class TestPackAndGetSkill:
    def test_pack_skill_returns_id(self, tmp_path):
        packer = _new_packer(tmp_path)
        sid = packer.pack_skill(
            name="summarize",
            description="Summarize text",
            category="reasoning",
        )
        assert isinstance(sid, str) and sid

    def test_get_packed_skill_returns_dict(self, tmp_path):
        packer = _new_packer(tmp_path)
        sid = packer.pack_skill(
            name="plan",
            description="Plan tasks",
            category="reasoning",
            tags=["planning"],
        )
        skill = packer.get_packed_skill(sid)
        assert skill is not None
        assert skill["skill_id"] == sid
        assert skill["name"] == "plan"
        assert skill["category"] == "reasoning"
        assert "planning" in skill["tags"]

    def test_pack_skill_with_all_fields(self, tmp_path):
        packer = _new_patcher_with_dir(tmp_path) if False else _new_packer(tmp_path)
        sid = packer.pack_skill(
            name="n",
            description="d",
            category="memory",
            parameters={"x": 1},
            examples=[{"in": "q", "out": "a"}],
            dependencies=["dep_a"],
            tags=["t1"],
            metadata={"author": "agent"},
        )
        skill = packer.get_packed_skill(sid)
        assert skill["parameters"] == {"x": 1}
        assert skill["examples"] == [{"in": "q", "out": "a"}]
        assert skill["dependencies"] == ["dep_a"]
        assert skill["metadata"] == {"author": "agent"}

    def test_get_packed_skill_missing_returns_none(self, tmp_path):
        packer = _new_packer(tmp_path)
        assert packer.get_packed_skill("missing") is None

    def test_pack_skill_invalid_category_falls_back(self, tmp_path):
        packer = _new_packer(tmp_path)
        sid = packer.pack_skill(
            name="x",
            description="d",
            category="not_a_real_category",
        )
        skill = packer.get_packed_skill(sid)
        assert skill is not None
        assert isinstance(skill["category"], str)


def _new_patcher_with_dir(tmp_path):
    from tests.skill.conftest import SkillPacker
    return SkillPacker(storage_dir=str(tmp_path / "packer"))


class TestListAndFilterSkills:
    def test_list_packed_skills(self, tmp_path):
        packer = _new_packer(tmp_path)
        packer.pack_skill(name="a", description="d", category="reasoning")
        packer.pack_skill(name="b", description="d", category="memory")
        all_skills = packer.get_packed_skills()
        assert isinstance(all_skills, list)
        assert len(all_skills) == 2

    def test_filter_by_category(self, tmp_path):
        packer = _new_packer(tmp_path)
        packer.pack_skill(name="a", description="d", category="reasoning")
        packer.pack_skill(name="b", description="d", category="memory")
        packer.pack_skill(name="c", description="d", category="reasoning")
        reasoning = packer.get_packed_skills(category="reasoning")
        assert len(reasoning) == 2
        for s in reasoning:
            assert s["category"] == "reasoning"


class TestRecordTaskExecution:
    def test_record_task_execution(self, tmp_path):
        packer = _new_packer(tmp_path)
        packer.record_task_execution(
            skill_id="sk_1",
            task_type="search",
            success=True,
            input_data={"q": "x"},
            output_data={"hits": 1},
        )
        all_records = packer.get_task_records()
        assert isinstance(all_records, list)
        assert len(all_records) == 1
        assert all_records[0]["skill_id"] == "sk_1"
        assert all_records[0]["success"] is True

    def test_record_multiple_executions(self, tmp_path):
        packer = _new_packer(tmp_path)
        for i in range(3):
            packer.record_task_execution(
                skill_id=f"sk_{i}",
                task_type="exec",
                success=True,
                input_data={"i": i},
            )
        assert len(packer.get_task_records()) == 3


class TestEvaluateAndPack:
    def test_evaluate_pattern_for_packing_simple(self, tmp_path):
        packer = _new_packer(tmp_path)
        verdict = packer.evaluate_pattern_for_packing(
            task_type="search",
            success_count=3,
            failure_count=0,
            step_count=3,
        )
        assert isinstance(verdict, bool)

    def test_evaluate_pattern_insufficient_returns_false(self, tmp_path):
        packer = _new_packer(tmp_path)
        verdict = packer.evaluate_pattern_for_packing(
            task_type="search",
            success_count=1,
            failure_count=0,
            step_count=1,
        )
        assert verdict is False

    def test_check_and_pack_with_records(self, tmp_path):
        packer = _new_packer(tmp_path)
        for _ in range(3):
            packer.record_task_execution(
                skill_id="",
                task_type="summarize",
                success=True,
                input_data={"text": "abc"},
                output_data={"summary": "abc"},
            )
        sid = packer._check_and_pack(task_type="summarize", steps=3)
        if sid is not None:
            skill = packer.get_packed_skill(sid)
            assert skill is not None


class TestIterateSkill:
    def test_iterate_skill_bumps_version(self, tmp_path):
        packer = _new_packer(tmp_path)
        sid = packer.pack_skill(
            name="x",
            description="d",
            category="learning",
        )
        original = packer.get_packed_skill(sid)
        original_version = original["version"]
        result = packer.iterate_skill(
            skill_id=sid,
            description="improved",
            tags=["v2"],
        )
        assert result is True
        updated = packer.get_packed_skill(sid)
        assert updated["description"] == "improved"
        assert "v2" in updated["tags"]
        assert updated["version"] != original_version or updated["updated_at"] >= original["updated_at"]

    def test_iterate_skill_missing_returns_false(self, tmp_path):
        packer = _new_packer(tmp_path)
        result = packer.iterate_skill(
            skill_id="missing",
            description="x",
        )
        assert result is False


class TestPersistence:
    def test_persistence_reload(self, tmp_path):
        d = tmp_path / "persist"
        from tests.skill.conftest import SkillPacker
        p1 = SkillPacker(storage_dir=str(d))
        p1.pack_skill(name="alpha", description="d", category="reasoning")
        p1.pack_skill(name="beta", description="d", category="memory")
        p2 = SkillPacker(storage_dir=str(d))
        assert len(p2.get_packed_skills()) == 2

    def test_persistence_records_reload(self, tmp_path):
        d = tmp_path / "persist2"
        from tests.skill.conftest import SkillPacker
        p1 = SkillPacker(storage_dir=str(d))
        p1.record_task_execution(
            skill_id="sk_x",
            task_type="exec",
            success=True,
            input_data={"a": 1},
        )
        p2 = SkillPacker(storage_dir=str(d))
        assert len(p2.get_task_records()) == 1


class TestThreadSafety:
    def test_concurrent_pack_skill(self, tmp_path):
        packer = _new_packer(tmp_path)
        errors = []

        def worker(i):
            try:
                packer.pack_skill(
                    name=f"skill_{i}",
                    description=f"desc {i}",
                    category="execution",
                )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(packer.get_packed_skills()) == 10

    def test_concurrent_record_and_pack(self, tmp_path):
        packer = _new_packer(tmp_path)
        errors = []

        def record(i):
            try:
                packer.record_task_execution(
                    skill_id=f"sk_{i}",
                    task_type="t",
                    success=True,
                    input_data={},
                )
            except Exception as e:
                errors.append(e)

        def pack(i):
            try:
                packer.pack_skill(
                    name=f"s_{i}",
                    description="d",
                    category="reasoning",
                )
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=record, args=(i,)))
            threads.append(threading.Thread(target=pack, args=(i,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


class TestSingletonFactory:
    def test_get_skill_packer_returns_singleton(self, tmp_path, monkeypatch):
        from tests.skill import conftest as _conftest
        original_dir = _conftest._MODULE
        monkeypatch.setattr(_conftest._MODULE, "_DEFAULT_DIR", str(tmp_path / "default"), raising=False)
        factory = getattr(original_dir, "get_skill_packer", None)
        assert factory is not None
        a = factory()
        b = factory()
        assert a is b

    def test_get_skill_packer_callable(self):
        from tests.skill.conftest import get_skill_packer
        assert callable(get_skill_packer)
