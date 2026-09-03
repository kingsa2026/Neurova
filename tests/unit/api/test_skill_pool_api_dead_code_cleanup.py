"""s5 TDD: 清理 skill_pool_api 中的死代码 _get_spm()

背景:
- _get_spm() 定义在 skill_pool_api.py:69, 但全代码库零调用方 (grep _get_spm
  只返回 1 行, 即定义本身).
- 它的语义是"获取 SkillPoolManager 单例", 但 s2/s4 修复后 list_private_skills
  改为直接调用 SkillService, 不再需要 _get_spm 桥接.
- 保留死代码会让后续读者误以为"还有调用方", 增加心智负担.

契约: 删除后, skill_pool_api 模块不应再导出 _get_spm 属性.
"""

import importlib
import inspect


def test_get_spm_is_not_defined_in_skill_pool_api():
    """s5: 删除 _get_spm 后, 该函数不应再存在于 skill_pool_api 模块.

    RED: 当前 _get_spm 存在 → hasattr 返回 True → assert not False 失败.
    GREEN: 删除 _get_spm 定义后 → hasattr 返回 False → 通过.
    """
    mod = importlib.import_module("neurova.api.endpoints.skill_pool_api")
    assert not hasattr(mod, "_get_spm"), (
        "skill_pool_api._get_spm 是死代码 (零调用方), 应删除. "
        "s2/s4 修复后 list_private_skills 直接调用 SkillService, 不再需要此桥接."
    )


def test_skill_generator_is_not_dead_code():
    """s5 守护测试: SkillGenerator 不是死代码, 测试套件仍在使用它.

    防止后续误删 skill_generator.py (此前的 audit 报告将其标为
    "孤立死模块（待确认）", 实际有 23 个测试通过).
    """
    from neurova.skills.skill_generator import SkillGenerator

    # 静态契约: SkillGenerator 是 class 且可实例化
    assert inspect.isclass(SkillGenerator), "SkillGenerator 必须是 class"
    instance = SkillGenerator()
    assert instance is not None, "SkillGenerator 必须可无参实例化"

    # 行为契约: SkillGenerator 暴露 generate_skill 协程
    assert hasattr(instance, "generate_skill"), "SkillGenerator 必须暴露 generate_skill"
    assert inspect.iscoroutinefunction(instance.generate_skill), (
        "generate_skill 必须是 async 方法"
    )
