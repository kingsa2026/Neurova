"""
GitHub Push Skill 测试

测试 GitHub 推送技能的各种功能
"""

import pytest
import asyncio
import subprocess
import tempfile
import shutil
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

#: 临时仓里 `git init/config` 的预算唯一出处（毫秒级；此前无 `timeout=`＝无界等待）。
#: 取低于全局 30s 的 20s——先到点的应当是子进程那条诚实的 TimeoutExpired，而不是 thread 法
#: 的全局墙把整场跑测带走（§6-402 批 K 口径）。
GIT_WALL_S = 20

# 添加项目根目录到路径
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from neurova.skills.builtin.github_push import GitHubPushSkill, create_github_push_skill, push_to_github
from neurova.skill_system import SkillResult


class TestGitHubPushSkill:
    """GitHub Push Skill 测试类"""

    def setup_method(self):
        """每个测试方法前设置"""
        self.skill = create_github_push_skill()
        self.test_dir = None

    def teardown_method(self):
        """每个测试方法后清理"""
        if self.test_dir and self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_skill_creation(self):
        """测试技能创建"""
        assert self.skill.name == "github_push"
        assert "GitHub" in self.skill.description
        assert self.skill.status.value == "active"

    def test_skill_info(self):
        """测试技能信息"""
        info = self.skill.get_info()
        assert info.name == "github_push"
        assert "git" in info.tags
        assert "github" in info.tags
        # 现行 SkillInfo.parameters 为参数定义 dict 列表（name 键），非映射。
        # 残留处理 2026-09-13 适配形状，意图保留。
        param_names = {p.get("name") for p in info.parameters}
        assert "action" in param_names
        assert "message" in param_names

    @pytest.mark.asyncio
    async def test_get_status(self):
        """测试获取状态"""
        # 创建临时目录作为测试仓库
        self.test_dir = Path(tempfile.mkdtemp())
        (self.test_dir / "test.txt").write_text("test content")

        # 初始化 git 仓库：目录交给 `cwd=` 传，不经 shell。
        # 原形是 `os.system(f"cd {self.test_dir} && git init")`——Windows 的 cmd 里
        # `cd D:\x` 不改盘符，于是这条命令实际跑在 pytest 的 CWD（＝开发者仓库根）上，
        # 实测 stdout `Reinitialized existing Git repository in E:/…/.git/`：一次单元跑测
        # 在开发者的仓里 git init，并接着改写 user.name/user.email（§6-196 批 39）。
        for args in (["git", "init"],
                     ["git", "config", "user.email", "b39-scratch@example.invalid"],
                     ["git", "config", "user.name", "B39 Scratch"]):
            subprocess.run(args, cwd=str(self.test_dir), check=True,
                           capture_output=True, encoding="utf-8", errors="replace",
                           timeout=GIT_WALL_S)

        # 测试状态获取
        self.skill.repo_path = self.test_dir
        result = await self.skill.execute({"action": "status"})

        assert result.success
        assert "files" in result.data
        assert "clean" in result.data

    @pytest.mark.asyncio
    async def test_full_push_workflow(self):
        """测试完整推送工作流"""
        # 这个测试需要实际的 Git 仓库和远程仓库
        # 在实际环境中可以跳过
        pytest.skip("需要实际 Git 仓库环境")

    def test_create_github_push_skill(self):
        """测试创建技能的便捷函数"""
        skill = create_github_push_skill()
        assert isinstance(skill, GitHubPushSkill)
        assert skill.name == "github_push"

    @pytest.mark.asyncio
    async def test_push_to_github_function(self):
        """测试 push_to_github 便捷函数"""
        # 这个测试需要实际的 Git 仓库
        pytest.skip("需要实际 Git 仓库环境")

    @pytest.mark.asyncio
    async def test_error_handling(self):
        """测试错误处理"""
        # 测试未知操作
        result = await self.skill.execute({"action": "unknown"})
        assert not result.success
        assert "未知操作" in result.error

    def test_skill_parameters(self):
        """测试技能参数定义"""
        info = self.skill.get_info()
        # 列表形参数面 → 建 name→定义 映射后原断言保持（残留处理 2026-09-13）
        params = {p.get("name"): p for p in info.parameters}

        # 检查必要参数
        assert "action" in params
        assert "message" in params
        assert "push_to_main" in params

        # 检查参数类型
        assert params["action"]["type"] == "string"
        assert params["push_to_main"]["type"] == "boolean"


class TestGitHubPushSkillIntegration:
    """GitHub Push Skill 集成测试"""

    @pytest.mark.asyncio
    async def test_skill_registration(self):
        """测试技能注册"""
        from neurova.skill_system import create_default_skills

        registry = create_default_skills()
        assert registry.has_skill("github_push")

        skill = registry.get_skill("github_push")
        assert skill is not None
        assert skill.name == "github_push"


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])