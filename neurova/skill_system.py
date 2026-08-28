"""
Skill System - Skill 执行系统
管理 Agent 可用的技能/工具，支持动态注册、执行和权限控制

D1 任务重构版本：
- 增强事件触发能力（预留事件总线接口）
- Skill 执行前后触发事件通知
- 保持 SkillRegistry 向后兼容
"""

from neurova.core.logger import get_logger
import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

logger = get_logger(__name__)


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

    # 事件类型常量（与 _emit_event 传入的字符串一致，供按类型注册回调使用）
    PRE_EXECUTE = "before_execute"
    POST_EXECUTE = "after_execute"
    ERROR = "error"

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
                get_logger(__name__).error(f"事件处理失败: {e}")


class ToolSequenceSkill(Skill):
    """把 manifest.config.tool_sequence 解释为可执行的多步技能。

    模式挖掘器（pattern_miner）、自然语言合成器（nl_synthesizer）、
    自动技能封装器（AutoSkillBuilder）产出的 manifest 都用相同的
    tool_sequence 形态。注册到 SkillRegistry 后，调用方即可实际执行
    序列内每一步（通过 tool_router），而不只是拿到一个空壳 Skill。

    占位符约定：步骤 params 中的 `{step_<idx>.<field>}` 会被替换为
    前置步骤执行结果的对应字段，方便步间变量传递。
    """

    def __init__(
        self,
        name: str,
        description: str,
        tool_sequence: list,
        tool_router: Any = None,
    ):
        super().__init__(name=name, description=description)
        self.config = {"tool_sequence": tool_sequence}
        self._tool_router = tool_router

    async def execute(
        self, params: Dict[str, Any], context: Optional[Dict[str, Any]] = None
    ) -> SkillResult:
        sequence = (self.config or {}).get("tool_sequence") or []
        if not sequence:
            return SkillResult(success=False, error="技能 tool_sequence 为空")

        step_outputs: Dict[int, Any] = {}
        for idx, step in enumerate(sequence):
            if not isinstance(step, dict):
                return SkillResult(
                    success=False,
                    error=f"第 {idx} 步格式错误：必须是 dict",
                )
            tool_name = step.get("tool")
            step_params = step.get("params") or {}
            if not tool_name:
                return SkillResult(success=False, error=f"第 {idx} 步缺少 tool 字段")
            if not self._tool_router:
                return SkillResult(
                    success=False,
                    error="自动技能执行需要 Agent 工具路由器（AgentSkill Manager未启用）",
                )
            rendered = self._render_params(step_params, step_outputs)
            try:
                _rv = self._tool_router.execute(
                    tool_name=tool_name,
                    params=rendered,
                    agent_id=context.get("agent_id") if context else None,
                    user_id=context.get("user_id") if context else None,
                )
                result = await _rv if asyncio.iscoroutine(_rv) else _rv
            except Exception as exc:
                return SkillResult(
                    success=False,
                    error=f"第 {idx} 步工具 {tool_name} 异常: {exc}",
                )
            if result is None or not getattr(result, "success", False):
                return SkillResult(
                    success=False,
                    error=getattr(result, "error", None)
                    or f"第 {idx} 步工具 {tool_name} 失败",
                )
            step_outputs[idx] = getattr(result, "result", None)
        return SkillResult(success=True, data=step_outputs)

    @staticmethod
    def _render_params(
        params: Dict[str, Any], step_outputs: Dict[int, Any]
    ) -> Dict[str, Any]:
        """把 `{step_<idx>.<field>}` 占位符替换为前序步骤输出。"""
        import re

        pattern = re.compile(r"\{step_(\d+)(?:\.([\w\.]+))?\}")

        def lookup(match):
            idx = int(match.group(1))
            path = match.group(2)
            value = step_outputs.get(idx)
            if value is None or not path:
                return ""
            for part in path.split("."):
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = getattr(value, part, None)
                if value is None:
                    return ""
            return str(value)

        rendered: Dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str):
                rendered[key] = pattern.sub(lookup, value)
            else:
                rendered[key] = value
        return rendered


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
        """搜索网络

        Bug W-4 修复: 原为 `return []` 空实现（stub），导致 Skill 路径即使被调用也返回空。
        现使用 urllib 直接发起搜索请求，与 tool_executor._execute_web_search 逻辑对齐，
        保证 WebSearchSkill 路径独立可用（不依赖 ToolExecutor / agent_ref）。
        """
        if not query:
            return []
        try:
            import urllib.request
            import urllib.parse
            import re

            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&hl=zh-CN"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            snippets = re.findall(r'<div[^>]*class="[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
            text = re.sub(r"<[^>]+>", "", " ".join(snippets[:5]))
            text = re.sub(r"\s+", " ", text).strip()[:500]
            return [
                {
                    "query": query,
                    "snippet": text or f"搜索 '{query}' 完成，但未能提取摘要。",
                }
            ]
        except Exception as e:
            return [{"query": query, "error": f"搜索失败: {e}"}]


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
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                return {"content": content, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _write_file(self, file_path: str, content: str, params: Dict) -> Dict:
        """写入文件"""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}


@runtime_checkable
class SkillRegistryProtocol(Protocol):
    """SkillRegistry 统一接口协议(架构深化候选 1)。

    根因: 类 A (neurova/skill_system.py SkillRegistry) 和类 B
    (neurova/skills/registry.py SkillRegistry) API 完全不兼容,导致
    V2-1/V2-2/V2-5/V2-7 四处静默失败。此 Protocol 显式声明统一 seam,
    两个实现都应满足此接口。调用方应依赖 Protocol 而非具体类。

    Deletion test: 删除此 Protocol 后,API 不匹配的 complexity 重新散布到
    orchestrator/tool_router/chat_pipeline 三个调用方,因此 Protocol earns its keep。

    Interface(seam):
        - skills: Dict[str, Skill] — 已注册 Skill 字典(类 B 实现需解包元组)
        - register(skill: Skill) -> None — 注册单个 Skill
        - register_skill(manifest, path=None) -> bool — 兼容 API,接受 manifest
        - list_skills() -> List[Any] — 列出所有 Skill 信息
        - execute_skill(name, args, context=None) -> Any — 异步执行 Skill
    """

    @property
    def skills(self) -> Dict[str, "Skill"]:
        """已注册的 Skill 字典。"""
        ...

    def register(self, skill: "Skill") -> None:
        """注册单个 Skill。"""
        ...

    def register_skill(self, manifest: Any, path: Optional[Any] = None) -> bool:
        """兼容 API:接受 manifest 对象注册 Skill。"""
        ...

    def list_skills(self) -> List[Any]:
        """列出所有 Skill 信息。"""
        ...

    async def execute_skill(
        self, skill_name: str, params: Dict[str, Any], context: Optional[Dict] = None
    ) -> "SkillResult":
        """异步执行 Skill。"""
        ...


class SkillRegistry:
    """Skill 注册表"""

    def __init__(self, runtime_manager=None):
        self._skills: Dict[str, Skill] = {}
        self._event_handlers: List[Callable] = []
        self._event_callbacks: Dict[str, List[Callable]] = {}
        self._runtime_manager = runtime_manager

    def register(self, skill: Skill):
        """注册 Skill"""
        self._skills[skill.name] = skill
        skill.add_event_handler(self._on_skill_event)

    @property
    def skills(self) -> Dict[str, Skill]:
        """已注册的 Skill 字典(只读视图)。

        Bug V2-1 修复:orchestrator.py:731 和 base.py:241 都用
        `skill_registry.skills.items()` 迭代,但原实现只有私有 _skills 字段,
        访问 .skills 抛 AttributeError,被 except Exception 静默吞掉,
        导致 Skill 工具永远不进入 LLM tools 列表。
        暴露此 property 让外部代码能以 .skills 访问。
        """
        return self._skills

    def register_skill(self, manifest, path=None) -> bool:
        """兼容 API:接受 manifest + path 两参数注册 Skill。

        Bug V2-5 修复:chat_pipeline.py:647 调用
        `skill_registry.register_skill(manifest, sentinel_path)`,
        但类 A SkillRegistry 只有 `register(skill)`(单参数),
        调用抛 AttributeError,被 except 吞掉,合成工具永远无法注册。

        此方法接受 manifest 对象,从中提取 name/description 构造 Skill 后
        委托到 register()。如果 manifest 已是 Skill 实例,直接注册。

        当 manifest.config 含 tool_sequence（来自模式挖掘 / NL 合成 / AutoSkillBuilder
        的自动技能 manifest）时，自动构造可执行的 ToolSequenceSkill，
        让"能看见不能调"的空壳变回真正可运行的技能。
        """
        try:
            if isinstance(manifest, Skill):
                self.register(manifest)
                return True
            name = getattr(manifest, "name", None) or getattr(manifest, "id", None) or str(manifest)
            description = getattr(manifest, "description", "") or ""
            _config = getattr(manifest, "config", None)
            config_dict = _config if isinstance(_config, dict) else {}

            # 自动技能：含 tool_sequence 时构造可执行子类
            if isinstance(config_dict.get("tool_sequence"), list) and config_dict["tool_sequence"]:
                tool_router = getattr(self, "tool_router", None)
                skill = ToolSequenceSkill(
                    name=name,
                    description=description,
                    tool_sequence=config_dict["tool_sequence"],
                    tool_router=tool_router,
                )
                skill.config = config_dict  # 保留原 manifest 的所有元数据
                self.register(skill)
                return True

            skill = Skill(name=name, description=description)
            skill.config = config_dict
            self.register(skill)
            return True
        except Exception:
            return False

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

    def clear(self) -> None:
        """清空所有已注册技能（主要用于测试与重置）。"""
        self._skills.clear()

    async def execute_skill(
        self, skill_name: str, params: Dict[str, Any], context: Optional[Dict] = None
    ) -> SkillResult:
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

    @property
    def runtime_manager(self):
        """获取 RuntimeManager（延迟初始化）"""
        if self._runtime_manager is None:
            try:
                from neurova.execution_layers import get_runtime_manager

                self._runtime_manager = get_runtime_manager()
            except ImportError:
                logger.debug("execution_layers 模块不可用")
        return self._runtime_manager

    async def execute_skill_isolated(
        self,
        skill_name: str,
        params: Dict[str, Any],
        context: Optional[Dict] = None,
        runtime_type: str = "local",
    ) -> SkillResult:
        """
        在隔离运行时中执行 Skill

        通过 RuntimeManager 在独立运行时（Local/Docker）中执行技能，
        提供进程级隔离，防止技能崩溃影响主进程。

        Args:
            skill_name: 技能名称
            params: 技能参数
            context: 执行上下文
            runtime_type: 运行时类型（local / docker）
        """
        start_time = time.time()

        skill = self.get_skill(skill_name)
        if not skill:
            return SkillResult(success=False, error=f"Skill {skill_name} 不存在")

        rm = self.runtime_manager
        if rm is None:
            logger.debug("RuntimeManager 不可用，降级为普通执行")
            return await self.execute_skill(skill_name, params, context)

        try:
            from neurova.execution_layers import RuntimeFactory, RuntimeType

            rt = RuntimeType.DOCKER if runtime_type == "docker" else RuntimeType.LOCAL
            runtime = RuntimeFactory.create(rt, runtime_id=f"skill_{skill_name}_{int(time.time())}")
            await runtime.start()

            try:
                import json as _json

                exec_env = {
                    "NEUROVA_SKILL_NAME": skill_name,
                    "NEUROVA_SKILL_ARGS": _json.dumps(params),
                }
                if context:
                    exec_env["NEUROVA_SKILL_CONTEXT"] = _json.dumps(context)

                exec_result = await runtime.exec(
                    command="python",
                    args=[
                        "-c",
                        (
                            "import asyncio, json, os; "
                            f"from neurova.skill_system import SkillRegistry; "
                            f"args = json.loads(os.environ.get('NEUROVA_SKILL_ARGS', '{{}}')); "
                            f"result = asyncio.run(SkillRegistry().execute_skill('{skill_name}', args)); "
                            "print(json.dumps({'success': result.success, 'data': result.data}))"
                        ),
                    ],
                    env=exec_env,
                    timeout=params.get("timeout", 60),
                )

                duration_ms = (time.time() - start_time) * 1000

                if exec_result.success:
                    return SkillResult(
                        success=True,
                        data={"stdout": exec_result.stdout, "runtime_type": runtime_type},
                        execution_time=duration_ms,
                    )
                else:
                    return SkillResult(
                        success=False,
                        error=exec_result.stderr or exec_result.error or "Isolated execution failed",
                        execution_time=duration_ms,
                    )
            finally:
                await runtime.stop()

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("隔离执行 Skill 失败: %s", e)
            return await self.execute_skill(skill_name, params, context)

    def add_event_handler(self, handler: Callable):
        """添加事件处理器"""
        self._event_handlers.append(handler)

    def _on_skill_event(self, event: SkillEvent):
        """处理 Skill 事件"""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                get_logger(__name__).error(f"事件处理失败: {e}")

    def register_event_callback(self, event_type: str, handler: Callable):
        """按事件类型注册回调。

        与 add_event_handler(handler) 不同：此回调按 event_type 触发，
        handler 收到 (skill, data) 两个参数（skill 为 None 表示未注册的 skill）。
        供 agent_core._init_router 按 SkillEvent.POST_EXECUTE 等事件类型注册回调。
        """
        self._event_callbacks.setdefault(event_type, []).append(handler)

    def _emit_event(self, event_type: str, skill_name: str, data: Any = None):
        """触发事件"""
        event = SkillEvent(event_type, skill_name, data)
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                get_logger(__name__).error(f"事件处理失败: {e}")
        # 按事件类型分发给 register_event_callback 注册的回调（传 skill + data）
        skill = self._skills.get(skill_name)
        for handler in self._event_callbacks.get(event_type, []):
            try:
                handler(skill, data)
            except Exception as e:
                get_logger(__name__).error(f"事件回调处理失败: {e}")


def create_default_skills(memory_manager=None) -> SkillRegistry:
    """
    创建默认 Skill 注册表

    Args:
        memory_manager: 记忆管理器

    Returns:
        Skill 注册表
    """
    registry = SkillRegistry()

    # 优先使用内置 executor（功能更完整，且文件操作带沙箱路径防护）。
    # 通过 ExecutorBackedSkill 把同步 executor 桥接为异步 Skill，
    # 使 execute_skill() 真正调用到这些 executor 的实现。
    try:
        from neurova.skills.builtin import create_builtin_executor_skills

        for skill in create_builtin_executor_skills(memory_manager):
            registry.register(skill)
    except Exception as exc:
        logger.warning("内置 executor 注册失败，回退到内置 Skill 子类: %s", exc)
        registry.register(MemorySkill(memory_manager))
        registry.register(WebSearchSkill())
        registry.register(FileOperationSkill())

    return registry


# ------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------

_skill_registry_singleton = None


def get_skill_registry(memory_manager=None) -> "SkillRegistry":
    """获取全局 SkillRegistry 单例。

    生产代码（如 neurflow/node_registry.py、adapters.py）通过
    `from neurova.skill_system import get_skill_registry` 获取默认注册表。
    首次调用时惰性创建；后续调用（无论是否传 memory_manager）返回同一实例。
    """
    global _skill_registry_singleton
    if _skill_registry_singleton is None:
        _skill_registry_singleton = create_default_skills(memory_manager)
    return _skill_registry_singleton
