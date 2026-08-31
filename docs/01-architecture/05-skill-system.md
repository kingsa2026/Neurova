# Skill 系统设计

## 1. 概述

### 1.1 设计目标
- 统一的 Skill 接口抽象
- 支持动态注册和执行
- 完善的错误处理和日志
- 支持事件触发机制
- 与记忆系统集成

### 1.2 Skill 分类

```
Skill 系统
├── 内置 Skill
│   ├── 记忆类 (memory) - 记忆搜索和存储
│   ├── 搜索类 (web_search) - 网络搜索
│   └── 文件类 (file_operation) - 文件读写操作
│
└── 自定义 Skill
    └── 通过 SkillRegistry 注册的扩展技能
```

## 2. Skill 数据模型

### 2.1 Skill 状态

```python
from enum import Enum

class SkillStatus(Enum):
    """Skill 状态"""
    ACTIVE = "active"      # 活跃状态
    INACTIVE = "inactive"  # 非活跃状态
    LOADING = "loading"    # 加载中
    ERROR = "error"        # 错误状态
```

### 2.2 Skill 执行结果

```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class SkillResult:
    """Skill 执行结果"""
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
```

### 2.3 Skill 信息

```python
from datetime import datetime

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
```

### 2.4 Skill 事件

```python
from datetime import datetime

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
```

## 3. Skill 接口定义

### 3.1 Skill 抽象基类

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
import logging
import time

class Skill(ABC):
    """Skill 基类"""
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.status = SkillStatus.ACTIVE
        self._event_handlers: List[Callable] = []
    
    @abstractmethod
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
```

## 4. 内置 Skill 实现

### 4.1 记忆 Skill

```python
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
```

### 4.2 网络搜索 Skill

```python
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
```

### 4.3 文件操作 Skill

```python
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
```

## 5. Skill 注册表

### 5.1 核心实现

```python
from typing import Dict, List, Optional, Callable
import threading
import asyncio
import inspect

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
```

### 5.2 默认 Skill 创建

```python
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
```

## 6. Skill 扩展系统

### 6.1 技能市场集成

```python
# skills/models.py 中定义的数据模型

class SkillSource(Enum):
    """技能来源"""
    LOCAL = "local"           # 本地技能
    MARKETPLACE = "marketplace"  # 市场技能
    BUILTIN = "builtin"       # 内置技能

@dataclass
class Skill:
    """技能主模型"""
    id: str = ""
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    source: SkillSource = SkillSource.LOCAL
    enabled: bool = True
    metadata: Optional[SkillMetadata] = None
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
```

### 6.2 技能注册表（市场版）

```python
class SkillRegistry:
    """
    SkillRegistry - 中央注册表
    
    实现Singleton模式，确保全局唯一的注册表实例。
    线程安全的技能注册与管理。
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """初始化注册表（仅执行一次）"""
        if self._initialized:
            return
        
        self._skills: Dict[str, Tuple[Skill, Path]] = {}
        self._startup_hooks: List[HookRegistration] = []
        self._shutdown_hooks: List[HookRegistration] = []
        self._control_commands: List[ControlCommandRegistration] = []
        self._event_callbacks: Dict[str, List[Callable]] = {}
        self._runtime_helpers: Dict[str, Any] = {}
        self._initialized = True
        self._logger = logging.getLogger(__name__)
    
    def register_skill(self, manifest: Skill, path: Path) -> bool:
        """注册技能"""
        with self._lock:
            if manifest.id in self._skills:
                self._logger.warning(f"技能 {manifest.id} 已注册")
                return False
            
            self._skills[manifest.id] = (manifest, path)
            self._trigger_event("skill_registered", {"skill_id": manifest.id})
            return True
    
    def register(self, manifest: Skill, path: Path) -> bool:
        """注册技能（别名）"""
        return self.register_skill(manifest, path)
    
    def execute_skill(self, skill_id: str, *args, **kwargs) -> Any:
        """执行技能"""
        skill_info = self.get_skill(skill_id)
        if skill_info is None:
            raise ValueError(f"技能 {skill_id} 未注册")
        
        manifest, path = skill_info
        self._trigger_event("skill_executing", {"skill_id": skill_id})
        
        # 这里可以添加实际的技能执行逻辑
        # 目前返回一个模拟结果
        return {"skill_id": skill_id, "status": "executed"}
```

## 7. 事件系统

### 7.1 事件类型

```python
# 支持的事件类型
EVENT_TYPES = [
    "before_execute",    # 执行前
    "after_execute",     # 执行后
    "error",            # 错误
    "skill_registered",  # 技能注册
    "skill_unregistered",  # 技能注销
    "skill_executing",   # 技能执行中
]
```

### 7.2 事件处理

```python
class EventHandler:
    """事件处理器"""
    
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}
    
    def register(self, event_type: str, handler: Callable):
        """注册事件处理器"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def unregister(self, event_type: str, handler: Callable):
        """注销事件处理器"""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]
    
    async def trigger(self, event_type: str, data: Any = None):
        """触发事件"""
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logging.getLogger(__name__).error(f"事件处理失败: {e}")
```

## 8. 配置示例

### 8.1 Skill 配置

```yaml
# skills.yaml
skills:
  # 内置 Skill
  - id: "memory"
    enabled: true
    config:
      max_results: 10
  
  - id: "web_search"
    enabled: true
    config:
      default_engine: "google"
      api_key: "${GOOGLE_SEARCH_API_KEY}"
  
  - id: "file_operation"
    enabled: true
    config:
      allowed_directories:
        - "/app/data"
        - "/tmp"
      max_file_size: 10485760  # 10MB
  
  # 自定义 Skill
  - id: "custom_analyzer"
    path: "/app/skills/analyzer.py"
    enabled: true
    config:
      model_path: "/app/models/analyzer.pkl"
```

### 8.2 事件配置

```yaml
# events.yaml
events:
  # 执行前事件
  before_execute:
    - handler: "log_execution"
      level: "info"
  
  # 执行后事件
  after_execute:
    - handler: "record_metrics"
      enabled: true
  
  # 错误事件
  error:
    - handler: "send_alert"
      enabled: true
      channels: ["email", "slack"]
```

## 9. 最佳实践

### 9.1 Skill 开发规范

1. **单一职责**: 每个 Skill 只负责一个特定功能
2. **错误处理**: 所有异常都应该被捕获并返回 SkillResult
3. **性能监控**: 记录执行时间用于性能分析
4. **日志记录**: 使用结构化日志记录关键操作
5. **资源清理**: 在 Skill 关闭时释放所有资源

### 9.2 事件使用规范

1. **事件命名**: 使用小写字母和下划线，如 `before_execute`
2. **事件数据**: 保持事件数据简单，避免传递复杂对象
3. **错误处理**: 事件处理器中的异常不应影响主流程
4. **性能考虑**: 避免在事件处理器中执行耗时操作

### 9.3 注册表使用规范

1. **线程安全**: 注册表操作是线程安全的
2. **单例模式**: 使用单例模式确保全局唯一
3. **生命周期管理**: 正确处理 Skill 的注册和注销
4. **资源管理**: 在系统关闭时清理所有 Skill

## 10. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-06-07 | 初始版本，基于当前 skill_system.py 实现 |

---

**最后更新**: 2026-06-07
**维护者**: Neurova 开发团队