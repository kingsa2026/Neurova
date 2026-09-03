"""
Test cases for neurova.skill_system module
"""
import pytest
import os
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from neurova.skill_system.skill_pool_manager import (
    SkillPoolType,
    SkillVisibility,
    SkillMetadata,
    SkillPoolManager,
)


class TestSkillPoolType:
    """Test cases for SkillPoolType enum."""

    def test_skill_pool_type_values(self):
        """Test SkillPoolType enum values."""
        assert SkillPoolType.PUBLIC.value == "public"
        assert SkillPoolType.PRIVATE.value == "private"
        assert SkillPoolType.AGENT.value == "agent"

    def test_skill_pool_type_members(self):
        """Test SkillPoolType enum members."""
        assert len(SkillPoolType) == 3
        assert "PUBLIC" in SkillPoolType.__members__
        assert "PRIVATE" in SkillPoolType.__members__
        assert "AGENT" in SkillPoolType.__members__


class TestSkillVisibility:
    """Test cases for SkillVisibility enum."""

    def test_skill_visibility_values(self):
        """Test SkillVisibility enum values."""
        assert SkillVisibility.PUBLIC.value == "public"
        assert SkillVisibility.PRIVATE.value == "private"
        assert SkillVisibility.SHARED.value == "shared"

    def test_skill_visibility_members(self):
        """Test SkillVisibility enum members."""
        assert len(SkillVisibility) == 3
        assert "PUBLIC" in SkillVisibility.__members__
        assert "PRIVATE" in SkillVisibility.__members__
        assert "SHARED" in SkillVisibility.__members__


class TestSkillMetadata:
    """Test cases for SkillMetadata class (2.0 API)."""

    def test_skill_metadata_creation(self):
        metadata = SkillMetadata(
            skill_id="test_skill",
            name="test_skill",
            description="A test skill",
            version="1.0.0",
            author="test_author",
        )
        assert metadata.skill_id == "test_skill"
        assert metadata.name == "test_skill"
        assert metadata.description == "A test skill"
        assert metadata.version == "1.0.0"
        assert metadata.author == "test_author"

    def test_skill_metadata_defaults(self):
        metadata = SkillMetadata(skill_id="test_skill", name="test_skill")
        assert metadata.name == "test_skill"
        assert metadata.description == ""
        assert metadata.version == "1.0.0"
        assert metadata.author == ""
        assert metadata.visibility == SkillVisibility.PRIVATE
        assert metadata.tags == []

    def test_skill_metadata_to_dict(self):
        metadata = SkillMetadata(
            skill_id="test_skill",
            name="test_skill",
            description="A test skill",
            version="2.0.0",
            author="test_author",
            tags=["test", "demo"],
        )
        data = metadata.to_dict()
        assert data["skill_id"] == "test_skill"
        assert data["name"] == "test_skill"
        assert data["description"] == "A test skill"
        assert data["version"] == "2.0.0"
        assert data["author"] == "test_author"
        assert data["tags"] == ["test", "demo"]

    def test_skill_metadata_from_dict(self):
        data = {
            "skill_id": "test_skill",
            "name": "test_skill",
            "description": "A test skill",
            "version": "1.0.0",
            "author": "test_author",
            "tags": ["test"],
        }
        metadata = SkillMetadata.from_dict(data)
        assert metadata.skill_id == "test_skill"
        assert metadata.name == "test_skill"
        assert metadata.description == "A test skill"
        assert metadata.tags == ["test"]


