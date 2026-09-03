"""Skills System 2.0 - 数据模型测试"""

import pytest
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from neurova.skills.models import (
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
        """测试技能来源值"""
        assert SkillSource.BUILTIN.value == "builtin"
        assert SkillSource.POOL.value == "pool"
        assert SkillSource.AGENT_PRIVATE.value == "agent"
        assert SkillSource.HUB.value == "hub"
        assert SkillSource.AUTO_GENERATED.value == "auto"

    def test_skill_source_members(self):
        """测试所有成员"""
        members = list(SkillSource)
        assert len(members) == 5


class TestSkillInfo:
    """测试SkillInfo数据类"""

    def test_create_skill_info_minimal(self):
        """创建最小SkillInfo"""
        info = SkillInfo(name="test_skill")
        assert info.name == "test_skill"
        assert info.version_text == "0.1.0"
        assert info.source == SkillSource.AGENT_PRIVATE
        assert info.enabled is True
        assert info.evolution_history == []
        assert info.usage_statistics == {}
        assert info.experience_records == []

    def test_create_skill_info_full(self):
        """创建完整SkillInfo"""
        info = SkillInfo(
            name="advanced_skill",
            description="一个高级技能",
            version_text="1.2.3",
            content="def execute(): pass",
            source=SkillSource.BUILTIN,
            tags=["ai", "nlp"],
            emoji="🤖",
            evolution_history=[{"version": "1.0.0", "change": "初始版本"}],
            usage_statistics={"total_calls": 100, "success_rate": 0.95},
        )
        assert info.name == "advanced_skill"
        assert info.version_text == "1.2.3"
        assert info.source == SkillSource.BUILTIN
        assert "ai" in info.tags
        assert info.emoji == "🤖"

    def test_to_dict(self):
        """转换为字典"""
        info = SkillInfo(name="test", description="测试")
        data = info.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "test"
        assert data["description"] == "测试"
        assert data["version_text"] == "0.1.0"
        assert data["source"] == "agent"

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "name": "test_skill",
            "description": "测试技能",
            "version_text": "2.0.0",
            "source": "builtin",
            "tags": ["test"],
            "enabled": True,
        }
        info = SkillInfo.from_dict(data)
        assert info.name == "test_skill"
        assert info.version_text == "2.0.0"
        assert info.source == SkillSource.BUILTIN

    def test_round_trip(self):
        """往返转换测试"""
        original = SkillInfo(
            name="round_trip_test",
            description="往返测试",
            version_text="1.0.0",
            tags=["test", "round_trip"],
        )
        data = original.to_dict()
        restored = SkillInfo.from_dict(data)
        assert restored.name == original.name
        assert restored.description == original.description
        assert restored.version_text == original.version_text
        assert restored.tags == original.tags


