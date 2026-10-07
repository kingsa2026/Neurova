"""
SkillExecutor - 技能执行器基类

manifest/executor 分离模式：
- Skill dataclass（skills.models.Skill）保持 manifest 角色（元数据）
- SkillExecutor 处理 execute() 方法（行为）
- SkillRegistry 同时管理 manifest 和 executor

这避免修改 skills.models.Skill 的现有 manifest 语义，
同时让 SkillRegistry.execute_skill() 能调用真实执行逻辑。
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 运行层符号单一事实源：注册表与 agent 热路径读的是 core 那份（data 形状）。
# executor 层的 SkillResult(output=...) 只服务 executor 内部，两者在桥接处显式转换。
from neurova.skill_system.core import Skill as _RuntimeSkill
from neurova.skill_system.core import SkillResult as _SkillResult


@dataclass
class SkillResult:
    """技能执行结果

    Attributes:
        success: 执行是否成功
        output: 执行输出（成功时）
        error: 错误信息（失败时）
        metadata: 执行元数据（执行时间、调用次数等）
    """

    success: bool = True
    output: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillExecutor(ABC):
    """技能执行器抽象基类

    子类必须实现 execute() 方法。
    属性 skill_id / skill_name 由 BaseSkillExecutor 提供。
    """

    @abstractmethod
    def execute(self, *args, **kwargs) -> SkillResult:
        """执行技能

        Args:
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            SkillResult: 执行结果
        """
        ...


class BaseSkillExecutor(SkillExecutor):
    """技能执行器基类（提供通用 __init__ 和 __repr__）

    子类只需实现 execute() 方法。
    """

    def __init__(self, skill_id: str, skill_name: str = ""):
        self.skill_id = skill_id
        self.skill_name = skill_name or skill_id

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(skill_id={self.skill_id!r}, skill_name={self.skill_name!r})"


class ExecutorBackedSkill(_RuntimeSkill):
    """将同步 BaseSkillExecutor 桥接为可被 SkillRegistry 调用的异步 Skill。

    - 继承运行时 Skill 基类：`SkillRegistry.register_skill()` 的
      `isinstance(manifest, Skill)` 分支据此才走得到正确入口；
    - execute() 在线程池中运行同步 executor，避免阻塞事件循环；
    - 把 executor 层的 SkillResult(output=...) 转成运行层的
      SkillResult(data=...)——后者才是注册表与 agent 热路径读的那份。
    """

    def __init__(self, executor: "BaseSkillExecutor"):
        super().__init__(executor.skill_id, executor.skill_name)
        self._executor = executor

    def _get_parameters(self) -> Dict[str, Any]:
        """获取该技能的工具参数 Schema（OpenAI function calling 格式）。

        为内置技能返回完整参数定义；否则返回空 dict。
        （工具 schema 退化修复：避免桥接技能因缺少 _get_parameters 而以空参数进列表，
        让 LLM 看到"不知道传什么参"而不调用工具。）
        """
        try:
            from neurova.skills.builtin.schemas import get_builtin_skill_parameters

            return get_builtin_skill_parameters(self.name)
        except Exception:
            return {}

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None):
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._executor.execute, params)
        if result is None:
            return _SkillResult(success=False, error="executor 返回空结果")
        return _SkillResult(
            success=result.success,
            data=result.output,
            error=result.error,
            metadata=result.metadata,
        )
