"""Skills System 2.0 - SkillService测试"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from unittest.mock import patch, MagicMock

from neurova.skills.models import SkillInfo, SkillSource, ExperienceRecord
from neurova.skills.skill_service import SkillService


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """创建临时工作区目录"""
    workspace = tmp_path / "workspaces" / "test_agent"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def skill_service(temp_workspace: Path) -> SkillService:
    """创建SkillService实例"""
    return SkillService(workspace_dir=temp_workspace, agent_id="test_agent")


@pytest.fixture
def sample_skill_content() -> str:
    """示例技能内容"""
    return "def run():\n    return 'hello world'"


class TestSkillServiceInit:
    """测试SkillService初始化"""

    def test_init_creates_directory(self, temp_workspace: Path):
        """初始化时创建目录"""
        svc = SkillService(workspace_dir=temp_workspace, agent_id="agent1")
        assert (temp_workspace / "skills").exists()
        assert (temp_workspace / "skills" / "skill.json").exists()

    def test_init_with_existing_manifest(self, temp_workspace: Path):
        """初始化时加载已存在的清单"""
        skills_dir = temp_workspace / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        manifest_data = {"existing_skill": {"name": "existing_skill"}}
        (skills_dir / "skill.json").write_text(
            json.dumps(manifest_data), encoding="utf-8"
        )

        svc = SkillService(workspace_dir=temp_workspace, agent_id="agent1")
        skills = svc.list_skills()
        assert len(skills) == 1


class TestSkillServiceListSkills:
    """测试list_skills方法"""

    def test_list_empty(self, skill_service: SkillService):
        """列出空技能列表"""
        skills = skill_service.list_skills()
        assert skills == []

    def test_list_skills(self, skill_service: SkillService, sample_skill_content: str):
        """列出技能"""
        skill_service.create_skill("skill1", sample_skill_content)
        skills = skill_service.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "skill1"


class TestSkillServiceCreateSkill:
    """测试create_skill方法"""

    def test_create_skill(self, skill_service: SkillService, sample_skill_content: str):
        """创建技能"""
        skill_info = skill_service.create_skill("new_skill", sample_skill_content)
        assert skill_info is not None
        assert skill_info.name == "new_skill"
        assert skill_info.enabled is True

        # 验证文件已创建
        skill_file = skill_service.skills_dir / "new_skill" / "skill.py"
        assert skill_file.exists()
        assert skill_file.read_text(encoding="utf-8") == sample_skill_content

    def test_create_skill_disabled(self, skill_service: SkillService):
        """创建禁用状态的技能"""
        skill_info = skill_service.create_skill("disabled_skill", "def test(): pass", enable=False)
        assert skill_info.enabled is False

    def test_create_duplicate_skill(self, skill_service: SkillService, sample_skill_content: str):
        """创建重复技能"""
        skill_service.create_skill("dup_skill", sample_skill_content)
        result = skill_service.create_skill("dup_skill", sample_skill_content)
        assert result is None


class TestSkillServiceSaveSkill:
    """测试save_skill方法"""

    def test_save_skill(self, skill_service: SkillService, sample_skill_content: str):
        """保存技能"""
        skill_service.create_skill("save_test", sample_skill_content)
        new_content = "def run():\n    return 'updated'"
        result = skill_service.save_skill("save_test", new_content)
        assert result is True

        # 验证文件已更新
        skill_file = skill_service.skills_dir / "save_test" / "skill.py"
        assert skill_file.read_text(encoding="utf-8") == new_content

    def test_save_skill_rename(self, skill_service: SkillService, sample_skill_content: str):
        """保存技能并重命名"""
        skill_service.create_skill("old_name", sample_skill_content)
        result = skill_service.save_skill("old_name", sample_skill_content, target_name="new_name")
        assert result is True

        # 验证旧目录已删除，新目录已创建
        assert not (skill_service.skills_dir / "old_name").exists()
        assert (skill_service.skills_dir / "new_name").exists()

    def test_save_nonexistent_skill(self, skill_service: SkillService):
        """保存不存在的技能"""
        result = skill_service.save_skill("nonexistent", "content")
        assert result is False


class TestSkillServiceEnableDisable:
    """测试enable_skill和disable_skill方法"""

    def test_enable_skill(self, skill_service: SkillService, sample_skill_content: str):
        """启用技能"""
        skill_service.create_skill("enable_test", sample_skill_content, enable=False)
        result = skill_service.enable_skill("enable_test")
        assert result is True

        # 验证清单已更新
        manifest = skill_service._load_manifest()
        assert manifest["enable_test"]["enabled"] is True

    def test_disable_skill(self, skill_service: SkillService, sample_skill_content: str):
        """禁用技能"""
        skill_service.create_skill("disable_test", sample_skill_content, enable=True)
        result = skill_service.disable_skill("disable_test")
        assert result is True

        # 验证清单已更新
        manifest = skill_service._load_manifest()
        assert manifest["disable_test"]["enabled"] is False

    def test_enable_nonexistent_skill(self, skill_service: SkillService):
        """启用不存在的技能"""
        result = skill_service.enable_skill("nonexistent")
        assert result is False


class TestSkillServiceDeleteSkill:
    """测试delete_skill方法"""

    def test_delete_skill(self, skill_service: SkillService, sample_skill_content: str):
        """删除技能"""
        skill_service.create_skill("delete_test", sample_skill_content)
        result = skill_service.delete_skill("delete_test")
        assert result is True

        # 验证已从清单中删除
        manifest = skill_service._load_manifest()
        assert "delete_test" not in manifest

        # 验证目录已删除
        assert not (skill_service.skills_dir / "delete_test").exists()

    def test_delete_nonexistent_skill(self, skill_service: SkillService):
        """删除不存在的技能"""
        result = skill_service.delete_skill("nonexistent")
        assert result is False


class TestSkillServiceEvolveSkill:
    """测试evolve_skill方法（Neurova特色）"""

    def test_evolve_skill(self, skill_service: SkillService, sample_skill_content: str):
        """进化技能"""
        skill_service.create_skill("evolve_test", sample_skill_content)

        feedback = {
            "performance": {"execution_time": 2.0, "success_rate": 0.7},
            "user_feedback": "有点慢",
            "source": "test",
        }

        evolved = skill_service.evolve_skill("evolve_test", feedback)
        assert evolved is not None
        assert evolved.version_text == "0.1.1"  # 版本号递增
        assert len(evolved.evolution_history) > 0

    def test_evolve_nonexistent_skill(self, skill_service: SkillService):
        """进化不存在的技能"""
        with pytest.raises(ValueError):
            skill_service.evolve_skill("nonexistent", {})


class TestSkillServicePackageSkill:
    """测试package_skill方法（Neurova特色）"""

    def test_package_skill(self, skill_service: SkillService, sample_skill_content: str, tmp_path: Path):
        """打包技能"""
        skill_service.create_skill("package_test", sample_skill_content)
        output_path = tmp_path / "package_test.zip"

        result = skill_service.package_skill("package_test", output_path)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_package_nonexistent_skill(self, skill_service: SkillService):
        """打包不存在的技能"""
        with pytest.raises(ValueError):
            skill_service.package_skill("nonexistent")


class TestSkillServiceCallExperience:
    """测试call_experience方法（Neurova特色）"""

    def test_call_experience(self, skill_service: SkillService, sample_skill_content: str):
        """调用经验"""
        skill_service.create_skill("exp_test", sample_skill_content)

        # 添加经验记录
        manifest = skill_service._load_manifest()
        skill_data = manifest["exp_test"]
        skill_data["experience_records"] = [
            {
                "skill_name": "exp_test",
                "context": {"user_input": "测试输入"},
                "result": {"output": "测试输出"},
                "success": True,
                "timestamp": "2026-05-12T22:00:00",
            }
        ]
        skill_service._save_manifest(manifest)

        # 调用经验
        context = {"user_input": "测试输入"}
        exp = skill_service.call_experience("exp_test", context)
        assert exp is not None
        assert exp.skill_name == "exp_test"

    def test_call_experience_no_match(self, skill_service: SkillService, sample_skill_content: str):
        """调用经验（无匹配）"""
        skill_service.create_skill("no_match", sample_skill_content)
        context = {"user_input": "完全不同的输入"}
        exp = skill_service.call_experience("no_match", context)
        # 可能返回None或匹配度最低的记录
        assert exp is None or exp.skill_name == "no_match"


class TestSkillServiceGetSkillStats:
    """测试get_skill_stats方法"""

    def test_get_skill_stats(self, skill_service: SkillService, sample_skill_content: str):
        """获取技能统计"""
        skill_service.create_skill("stats_test", sample_skill_content)
        stats = skill_service.get_skill_stats("stats_test")

        assert stats["skill_name"] == "stats_test"
        assert stats["version"] == "0.1.0"
        assert stats["enabled"] is True
        assert stats["usage_count"] == 0

    def test_get_nonexistent_skill_stats(self, skill_service: SkillService):
        """获取不存在的技能统计"""
        with pytest.raises(ValueError):
            skill_service.get_skill_stats("nonexistent")


class TestSkillServiceRecordUsage:
    """测试record_usage方法"""

    def test_record_usage(self, skill_service: SkillService, sample_skill_content: str):
        """记录技能使用"""
        skill_service.create_skill("record_test", sample_skill_content)

        context = {"user_input": "测试"}
        result = {"output": "结果"}
        skill_service.record_usage("record_test", context, result, success=True)

        # 验证统计已更新
        stats = skill_service.get_skill_stats("record_test")
        assert stats["usage_count"] == 1
        assert stats["success_count"] == 1
        assert stats["failure_count"] == 0

        # 验证经验记录已添加
        manifest = skill_service._load_manifest()
        assert len(manifest["record_test"]["experience_records"]) == 1


class TestSkillServiceIncrementVersion:
    """测试_increment_version方法"""

    def test_increment_version(self, skill_service: SkillService):
        """递增版本号"""
        new_version = skill_service._increment_version("1.0.0")
        assert new_version == "1.0.1"

        new_version = skill_service._increment_version("1.0.9")
        assert new_version == "1.0.10"

    def test_increment_invalid_version(self, skill_service: SkillService):
        """递增无效版本号"""
        new_version = skill_service._increment_version("invalid")
        assert new_version == "1.0.0"
