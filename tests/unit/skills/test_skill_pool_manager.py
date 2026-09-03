"""
测试技能池管理器
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List

import pytest

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.skill_system.skill_pool_manager import (
    SkillPoolManager,
    SkillPoolType,
    SkillVisibility,
    SkillMetadata,
)


class TestSkillMetadata:
    """测试技能元数据"""

    def test_create_skill_metadata(self):
        """测试创建技能元数据"""
        skill = SkillMetadata(
            skill_id="test-skill",
            name="测试技能",
            description="测试描述",
            pool_type=SkillPoolType.PRIVATE,
            visibility=SkillVisibility.PRIVATE,
            owner_user_id="user-1",
        )
        
        assert skill.skill_id == "test-skill"
        assert skill.name == "测试技能"
        assert skill.pool_type == SkillPoolType.PRIVATE
        assert skill.visibility == SkillVisibility.PRIVATE
        assert skill.owner_user_id == "user-1"

    def test_to_dict(self):
        """测试转换为字典"""
        skill = SkillMetadata(
            skill_id="test-skill",
            name="测试技能",
            description="测试描述",
            owner_user_id="user-1",
        )
        
        data = skill.to_dict()
        
        assert data["skill_id"] == "test-skill"
        assert data["name"] == "测试技能"
        assert data["owner_user_id"] == "user-1"

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "skill_id": "test-skill",
            "name": "测试技能",
            "description": "测试描述",
            "version": "1.0.0",
            "author": "test",
            "pool_type": "private",
            "visibility": "private",
            "owner_user_id": "user-1",
            "shared_with": [],
            "pushed_to_agents": [],
            "tags": ["test"],
            "install_count": 0,
            "rating": 0.0,
            "rating_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        skill = SkillMetadata.from_dict(data)
        
        assert skill.skill_id == "test-skill"
        assert skill.name == "测试技能"
        assert skill.pool_type == SkillPoolType.PRIVATE
        assert skill.visibility == SkillVisibility.PRIVATE
        assert skill.owner_user_id == "user-1"


class TestSkillPoolManager:
    """测试技能池管理器"""

    @pytest.fixture
    def manager(self, tmp_path):
        """创建测试用的技能池管理器"""
        mgr = SkillPoolManager({"data_dir": str(tmp_path)})
        mgr._on_init()
        return mgr

    def test_init_dirs(self, manager, tmp_path):
        """测试初始化目录"""
        assert (tmp_path / "skills" / "public").exists()
        assert (tmp_path / "skills" / "private").exists()

    def test_list_public_skills_empty(self, manager):
        """测试列出空公共技能池"""
        skills = manager.list_public_skills("user-1")
        assert len(skills) == 0

    def test_get_public_skill_not_found(self, manager):
        """测试获取不存在的公共技能"""
        skill = manager.get_public_skill("non-existent")
        assert skill is None

    def test_create_private_skill(self, manager, tmp_path):
        """测试创建专属技能"""
        skill = manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
            visibility=SkillVisibility.PRIVATE,
            tags=["test", "private"],
        )
        
        assert skill is not None
        assert skill.skill_id == "my-skill"
        assert skill.name == "我的技能"
        assert skill.owner_user_id == "user-1"
        assert skill.visibility == SkillVisibility.PRIVATE
        
        # 验证目录是否创建
        skill_dir = tmp_path / "skills" / "private" / "user-1" / "my-skill"
        assert skill_dir.exists()
        
        # 验证元数据是否保存
        metadata_file = tmp_path / "skills" / "private" / "user-1" / "metadata.json"
        assert metadata_file.exists()

    def test_create_private_skill_duplicate(self, manager):
        """测试创建重复的专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 再次创建同名技能
        skill = manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能2",
            description="测试描述2",
            user_id="user-1",
        )
        
        assert skill is None  # 应该返回None

    def test_list_private_skills(self, manager):
        """测试列出专属技能"""
        # 创建两个技能
        manager.create_private_skill(
            skill_id="skill-1",
            name="技能1",
            description="描述1",
            user_id="user-1",
        )
        
        manager.create_private_skill(
            skill_id="skill-2",
            name="技能2",
            description="描述2",
            user_id="user-1",
            visibility=SkillVisibility.SHARED,
        )
        
        # 列出技能
        skills = manager.list_private_skills("user-1")
        
        assert len(skills) == 2

    def test_list_private_skills_with_visibility_filter(self, manager):
        """测试按可见性过滤列出专属技能"""
        # 创建两个技能
        manager.create_private_skill(
            skill_id="skill-1",
            name="技能1",
            description="描述1",
            user_id="user-1",
            visibility=SkillVisibility.PRIVATE,
        )
        
        manager.create_private_skill(
            skill_id="skill-2",
            name="技能2",
            description="描述2",
            user_id="user-1",
            visibility=SkillVisibility.SHARED,
        )
        
        # 按可见性过滤
        skills = manager.list_private_skills("user-1", visibility=SkillVisibility.PRIVATE)
        
        assert len(skills) == 1
        assert skills[0].visibility == SkillVisibility.PRIVATE

    def test_get_private_skill(self, manager):
        """测试获取专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        skill = manager.get_private_skill("my-skill", "user-1")
        
        assert skill is not None
        assert skill.skill_id == "my-skill"
        assert skill.name == "我的技能"

    def test_get_private_skill_not_found(self, manager):
        """测试获取不存在的专属技能"""
        skill = manager.get_private_skill("non-existent", "user-1")
        assert skill is None

    def test_update_private_skill(self, manager):
        """测试更新专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 更新技能
        result = manager.update_private_skill(
            skill_id="my-skill",
            user_id="user-1",
            name="更新后的技能",
            visibility=SkillVisibility.SHARED,
            tags=["updated"],
        )
        
        assert result == True
        
        # 验证更新
        skill = manager.get_private_skill("my-skill", "user-1")
        assert skill.name == "更新后的技能"
        assert skill.visibility == SkillVisibility.SHARED
        assert "updated" in skill.tags

    def test_update_private_skill_not_owner(self, manager):
        """测试非所有者更新专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 尝试用其他用户更新
        result = manager.update_private_skill(
            skill_id="my-skill",
            user_id="user-2",
            name="恶意更新",
        )
        
        assert result == False  # 应该失败

    def test_delete_private_skill(self, manager, tmp_path):
        """测试删除专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 验证目录存在
        skill_dir = tmp_path / "skills" / "private" / "user-1" / "my-skill"
        assert skill_dir.exists()
        
        # 删除技能
        result = manager.delete_private_skill("my-skill", "user-1")
        
        assert result == True
        
        # 验证删除
        skill = manager.get_private_skill("my-skill", "user-1")
        assert skill is None
        
        # 验证目录是否删除
        assert not skill_dir.exists()

    def test_delete_private_skill_not_owner(self, manager):
        """测试非所有者删除专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 尝试用其他用户删除
        result = manager.delete_private_skill("my-skill", "user-2")
        
        assert result == False  # 应该失败

    def test_share_private_skill(self, manager):
        """测试共享专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 共享技能
        result = manager.share_private_skill("my-skill", "user-1", "user-2")
        
        assert result == True
        
        # 验证共享
        skill = manager.get_private_skill("my-skill", "user-1")
        assert skill.visibility == SkillVisibility.SHARED
        assert "user-2" in skill.shared_with

    def test_share_private_skill_not_owner(self, manager):
        """测试非所有者共享专属技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 尝试用其他用户共享
        result = manager.share_private_skill("my-skill", "user-2", "user-3")
        
        assert result == False  # 应该失败

    def test_push_skill_to_agent(self, manager):
        """测试推送技能给Agent"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 推送技能
        result = manager.push_skill_to_agent(
            skill_id="my-skill",
            user_id="user-1",
            agent_id="agent-1",
            is_public=False,
        )
        
        assert result == True
        
        # 验证推送
        skill = manager.get_private_skill("my-skill", "user-1")
        assert "agent-1" in skill.pushed_to_agents

    def test_unpush_skill_from_agent(self, manager):
        """测试从Agent取消推送技能"""
        manager.create_private_skill(
            skill_id="my-skill",
            name="我的技能",
            description="测试描述",
            user_id="user-1",
        )
        
        # 先推送
        manager.push_skill_to_agent(
            skill_id="my-skill",
            user_id="user-1",
            agent_id="agent-1",
            is_public=False,
        )
        
        # 取消推送
        result = manager.unpush_skill_from_agent(
            skill_id="my-skill",
            user_id="user-1",
            agent_id="agent-1",
            is_public=False,
        )
        
        assert result == True
        
        # 验证取消推送
        skill = manager.get_private_skill("my-skill", "user-1")
        assert "agent-1" not in skill.pushed_to_agents

    def test_get_agent_skills(self, manager):
        """测试获取Agent的所有技能"""
        # 创建两个技能并推送给同一个Agent
        manager.create_private_skill(
            skill_id="skill-1",
            name="技能1",
            description="描述1",
            user_id="user-1",
        )
        
        manager.create_private_skill(
            skill_id="skill-2",
            name="技能2",
            description="描述2",
            user_id="user-1",
        )
        
        manager.push_skill_to_agent("skill-1", "user-1", "agent-1", False)
        manager.push_skill_to_agent("skill-2", "user-1", "agent-1", False)
        
        # 获取Agent的技能
        skills = manager.get_agent_skills("agent-1")
        
        assert len(skills) == 2

    def test_admin_list_all_skills(self, manager):
        """测试管理员列出所有技能"""
        # 创建公共技能（需要修改代码支持，这里暂时跳过）
        # 创建专属技能
        manager.create_private_skill(
            skill_id="skill-1",
            name="技能1",
            description="描述1",
            user_id="user-1",
        )
        
        manager.create_private_skill(
            skill_id="skill-2",
            name="技能2",
            description="描述2",
            user_id="user-2",
        )
        
        # 管理员列出所有技能
        skills = manager.admin_list_all_skills()
        
        assert len(skills) == 2

    def test_admin_delete_user_skills(self, manager, tmp_path):
        """测试管理员删除用户的所有专属技能"""
        # 创建两个技能
        manager.create_private_skill(
            skill_id="skill-1",
            name="技能1",
            description="描述1",
            user_id="user-1",
        )
        
        manager.create_private_skill(
            skill_id="skill-2",
            name="技能2",
            description="描述2",
            user_id="user-1",
        )
        
        # 验证技能存在
        skills = manager.list_private_skills("user-1")
        assert len(skills) == 2
        
        # 管理员删除用户的所有技能
        deleted_count = manager.admin_delete_user_skills("user-1")
        
        assert deleted_count == 2
        
        # 验证删除
        skills = manager.list_private_skills("user-1")
        assert len(skills) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