class TestSkillEvolutionRecord:
    """测试SkillEvolutionRecord数据类"""

    def test_create_evolution_record(self):
        """创建进化记录"""
        record = SkillEvolutionRecord(
            version="1.1.0",
            timestamp="2026-05-12T22:00:00",
            change_description="优化性能",
            performance_improvement=0.15,
            feedback_source="user_feedback",
        )
        assert record.version == "1.1.0"
        assert record.performance_improvement == 0.15
        assert record.feedback_source == "user_feedback"

    def test_to_dict(self):
        """转换为字典"""
        record = SkillEvolutionRecord(
            version="1.0.0",
            timestamp="2026-05-12T10:00:00",
            change_description="初始版本",
            performance_improvement=0.0,
            feedback_source="initial",
        )
        data = record.to_dict()
        assert data["version"] == "1.0.0"
        assert data["performance_improvement"] == 0.0

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "version": "2.0.0",
            "timestamp": "2026-05-12T22:00:00",
            "change_description": "重大更新",
            "performance_improvement": 0.25,
            "feedback_source": "auto_evolution",
        }
        record = SkillEvolutionRecord.from_dict(data)
        assert record.version == "2.0.0"
        assert record.performance_improvement == 0.25


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
        """创建技能清单"""
        manifest = SkillManifest(
            id="skill-123",
            name="Test Skill",
            version="1.0.0",
            description="测试技能",
            author="test-author",
            tags=["test"],
            dependencies=["dep1"],
            entry_points={"main": "main", "setup": "setup"},
        )
        assert manifest.id == "skill-123"
        assert manifest.name == "Test Skill"
        assert manifest.version == "1.0.0"

    def test_to_dict(self):
        """转换为字典"""
        manifest = SkillManifest(
            id="manifest-1",
            name="Manifest Test",
            version="0.1.0",
        )
        data = manifest.to_dict()
        assert data["id"] == "manifest-1"
        assert data["name"] == "Manifest Test"
        assert "entry_points" in data
        assert "metadata" in data

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "id": "from-dict-test",
            "name": "From Dict",
            "version": "1.0.0",
            "description": "测试",
            "tags": ["test"],
        }
        manifest = SkillManifest.from_dict(data)
        assert manifest.id == "from-dict-test"
        assert manifest.name == "From Dict"


class TestPluginEntryPoints:
    """测试PluginEntryPoints数据类"""

    def test_default_entry_points(self):
        """默认入口点"""
        entry = PluginEntryPoints()
        assert entry.main == "main"
        assert entry.setup == "setup"
        assert entry.teardown == "teardown"
        assert entry.config == "config"

    def test_custom_entry_points(self):
        """自定义入口点"""
        entry = PluginEntryPoints(
            main="custom_main",
            setup="custom_setup",
        )
        assert entry.main == "custom_main"
        assert entry.setup == "custom_setup"

    def test_to_dict(self):
        """转换为字典"""
        entry = PluginEntryPoints()
        data = entry.to_dict()
        assert data["main"] == "main"
        assert data["setup"] == "setup"
        assert data["teardown"] == "teardown"
        assert data["config"] == "config"


class TestSkillRecord:
    """测试SkillRecord数据类"""

    def test_create_skill_record(self):
        """创建技能注册记录"""
        from pathlib import Path
        
        manifest = SkillManifest(
            id="record-test",
            name="Record Test",
            version="1.0.0",
        )
        record = SkillRecord(
            skill_id="skill-456",
            manifest=manifest,
            source_path=Path("/test/path"),
            registered_at="2026-05-12T22:00:00",
            enabled=True,
            instance=None,
            usage_count=10,
            last_used=None,
            diagnostics=[],
        )
        assert record.skill_id == "skill-456"
        assert record.manifest.name == "Record Test"
        assert record.enabled is True
        assert record.usage_count == 10

    def test_to_dict(self):
        """转换为字典"""
        import os
        from pathlib import Path
        
        manifest = SkillManifest(id="test", name="Test", version="1.0.0")
        record = SkillRecord(
            skill_id="rec-1",
            manifest=manifest,
            source_path=Path("/test"),
            registered_at="2026-05-12T10:00:00",
            enabled=True,
            instance=None,
            usage_count=0,
            last_used=None,
            diagnostics=[],
        )
        data = record.to_dict()
        assert data["skill_id"] == "rec-1"
        assert isinstance(data["manifest"], dict)
        # Windows 上路径分隔符可能是反斜杠，使用 os.path.normpath 比较
        assert os.path.normpath(data["source_path"]) == os.path.normpath("/test")
        assert data["instance"] is None

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
        record = SkillRecord.from_dict(data)
        assert record.skill_id == "rec-from-dict"
        assert record.manifest.id == "manifest-from-dict"
        assert record.usage_count == 5
        # Windows 上路径分隔符可能是反斜杠，使用 os.path.normpath 比较
        assert os.path.normpath(str(record.source_path)) == os.path.normpath("/test/path")
