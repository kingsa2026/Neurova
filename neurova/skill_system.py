"""
Skill System - Skill 执行系统
管理 Agent 可用的技能/工具，支持动态注册、执行和权限控制

D1 任务重构版本：
- 增强事件触发能力（预留事件总线接口）
- Skill 执行前后触发事件通知
- 保持 SkillRegistry 向后兼容
"""

import logging
import inspect
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

class SkillStatus(Enum):
    """Skill 状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOADING = "loading"
    ERROR = "error"

@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0

@dataclass
class SkillInfo:
    """Skill 信息"""
    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    required_params: List[str] = field(default_factory=list)
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

class SkillEvent:
    """Skill 事件"""

    def __init__(self, event_type: str, skill_name: str, data: Any = None):
        self.event_type = event_type
        self.skill_name = skill_name
        self.data = data
        self.timestamp = datetime.now()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "skill_name": self.skill_name,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }

class Skill:
    """Skill 基类"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.status = SkillStatus.ACTIVE
        self._event_handlers: List[Callable] = []

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """
        执行 Skill

        Args:
            params: 参数
            context: 上下文

        Returns:
            执行结果
        """
        raise NotImplementedError("子类必须实现 execute 方法")

    def get_info(self) -> SkillInfo:
        """获取 Skill 信息"""
        return SkillInfo(
            name=self.name,
            description=self.description,
            status=self.status,
        )

    def add_event_handler(self, handler: Callable):
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def _emit_event(self, event_type: str, data: Any = None):
        """触发事件"""
        event = SkillEvent(event_type, self.name, data)
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logging.getLogger(__name__).error(f"事件处理失败: {e}")

class MemorySkill(Skill):
    """记忆 Skill"""

    def __init__(self, memory_manager=None):
        super().__init__("memory", "记忆管理 Skill")
        self.memory_manager = memory_manager

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """执行记忆操作"""
        start_time = time.time()

        try:
            action = params.get("action", "search")

            if action == "search":
                query = params.get("query", "")
                results = await self._search_memory(query, params)
                return SkillResult(
                    success=True,
                    data=results,
                    execution_time=time.time() - start_time,
                )
            elif action == "store":
                content = params.get("content", "")
                result = await self._store_memory(content, params)
                return SkillResult(
                    success=True,
                    data=result,
                    execution_time=time.time() - start_time,
                )
            else:
                return SkillResult(
                    success=False,
                    error=f"未知操作: {action}",
                    execution_time=time.time() - start_time,
                )

        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def _search_memory(self, query: str, params: Dict) -> List[Dict]:
        """搜索记忆"""
        # 这里应该调用记忆管理器
        return []

    async def _store_memory(self, content: str, params: Dict) -> Dict:
        """存储记忆"""
        # 这里应该调用记忆管理器
        return {"stored": True}

class WebSearchSkill(Skill):
    """网络搜索 Skill"""

    def __init__(self):
        super().__init__("web_search", "网络搜索 Skill")

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """执行网络搜索"""
        start_time = time.time()

        try:
            query = params.get("query", "")
            results = await self._search_web(query, params)
            return SkillResult(
                success=True,
                data=results,
                execution_time=time.time() - start_time,
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def _search_web(self, query: str, params: Dict) -> List[Dict]:
        """搜索网络"""
        # 这里应该实现网络搜索逻辑
        return []

class FileOperationSkill(Skill):
    """文件操作 Skill"""

    def __init__(self):
        super().__init__("file_operation", "文件操作 Skill")

    async def execute(self, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """执行文件操作"""
        start_time = time.time()

        try:
            operation = params.get("operation", "read")

            if operation == "read":
                file_path = params.get("file_path", "")
                result = await self._read_file(file_path, params)
                return SkillResult(
                    success=True,
                    data=result,
                    execution_time=time.time() - start_time,
                )
            elif operation == "write":
                file_path = params.get("file_path", "")
                content = params.get("content", "")
                result = await self._write_file(file_path, content, params)
                return SkillResult(
                    success=True,
                    data=result,
                    execution_time=time.time() - start_time,
                )
            else:
                return SkillResult(
                    success=False,
                    error=f"未知操作: {operation}",
                    execution_time=time.time() - start_time,
                )

        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                execution_time=time.time() - start_time,
            )

    async def _read_file(self, file_path: str, params: Dict) -> Dict:
        """读取文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return {"content": content, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _write_file(self, file_path: str, content: str, params: Dict) -> Dict:
        """写入文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

class SkillRegistry:
    """Skill 注册表"""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._event_handlers: List[Callable] = []

    def register(self, skill: Skill):
        """注册 Skill"""
        self._skills[skill.name] = skill
        skill.add_event_handler(self._on_skill_event)

    def unregister(self, skill_name: str):
        """注销 Skill"""
        if skill_name in self._skills:
            del self._skills[skill_name]

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """获取 Skill"""
        return self._skills.get(skill_name)

    def has_skill(self, skill_name: str) -> bool:
        """检查 Skill 是否存在"""
        return skill_name in self._skills

    def list_skills(self) -> List[SkillInfo]:
        """列出所有 Skill"""
        return [skill.get_info() for skill in self._skills.values()]

    def get_skill_names(self) -> List[str]:
        """获取所有 Skill 名称"""
        return list(self._skills.keys())

    async def execute_skill(self, skill_name: str, params: Dict[str, Any], context: Optional[Dict] = None) -> SkillResult:
        """执行 Skill"""
        skill = self.get_skill(skill_name)
        if not skill:
            return SkillResult(success=False, error=f"Skill {skill_name} 不存在")

        # 触发前置事件
        self._emit_event("before_execute", skill_name, params)

        try:
            result = await skill.execute(params, context)

            # 触发后置事件
            self._emit_event("after_execute", skill_name, result)

            return result
        except Exception as e:
            # 触发错误事件
            self._emit_event("error", skill_name, {"error": str(e)})
            return SkillResult(success=False, error=str(e))

    def add_event_handler(self, handler: Callable):
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def _on_skill_event(self, event: SkillEvent):
        """处理 Skill 事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logging.getLogger(__name__).error(f"事件处理失败: {e}")

    def _emit_event(self, event_type: str, skill_name: str, data: Any = None):
        """触发事件"""
        event = SkillEvent(event_type, skill_name, data)
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logging.getLogger(__name__).error(f"事件处理失败: {e}")

def create_default_skills(memory_manager=None) -> SkillRegistry:
    """
    创建默认 Skill 注册表

    Args:
        memory_manager: 记忆管理器

    Returns:
        Skill 注册表
    """
    registry = SkillRegistry()

    # 注册默认 Skill
    registry.register(MemorySkill(memory_manager))
    registry.register(WebSearchSkill())
    registry.register(FileOperationSkill())

    return registry