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
    """创建SkillService实例（skills_dir 指向工作区 skills 子目录）"""
    return SkillService(agent_id="test_agent", skills_dir=str(temp_workspace / "skills"))


@pytest.fixture
def sample_skill_content() -> str:
    """示例技能内容"""
    return "def run():\n    return 'hello world'"


# ================================================================
# 实现 1.0 方法面：install_skill / uninstall_skill / enable_skill /
# disable_skill / list_skills / get_skill_info / record_skill_usage /
# get_skill_usage / register_auto_skill / update_auto_skill
# ================================================================


class TestInit:
    """初始化"""

    def test_init_creates_directory(self, skill_service: SkillService, temp_workspace: Path):
        """初始化应创建 skills 目录"""
        assert (temp_workspace / "skills").exists()

    def test_list_empty(self, skill_service: SkillService):
        """初始无技能"""
        assert skill_service.list_skills() == []


class TestAutoSkill:
    """register_auto_skill / update_auto_skill（S3 P0 #2 桥接）"""

    def test_register_auto_skill(self, skill_service: SkillService):
        ok = skill_service.register_auto_skill("auto1", "自动技能", description="d", config={"k": "v"})
        assert ok is True
        skills = skill_service.list_skills()
        assert any(s["id"] == "auto1" for s in skills)

    def test_register_duplicate(self, skill_service: SkillService):
        assert skill_service.register_auto_skill("dup", "n1") is True
        assert skill_service.register_auto_skill("dup", "n2") is False

    def test_update_auto_skill(self, skill_service: SkillService):
        skill_service.register_auto_skill("up1", "n")
        ok = skill_service.update_auto_skill("up1", version="2.0.0")
        assert ok is True
        assert skill_service.get_skill_info("up1")["version"] == "2.0.0"

    def test_update_nonexistent(self, skill_service: SkillService):
        assert skill_service.update_auto_skill("ghost", version="2.0.0") is False


class TestEnableDisable:
    """enable_skill / disable_skill"""

    def _install(self, svc, skill_id):
        import tempfile
        src = Path(tempfile.mkdtemp()) / skill_id
        src.mkdir(parents=True, exist_ok=True)
        manifest_file = src / "manifest.json"
        import json as _json
        manifest_file.write_text(_json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}), encoding="utf-8")
        svc.install_skill(str(src))

    def test_disable_skill(self, skill_service):
        self._install(skill_service, "dis1")
        result = skill_service.disable_skill("dis1")
        assert result.get("success") is True

    def test_enable_skill(self, skill_service):
        self._install(skill_service, "en1")
        skill_service.disable_skill("en1")
        result = skill_service.enable_skill("en1")
        assert result.get("success") is True

    def test_enable_nonexistent(self, skill_service):
        result = skill_service.enable_skill("ghost")
        assert result.get("success") is False


class TestUsage:
    """record_skill_usage / get_skill_usage"""

    def _install(self, svc, skill_id):
        import tempfile
        src = Path(tempfile.mkdtemp()) / skill_id
        src.mkdir(parents=True, exist_ok=True)
        manifest_file = src / "manifest.json"
        import json as _json
        manifest_file.write_text(_json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}), encoding="utf-8")
        svc.install_skill(str(src))

    def test_record_usage(self, skill_service):
        self._install(skill_service, "use1")
        assert skill_service.record_skill_usage("use1", success=True) is True
        stats = skill_service.get_skill_usage("use1")
        assert stats["use_count"] >= 1
        assert stats["success_count"] == 1

    def test_record_usage_nonexistent(self, skill_service):
        assert skill_service.record_skill_usage("ghost", success=True) is False


class TestListInfo:
    """list_skills / get_skill_info"""

    def _install(self, svc, skill_id):
        import tempfile
        src = Path(tempfile.mkdtemp()) / skill_id
        src.mkdir(parents=True, exist_ok=True)
        manifest_file = src / "manifest.json"
        import json as _json
        manifest_file.write_text(_json.dumps({"id": skill_id, "name": skill_id, "version": "1.0.0"}), encoding="utf-8")
        svc.install_skill(str(src))

    def test_list_skills(self, skill_service):
        self._install(skill_service, "ls1")
        skills = skill_service.list_skills()
        assert any(s["id"] == "ls1" for s in skills)

    def test_get_skill_info(self, skill_service):
        self._install(skill_service, "info1")
        info = skill_service.get_skill_info("info1")
        assert info is not None
        assert info["id"] == "info1"

    def test_get_skill_info_nonexistent(self, skill_service):
        assert skill_service.get_skill_info("ghost") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
