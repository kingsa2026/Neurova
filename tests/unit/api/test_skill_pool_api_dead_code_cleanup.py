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


# P1-13（全库断点审计 2026-11-12，拍板：退役）：原 test_skill_generator_is_not_dead_code
# 随 skill_generator.py 退役摘除——"测试套件仍在使用它"不构成生产在役判据
# （测试代码不计入消费方），与教义第 7 条的口径一致。
