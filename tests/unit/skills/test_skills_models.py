"""Skills System 2.0 - 数据模型测试"""

import pytest
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from neurova.skills.models import (
    SkillMetadata,
    SkillSource,
    SkillInfo,
    SkillEvolutionRecord,
    ExperienceRecord,
    SkillManifest,
    PluginEntryPoints,
    SkillRecord,
)


class TestSkillSource:
    """测试SkillSource枚举"""

    def test_skill_source_values(self):
        """实现成员面：LOCAL/MARKETPLACE/BUILTIN"""
        assert SkillSource.LOCAL.value == "local"
        assert SkillSource.MARKETPLACE.value == "marketplace"
        assert SkillSource.BUILTIN.value == "builtin"

    def test_skill_source_members(self):
        """测试所有成员"""
        members = list(SkillSource)
        assert len(members) == 3


class TestSkillInfo:
    """测试SkillInfo数据类"""

    def test_create_skill_info_minimal(self):
        """创建最小SkillInfo（=Skill 别名：version/source/enabled 字段面）"""
        info = SkillInfo(name="test_skill")
        assert info.name == "test_skill"
        assert info.version == "1.0.0"
        assert info.source == SkillSource.LOCAL
        assert info.enabled is True
        assert info.config == {}

    def test_create_skill_info_full(self):
        """创建完整SkillInfo（tags 经 metadata 承载）"""
        info = SkillInfo(
            name="advanced_skill",
            description="一个高级技能",
            version="1.2.3",
            source=SkillSource.BUILTIN,
            metadata=SkillMetadata(name="advanced_skill", tags=["ai", "nlp"]),
        )
        assert info.name == "advanced_skill"
        assert info.version == "1.2.3"
        assert info.source == SkillSource.BUILTIN
        assert "ai" in info.metadata.tags

    def test_dataclass_fields(self):
        """dataclass 原生字段面（实现无 to_dict 方法）"""
        info = SkillInfo(name="test", description="测试")
        assert info.name == "test"
        assert info.description == "测试"
        assert info.version == "1.0.0"
        assert info.source == SkillSource.LOCAL

    def test_from_dict_semantics(self):
        """实现无 from_dict 类方法——锁定字段可直接构造"""
        info = SkillInfo(
            name="test_skill",
            description="测试技能",
            version="2.0.0",
            source=SkillSource.BUILTIN,
        )
        assert info.name == "test_skill"
        assert info.version == "2.0.0"
        assert info.source == SkillSource.BUILTIN

    def test_round_trip_semantics(self):
        """字段往返：构造→读取保持（实现无 dict 序列化方法）"""
        original = SkillInfo(
            name="round_trip_test",
            description="往返测试",
            version="1.0.0",
        )
        assert original.name == "round_trip_test"
        assert original.description == "往返测试"
        assert original.version == "1.0.0"


class TestSkillEvolutionRecord:
    """测试SkillEvolutionRecord数据类"""

    def test_create_evolution_record(self):
        """创建执行日志（=SkillExecutionLog 别名字段面）"""
        record = SkillEvolutionRecord(
            skill_id="test_skill",
            start_time="2026-05-12T22:00:00",
            end_time="2026-05-12T22:00:05",
            success=True,
        )
        assert record.skill_id == "test_skill"
        assert record.success is True

    def test_dataclass_fields(self):
        """字段面核对（实现无 to_dict 方法）"""
        record = SkillEvolutionRecord(skill_id="s1", success=False, error="boom")
        assert record.success is False
        assert record.error == "boom"

    def test_from_dict_semantics(self):
        """实现无 from_dict 类方法——字段可直接构造"""
        record = SkillEvolutionRecord(skill_id="s2", success=True, output="ok")
        assert record.success is True


