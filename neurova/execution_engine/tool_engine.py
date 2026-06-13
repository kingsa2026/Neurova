"""
工具引擎 - 手脚的核心

Neurova CogArch 1.0.0 的执行组件之一
负责：智能工具选择、自动参数填充、安全执行、工具调用记录、工具链执行
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import functools
import inspect
import logging
import typing
import uuid
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


def cache_token(func_name: str, args: tuple, kwargs: dict) -> str:
    """生成缓存键"""
    import hashlib

    key = f"{func_name}:{args}:{sorted(kwargs.items())}"
    return hashlib.md5(key.encode()).hexdigest()


def cached(ttl: float = 300):
    """缓存装饰器（简化版）"""

    def decorator(func):
        _cache: typing.Dict[str, typing.Tuple[float, typing.Any]] = {}

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            key = cache_token(func.__name__, args, kwargs)
            now = datetime.datetime.now().timestamp()

            if key in _cache:
                ts, val = _cache[key]
                if now - ts < ttl:
                    return val

            result = await func(*args, **kwargs)
            _cache[key] = (now, result)
            return result

        wrapper._cache = _cache
        return wrapper

    return decorator


class ToolStatus(Enum):
    """工具状态"""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


@dataclass
class ToolParameter:
    """工具参数定义"""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    default: typing.Any = None
    enum_values: typing.Optional[typing.List[str]] = None
    constraints: typing.Optional[typing.Dict[str, typing.Any]] = None

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        d = {"name": self.name, "type": self.type, "description": self.description, "required": self.required}
        if self.default is not None:
            d["default"] = self.default
        if self.enum_values:
            d["enum"] = self.enum_values
        return d


@dataclass
class ToolDefinition:
    """工具定义"""

    name: str
    description: str = ""
    parameters: typing.List[ToolParameter] = field(default_factory=list)
    status: ToolStatus = ToolStatus.AVAILABLE
    version: str = "1.0.0"
    tags: typing.List[str] = field(default_factory=list)
    owner: str = ""
    shared_with: typing.List[str] = field(default_factory=list)
    is_public: bool = False

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [p.to_dict() for p in self.parameters],
            "status": self.status.value,
            "version": self.version,
            "tags": self.tags,
            "owner": self.owner,
            "is_public": self.is_public,
        }


@dataclass
class ToolInvocation:
    """工具调用记录"""

    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    arguments: typing.Dict[str, typing.Any] = field(default_factory=dict)
    result: typing.Any = None
    error: typing.Optional[str] = None
    start_time: typing.Optional[datetime.datetime] = None
    end_time: typing.Optional[datetime.datetime] = None
    duration: typing.Optional[float] = None
    success: bool = True
    user_id: typing.Optional[str] = None
    agent_id: typing.Optional[str] = None

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        return {
            "invocation_id": self.invocation_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "error": self.error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration": self.duration,
            "success": self.success,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
        }


@dataclass
class ToolSelection:
    """工具选择结果"""

    tool_name: str
    confidence: float
    reason: str = ""
    parameters: typing.Dict[str, typing.Any] = field(default_factory=dict)


@dataclass
class ToolCallingContext:
    """工具调用上下文"""

    agent_id: str = ""
    user_id: str = ""
    session_id: str = ""
    conversation_history: typing.List[typing.Dict[str, typing.Any]] = field(default_factory=list)
    metadata: typing.Dict[str, typing.Any] = field(default_factory=dict)


@dataclass
class ToolVersion:
    """工具版本"""

    version: str
    tool_func: typing.Optional[typing.Callable] = None
    definition: typing.Optional[ToolDefinition] = None
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    is_active: bool = True


@dataclass
class ToolDiscoveryResult:
    """工具发现结果"""

    tools: typing.List[ToolDefinition] = field(default_factory=list)
    source: str = ""
    discovered_at: datetime.datetime = field(default_factory=datetime.datetime.now)


class ToolEngine:
    """
    工具引擎

    管理工具注册、执行、版本控制、共享和发现。
    """

    def __init__(self, config: typing.Dict[str, typing.Any] = None, tool_guard: typing.Any = None):
        self._config = config or {}
        self._lock = __import__("threading").RLock()
        self.tool_guard = tool_guard or self._create_default_guard()

        # 工具注册表
        self._tools: typing.Dict[str, ToolDefinition] = {}
        self._tool_funcs: typing.Dict[str, typing.Callable] = {}

        # 版本控制
        self._versions: typing.Dict[str, typing.List[ToolVersion]] = {}

        # 调用历史
        self._invocations: collections.deque = collections.deque(maxlen=10000)

        # 共享记录
        self._shared_tools: typing.Dict[str, typing.List[str]] = {}  # tool_name -> [user_ids]

    def _create_default_guard(self):
        """创建默认的工具守卫"""

        class DefaultGuard:
            def guard(self, **kwargs):
                return type("GuardResult", (), {"is_safe": True, "findings": []})()

        return DefaultGuard()

        logger.info("ToolEngine 初始化完成")

    def register_tool(
        self,
        tool_name: str,
        tool_func: typing.Callable,
        description: str = "",
        parameters: typing.List[ToolParameter] = None,
        tags: typing.List[str] = None,
        status: ToolStatus = None,
        owner: str = "",
        is_public: bool = False,
    ) -> None:
        """注册工具

        Args:
            tool_name: 工具名称
            tool_func: 工具函数
            description: 工具描述
            parameters: 参数定义列表
            tags: 标签列表
            status: 工具状态
            owner: 工具所有者（用于多租户隔离）
            is_public: 是否公开
        """
        with self._lock:
            # 提取参数信息
            if parameters is None:
                parameters = self._extract_parameters(tool_func)

            definition = ToolDefinition(
                name=tool_name,
                description=description or (tool_func.__doc__ or "").strip(),
                parameters=parameters,
                tags=tags or [],
                status=status or ToolStatus.AVAILABLE,
                owner=owner,
                is_public=is_public,
            )

            self._tools[tool_name] = definition
            self._tool_funcs[tool_name] = tool_func

            # 创建初始版本
            if tool_name not in self._versions:
                self._versions[tool_name] = []
            self._versions[tool_name].append(ToolVersion(version="1.0.0", tool_func=tool_func, definition=definition))

            logger.debug("工具已注册: %s", tool_name)

    def unregister_tool(self, tool_name: str) -> bool:
        """取消注册工具"""
        with self._lock:
            if tool_name in self._tools:
                del self._tools[tool_name]
                del self._tool_funcs[tool_name]
                logger.debug("工具已取消注册: %s", tool_name)
                return True
            return False

    def get_tool(self, tool_name: str) -> typing.Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(tool_name)

    def list_tools(self, status: ToolStatus = None, tags: typing.List[str] = None) -> typing.List[ToolDefinition]:
        """列出工具"""
        tools = list(self._tools.values())
        if status:
            tools = [t for t in tools if t.status == status]
        if tags:
            tools = [t for t in tools if any(tag in t.tags for tag in tags)]
        return tools

    def get_tool_versions(self, tool_name: str) -> typing.List[ToolVersion]:
        """获取工具版本列表"""
        return self._versions.get(tool_name, [])

    def get_tool_version(self, tool_name: str, version: str) -> typing.Optional[ToolVersion]:
        """获取特定版本"""
        for v in self._versions.get(tool_name, []):
            if v.version == version:
                return v
        return None

    def set_active_version(self, tool_name: str, version: str) -> bool:
        """设置活跃版本"""
        with self._lock:
            for v in self._versions.get(tool_name, []):
                if v.version == version:
                    v.is_active = True
                    if v.tool_func:
                        self._tool_funcs[tool_name] = v.tool_func
                    if v.definition:
                        self._tools[tool_name] = v.definition
                    # 将其他版本设为非活跃
                    for other in self._versions[tool_name]:
                        if other.version != version:
                            other.is_active = False
                    return True
            return False

    def share_tool_with_user(self, tool_name: str, user_id: str) -> bool:
        """与用户共享工具"""
        with self._lock:
            if tool_name not in self._tools:
                return False
            if tool_name not in self._shared_tools:
                self._shared_tools[tool_name] = []
            if user_id not in self._shared_tools[tool_name]:
                self._shared_tools[tool_name].append(user_id)
                self._tools[tool_name].shared_with.append(user_id)
            return True

    def unshare_tool_with_user(self, tool_name: str, user_id: str) -> bool:
        """取消共享"""
        with self._lock:
            if tool_name in self._shared_tools and user_id in self._shared_tools[tool_name]:
                self._shared_tools[tool_name].remove(user_id)
                if user_id in self._tools[tool_name].shared_with:
                    self._tools[tool_name].shared_with.remove(user_id)
                return True
            return False

    def publish_tool(self, tool_name: str) -> bool:
        """发布工具为公开"""
        with self._lock:
            if tool_name in self._tools:
                self._tools[tool_name].is_public = True
                return True
            return False

    def unpublish_tool(self, tool_name: str) -> bool:
        """取消发布"""
        with self._lock:
            if tool_name in self._tools:
                self._tools[tool_name].is_public = False
                return True
            return False

    def get_tools_shared_with_me(self, user_id: str) -> typing.List[ToolDefinition]:
        """获取与我共享的工具"""
        return [t for t in self._tools.values() if user_id in t.shared_with]

    def get_my_shared_tools(self, owner: str) -> typing.List[ToolDefinition]:
        """获取我共享的工具"""
        return [t for t in self._tools.values() if t.owner == owner and t.shared_with]

    def discover_public_tools(self) -> ToolDiscoveryResult:
        """发现公开工具"""
        public = [t for t in self._tools.values() if t.is_public]
        return ToolDiscoveryResult(tools=public, source="local")

    def discover_tools(self, query: str = "", tags: typing.List[str] = None) -> ToolDiscoveryResult:
        """发现工具"""
        tools = list(self._tools.values())
        if query:
            tools = [t for t in tools if query.lower() in t.name.lower() or query.lower() in t.description.lower()]
        if tags:
            tools = [t for t in tools if any(tag in t.tags for tag in tags)]
        return ToolDiscoveryResult(tools=tools, source="local")

    def select_tools(
        self, query: str, context: ToolCallingContext = None, top_k: int = 3
    ) -> typing.List[ToolSelection]:
        """智能工具选择"""
        results = []
        query_lower = query.lower()

        for name, defn in self._tools.items():
            if defn.status != ToolStatus.AVAILABLE:
                continue

            # 简单匹配：名称 + 描述 + 标签
            score = 0.0
            if query_lower in name.lower():
                score += 0.5
            if query_lower in defn.description.lower():
                score += 0.3
            for tag in defn.tags:
                if query_lower in tag.lower():
                    score += 0.2

            if score > 0:
                results.append(ToolSelection(tool_name=name, confidence=min(score, 1.0), reason=f"匹配查询: {query}"))

        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:top_k]

    def prepare_arguments(self, tool_name: str, raw_args: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any]:
        """准备工具参数

        对于没有定义参数的工具（如 MCP 动态工具），直接透传原始参数。
        """
        defn = self._tools.get(tool_name)
        if not defn:
            return raw_args

        # 无显式参数定义时，直接透传原始参数（支持 **kwargs 动态工具如 MCP）
        if not defn.parameters:
            return raw_args

        prepared = {}
        missing_required = []
        for param in defn.parameters:
            if param.name in raw_args:
                prepared[param.name] = raw_args[param.name]
            elif param.default is not None:
                prepared[param.name] = param.default
            elif param.required:
                missing_required.append(param.name)

        if missing_required:
            raise ValueError(f"缺少必需参数: {', '.join(missing_required)}")

        return prepared

    async def _validate_parameters(
        self, tool_def: typing.Union[str, ToolDefinition], parameters: typing.Dict[str, typing.Any]
    ) -> None:
        """验证参数类型和约束"""
        if isinstance(tool_def, str):
            defn = self._tools.get(tool_def)
        else:
            defn = tool_def

        if not defn:
            return

        for param in defn.parameters:
            if param.name not in parameters:
                if param.required:
                    raise ValueError(f"缺少必需参数: {param.name}")
                continue

            value = parameters[param.name]

            # 类型验证
            type_checks = {
                "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
                "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
                "string": lambda v: isinstance(v, str),
                "boolean": lambda v: isinstance(v, bool),
                "array": lambda v: isinstance(v, list),
                "object": lambda v: isinstance(v, dict),
            }

            if param.type in type_checks and not type_checks[param.type](value):
                raise ValueError(f"参数 {param.name} 类型错误: 期望 {param.type}, 实际 {type(value).__name__}")

            # 约束验证
            if param.constraints:
                if param.type in ("integer", "number"):
                    if "min" in param.constraints and value < param.constraints["min"]:
                        raise ValueError(f"参数 {param.name} 小于最小值 {param.constraints['min']}")
                    if "max" in param.constraints and value > param.constraints["max"]:
                        raise ValueError(f"参数 {param.name} 大于最大值 {param.constraints['max']}")

    async def execute(
        self,
        tool_name: str,
        parameters: typing.Dict[str, typing.Any] = None,
        timeout: float = None,
        context: ToolCallingContext = None,
    ) -> typing.Any:
        """执行工具"""
        invocation = ToolInvocation(tool_name=tool_name, arguments=parameters or {}, start_time=datetime.datetime.now())

        try:
            func = self._tool_funcs.get(tool_name)
            if func is None:
                raise ValueError(f"工具未注册: {tool_name}")

            # 准备参数
            prepared = self.prepare_arguments(tool_name, parameters or {})

            # 执行
            if inspect.iscoroutinefunction(func):
                if timeout:
                    result = await asyncio.wait_for(func(**prepared), timeout=timeout)
                else:
                    result = await func(**prepared)
            else:
                result = func(**prepared)

            invocation.result = result
            invocation.success = True

        except Exception as e:
            invocation.error = str(e)
            invocation.success = False
            logger.error("工具执行失败: %s, 错误: %s", tool_name, e)
            raise
        finally:
            invocation.end_time = datetime.datetime.now()
            invocation.duration = (invocation.end_time - invocation.start_time).total_seconds()
            self._invocations.append(invocation)

        return invocation.result

    async def execute_with_safeguards(
        self,
        tool_name: str,
        parameters: typing.Dict[str, typing.Any] = None,
        timeout: float = 30,
        context: ToolCallingContext = None,
        user_id: str = None,
        agent_id: str = None,
    ) -> typing.Any:
        """安全执行工具（带防护）"""
        # 检查工具状态
        defn = self._tools.get(tool_name)
        if not defn:
            raise ValueError(f"工具未注册: {tool_name}")
        if defn.status != ToolStatus.AVAILABLE:
            raise ValueError(f"工具不可用: {tool_name}, 状态: {defn.status.value}")

        # 执行工具
        result = await self.execute(tool_name, parameters, timeout, context)

        # 更新调用记录的用户信息
        if self._invocations:
            last_invocation = self._invocations[-1]
            if last_invocation.tool_name == tool_name:
                last_invocation.user_id = user_id
                last_invocation.agent_id = agent_id

        return result

    async def chain_tools(
        self, chain: typing.List[typing.Dict[str, typing.Any]], initial_input: typing.Any = None
    ) -> typing.Any:
        """链式执行工具"""
        result = initial_input

        for step in chain:
            tool_name = step.get("tool_name", "")
            params = step.get("parameters", {})

            # 将上一步结果注入参数
            if result is not None and "input_key" in step:
                params[step["input_key"]] = result

            result = await self.execute(tool_name, params)

        return result

    def _extract_parameters(self, func: typing.Callable) -> typing.List[ToolParameter]:
        """从函数签名提取参数"""
        parameters = []
        try:
            sig = inspect.signature(func)
            for name, param in sig.parameters.items():
                if name in ("self", "cls"):
                    continue
                # 跳过 *args 和 **kwargs
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue
                p = ToolParameter(
                    name=name,
                    type="string",
                    required=param.default is inspect.Parameter.empty,
                    default=None if param.default is inspect.Parameter.empty else param.default,
                )
                parameters.append(p)
        except Exception:
            pass
        return parameters

    def _is_skill_tool(self, tool_name: str) -> bool:
        """检查是否为技能工具"""
        return tool_name.startswith("skill.")

    def get_tool_history(self, tool_name: str, user_id: str = None, limit: int = 100) -> typing.List[ToolInvocation]:
        """获取工具调用历史"""
        invocations = list(self._invocations)

        # 按工具名过滤
        invocations = [i for i in invocations if i.tool_name == tool_name]

        # 按用户ID过滤（如果提供）
        if user_id is not None:
            invocations = [i for i in invocations if getattr(i, "user_id", None) == user_id]

        # 按时间倒序排序
        invocations.sort(key=lambda x: x.start_time or datetime.datetime.min, reverse=True)

        return invocations[:limit]

    def get_invocation(self, invocation_id: str, user_id: str = None) -> typing.Optional[ToolInvocation]:
        """获取特定的调用记录"""
        for invocation in self._invocations:
            if invocation.invocation_id == invocation_id:
                # 如果指定了用户ID，检查权限
                if user_id is not None:
                    # 检查调用记录是否属于该用户
                    if getattr(invocation, "user_id", None) != user_id:
                        return None
                return invocation
        return None

    def get_statistics(self) -> typing.Dict[str, typing.Any]:
        """获取统计信息"""
        invocations = list(self._invocations)
        total = len(invocations)
        successful = sum(1 for i in invocations if i.success)

        return {
            "total_tools": len(self._tools),
            "total_invocations": total,
            "successful_invocations": successful,
            "failed_invocations": total - successful,
            "success_rate": successful / total if total > 0 else 0,
            "average_duration": sum(i.duration or 0 for i in invocations) / total if total > 0 else 0,
        }