class TestSkillPoolManager:
    """Test cases for SkillPoolManager class (2.0 API)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SkillPoolManager(
            base_dir=self.temp_dir,
            config={"enabled": True},
        )
        # 2.0 契约: 构造函数不创建目录，需显式调用 _on_init()
        self.manager._on_init()

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_skill_pool_manager_creation(self):
        assert self.manager is not None
        assert hasattr(self.manager, "list_public_skills")
        assert hasattr(self.manager, "list_private_skills")

    def test_skill_pool_manager_has_proper_attributes(self):
        # 2.0 使用 _data_dir 作为根目录（非 1.0 的 _base_dir），
        # 且不再维护内存 _metadata / 独立 _agent_pool_dir。
        assert hasattr(self.manager, "_data_dir")
        assert hasattr(self.manager, "_public_pool_dir")
        assert hasattr(self.manager, "_private_pool_dir")

    def test_init_dirs(self):
        assert os.path.exists(self.manager._public_pool_dir)
        assert os.path.exists(self.manager._private_pool_dir)

    def test_list_public_skills_empty(self):
        skills = self.manager.list_public_skills()
        assert skills == []

    def test_install_public_skill(self):
        skill_metadata = SkillMetadata(
            skill_id="test_skill",
            name="test_skill",
            description="A test skill",
            version="1.0.0",
        )
        result = self.manager.install_public_skill(skill_metadata)
        assert result is True
        skills = self.manager.list_public_skills()
        assert len(skills) == 1
        assert skills[0].skill_id == "test_skill"

    def test_list_public_skills(self):
        for i in range(3):
            self.manager.install_public_skill(
                SkillMetadata(skill_id=f"skill_{i}", name=f"skill_{i}")
            )
        skills = self.manager.list_public_skills()
        assert len(skills) == 3

    def test_get_public_skill(self):
        skill_metadata = SkillMetadata(
            skill_id="test_skill",
            name="test_skill",
            description="A test skill",
            version="1.0.0",
        )
        self.manager.install_public_skill(skill_metadata)
        skill = self.manager.get_public_skill("test_skill")
        assert skill is not None
        assert skill.name == "test_skill"

    def test_get_public_skill_not_found(self):
        skill = self.manager.get_public_skill("nonexistent")
        assert skill is None

    def test_list_private_skills_empty(self):
        skills = self.manager.list_private_skills("user123")
        assert skills == []

    def test_create_private_skill(self):
        result = self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My private skill",
            user_id="user123",
        )
        assert result is not None
        assert result.skill_id == "my_skill"
        skills = self.manager.list_private_skills("user123")
        assert len(skills) == 1
        assert skills[0].name == "my_skill"

    def test_get_private_skill(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My private skill",
            user_id="user123",
        )
        skill = self.manager.get_private_skill("my_skill", "user123")
        assert skill is not None
        assert skill.name == "my_skill"

    def test_update_private_skill(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My private skill",
            user_id="user123",
        )
        # 2.0 update_private_skill 返回 bool，并通过 name 字段更新
        result = self.manager.update_private_skill(
            skill_id="my_skill",
            user_id="user123",
            name="renamed_skill",
        )
        assert result is True
        skill = self.manager.get_private_skill("my_skill", "user123")
        assert skill.name == "renamed_skill"

    def test_delete_private_skill(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My private skill",
            user_id="user123",
        )
        result = self.manager.delete_private_skill("my_skill", "user123")
        assert result is True
        skills = self.manager.list_private_skills("user123")
        assert len(skills) == 0

    def test_share_private_skill(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My private skill",
            user_id="user123",
        )
        result = self.manager.share_private_skill(
            skill_name="my_skill",
            owner="user123",
            target="user456",
        )
        assert result is True

    def test_push_skill_to_agent(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My skill",
            user_id="user123",
        )
        result = self.manager.push_skill_to_agent(
            skill_id="my_skill",
            user_id="user123",
            agent_id="agent_001",
        )
        assert result is True
        agent_skills = self.manager.get_agent_skills("agent_001")
        assert "my_skill" in [s.skill_id for s in agent_skills]

    def test_unpush_skill_from_agent(self):
        self.manager.create_private_skill(
            skill_id="my_skill",
            name="my_skill",
            description="My skill",
            user_id="user123",
        )
        self.manager.push_skill_to_agent(
            skill_id="my_skill",
            user_id="user123",
            agent_id="agent_001",
        )
        result = self.manager.unpush_skill_from_agent(
            skill_id="my_skill",
            user_id="user123",
            agent_id="agent_001",
        )
        assert result is True
        agent_skills = self.manager.get_agent_skills("agent_001")
        assert "my_skill" not in [s.skill_id for s in agent_skills]

    def test_get_agent_skills_empty(self):
        skills = self.manager.get_agent_skills("agent_001")
        assert skills == []

    def test_admin_list_all_skills(self):
        for i in range(3):
            self.manager.create_private_skill(
                skill_id=f"skill_{i}",
                name=f"skill_{i}",
                description=f"Skill {i}",
                user_id="user123",
            )
        all_skills = self.manager.admin_list_all_skills()
        assert len(all_skills) == 3

    def test_admin_delete_user_skills(self):
        for i in range(3):
            self.manager.create_private_skill(
                skill_id=f"skill_{i}",
                name=f"skill_{i}",
                description=f"Skill {i}",
                user_id="user123",
            )
        result = self.manager.admin_delete_user_skills("user123")
        assert result == 3
        skills = self.manager.list_private_skills("user123")
        assert len(skills) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
