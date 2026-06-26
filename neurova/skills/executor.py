"""
SkillExecutor - 技能执行器基类

manifest/executor 分离模式：
- Skill dataclass（skills.models.Skill）保持 manifest 角色（元数据）
- SkillExecutor 处理 execute() 方法（行为）
- SkillRegistry 同时管理 manifest 和 executor

这避免修改 skills.models.Skill 的现有 manifest 语义，
同时让 SkillRegistry.execute_skill() 能调用真实执行逻辑。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


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
