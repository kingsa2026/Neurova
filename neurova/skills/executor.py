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


@dataclass
class _SkillInfo:
    """最小 SkillInfo，兼容 SkillRegistry.list_skills() 的访问方式。"""

    name: str
    description: str = ""
    status: str = "active"


@dataclass
class _SkillResult:
    """最小 SkillResult，暴露 success / data / error / metadata 供调用方使用。"""

    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0


class ExecutorBackedSkill:
    """将同步 BaseSkillExecutor 桥接为可被 SkillRegistry 调用的异步 Skill。

    设计要点（规避项目内的模块遮蔽 bug）：
    - neurova/skill_system 同时存在「包」与「文件」两份定义，import 解析到
      包 __init__.py，而该 __init__ 在 from skill_pool_manager import Skill
      失败后会回退为一个**占位 Skill**（仅有 name/description，缺少
      add_event_handler / execute），导致继承该占位类的适配器在
      SkillRegistry.register() 调用 skill.add_event_handler() 时抛 AttributeError。
    - 因此本适配器**不继承**被遮蔽的占位 Skill，而是自包含实现
      SkillRegistry 实际依赖的接口：name、add_event_handler、get_info、
      异步 execute。这样无论 Skill 基类如何被遮蔽都能正常注册与执行。

    - execute() 在线程池中运行同步 executor，避免阻塞事件循环；
    - 将 executor.SkillResult(output=...) 转换为 _SkillResult(data=...)。
    """

    def __init__(self, executor: "BaseSkillExecutor"):
        self._executor = executor
        self.name = executor.skill_id
        self.description = executor.skill_name
        self.status = "active"
        self._event_handlers: List[Callable] = []

    def add_event_handler(self, handler: Callable) -> None:
        self._event_handlers.append(handler)

    def get_info(self) -> _SkillInfo:
        return _SkillInfo(
            name=self.name, description=self.description, status=self.status
        )

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
