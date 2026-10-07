"""刀1：github_push 不得另开第二条符号源（红→绿 TDD）

修复前实测缺陷（同一进程内取到的对象不同一）：
- `neurova/skills/builtin/github_push/skill.py:26-39` 用**另一个** cache key
  （`neurova.skill_system_module`）把同一份 `skill_system.py` 再 exec 一遍，
  于是 `Skill`/`SkillResult`/`SkillStatus` 与门面那份是**不同的类对象**。
- 后果可实测：`isinstance(create_github_push_skill(), neurova.skill_system.Skill)`
  为 False —— 注册表 `register_skill()` 的 `isinstance(manifest, Skill)` 分支
  因此对 github_push 产物静默走错路，而装配处的 try/except 只 warning 跳过。

判据只锁"同一符号必须同一对象"这一条契约，不锁符号来自哪个文件——
刀3 把影子文件搬进包内后，本文件断言无需改写仍成立。
"""

import inspect
import sys

import pytest

import neurova.skill_system as facade
from neurova.skills.builtin.github_push import skill as github_push_module


@pytest.fixture
def runtimeSkillModule():
    """门面所发 `Skill` 的真实归属模块（即注册表返回结果的同一归属模块）。"""
    return inspect.getmodule(facade.Skill)


def testGitHubPushSkillIsFacadeSkill():
    """github_push 的产物必须是门面所发 Skill 的实例（不是同名的另一份类）。"""
    from neurova.skills.builtin.github_push.skill import create_github_push_skill

    instance = create_github_push_skill()
    assert isinstance(instance, facade.Skill), (
        "github_push 继承了另一份同名 Skill 类：注册表 isinstance 分支会静默走错路"
    )


def testSkillSymbolsSharedWithRuntimeModule(runtimeSkillModule):
    """Skill / SkillResult 两个符号必须与运行时归属模块同一对象。"""
    assert github_push_module.Skill is facade.Skill
    assert github_push_module.Skill is runtimeSkillModule.Skill
    assert github_push_module.SkillResult is runtimeSkillModule.SkillResult, (
        "github_push 返回的结果类与注册表返回的结果类不同一（同一符号两条取用路径）"
    )


def testNoSecondExecOfSkillSystem():
    """禁止再用 spec_from_file_location 自取第二份符号（防回流源级守卫）。"""
    src = inspect.getsource(github_push_module)
    assert "spec_from_file_location" not in src, (
        "github_push/skill.py 不得反射加载 skill_system——门面已是唯一入口"
    )
    assert "neurova.skill_system_module" not in sys.modules, (
        "不应存在 skill_system 的第二次 exec 缓存键"
    )
