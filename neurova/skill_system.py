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

        # P0-4：manifest 声明式权限——按自身声明裁决每一步（fail-closed）。
        # 无声明（存量技能）parse 为 None，维持旧行为，由治理预检兜底。
        from neurova.skills.permissions import check_tool_permission, parse_permissions

        _perm = parse_permissions((self.config or {}).get("permissions"))

        step_outputs: Dict[int, Any] = {}
        for idx, step in enumerate(sequence):
            # 步进归一化：进化产物（genetic_engine/skill_encapsulation/nl_synthesizer、
            # 冷启动恢复）的 tool_sequence 是 List[str]；create_skill 产物是
            # dict。str 步在此统一为 {"tool": str}，否则自动技能注册成功但
            # 调用必败（"第 0 步格式错误"），闭环后段全是假失败数据。
            if isinstance(step, str):
                step = {"tool": step, "params": {}}
            if not isinstance(step, dict):
                return SkillResult(
                    success=False,
                    error=f"第 {idx} 步格式错误：必须是 dict 或 str",
                )
            tool_name = step.get("tool")
            step_params = step.get("params") or {}
            if not tool_name:
                return SkillResult(success=False, error=f"第 {idx} 步缺少 tool 字段")

            # P0-4：步进裁决在路由之前——被拒步进不得真的执行工具
            if _perm is not None:
                _denial = check_tool_permission(_perm, tool_name)
                if _denial:
                    return SkillResult(
                        success=False,
                        error=f"第 {idx} 步工具被技能权限声明拒绝: {_denial}",
                    )

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
        - get_skill(name) -> Skill | None — 定位单个 Skill 的唯一取键口
        - register(skill: Skill) -> None — 注册单个 Skill
        - register_skill(manifest, path=None) -> bool — 兼容 API,接受 manifest
        - list_skills() -> List[Any] — 列出所有 Skill 信息
        - execute_skill(name, args, context=None) -> Any — 异步执行 Skill
    """

    @property
    def skills(self) -> Dict[str, "Skill"]:
        """已注册的 Skill 字典。"""
        ...

    def get_skill(self, skill_name: str) -> Optional["Skill"]:
        """定位单个 Skill——name 与身份域两个形态都归一到同一个对象。

        工单 014 把它补进协议面：此前协议没有"定位"这一口，调用方只能
        `skills.get(name)` 字典直取，那是只认 name 的第二套键域，与进化侧
        身份域（skill_id）在 id != name 时分叉。类 B 已退役（ADR 0011），
        "get_skill 可能是协程"的歧义不复存在。
        """
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
        # 身份域索引（工单 014）：skill_id/id → 同一个 Skill 对象。
        # 主字典按 skill.name 建键（name 是执行与展示域：工具清单、LLM 调用都用它），
        # 而进化侧取键拿的是 resolve_skill_identity()（skill_id 优先）—— 两者在
        # id != name 时不是同一个串，于是改进/启停/执行全在静默取空。
        self._identity_index: Dict[str, Skill] = {}
        self._event_handlers: List[Callable] = []
        self._event_callbacks: Dict[str, List[Callable]] = {}
        self._runtime_manager = runtime_manager
        import threading
        self._registration_lock = threading.RLock()
        # 同名覆盖计数（工单 006 的可观测读数，供运维复算存量库的冲突规模）
        self._name_collision_count = 0
        # 工具路由器注入: 恢复/注册 ToolSequenceSkill(自动技能)时需要
        # 执行体依靠此路由逐步骤执行工具; 未注入时合成技能"能看见不能调"
        self.tool_router: Any = None

    def set_tool_router(self, tool_router: Any) -> None:
        """绑定工具路由器（agent_core.init_tools 在创建 ToolRouter 后调用）"""
        self.tool_router = tool_router

    def register(self, skill: Skill):
        """注册 Skill。

        Wave G-2 注册边界单源化：入口处 canonicalize——无显式 skill_id 的
        运行时对象补写身份（fallback=注册键名），此后所有消费方（漏斗/记账/
        schema/API）对注册对象的取值恒单跳命中 skill_id；已有身份永不覆写
        （工具名与账本 id 可以合法不同，覆写撕裂血缘）。
        """
        from neurova.skills.skill_contract import canonicalize_skill_identity

        from neurova.skills.creation_governance import manifest_fingerprint

        with self._registration_lock:
            key = manifest_fingerprint({"config": getattr(skill, "config", {}),
                                        "description": skill.description})
            for existing in self._skills.values():
                if key and manifest_fingerprint({"config": getattr(existing, "config", {}),
                                                  "description": existing.description}) == key:
                    return existing
            # canonicalize 已经算出最终身份，直接用它登记，不再二次解析
            identity = canonicalize_skill_identity(skill, fallback=getattr(skill, "name", "") or "")
            # 同名覆盖告警（工单 006 / 审计 L-06b）：注册表按 `skill.name` 建键，
            # 而身份是 `skill_id`——`name ≠ skill_id` 的自动技能（历史生成器遗留）
            # 会**静默**顶掉先到的同名条目，工具面永远看不到少了一个。此处只出声
            # 不硬拒（存量库当场硬拒会让装配失败），迁移方案另票。
            self._warn_on_name_collision(skill)
            self._skills[skill.name] = skill
            if identity:
                self._identity_index[identity] = skill
            return skill

    def _warn_on_name_collision(self, skill: "Skill") -> None:
        """同名不同身份的覆盖出声（计数可观测，不硬拒）。"""
        existing = self._skills.get(skill.name)
        if existing is None or existing is skill:
            return
        from neurova.skills.skill_contract import resolve_skill_identity

        incoming = resolve_skill_identity(skill, fallback=getattr(skill, "name", ""))
        resident = resolve_skill_identity(existing, fallback=getattr(existing, "name", ""))
        if incoming and resident and incoming == resident:
            return
        self._name_collision_count = getattr(self, "_name_collision_count", 0) + 1
        logger.warning(
            "技能同名覆盖（name=%s）：%s 顶替 %s；注册表按 name 建键，两者身份不同则"
            "先到者在工具面上静默消失（累计 %d 次）",
            skill.name, incoming or "?", resident or "?", self._name_collision_count,
        )

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

            # P0-4：manifest 携带的权限声明并入 config（运行时按声明裁决）
            _perm_raw = getattr(manifest, "permissions", None)
            if _perm_raw is not None and "permissions" not in config_dict:
                _perm_dict = (
                    _perm_raw.to_dict() if hasattr(_perm_raw, "to_dict") else _perm_raw
                )
                if isinstance(_perm_dict, dict):
                    config_dict = {**config_dict, "permissions": _perm_dict}

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
                self._carry_manifest_identity(skill, manifest)
                self.register(skill)
                return True

            skill = Skill(name=name, description=description)
            skill.config = config_dict
            self._carry_manifest_identity(skill, manifest)
            self.register(skill)
            return True
        except Exception:
            return False

    @staticmethod
    def _carry_manifest_identity(skill, manifest) -> None:
        """register_skill 兼容 API 边界：manifest 上的账本身份（id/skill_id）
        传递给运行时对象——注册键=name 不得冒充身份（Wave G-2 单源化）。"""
        from neurova.skills.skill_contract import resolve_skill_identity

        ident = resolve_skill_identity(manifest)
        try:
            if ident and not (getattr(skill, "skill_id", "") or "").strip():
                skill.skill_id = ident
        except Exception:  # noqa: BLE001 - 只读对象降级，register() 仍按 name 归一
            pass

    def _lookup(self, key: str) -> Optional[Skill]:
        """注册表唯一的取键口：name 与身份域都归一到同一个对象（工单 014）。

        归一只做在这里，不在 8 个调用方各写一次 resolve —— 那会长出第 9 处口径，
        而两处口径迟早漂移（本批一路在拆的就是这个）。
        """
        skill = self._skills.get(key)
        if skill is not None:
            return skill
        return self._identity_index.get(key)

    def set_skill_enabled(self, skill_name: str, enabled: bool) -> bool:
        """启用/禁用技能（2026-09-07 C1 闭环：skill 端点 enable/disable 的真实实现）。

        Returns:
            True 表示状态已变更；技能不存在返回 False。
        """
        skill = self._lookup(skill_name)
        if skill is None:
            return False
        from neurova.skill_system_module_standalone import SkillStatus

        skill.status = SkillStatus.ACTIVE if enabled else SkillStatus.INACTIVE
        return True

    def unregister(self, skill_name: str):
        """注销 Skill（任一历史形态的键都要能注销干净）"""
        skill = self._lookup(skill_name)
        if skill is None:
            return
        self._skills.pop(getattr(skill, "name", skill_name), None)
        for identity, target in list(self._identity_index.items()):
            if target is skill:
                self._identity_index.pop(identity, None)

    def get_skill(self, skill_name: str) -> Optional[Skill]:
        """获取 Skill（name / skill_id 皆可）"""
        return self._lookup(skill_name)

    def has_skill(self, skill_name: str) -> bool:
        """检查 Skill 是否存在（与 get_skill 同一口径，不许两套判定）"""
        return self._lookup(skill_name) is not None

    def list_skills(self) -> List[SkillInfo]:
        """列出所有 Skill"""
        return [skill.get_info() for skill in self._skills.values()]

    def get_skill_names(self) -> List[str]:
        """获取所有 Skill 名称"""
        return list(self._skills.keys())

    def clear(self) -> None:
        """清空所有已注册技能（主要用于测试与重置）。"""
        self._skills.clear()
        self._identity_index.clear()

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
        skill = self._lookup(skill_name)
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
        from neurova.skills.builtin import create_builtin_skills

        for skill in create_builtin_skills(memory_manager):
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


def registered_collision_count() -> int:
    """已创建的注册表上的同名覆盖累计次数（未创建时为 0）。

    观测面读数（工单 006）：跨模块直接读模块私有量会绕过包代理，故在此开一个
    只读取数口。**抓指标绝不懒建注册表**——没有注册表就是 0，不为读数造对象。
    """
    return int(getattr(_skill_registry_singleton, "_name_collision_count", 0) or 0)


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