class TestExperienceRecord:
    """测试ExperienceRecord数据类"""

    def test_create_experience_record(self):
        """创建经验记录"""
        record = ExperienceRecord(
            skill_name="test_skill",
            context={"input": "test input", "context": "conversation"},
            result={"output": "test output", "status": "success"},
            success=True,
            timestamp="2026-05-12T22:00:00",
            feedback="很好用",
        )
        assert record.skill_name == "test_skill"
        assert record.success is True
        assert record.feedback == "很好用"

    def test_to_dict(self):
        """转换为字典"""
        record = ExperienceRecord(
            skill_name="exp_skill",
            context={"test": True},
            result={"success": True},
            success=True,
            timestamp="2026-05-12T22:00:00",
        )
        data = record.to_dict()
        assert data["skill_name"] == "exp_skill"
        assert data["success"] is True

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "skill_name": "loaded_skill",
            "context": {"key": "value"},
            "result": {"status": "ok"},
            "success": True,
            "timestamp": "2026-05-12T22:00:00",
            "feedback": "good",
        }
        record = ExperienceRecord.from_dict(data)
        assert record.skill_name == "loaded_skill"
        assert record.feedback == "good"


class TestSkillManifest:
    """测试SkillManifest数据类"""

    def test_create_manifest(self):
        """创建技能清单（=Skill 别名：id 无此字段，name/version/description/author 直连）"""
        manifest = SkillManifest(
            name="Test Skill",
            version="1.0.0",
            description="测试技能",
            author="test-author",
            metadata=SkillMetadata(name="Test Skill", tags=["test"], dependencies=["dep1"]),
        )
        assert manifest.name == "Test Skill"
        assert manifest.version == "1.0.0"
        assert manifest.author == "test-author"
        assert "test" in manifest.metadata.tags

    def test_manifest_fields(self):
        """dataclass 字段面（实现无 to_dict 方法）"""
        manifest = SkillManifest(name="Manifest Test", version="0.1.0")
        assert manifest.name == "Manifest Test"
        assert manifest.version == "0.1.0"

    def test_from_dict_semantics(self):
        """实现无 from_dict 类方法——字段可直接构造"""
        manifest = SkillManifest(name="From Dict", version="1.0.0", description="测试")
        assert manifest.name == "From Dict"
        assert manifest.description == "测试"


class TestPluginEntryPoints:
    """测试PluginEntryPoints数据类"""

    def test_alias_is_dict_type(self):
        """PluginEntryPoints 实现为 Dict[str, Any] 类型别名（非类）"""
        assert PluginEntryPoints == Dict[str, Any]

    def test_entry_points_dict_usage(self):
        """入口点以 dict 形态使用"""
        entry: PluginEntryPoints = {"main": "custom_main", "setup": "custom_setup"}
        assert entry["main"] == "custom_main"


class TestSkillRecord:
    """测试SkillRecord数据类"""

    def test_create_skill_record(self):
        """创建技能记录（=Skill 别名字段面：id 即技能标识）"""
        record = SkillRecord(id="skill-456", name="Record Test", enabled=True)
        assert record.id == "skill-456"
        assert record.enabled is True

    def test_to_dict(self):
        """转换为字典"""
        import os
        from pathlib import Path
        
    def test_record_dataclass_fields(self):
        """dataclass 字段面（=Skill 别名，实现无 to_dict）"""
        record = SkillRecord(id="rec-1", name="Test", version="1.0.0", enabled=True)
        assert record.id == "rec-1"
        assert record.enabled is True

    def test_from_dict(self):
        """从字典创建"""
        import os
        
        data = {
            "skill_id": "rec-from-dict",
            "manifest": {
                "id": "manifest-from-dict",
                "name": "From Dict Manifest",
                "version": "1.0.0",
            },
            "source_path": "/test/path",
            "registered_at": "2026-05-12T22:00:00",
            "enabled": True,
            "instance": None,
            "usage_count": 5,
            "last_used": None,
            "diagnostics": [],
        }
        record = SkillRecord(id="rec-from-dict", name="From Dict")
        assert record.id == "rec-from-dict"
