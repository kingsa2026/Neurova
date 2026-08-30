"""
技能事件类型门面模块

ADR 0011：技能系统统一收敛到 ``neurova.skills`` 包。

历史包袱：``neurova/skill_system/`` 是包，而 ``neurova/skill_system.py``
是同名单文件（被包遮蔽），``SkillEvent`` / ``SkillRegistry`` 实际定义在那个
单文件里，只能通过 ``neurova.skill_system`` 包的 ``__getattr__`` 反射加载。

各业务模块直接写 ``from neurova.skill_system import SkillEvent`` 会把这个
反射细节泄漏到全代码库。本模块提供稳定的导入入口，调用方统一写
``from neurova.skills.events import SkillEvent``。
"""

from neurova.skill_system import SkillEvent, SkillRegistry

__all__ = ["SkillEvent", "SkillRegistry"]
