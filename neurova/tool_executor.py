"""
ToolExecutor — 统一工具执行器

从 agent_core.py 提取 (P1 拆分)，负责：
- 文本工具调用解析与执行 (_execute_text_tool_calls)
- 肌肉记忆工具执行 (_execute_tool_from_memory)
- Skill/CLI/MCP 工具分派 (_execute_skill_tool, _execute_cli_tool)
- 集中化工具执行后钩子 (on_tool_executed)
- 内置工具参数信息 (_get_builtin_tool_params)

设计原则：
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性
- 可独立测试：不依赖 Agent 类的完整初始化
"""

import ast
import asyncio
import json
from neurova.builtin_tools import get_builtin_tool_params
from neurova.collaboration.canvas_ops import (
    CanvasOpError,
    CanvasVersionConflict,
    get_canvas_op_service,
)
from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
from neurova.core.logger import get_logger
import shlex
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# ToolEngine 延迟导入（避免循环依赖）
_TOOL_ENGINE_AVAILABLE = False
_ToolEngine = None

# ── 电脑/浏览器操作工具（Computer Use）─────────────────────────
# 执行后向会话广播 computer_action 实时事件，驱动聊天页分屏面板
COMPUTER_USE_TOOLS = frozenset(
    {
        "computer_screenshot",
        "computer_click",
        "computer_type",
        "computer_scroll",
        "computer_shell",
        "browser_navigate",
        "browser_click",
        "browser_type",
        "browser_screenshot",
        "browser_extract_text",
        "browser_dom_snapshot",
        "browser_click_role",
        "browser_fill_role",
    }
)


def describe_computer_action(tool_name: str, params: Dict) -> str:
    """生成电脑/浏览器操作的一句话摘要（面板操作日志用）"""
    if not isinstance(params, dict):
        params = {}
    if tool_name == "computer_screenshot":
        return "截取屏幕"
    if tool_name == "computer_click":
        return f"点击屏幕 ({params.get('x', '?')}, {params.get('y', '?')})"
    if tool_name == "computer_type":
        text = str(params.get("text", ""))
        return f"键入文本「{text[:30]}{'…' if len(text) > 30 else ''}」"
    if tool_name == "computer_scroll":
        return "滚动屏幕"
    if tool_name == "computer_shell":
        cmd = str(params.get("command", ""))
        return f"执行命令 {cmd[:60]}{'…' if len(cmd) > 60 else ''}"
    if tool_name == "browser_navigate":
        return f"打开网页 {params.get('url', '')}"
    if tool_name == "browser_click":
        return f"点击页面元素 {params.get('selector') or params.get('text', '')}"
    if tool_name == "browser_type":
        return f"在 {params.get('selector', '?')} 中输入文本"
    if tool_name == "browser_screenshot":
        return "截取浏览器页面"
    if tool_name == "browser_extract_text":
        return "提取页面文本"
    if tool_name == "browser_dom_snapshot":
        return "获取页面可访问性快照"
    if tool_name == "browser_click_role":
        return f"点击 {params.get('role', '?')}「{params.get('name', '')}」"
    if tool_name == "browser_fill_role":
        return f"在 {params.get('role', '?')}「{params.get('name', '')}」中输入"
    return tool_name


def _get_tool_engine_class():
    """延迟导入 ToolEngine 类"""
    global _TOOL_ENGINE_AVAILABLE, _ToolEngine
    if _ToolEngine is None:
        try:
            from neurova.execution_engine.tool_engine import ToolEngine

            _ToolEngine = ToolEngine
            _TOOL_ENGINE_AVAILABLE = True
        except ImportError:
            _TOOL_ENGINE_AVAILABLE = False
    return _ToolEngine


def _get_approval_manager():
    """获取审批管理器（模块级函数，便于测试注入）。"""
    from neurova.security.approval_manager import get_approval_manager

    return get_approval_manager()


class ToolExecutor:
    """统一工具执行器

    通过 agent_ref 访问 Agent 实例的：
    - _skill_registry, tool_router, tool_memory, tool_lifecycle, skill_packer
    - _tool_messages_list, config
    """

    # 内置工具分派表：工具名 → 执行方法名（调用时 getattr 解析）。
    # 根因修复：原 if/elif 分派链与 builtin_tools._BUILTIN_SCHEMAS 是两条
    # 平行结构、无机械关联，历史上已漂移三次——asr_transcribe/tts_synthesize
    # 有 schema 无执行体（LLM 调用必返回"未知内置工具"），run_code 有执行体
    # 无 schema（LLM 永远看不到）。改为分派表后，由不变量测试
    # tests/unit/tools/test_builtin_tools_expansion.py::TestSchemaDispatchConsistency
    # 保证 _BUILTIN_SCHEMAS ⊆ 本表，新增工具漏配执行体会直接被测试拦截。
    # 注意：search/execute_code 是历史兼容别名，不可删除。
    _builtin_dispatch: Dict[str, str] = {
        "memory_search": "_execute_memory_search",
        "search": "_execute_web_search",
        "web_search": "_execute_web_search",
        "weather": "_execute_weather",
        "file_read": "_execute_file_read",
        "file_write": "_execute_file_write",
        "file_create": "_execute_file_create",
        "file_delete": "_execute_file_delete",
        "file_edit": "_execute_file_edit",
        "file_list": "_execute_file_list",
        "file_search": "_execute_file_search",
        "web_fetch": "_execute_web_fetch",
        "calculator": "_execute_calculator",
        "get_datetime": "_execute_get_datetime",
        "computer_screenshot": "_execute_computer_screenshot",
        "computer_click": "_execute_computer_click",
        "computer_type": "_execute_computer_type",
        "computer_scroll": "_execute_computer_scroll",
        "computer_shell": "_execute_computer_shell",
        "browser_navigate": "_execute_browser_navigate",
        "browser_click": "_execute_browser_click",
        "browser_type": "_execute_browser_type",
        "browser_screenshot": "_execute_browser_screenshot",
        "browser_extract_text": "_execute_browser_extract_text",
        "browser_dom_snapshot": "_execute_browser_dom_snapshot",
        "browser_click_role": "_execute_browser_click_role",
        "browser_fill_role": "_execute_browser_fill_role",
        "planning": "_execute_planning",
        "youtube_transcript": "_execute_youtube_transcript",
        "bilibili_search": "_execute_bilibili_search",
        "rss_read": "_execute_rss_read",
        "v2ex_hot": "_execute_v2ex_hot",
        "social_search": "_execute_social_search",
        "emotion_analyze": "_execute_emotion_analyze",
        "asr_transcribe": "_execute_asr_transcribe",
        "tts_synthesize": "_execute_tts_synthesize",
        "voice_memory_search": "_execute_voice_memory_search",
        "run_code": "_execute_run_code",
        "execute_code": "_execute_run_code",
        "spawn_subagent": "_execute_spawn_subagent",
        "subagent_status": "_execute_subagent_status",
        "list_agents": "_execute_list_agents",
        "create_skill": "_execute_create_skill",
        # 画布交互工具（Phase 1）：语义操作层薄封装，见 _execute_canvas_* 注释
        "canvas_create": "_execute_canvas_create",
        "canvas_read": "_execute_canvas_read",
        "canvas_add_node": "_execute_canvas_add_node",
        "canvas_connect": "_execute_canvas_connect",
        "canvas_set_config": "_execute_canvas_set_config",
        "canvas_move_node": "_execute_canvas_move_node",
        "canvas_remove_node": "_execute_canvas_remove_node",
        "canvas_layout": "_execute_canvas_layout",
        "canvas_run": "_execute_canvas_run",
        "canvas_list_nodes": "_execute_canvas_list_nodes",
    }

    # file_search 跳过的噪音目录（依赖/构建/版本控制）
    _SEARCH_SKIP_DIRS = frozenset({
        ".git", ".hg", ".svn", "node_modules", "__pycache__",
        ".venv", "venv", "dist", "build", ".idea", ".vscode",
    })

    # calculator 指数上限 — 防止 9**999999999 这类表达式撑爆内存
    _CALC_MAX_EXPONENT = 10000

    def __init__(self, agent_ref):
        """
        初始化工具执行器

        Args:
            agent_ref: Agent 实例引用
        """
        self._agent = agent_ref
        self._messages_list: List[Dict] = []
        self._tool_engine = None  # ToolEngine 实例（延迟初始化）

    @property
    def tool_engine(self):
        """获取 ToolEngine 实例（延迟初始化）"""
        if self._tool_engine is None:
            # 首先尝试从 ExecutionEngine 获取
            try:
                from neurova.shared_core.execution_engine import ExecutionEngine

                engine = ExecutionEngine()
                if hasattr(engine, "_tool_engine") and engine._tool_engine is not None:
                    self._tool_engine = engine._tool_engine
                    logger.debug("从 ExecutionEngine 获取 ToolEngine")
                    return self._tool_engine
            except Exception as e:
                logger.debug("从 ExecutionEngine 获取 ToolEngine 失败: %s", e)

            # 如果 ExecutionEngine 不可用，创建新的 ToolEngine
            ToolEngineClass = _get_tool_engine_class()
            if ToolEngineClass:
                try:
                    self._tool_engine = ToolEngineClass()
                    logger.debug("创建新的 ToolEngine 实例")
                except Exception as e:
                    logger.warning("创建 ToolEngine 失败: %s", e)
        return self._tool_engine

    @property
    def _skill_registry(self):
        """获取 skill 注册表"""
        return getattr(self._agent, "_skill_registry", None)

    @property
    def tool_router(self):
        """获取工具路由器"""
        return getattr(self._agent, "tool_router", None)

    @property
    def tool_memory(self):
        """获取工具记忆"""
        return getattr(self._agent, "tool_memory", None)

    @property
    def tool_lifecycle(self):
        """获取工具生命周期"""
        return getattr(self._agent, "tool_lifecycle", None)

    @property
    def skill_packer(self):
        """获取 skill 打包器"""
        return getattr(self._agent, "skill_packer", None)

    @property
    def config(self):
        """获取配置"""
        return getattr(self._agent, "config", None)

    def _agent_identity(self) -> tuple:
        """解析执行身份 (user_id, agent_id)

        P2 修复: user_id/agent_id 位于 agent.config 上，Agent 实例本身没有这两个属性。
        原实现 getattr(self._agent, "user_id"/"agent_id") 恒为 None/""，
        导致 ToolEngine 安全防护、治理裁决、审批请求、审计日志全部丢失用户身份。

        三层隔离贯通: agent._current_user_id（JWT 登录用户，经
        ChatPipeline._init_agent_state 从 metadata 透传）优先于 config 层
        身份——config 是共享单例的静态配置，请求级登录用户才是归属主体。
        """
        agent = self._agent
        request_user = getattr(agent, "_current_user_id", None)
        config = getattr(agent, "config", None)
        user_id = (
            request_user
            or getattr(agent, "user_id", None)
            or getattr(config, "user_id", None)
            or "default"
        )
        agent_id = getattr(agent, "agent_id", None) or getattr(config, "agent_id", None)
        return user_id, agent_id

    def _ensure_messages_list(self, messages: Optional[List[Dict]] = None) -> List[Dict]:
        """确保消息列表存在"""
        if messages is None:
            if not self._messages_list:
                self._messages_list = []
            return self._messages_list
        return messages

    async def _execute_from_text(self, reply: str, user_input: str):
        """从文本回复中解析并执行工具调用"""
        import re

        # 简单的文本工具调用解析
        pattern = r'\[TOOL_CALL:(\w+)\((.*?)\)\]'
        matches = re.findall(pattern, reply, re.DOTALL)

        if not matches:
            return reply

        results = []
        for idx, (tool_name, args_str) in enumerate(matches):
            try:
                # 尝试解析 JSON 参数
                try:
                    arguments = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    # 非 JSON 参数不要静默设为空字典——会导致 run_code/file_write 等
                    # 破坏性工具以空参数执行（P2-#12）。先尝试字面量解析，失败则保留
                    # 原始文本，交由工具层决定，而非丢失参数。
                    try:
                        parsed = ast.literal_eval(args_str)
                        arguments = parsed if isinstance(parsed, dict) else {"_raw": args_str}
                    except (ValueError, SyntaxError):
                        logger.warning("工具 %s 参数非合法 JSON，按原始文本处理: %r", tool_name, args_str)
                        arguments = {"_raw": args_str}

                result = await self._execute_single_tool(tool_name, arguments)
                results.append(f"\n\n**{tool_name} 结果**: {json.dumps(result, ensure_ascii=False)[:2000]}")

                # Bug T-4 修复: 文本模式也写入 _tool_messages_list，与 list 模式（line 203-209）一致
                # 否则 chat_pipeline._collect_tool_messages() 收不到工具结果，
                # 前端 AGENT_TOOL_RESULT 事件的 tool_messages 永远为空
                # Bug A-2 修复: 添加 tool_name 字段，与 base.py 格式一致，
                # 使 post_chat_pipeline 的 tm.get("tool_name") 可正常工作
                if not hasattr(self._agent, "_tool_messages_list"):
                    self._agent._tool_messages_list = []
                self._agent._tool_messages_list.append(
                    {
                        "role": "tool",
                        "tool_call_id": f"text_{tool_name}_{idx}",
                        "name": tool_name,
                        "tool_name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False),
                        # P2-12 修复: 补齐 type/success/timestamp, 与 agent/loops/base.py
                        # 写入格式一致（理由同 list 模式）。
                        "type": "tool_result",
                        "result": result,
                        "success": self._result_is_success(result),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception as e:
                logger.error("Text tool execution failed: %s", e)
                results.append(f"\n\n**{tool_name} 错误**: {str(e)}")

        if results:
            return reply + "\n".join(results)
        return reply

    async def execute_text_tool_calls(
        self, tool_calls, messages: Optional[List[Dict]] = None
    ):
        """
        执行文本工具调用

        支持两种调用方式:
        1. execute_text_tool_calls(reply: str, user_input: str) — 从文本解析工具调用
        2. execute_text_tool_calls(tool_calls: List[Dict], messages) — 直接执行工具调用列表
        """
        # 如果第一个参数是字符串，从文本中解析工具调用
        if isinstance(tool_calls, str):
            return await self._execute_from_text(tool_calls, messages or "")

        messages = self._ensure_messages_list(messages)
        results = []

        for tool_call in tool_calls:
            try:
                # 解析工具调用
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                arguments_str = function.get("arguments", "{}")

                # 解析参数
                # P2-7 修复: 原实现在 JSONDecodeError 时静默 arguments={} 继续执行,
                # 会让 file_write/run_code 等破坏性工具以空参数执行。
                # 对齐 loops/base.py TOOLROBUST-A 策略: 解析失败不执行, 把错误作为该工具
                # 的结果回传(success=False), 交由 LLM 自行纠正参数格式。
                # 同时兼容部分 provider 直接传 dict 参数的情况。
                if isinstance(arguments_str, dict):
                    arguments = arguments_str
                else:
                    try:
                        arguments = json.loads(arguments_str) if str(arguments_str).strip() else {}
                    except (json.JSONDecodeError, TypeError, ValueError) as parse_err:
                        error_msg = f"工具 {tool_name} 参数 JSON 解析失败: {parse_err}"
                        logger.warning("%s | 原始参数: %r", error_msg, arguments_str)
                        results.append(
                            {
                                "tool_call_id": tool_call.get("id", ""),
                                "name": tool_name,
                                "result": {"error": error_msg},
                                "success": False,
                            }
                        )
                        continue

                # 执行工具
                result = await self._execute_single_tool(tool_name, arguments)
                results.append(
                    {
                        "tool_call_id": tool_call.get("id", ""),
                        "name": tool_name,
                        "result": result,
                        # P1 一致性修复: 成败依据结果内容判定, 不能无条件 True
                        "success": self._result_is_success(result),
                    }
                )

                # 记录到消息列表
                # BE-CORE-008 修复: 写入 agent._tool_messages_list（消费者读取此属性），
                # 而非 self._messages_list（ToolExecutor 本地列表，消费者不可见）
                # Bug A-2 修复: 添加 tool_name 字段，与 base.py 格式一致，
                # 使 post_chat_pipeline 的 tm.get("tool_name") 可正常工作
                if not hasattr(self._agent, "_tool_messages_list"):
                    self._agent._tool_messages_list = []
                self._agent._tool_messages_list.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "tool_name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False),
                        # P2-12 修复: 补齐 type/success/timestamp, 与 agent/loops/base.py
                        # 写入格式一致。否则 post_chat_pipeline._step_marketplace_publish 的
                        # `tm.get("type")=="tool_result" and tm.get("success")` 恒 False,
                        # 工具市场自动发布成为死步骤。
                        "type": "tool_result",
                        "result": result,
                        "success": self._result_is_success(result),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            except Exception as e:
                logger.error("工具执行失败: %s", e)
                results.append(
                    {
                        "tool_call_id": tool_call.get("id", ""),
                        "name": tool_name if "tool_name" in locals() else "unknown",
                        "error": str(e),
                        "success": False,
                    }
                )

        return results

    # P-E 修复（docs/tool-memory-muscle-analysis.md）：原 execute_from_memory
    # 同步版已删除——它把工具名当用户输入做语义匹配，且 confidence > 0.8 时
    # 直接返回 memory_result.get("result", {})（MuscleMemoryItem 无 result 字段，
    # 恒为空 dict）冒充工具执行结果；该方法无调用方，实际使用的是下方的
    # execute_from_memory_async（真实执行 + 反馈）。

    async def execute_from_memory_async(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Dict[str, Any]:
        """从肌肉记忆结果自动执行工具（异步版本，支持超时控制）

        Args:
            tool_memory_result: 肌肉记忆匹配结果（来自 check_tool_memory）
            user_input: 用户原始输入

        Returns:
            {"status": "success"|"failure", "result": ..., "tool_name": ..., "error": ...}
        """
        if not tool_memory_result:
            return {"status": "failure", "error": "空的 tool_memory_result", "tool_name": ""}

        tool_name = tool_memory_result.get("tool_name")
        tool_source = tool_memory_result.get("tool_source")
        tool_params = tool_memory_result.get("tool_params", tool_memory_result.get("tool_params_template", {}))

        if not tool_name:
            return {"status": "failure", "error": "ToolMemory 结果缺少 tool_name", "tool_name": ""}

        logger.info("自动执行工具（异步）: %s (来源: %s)", tool_name, tool_source)

        self._messages_list.append(
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_source": tool_source,
                "params": tool_params,
                "timestamp": datetime.now().isoformat(),
            }
        )

        try:
            result = await self._execute_single_tool(tool_name, tool_params)
            success = result is not None and "error" not in result

            # 记录工具使用
            if self.tool_memory:
                try:
                    self.tool_memory.record_tool_usage(
                        tool_name=tool_name,
                        success=success,
                        problem_text=user_input,
                        tool_source=tool_source,
                        tool_params=tool_params,
                    )
                except Exception as e:
                    logger.debug("工具记忆记录失败: %s", e)

            if success:
                return {"status": "success", "result": result, "tool_name": tool_name}
            else:
                error_msg = result.get("error", "未知错误") if isinstance(result, dict) else "执行失败"
                return {"status": "failure", "error": error_msg, "tool_name": tool_name, "result": result}

        except Exception as e:
            logger.error("工具自动执行异常: %s, %s", tool_name, e)
            return {"status": "failure", "error": str(e), "tool_name": tool_name}

    async def execute_skill_tool(self, skill_name: str, params: Dict, context: Optional[Dict] = None) -> Dict:
        """
        执行 Skill 工具

        Args:
            skill_name: Skill 名称
            params: 参数
            context: 上下文

        Returns:
            执行结果
        """
        if not self._skill_registry:
            return {"error": "Skill 注册表未初始化"}

        try:
            # 获取 Skill
            skill = self._skill_registry.get_skill(skill_name)
            if not skill:
                return {"error": f"Skill {skill_name} 不存在"}

            # 执行 Skill
            result = await skill.execute(params, context)
            return result

        except Exception as e:
            logger.error("Skill 执行失败: %s", e)
            return {"error": str(e)}

    async def execute_cli_tool(self, command: str, args: Optional[Dict] = None) -> Dict:
        """
        执行 CLI 工具

        Args:
            command: 命令
            args: 参数

        Returns:
            执行结果
        """
        try:
            # 构建完整命令
            # BE-CORE-011 修复: 用 shlex.quote() 转义 command 和 value，
            # 防止 shell 元字符（; | & ` $ 等）构成命令注入
            if args:
                # 将参数字典转换为命令行参数
                arg_parts = []
                for key, value in args.items():
                    if isinstance(value, bool):
                        if value:
                            arg_parts.append(f"--{key}")
                    else:
                        arg_parts.append(f"--{key}={shlex.quote(str(value))}")
                full_command = f"{shlex.quote(command)} {' '.join(arg_parts)}"
            else:
                full_command = shlex.quote(command)

            # 使用 ComputerUseManager 执行命令
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = await manager.shell(full_command)

            return {
                "success": result.get("returncode", -1) == 0,
                "returncode": result.get("returncode", -1),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "command": full_command,
                "tool_name": command,
            }
        except Exception as e:
            logger.error("CLI 工具执行失败: %s", e)
            return {"error": f"CLI 工具执行失败: {str(e)}"}

    async def execute(self, tool_name: str, params: Dict) -> Dict:
        """执行工具（公开入口，供 API 端点 / Agent Loop 调用）

        这是 ToolExecutor 的主公开接口。内部委托给 _execute_single_tool，
        后者实现四级回退链：ToolEngine → 内置工具 → Skill → ToolRouter。
        将复杂回退链隐藏在单一公开方法背后，使 API 端点无需感知内部细节。

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            执行结果 dict（成功含 success/result 字段，失败含 error 字段）
        """
        return await self._execute_single_tool(tool_name, params)

    @staticmethod
    def _result_is_success(result: Any) -> bool:
        """依据结果内容判定执行成败

        P1 修复: 各执行路径原实现在拿到返回值后无条件 success=True，
        但 builtin/skill/router 失败时返回 {"error": ...} 而不抛异常，
        导致失败被记为成功，污染肌肉记忆晋升与生命周期统计。
        约定: dict 结果含非空 error 键或 success=False 视为失败。
        """
        if isinstance(result, dict):
            if result.get("error"):
                return False
            if result.get("success") is False:
                return False
        return True

    async def _execute_single_tool(self, tool_name: str, params: Dict,
                                   skip_governance: bool = False) -> Dict:
        """
        执行单个工具（内部实现，含四级回退链）

        H5 修复: 所有执行路径（builtin/skill/ToolRouter/ToolEngine）统一在
        finally 中调用 on_tool_executed，确保记忆/生命周期钩子不被遗漏。
        Skill 路径可能由 agent_core._on_skill_post_execute 二次触发，此处
        允许重复（记录统计幂等，重复计数优于完全遗漏）。

        Args:
            tool_name: 工具名称
            params: 参数
            skip_governance: 跳过治理预检（仅供审批通过后的重放使用）

        Returns:
            执行结果
        """
        start = time.time()
        success = False
        result = None
        tool_source = "unknown"
        try:
            # 方案 P0-1.5: 统一治理预检 —— DENY 拦截、SANDBOX 隔离执行、
            # ASK 待确认；ALLOW / 无裁决内容返回 None 放行。
            precheck = (None if skip_governance
                        else await self._governance_precheck(tool_name, params))
            if precheck is not None:
                result = precheck
                return result

            # 遗留③a：工作流 Agent 派发（P2-4.2 闭环——chat 工具调用直达已发布工作流）
            if tool_name == "run_workflow_agent":
                tool_source = "workflow_agent"
                result = await self._execute_workflow_agent_tool(params)
                success = self._result_is_success(result)
                return result

            # 优先使用 ToolEngine（如果可用）
            if self.tool_engine:
                try:
                    # 获取 user_id 和 agent_id（如果可用）
                    user_id, agent_id = self._agent_identity()

                    result = await self.tool_engine.execute_with_safeguards(
                        tool_name=tool_name, parameters=params, user_id=user_id, agent_id=agent_id
                    )
                    logger.debug("ToolEngine 执行成功: %s", tool_name)
                    # P1 修复: 工具函数可能返回 {"error": ...} 而不抛异常，
                    # 成败必须依据结果内容判定，不能无条件记为成功。
                    success = self._result_is_success(result)
                    tool_source = "mcp"
                    return result
                except ValueError as e:
                    # 工具未注册或不可用，回退到其他方式
                    logger.debug("ToolEngine 工具 %s 未注册或不可用: %s", tool_name, e)
                except Exception as e:
                    logger.warning("ToolEngine 执行失败: %s, %s", tool_name, e)

            # 回退到原有逻辑
            # 内置工具：以 builtin_tools.py 的注册表为单一事实源动态判断，
            # 避免硬编码白名单与 ToolRouter/实际注册不一致（P2-#13）。
            if get_builtin_tool_params(tool_name) is not None:
                tool_source = "builtin"
                result = await self._execute_builtin_tool(tool_name, params)
                success = self._result_is_success(result)
                return result

            # Skill 工具
            if self._skill_registry and self._skill_registry.has_skill(tool_name):
                tool_source = "skill_system"
                # 隔离注入：身份并入 params（服务端赋值优先，防 LLM 参数伪造）
                _caller_id = str(self._agent_identity()[0] or "")
                result = await self.execute_skill_tool(
                    tool_name,
                    {**(params or {}), "_caller_user_id": _caller_id},
                    {"user_id": _caller_id},
                )
                success = self._result_is_success(result)
                return result

            # 通过工具路由器
            if self.tool_router:
                try:
                    tool_source = "tool_router"
                    # P0-3：请求级身份穿透到 MCP 防火墙（多用户共享连接，
                    # 裁决必须按发起请求的用户）
                    result = await self.tool_router.route(
                        tool_name,
                        params,
                        user_id=self._agent_identity()[0] or None,
                    )
                    success = self._result_is_success(result)
                    return result
                except Exception as e:
                    logger.debug("工具路由器执行失败: %s", e)

            return {"error": f"未知工具: {tool_name}"}
        finally:
            # H5: 所有路径统一触发 on_tool_executed（成功/失败均触发）
            elapsed = time.time() - start
            try:
                self.on_tool_executed(
                    tool_name=tool_name,
                    params=params,
                    user_input=getattr(self._agent, "_current_user_input", ""),
                    success=success,
                    tool_source=tool_source,
                    execution_time=elapsed,
                    result=result if isinstance(result, dict) else None,
                )
            except Exception:
                # 不让钩子异常吞掉工具执行结果，但必须记录堆栈
                logger.exception("on_tool_executed 钩子失败: %s", tool_name)

    async def _governance_precheck(self, tool_name: str, params: Dict) -> Optional[Dict]:
        """执行前统一治理预检（方案 P0-1.5 集成点，async：SANDBOX 的 Docker
        后端为异步执行）。

        覆盖所有执行路径（ToolEngine/builtin/skill/router），做四级裁决：
        allow / deny / ask / sandbox。

        P0-2（评测 M3/M4）：
        - MCP 工具（mcp.* 命名空间）走 scan_all 全参数扫描——参数键名不再
          决定是否被裁决
        - 治理不可用分级 fail-closed：MCP/未知来源 deny + 审计，内置白名单
          放行（治理是可选增强，不因治理故障瘫痪基础能力）

        Returns:
            None: 放行（无可裁决内容，或裁决为 ALLOW，或内置工具+治理故障）。
            Dict: DENY/SANDBOX/ASK/治理故障的替代结果，调用方应直接返回。
        """
        is_mcp = tool_name.startswith("mcp.")
        is_builtin = tool_name in self._builtin_dispatch

        try:
            from neurova.security.governance import GovernanceDecision, get_governance

            verdict = get_governance().evaluate_tool_call(
                tool_name,
                params,
                user_id=self._agent_identity()[0],
                scan_all=is_mcp,
            )
        except Exception as e:
            logger.warning("治理预检不可用 %s（fail-%s）: %s",
                           tool_name, "open/builtin" if is_builtin else "closed", e)
            return self._governance_fail_closed(tool_name, is_mcp, is_builtin, f"治理评估异常: {e}")

        if verdict is None:
            # 无可裁决内容（如 memory_search / screenshot 等），直接放行
            return None
        self._audit_governance(tool_name, verdict.to_dict(), params)

        if verdict.decision == GovernanceDecision.DENY:
            logger.warning("治理拦截工具 %s: %s", tool_name, "; ".join(verdict.reasons))
            return {
                "success": False,
                "error": "被治理策略拦截: " + "; ".join(verdict.reasons),
                "governance": verdict.to_dict(),
            }

        if verdict.decision == GovernanceDecision.SANDBOX:
            if is_mcp:
                # MCP 调用（远端协议/子进程）没有命令行沙箱语义——JSON 参数
                # 落沙箱执行无意义，按阻断处理（fail-closed 语义一致）
                logger.warning("MCP 工具 %s 命中沙箱策略但无沙箱执行语义，已阻止", tool_name)
                return {
                    "success": False,
                    "error": "该 MCP 调用命中沙箱策略，已阻止执行: " + "; ".join(verdict.reasons),
                    "governance": verdict.to_dict(),
                }
            from neurova.security.governance import extract_adjudicable_params

            command, file_path = extract_adjudicable_params(params, scan_all=False)
            if command:
                from neurova.sandbox.exec_sandbox import execute_in_sandbox_async

                # 异步入口：auto 模式下需要隔离且 Docker 可用时走容器（跨平台真隔离），
                # 否则回退平台后端（Windows AppContainer 为占位）
                sandbox_result = await execute_in_sandbox_async(command, severity=verdict.severity)
                sandbox_result["governance"] = verdict.to_dict()
                return sandbox_result
            # 文件类操作暂无文件系统沙箱后端：降级为阻止并说明原因
            logger.warning("文件操作命中沙箱策略但无文件沙箱后端，已阻止: %s", file_path)
            return {
                "success": False,
                "error": "该文件位置受保护，已阻止访问: " + "; ".join(verdict.reasons),
                "governance": verdict.to_dict(),
            }

        if verdict.decision == GovernanceDecision.ASK:
            # ASK 语义：创建待审批记录（metadata 存完整调用供批准后重放），
            # 前端据 approval_id 弹出确认框
            approval_id = self._create_approval_request(tool_name, params, verdict)
            return {
                "success": False,
                "pending_approval": True,
                "approval_id": approval_id,
                "tool_name": tool_name,
                "params": params,
                "error": "操作待用户确认: " + "; ".join(verdict.reasons),
                "governance": verdict.to_dict(),
            }

        return None  # ALLOW 放行

    def _governance_fail_closed(
        self, tool_name: str, is_mcp: bool, is_builtin: bool, reason: str
    ) -> Optional[Dict]:
        """治理不可用时的分级处置（P0-2 fail-open → 分级 fail-closed）。

        - 内置白名单工具：放行（治理是可选增强，基础能力不因治理故障瘫痪）
        - MCP / 未知来源（动态注册、来源不明）：deny 并留痕——未知代码面
          在无治理审查时放行等于裸奔
        """
        if is_builtin and not is_mcp:
            return None
        logger.warning("治理不可用，拒绝非内置工具 %s: %s", tool_name, reason)
        return {
            "success": False,
            "error": f"治理服务不可用，已拒绝执行（fail-closed）: {reason}",
            "governance": {
                "decision": "deny",
                "reasons": [reason],
                "severity": "none",
                "finding_count": 0,
            },
        }

    def _create_approval_request(self, tool_name: str, params: Dict, verdict) -> Optional[str]:
        """为 ASK 裁决创建待审批请求；失败不阻断主流程（返回 None 走原语义）。"""
        try:
            am = _get_approval_manager()
            command = str(params.get("command") or params.get("code") or "")
            _user_id, _agent_id = self._agent_identity()
            request = am.create_approval_request(
                agent_id=str(_agent_id or "default"),
                user_id=str(_user_id or ""),
                command=command or f"{tool_name}({params})",
                description=f"工具 {tool_name} 待人工确认",
                danger_reason="; ".join(verdict.reasons),
                metadata={
                    "tool_name": tool_name,
                    "params": params,
                    "governance": verdict.to_dict(),
                },
            )
            return getattr(request, "request_id", None)
        except Exception as e:  # noqa: BLE001 - 审批系统故障时保持可用
            logger.warning("创建审批请求失败，ASK 降级为直接拒绝: %s", e)
            return None

    def _audit_governance(self, tool_name: str, governance_info: Dict, params: Dict) -> None:
        """记录治理裁决到审计日志；任何失败不影响工具执行。"""
        try:
            from neurova.security.audit_logger import (
                AuditEventType,
                AuditLogEntry,
                AuditLogger,
                AuditSeverity,
            )

            decision = governance_info.get("decision", "unknown")
            # P0-2 修复：severity 是 AuditLogEntry 必填字段，此前未传导致
            # 所有治理审计写入静默失败（TypeError 被吞），deny 留痕落不了盘
            audit_severity = {
                "deny": AuditSeverity.HIGH,
                "sandbox": AuditSeverity.MEDIUM,
                "ask": AuditSeverity.MEDIUM,
                "allow": AuditSeverity.LOW,
            }.get(decision, AuditSeverity.MEDIUM)
            AuditLogger().log(
                AuditLogEntry(
                    event_type=(
                        AuditEventType.TOOL_EXECUTION
                        if decision == "allow"
                        else AuditEventType.SECURITY_EVENT
                    ),
                    severity=audit_severity,
                    user_id=str(self._agent_identity()[0] or ""),
                    action=f"governance:{decision}",
                    details={"tool": tool_name, "governance": governance_info},
                )
            )
        except Exception:
            logger.debug("治理审计日志写入失败: %s", tool_name, exc_info=True)

    async def _execute_workflow_agent_tool(self, params: Dict) -> Dict:
        """遗留③a：run_workflow_agent 工具实现（P2-4.2 chat→工作流闭环）。

        deps 经 neurflow_api 装配（set_workflow_agent_deps），本方法只做
        参数校验 + 信封转换。桥接失败信封（AGENT_NOT_FOUND 等）转为
        {"error": ...} 以兼容四级回退链的成败判定约定。
        """
        agent_id = (params or {}).get("agent_id")
        if not agent_id:
            return {"error": "run_workflow_agent requires params.agent_id"}

        from neurova.agent.workflow_agent import execute_workflow_agent

        inputs = (params or {}).get("inputs")
        if not isinstance(inputs, dict):
            inputs = {"message": (params or {}).get("message", "")}

        outcome = await execute_workflow_agent(agent_id, inputs)
        if outcome.get("success"):
            return {
                "success": True,
                "result": outcome.get("outputs"),
                "execution_id": outcome.get("execution_id"),
            }
        return {"error": outcome.get("error") or "WORKFLOW_AGENT_EXECUTION_FAILED"}

    async def _execute_builtin_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行内置工具(分派表驱动,见 _builtin_dispatch 注释)"""
        method_name = self._builtin_dispatch.get(tool_name)
        if method_name is None:
            return {"error": f"未知内置工具: {tool_name}"}
        # 三层隔离:browser_* 路径注入请求级 userId 到 ContextVar,
        # 让 BrowserManager(单例)能按 user 池化 camofox 后端,避免 _tabs/_active_target_id 跨用户污染。
        if tool_name.startswith("browser_"):
            self._inject_browser_identity()
        return await getattr(self, method_name)(params)

    def _inject_browser_identity(self) -> None:
        """从 _agent_identity 取 userId,写到 ContextVar + 通知 supervisor track。
        失败不阻断——单租户场景 userId=None 时仍走 fallback 路径。"""
        try:
            user_id, _ = self._agent_identity()
        except Exception:
            return
        if not user_id:
            return
        try:
            from neurova.core.identity_context import set_request_user_id

            set_request_user_id(user_id)
        except ImportError:
            pass
        try:
            from neurova.computer_use.camofox_supervisor import get_camofox_supervisor

            get_camofox_supervisor().track_user_id(user_id)
        except Exception:
            pass

    # ── 蜂群工具（SwarmManager 深度模块的薄封装） ────────────────

    async def _execute_spawn_subagent(self, params: Dict) -> Dict:
        """蜂群派生子 Agent 执行任务"""
        from neurova.agent.swarm import get_swarm_manager

        task = params.get("task", "")
        if not task:
            return {"error": "缺少 task 参数"}

        swarm = get_swarm_manager()
        return await swarm.spawn(
            task=str(task),
            agent_id=params.get("agent_id") or None,
            session_id=getattr(self._agent, "_current_session_id", None),
            background=bool(params.get("background", False)),
            origin="chat",
            stream=True,
            initiator_agent=self._agent,
        )

    async def _execute_subagent_status(self, params: Dict) -> Dict:
        """查询后台子 Agent 状态/结果"""
        from neurova.agent.swarm import get_swarm_manager

        subagent_id = params.get("subagent_id", "")
        if not subagent_id:
            return {"error": "缺少 subagent_id 参数"}
        return get_swarm_manager().status(subagent_id)

    async def _execute_list_agents(self, params: Dict) -> Dict:
        """列出可用 Agent（供蜂群派生时挑选执行者）"""
        agents_info = []
        try:
            from neurova.api.endpoints import get_app_state

            state = get_app_state()
            agents = (state or {}).get("agents", {}) or {}
            for aid, agent in agents.items():
                if agent is None:
                    continue
                cfg = getattr(agent, "config", None)
                llm_cfg = getattr(cfg, "llm_config", None)
                agents_info.append(
                    {
                        "agent_id": aid,
                        "name": getattr(cfg, "name", aid),
                        "description": (getattr(cfg, "description", "") or "")[:120],
                        "model": getattr(llm_cfg, "model", "") if llm_cfg else "",
                    }
                )
        except ImportError:
            return {"error": "Agent 注册中心不可用"}
        return {"agents": agents_info, "count": len(agents_info)}

    async def _execute_create_skill(self, params: Dict) -> Dict:
        """让 LLM 主动创建可复用技能（一组工具步骤的封装）。

        创建后立即通过 SkillRegistry.register_skill 注册，借助
        ToolSequenceSkill 的执行体解释器立刻可被调用——下一轮 LLM
        就能在工具列表中看到这个技能并直接调用。
        """
        from types import SimpleNamespace

        name = (params.get("name") or "").strip()
        description = (params.get("description") or "").strip()
        steps = params.get("steps")
        if not name or not description or not steps:
            missing = [
                k
                for k, v in (
                    ("name", name),
                    ("description", description),
                    ("steps", steps),
                )
                if not v
            ]
            return {"error": f"create_skill 缺少必填参数: {', '.join(missing)}"}
        if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
            return {"error": "create_skill.steps 必须是对象列表"}

        tool_sequence: list = []
        for idx, step in enumerate(steps):
            step_name = step.get("name")
            step_params = step.get("params") or {}
            if not step_name or not isinstance(step_params, dict):
                return {
                    "error": f"第 {idx} 步格式错误：必须包含 name 字段和 params 对象"
                }
            tool_sequence.append({"tool": step_name, "params": step_params})

        manifest = SimpleNamespace(
            name=name,
            id=name,
            description=description,
            config={"tool_sequence": tool_sequence, "source": "llm_created"},
        )
        registry = getattr(self._agent, "_skill_registry", None)
        if registry is None:
            return {"error": "当前 Agent 尚未初始化 SkillRegistry"}
        if not registry.register_skill(manifest):
            return {"error": f"注册技能 {name} 失败"}
        return {
            "success": True,
            "skill_name": name,
            "step_count": len(tool_sequence),
            "message": (
                f"技能 {name} 已创建并在 SkillRegistry 中注册，"
                f"下轮对话起 LLM 即可在工具列表中直接调用"
            ),
        }

    # ── 画布工具（CanvasOpService 语义操作层的薄封装） ───────────
    # 所有写操作经 canvas_ops（与 HTTP 端点 /canvas/{id}/ops 共用同一层，
    # 乐观锁 + 事件广播）。错误统一转为 {"success": False, "code": ...}
    # 供 LLM 分支处理：
    #   version_conflict  → 画布被用户抢占，canvas_read 重读后按新版本重试
    #   unknown_node_type → canvas_list_nodes 查询可用节点类型

    def _canvas_session_id(self) -> Optional[str]:
        return getattr(self._agent, "_current_session_id", None)

    @staticmethod
    def _canvas_error_result(e: Exception) -> Dict:
        if isinstance(e, CanvasVersionConflict):
            return {
                "success": False,
                "code": "version_conflict",
                "current_version": getattr(e, "current_version", None),
                "error": (
                    f"{e} —— 画布已被其他编辑者更新，请先用 canvas_read "
                    f"重新读取最新快照，再基于新版本号重试操作"
                ),
            }
        if isinstance(e, CanvasOpError):
            return {"success": False, "code": e.code, "error": str(e)}
        return {"success": False, "code": "canvas_error", "error": str(e)}

    async def _canvas_call(self, method: str, **kwargs) -> Dict:
        """调用 CanvasOpService；业务异常统一转为结构化错误 dict"""
        try:
            return await getattr(get_canvas_op_service(), method)(**kwargs)
        except (CanvasOpError, CanvasVersionConflict) as e:
            return self._canvas_error_result(e)

    @staticmethod
    def _is_canvas_error(result: Any) -> bool:
        return isinstance(result, dict) and result.get("success") is False

    async def _execute_canvas_create(self, params: Dict) -> Dict:
        name = str(params.get("name") or "").strip()
        if not name:
            return {"success": False, "code": "invalid_params", "error": "缺少画布名称 (name)"}
        record = await self._canvas_call(
            "create_canvas",
            name=name,
            description=str(params.get("description") or ""),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(record):
            return record
        return {
            "success": True,
            "canvas_id": record["id"],
            "version": record.get("version", 1),
            "message": "画布已创建并实时同步到前端画布页，后续操作请携带此 canvas_id",
        }

    async def _execute_canvas_read(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        if not canvas_id:
            return {"success": False, "code": "invalid_params", "error": "缺少 canvas_id"}
        record = await self._canvas_call("read_canvas", canvas_id=canvas_id)
        if self._is_canvas_error(record):
            return record
        return {
            "success": True,
            "canvas": record,
            "version": record.get("version"),
            "message": "后续修改操作可将此 version 作为 base_version 传入",
        }

    async def _execute_canvas_add_node(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        node_type = str(params.get("node_type") or "").strip()
        if not canvas_id or not node_type:
            return {
                "success": False,
                "code": "invalid_params",
                "error": "缺少 canvas_id 或 node_type",
            }
        node = await self._canvas_call(
            "add_node",
            canvas_id=canvas_id,
            node_type=node_type,
            config=params.get("config") or None,
            position=params.get("position") or None,
            label=params.get("label") or None,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(node):
            return node
        return {"success": True, "node": node}

    async def _execute_canvas_connect(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        source_node = str(params.get("source_node") or "").strip()
        target_node = str(params.get("target_node") or "").strip()
        if not canvas_id or not source_node or not target_node:
            return {
                "success": False,
                "code": "invalid_params",
                "error": "缺少 canvas_id / source_node / target_node",
            }
        edge = await self._canvas_call(
            "connect",
            canvas_id=canvas_id,
            source_node=source_node,
            target_node=target_node,
            source_port=params.get("source_port") or None,
            target_port=params.get("target_port") or None,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(edge):
            return edge
        return {"success": True, "edge": edge}

    async def _execute_canvas_set_config(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        node_id = str(params.get("node_id") or "").strip()
        values = params.get("values")
        if not canvas_id or not node_id:
            return {
                "success": False,
                "code": "invalid_params",
                "error": "缺少 canvas_id 或 node_id",
            }
        if not isinstance(values, dict):
            return {
                "success": False,
                "code": "invalid_params",
                "error": "values 必须是对象（键为节点表单字段 id）",
            }
        node = await self._canvas_call(
            "set_config",
            canvas_id=canvas_id,
            node_id=node_id,
            values=values,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(node):
            return node
        return {"success": True, "node": node}

    async def _execute_canvas_move_node(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        node_id = str(params.get("node_id") or "").strip()
        try:
            x = float(params.get("x"))
            y = float(params.get("y"))
        except (TypeError, ValueError):
            return {
                "success": False,
                "code": "invalid_params",
                "error": "x / y 必须是数值坐标",
            }
        if not canvas_id or not node_id:
            return {
                "success": False,
                "code": "invalid_params",
                "error": "缺少 canvas_id 或 node_id",
            }
        node = await self._canvas_call(
            "move_node",
            canvas_id=canvas_id,
            node_id=node_id,
            x=x,
            y=y,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(node):
            return node
        return {"success": True, "node": node}

    async def _execute_canvas_remove_node(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        node_id = str(params.get("node_id") or "").strip()
        if not canvas_id or not node_id:
            return {
                "success": False,
                "code": "invalid_params",
                "error": "缺少 canvas_id 或 node_id",
            }
        result = await self._canvas_call(
            "remove_node",
            canvas_id=canvas_id,
            node_id=node_id,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(result):
            return result
        return {"success": True, **result}

    async def _execute_canvas_layout(self, params: Dict) -> Dict:
        canvas_id = str(params.get("canvas_id") or "").strip()
        if not canvas_id:
            return {"success": False, "code": "invalid_params", "error": "缺少 canvas_id"}
        positions = await self._canvas_call(
            "apply_layout",
            canvas_id=canvas_id,
            base_version=params.get("base_version"),
            session_id=self._canvas_session_id(),
            actor="agent",
        )
        if self._is_canvas_error(positions):
            return positions
        return {"success": True, "positions": positions}

    async def _execute_canvas_list_nodes(self, params: Dict) -> Dict:
        limit = params.get("limit") or 20
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        nodes = await self._canvas_call(
            "list_nodes",
            query=params.get("query") or None,
            category=params.get("category") or None,
            limit=limit,
        )
        if self._is_canvas_error(nodes):
            return nodes
        return {"success": True, "nodes": nodes, "count": len(nodes)}

    async def _execute_canvas_run(self, params: Dict) -> Dict:
        """编译画布 → neurflow 同步执行 → 返回节点级结果摘要"""
        canvas_id = str(params.get("canvas_id") or "").strip()
        if not canvas_id:
            return {"success": False, "code": "invalid_params", "error": "缺少 canvas_id"}
        record = await self._canvas_call("read_canvas", canvas_id=canvas_id)
        if self._is_canvas_error(record):
            return record

        from neurova.collaboration.canvas_bridge import canvas_to_workflow

        try:
            workflow = canvas_to_workflow(record, name=record.get("name") or canvas_id)
        except ValueError as e:
            return {"success": False, "code": "invalid_canvas", "error": str(e)}

        inputs = params.get("inputs") or {}
        executor = get_workflow_executor()
        try:
            instance = executor.create_instance(workflow, inputs=inputs, user_id="agent")
            instance = await executor.execute(
                workflow,
                inputs=inputs,
                user_id="agent",
                session_id=self._canvas_session_id(),
                instance=instance,
            )
        except Exception as e:  # noqa: BLE001 - 执行失败要转成 LLM 可读结构
            logger.exception("画布工作流执行失败: %s", canvas_id)
            return {"success": False, "code": "run_failed", "error": str(e)}

        status = getattr(instance.status, "value", instance.status)
        node_results = {}
        for nid, nr in (getattr(instance, "node_results", None) or {}).items():
            node_results[nid] = {
                "status": getattr(nr.status, "value", nr.status),
                "output": getattr(nr, "output", None),
                "error": getattr(nr, "error", None),
                "duration": getattr(nr, "duration", None),
            }
        status_str = str(status)
        return {
            "success": status_str in ("completed", "succeeded", "success"),
            "status": status_str,
            "outputs": getattr(instance, "outputs", None) or {},
            "error": getattr(instance, "error", None),
            "node_results": node_results,
            "duration": getattr(instance, "duration", None),
        }

    @staticmethod
    def _blocking_fetch(url: str, user_agent: str, timeout: int = 10) -> str:
        """阻塞式 HTTP 抓取 — 只允许经 asyncio.to_thread 在线程池中调用。

        P2-11 修复: urllib.request.urlopen 是阻塞调用（最长卡 timeout 秒），
        原实现直接在事件循环中执行，会卡死整个服务（所有并发会话/心跳全停摆）。
        """
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    async def _execute_web_search(self, params: Dict) -> Dict:
        """执行网页搜索"""
        query = params.get("query") or params.get("q") or params.get("keywords", "")
        if not query:
            return {"error": "缺少搜索查询"}
        try:
            import urllib.parse
            # BUGFIX: 原生 google.com/search 页面需 JS 渲染且反爬，静态抓取拿不到摘要。
            # 改用 Bing HTML 接口（对无 JS 请求返回可解析的 b_caption / b_lineclamp 摘要）。
            url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&setlang=zh-hans"
            # P2-11 修复: 阻塞抓取移入线程池，不得卡死事件循环
            html = await asyncio.to_thread(self._blocking_fetch, url, "Mozilla/5.0")
            # 优先提取 b_caption 下的 <p>（Bing 摘要），退化为任意 <p>
            import re
            snippets = re.findall(r'<div[^>]*class="b_caption"[^>]*>[\s\S]*?<p[^>]*>(.*?)</p>', html, re.DOTALL)
            if not snippets:
                snippets = re.findall(r'<p[^>]*class="[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL)
            text = re.sub(r'<[^>]+>', '', ' '.join(snippets[:5]))
            text = re.sub(r'\s+', ' ', text).strip()[:500]
            return {"query": query, "results": text or f"搜索 '{query}' 完成，但未能提取摘要。请直接告诉用户搜索结果。"}
        except Exception as e:
            return {"query": query, "results": f"搜索 '{query}' 时出错: {e}"}

    async def _execute_weather(self, params: Dict) -> Dict:
        """执行天气查询"""
        location = params.get("location") or params.get("city") or params.get("query", "")
        if not location:
            return {"error": "缺少地点信息"}
        try:
            import urllib.parse
            # 使用 wttr.in 天气服务。
            # BUGFIX: 必须用非浏览器 UA。wttr.in 对 Mozilla/5.0 等浏览器 UA 返回完整 HTML 网页，
            # 导致 format=3 / lang=zh 参数失效，返回一整页 HTML 污染结果。
            # 使用 curl UA 才能得到 format=3 的精简文本（如 "许昌: 🌦️ +80°F"）。
            url = f"https://wttr.in/{urllib.parse.quote(location)}?format=3&lang=zh"
            # P2-11 修复: 阻塞抓取移入线程池，不得卡死事件循环
            text = (await asyncio.to_thread(self._blocking_fetch, url, "curl/8.5.0")).strip()
            # 兜底：极少数代理/部署环境下即使 curl UA 仍返回 HTML，则从中提取天气行
            if "<html" in text.lower() or "&lt;" in text:
                import re
                body = re.sub(r"<script[\s\S]*?</script>", "", text)
                body = re.sub(r"<style[\s\S]*?</style>", "", body)
                body = re.sub(r"<[^>]+>", "", body)
                body = re.sub(r"\s+", " ", body).strip()
                text = body[:200]
            return {"location": location, "weather": text}
        except Exception as e:
            return {"location": location, "error": f"天气查询失败: {e}"}

    # ── 常规 Agent 工具：网页抓取 / 计算 / 时间（对标 WebFetch 等标配）──

    @staticmethod
    def _html_to_text(html: str) -> str:
        """HTML 转纯文本：剥离 script/style/注释/标签，压缩空白"""
        import re

        body = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
        body = re.sub(r"<style[\s\S]*?</style>", "", body, flags=re.IGNORECASE)
        body = re.sub(r"<!--[\s\S]*?-->", "", body)
        body = re.sub(r"<[^>]+>", " ", body)
        body = (
            body.replace("&nbsp;", " ")
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
        )
        lines = [ln.strip() for ln in body.splitlines()]
        text = "\n".join(ln for ln in lines if ln)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    async def _execute_web_fetch(self, params: Dict) -> Dict:
        """抓取网页正文并转纯文本（仅 http/https，拒绝 file:// 等本地协议）"""
        import urllib.parse

        url = (params.get("url") or "").strip()
        if not url:
            return {"error": "缺少 url 参数"}
        scheme = urllib.parse.urlparse(url).scheme.lower()
        if scheme not in ("http", "https"):
            return {"error": f"不支持的协议: {scheme or '(空)'}，仅支持 http/https"}
        try:
            max_chars = int(params.get("max_chars", 8000))
        except (TypeError, ValueError):
            max_chars = 8000

        try:
            # 阻塞抓取走线程池（复用 P2-11 的 _blocking_fetch），不卡事件循环
            html = await asyncio.to_thread(self._blocking_fetch, url, "Mozilla/5.0", 15)
            text = self._html_to_text(html)
            return {
                "url": url,
                "content": text[:max_chars],
                "chars": len(text),
                "truncated": len(text) > max_chars,
            }
        except Exception as e:
            return {"url": url, "error": f"网页抓取失败: {e}"}

    async def _execute_calculator(self, params: Dict) -> Dict:
        """安全数学计算：AST 白名单求值，绝不执行任意代码（无 eval/exec）"""
        import math
        import operator

        expression = (params.get("expression") or "").strip()
        if not expression:
            return {"error": "缺少 expression 参数"}

        binops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        unaryops = {ast.UAdd: operator.pos, ast.USub: operator.neg}
        functions = {
            "sqrt": math.sqrt, "abs": abs, "round": round,
            "min": min, "max": max,
            "sin": math.sin, "cos": math.cos, "tan": math.tan,
            "log": math.log, "log2": math.log2, "log10": math.log10,
            "floor": math.floor, "ceil": math.ceil,
        }
        constants = {"pi": math.pi, "e": math.e}

        def eval_node(node):
            if isinstance(node, ast.Expression):
                return eval_node(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in binops:
                left = eval_node(node.left)
                right = eval_node(node.right)
                if type(node.op) is ast.Pow and abs(right) > self._CALC_MAX_EXPONENT:
                    raise ValueError(f"指数过大（超过 {self._CALC_MAX_EXPONENT}）")
                return binops[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in unaryops:
                return unaryops[type(node.op)](eval_node(node.operand))
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                    raise ValueError("仅允许调用白名单函数")
                if node.keywords:
                    raise ValueError("不支持关键字参数")
                return functions[node.func.id](*[eval_node(a) for a in node.args])
            if isinstance(node, ast.Name) and node.id in constants:
                return constants[node.id]
            raise ValueError(f"不支持的语法: {type(node).__name__}")

        try:
            value = eval_node(ast.parse(expression, mode="eval"))
        except ZeroDivisionError:
            return {"expression": expression, "error": "除零错误"}
        except OverflowError:
            return {"expression": expression, "error": "数值溢出"}
        except Exception as e:
            return {"expression": expression, "error": f"表达式无法计算: {e}"}

        if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
            value = int(value)  # 4.0 → 4，便于阅读
        return {"expression": expression, "result": value}

    async def _execute_get_datetime(self, params: Dict) -> Dict:
        """获取当前日期时间或换算时间戳（支持 IANA 时区名与 ±HH:MM 偏移）"""
        import re
        from datetime import timedelta, timezone as dt_timezone

        tz_param = (params.get("timezone") or params.get("tz") or "").strip()
        ts_param = params.get("timestamp")

        try:
            if ts_param is not None and str(ts_param).strip() != "":
                base_dt = datetime.fromtimestamp(float(ts_param), tz=dt_timezone.utc)
            else:
                base_dt = datetime.now(dt_timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError) as e:
            return {"error": f"无效的时间戳: {ts_param}（{e}）"}

        if tz_param:
            tz = None
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(tz_param)
            except Exception:
                # IANA 名称解析失败时，尝试 ±HH:MM / GMT+H 风格的偏移
                m = re.fullmatch(r"(?:GMT|UTC)?\s*([+-])(\d{1,2})(?::?(\d{2}))?", tz_param)
                if m:
                    sign = 1 if m.group(1) == "+" else -1
                    hours, minutes = int(m.group(2)), int(m.group(3) or 0)
                    if hours <= 23 and minutes <= 59:
                        tz = dt_timezone(sign * timedelta(hours=hours, minutes=minutes))
            if tz is None:
                return {
                    "error": f"无法解析时区: {tz_param}（支持 Asia/Shanghai 等 IANA 名称或 +08:00 偏移）"
                }
            dt = base_dt.astimezone(tz)
        else:
            dt = base_dt.astimezone()  # 系统本地时区

        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return {
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "date": dt.strftime("%Y-%m-%d"),
            "time": dt.strftime("%H:%M:%S"),
            "iso": dt.isoformat(),
            "weekday": weekdays[dt.weekday()],
            "timezone": str(dt.tzinfo),
            "timestamp": int(base_dt.timestamp()),
        }

    async def _execute_memory_search(self, params: Dict) -> Dict:
        """执行记忆搜索"""
        try:
            query = params.get("query", "")
            category = params.get("category")
            limit = params.get("limit", 5)

            if not query:
                return {"error": "缺少搜索查询"}

            # 获取 MemoryManager
            memory_manager = None
            if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                memory_manager = self._agent.memory_manager
            else:
                # 创建临时 MemoryManager（降级模式）
                from neurova.cognitive_layers.memory_layer.manager import MemoryManager

                memory_manager = MemoryManager()

            # 执行搜索
            memories = memory_manager.recall(
                query=query,
                category=category,
                limit=limit,
            )

            # 格式化结果
            results = []
            for memory in memories:
                results.append(
                    {
                        "id": memory.get("id", ""),
                        "content": memory.get("content", ""),
                        "category": memory.get("category", ""),
                        "temperature": memory.get("temperature", 0.0),
                        "created_at": memory.get("created_at", ""),
                    }
                )

            return {
                "success": True,
                "results": results,
                "query": query,
                "category": category,
                "limit": limit,
                "count": len(results),
            }
        except Exception as e:
            logger.error("记忆搜索执行失败: %s", e)
            return {"error": f"记忆搜索执行失败: {str(e)}"}

    async def _execute_file_read(self, params: Dict) -> Dict:
        """执行文件读取"""
        file_path = params.get("file_path", "")
        offset = params.get("offset", 0)
        encoding = params.get("encoding", "utf-8")

        try:
            with open(file_path, "r", encoding=encoding) as f:
                lines = f.readlines()
                if offset > 0:
                    lines = lines[offset - 1 :]  # offset 从 1 开始
                content = "".join(lines)
                return {"content": content, "lines": len(lines)}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_write(self, params: Dict) -> Dict:
        """执行文件写入"""
        file_path = params.get("file_path", "")
        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")

        try:
            with open(file_path, "w", encoding=encoding) as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_create(self, params: Dict) -> Dict:
        """执行文件创建"""
        file_path = params.get("file_path", "")
        content = params.get("content", "")

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
                return {"success": True, "file_path": file_path}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_delete(self, params: Dict) -> Dict:
        """执行文件删除"""
        import os

        file_path = params.get("file_path", "")

        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                return {"success": True, "file_path": file_path}
            else:
                return {"error": f"文件不存在: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

    async def _execute_file_edit(self, params: Dict) -> Dict:
        """执行文件编辑"""
        file_path = params.get("file_path", "")
        old_str = params.get("old_str", "")
        new_str = params.get("new_str", "")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            if old_str in content:
                new_content = content.replace(old_str, new_str, 1)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                return {"success": True, "file_path": file_path}
            else:
                return {"error": "未找到目标文本"}
        except Exception as e:
            return {"error": str(e)}

    # ── 常规 Agent 工具：文件枚举 / 内容搜索（对标 Glob/Grep）──
    # 安全设计：path 参数会进入治理预检（_governance_precheck 扫描 path），
    # 但 pattern 不会；因此此处额外做路径规范化 + 拒绝 .. 段 + 结果约束在
    # 基准目录内，防止 glob/walk 经 ../ 或符号链接逃逸出预期目录。

    @staticmethod
    def _safe_search_base(path: str) -> tuple:
        """规范化搜索根目录并防路径穿越。

        Returns:
            (绝对路径, None) 或 ("", 错误信息)
        """
        import os

        raw = (path or "").strip() or "."
        normalized = os.path.normpath(raw)
        segments = [s for s in normalized.replace("\\", "/").split("/") if s not in ("", ".")]
        if ".." in segments:
            return "", "路径包含 ..，已禁止（防路径穿越）"
        return os.path.abspath(normalized), None

    @staticmethod
    def _path_within(child: str, base: str) -> bool:
        """child 是否位于 base 目录内（均为绝对路径）"""
        import os

        return child == base or child.startswith(base + os.sep)

    async def _execute_file_list(self, params: Dict) -> Dict:
        """文件枚举（glob 模式，默认递归子目录）"""
        import glob
        import os

        pattern = params.get("pattern", "")
        if not pattern:
            return {"error": "缺少 pattern 参数"}
        if ".." in pattern.replace("\\", "/").split("/"):
            return {"error": "pattern 包含 ..，已禁止（防路径穿越）"}
        base = params.get("path") or "."
        recursive = bool(params.get("recursive", True))

        try:
            if os.path.isabs(pattern):
                # 绝对模式：已单独拒绝 ..，不做基目录约束
                full_pattern = pattern
                base_abs = None
            else:
                base_abs, err = self._safe_search_base(base)
                if err:
                    return {"error": err}
                if recursive:
                    # recursive 下 ** 匹配零或多层目录，根目录下的文件也能命中
                    full_pattern = os.path.join(base_abs, "**", pattern)
                else:
                    full_pattern = os.path.join(base_abs, pattern)

            matches = sorted(glob.glob(full_pattern, recursive=recursive))
            if base_abs is not None:
                # 纵深防御：结果必须全部落在基准目录内（防符号链接逃逸）
                matches = [
                    m for m in matches
                    if self._path_within(os.path.abspath(m), base_abs)
                ]
            limit = 500
            truncated = len(matches) > limit
            matches = matches[:limit]
            return {
                "files": matches,
                "count": len(matches),
                "truncated": truncated,
                "pattern": pattern,
            }
        except Exception as e:
            return {"error": f"文件枚举失败: {e}"}

    async def _execute_file_search(self, params: Dict) -> Dict:
        """文件内容搜索（grep：返回 文件/行号/行内容）

        只读操作；遍历范围被 _safe_search_base 规范化并禁止 ..，
        打开的文件全部来自校验后基准目录内的 os.walk 结果。
        """
        import fnmatch
        import os
        import re

        pattern = params.get("pattern", "")
        if not pattern:
            return {"error": "缺少 pattern 参数"}
        path = params.get("path", "")
        if not path:
            return {"error": "缺少 path 参数"}
        include = params.get("include") or None
        try:
            max_results = int(params.get("max_results", 50))
        except (TypeError, ValueError):
            max_results = 50

        target, err = self._safe_search_base(path)
        if err:
            return {"error": err}
        if not os.path.exists(target):
            return {"error": f"路径不存在: {path}"}

        try:
            regex = re.compile(pattern)
        except re.error:
            # 非法正则降级为字面量匹配，而不是报错
            regex = re.compile(re.escape(pattern))

        if os.path.isfile(target):
            candidates = [target]
        else:
            candidates = []
            file_cap = 2000  # 防止超大目录拖垮搜索
            for root, dirs, names in os.walk(target):
                dirs[:] = [d for d in dirs if d not in self._SEARCH_SKIP_DIRS]
                for name in names:
                    if include and not fnmatch.fnmatch(name, include):
                        continue
                    candidates.append(os.path.join(root, name))
                    if len(candidates) >= file_cap:
                        break
                if len(candidates) >= file_cap:
                    break

        matches = []
        for candidate in candidates:
            try:
                with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                    if "\x00" in f.read(4096):
                        continue  # 跳过二进制文件
                    f.seek(0)
                    for lineno, line in enumerate(f, 1):
                        if regex.search(line):
                            matches.append(
                                {
                                    "file": candidate,
                                    "line": lineno,
                                    "text": line.strip()[:200],
                                }
                            )
                            if len(matches) >= max_results:
                                break
            except (OSError, UnicodeDecodeError):
                continue
            if len(matches) >= max_results:
                break

        return {
            "matches": matches,
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "pattern": pattern,
        }

    async def _execute_computer_screenshot(self, params: Dict) -> Dict:
        """执行屏幕截图

        LLM 面向结果只含元信息（base64 会撑爆上下文与会话存储），
        完整截图通过 computer_action 事件实时推给前端分屏面板。
        """
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            # ImageGrab 是阻塞调用，放线程池避免卡事件循环
            screenshot_data = await asyncio.to_thread(manager.screenshot)
            if screenshot_data:
                import base64

                b64_str = base64.b64encode(screenshot_data).decode("utf-8")
                result = {"success": True, "format": "png", "size_bytes": len(screenshot_data)}
                await self._emit_computer_event("computer_screenshot", params, result, screenshot_base64=b64_str)
                return result
            else:
                result = {"error": "截图失败：无可用后端"}
                await self._emit_computer_event("computer_screenshot", params, result)
                return result
        except Exception as e:
            logger.error("截图执行失败: %s", e)
            return {"error": f"截图执行失败: {str(e)}"}

    async def _execute_computer_click(self, params: Dict) -> Dict:
        """执行鼠标点击"""
        try:
            x = params.get("x")
            y = params.get("y")
            button = params.get("button", "left")

            if x is None or y is None:
                return {"error": "缺少必要的坐标参数 x, y"}

            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            # pyautogui 阻塞调用放线程池
            success = await asyncio.to_thread(manager.click, int(x), int(y), button)

            result = (
                {"success": True, "x": x, "y": y, "button": button}
                if success
                else {"error": "点击操作失败", "x": x, "y": y}
            )
            await self._emit_computer_event("computer_click", params, result)
            return result
        except Exception as e:
            logger.error("点击执行失败: %s", e)
            return {"error": f"点击执行失败: {str(e)}"}

    async def _execute_computer_type(self, params: Dict) -> Dict:
        """执行键盘输入"""
        try:
            text = params.get("text", "")
            if not text:
                return {"error": "缺少输入文本"}

            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            success = await asyncio.to_thread(manager.type_text, text)

            result = (
                {"success": True, "text": text, "length": len(text)}
                if success
                else {"error": "输入操作失败"}
            )
            await self._emit_computer_event("computer_type", params, result)
            return result
        except Exception as e:
            logger.error("输入执行失败: %s", e)
            return {"error": f"输入执行失败: {str(e)}"}

    async def _execute_computer_scroll(self, params: Dict) -> Dict:
        """执行屏幕滚动"""
        try:
            scroll_y = params.get("scroll_y", 0)
            # 不指定坐标时在当前指针位置滚动（避免把鼠标强制移到屏幕中心/角落）
            x = params.get("x")
            y = params.get("y")

            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            success = await asyncio.to_thread(manager.scroll, x, y, int(scroll_y) or 3)

            result = (
                {"success": True, "scroll_x": params.get("scroll_x", 0), "scroll_y": scroll_y}
                if success
                else {"error": "滚动操作失败（需要 pyautogui）"}
            )
            await self._emit_computer_event("computer_scroll", params, result)
            return result
        except Exception as e:
            logger.error("滚动执行失败: %s", e)
            return {"error": f"滚动执行失败: {str(e)}"}

    async def _execute_computer_shell(self, params: Dict) -> Dict:
        """执行 shell 命令"""
        try:
            command = params.get("command", "")
            if not command:
                return {"error": "缺少命令参数"}

            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            raw = await manager.shell(command)

            result = {
                "success": raw.get("returncode", -1) == 0,
                "returncode": raw.get("returncode", -1),
                "stdout": raw.get("stdout", ""),
                "stderr": raw.get("stderr", ""),
                "command": command,
            }
            await self._emit_computer_event("computer_shell", params, result)
            return result
        except Exception as e:
            logger.error("Shell 命令执行失败: %s", e)
            return {"error": f"Shell 命令执行失败: {str(e)}"}

    # ── 浏览器操作工具（ComputerUseManager → BrowserManager 多后端）──

    @staticmethod
    def _normalize_browser_result(result: Any) -> Dict:
        """BrowserResult(dataclass)/dict/None → LLM 面向的紧凑 dict（不含截图大对象）"""
        if isinstance(result, dict):
            normalized = dict(result)
            normalized.pop("image_base64", None)
            if normalized.get("error"):
                normalized["success"] = False
            return normalized
        if result is None:
            return {"success": False, "error": "浏览器管理器不可用"}
        to_dict = getattr(result, "to_dict", None)
        if not callable(to_dict):
            return {"success": False, "error": "浏览器返回格式未知"}
        normalized = dict(to_dict())
        normalized.pop("has_screenshot", None)
        if not normalized.get("success") and not normalized.get("error"):
            normalized["error"] = "浏览器操作失败"
        return normalized

    async def _emit_computer_event(
        self,
        tool_name: str,
        params: Dict,
        result: Dict,
        screenshot_base64: Optional[str] = None,
    ) -> None:
        """电脑/浏览器操作实时事件广播（computer_action）

        通过 SessionSyncManager 推送到会话 WS，驱动聊天页分屏面板；
        广播失败静默处理，绝不影响工具执行主流程。
        """
        if tool_name not in COMPUTER_USE_TOOLS:
            return
        session_id = getattr(self._agent, "_current_session_id", None)
        if not session_id:
            return
        try:
            from neurova.sync.session_sync_manager import (
                EventType,
                SessionEvent,
                get_session_sync_manager,
            )

            payload: Dict[str, Any] = {
                "tool": tool_name,
                "params": params,
                "success": bool(result.get("success")) if isinstance(result, dict) else False,
                "summary": describe_computer_action(tool_name, params),
                "timestamp": datetime.now().isoformat(),
            }
            error = result.get("error") if isinstance(result, dict) else None
            if error:
                payload["error"] = str(error)
            url = result.get("url") if isinstance(result, dict) else None
            if url:
                payload["url"] = url
            if screenshot_base64:
                payload["screenshot"] = screenshot_base64

            mgr = get_session_sync_manager()
            mgr.register_or_create_session(session_id=session_id, user_id="agent")
            event = SessionEvent(
                event_type=EventType.COMPUTER_ACTION,
                session_id=session_id,
                source_channel="tool",
                payload=payload,
            )
            await mgr.broadcast_event(session_id, event)
        except Exception as e:  # noqa: BLE001 - 广播失败不影响主流程
            logger.debug("computer_action 事件广播失败 (%s): %s", tool_name, e)

    async def _execute_browser_navigate(self, params: Dict) -> Dict:
        """浏览器导航到 URL"""
        url = str(params.get("url") or "").strip()
        if not url:
            return {"error": "缺少 URL 参数"}
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = self._normalize_browser_result(await manager.browser_navigate(url))
            await self._emit_computer_event("browser_navigate", params, result)
            return result
        except Exception as e:
            logger.error("浏览器导航失败: %s", e)
            return {"error": f"浏览器导航失败: {str(e)}"}

    async def _execute_browser_click(self, params: Dict) -> Dict:
        """点击页面元素（CSS 选择器或可见文本）"""
        selector = str(params.get("selector") or "").strip()
        text = str(params.get("text") or "").strip()
        if not selector and not text:
            return {"error": "缺少 selector 或 text 参数"}
        target = selector or f"text={text}"
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = self._normalize_browser_result(await manager.browser_click(target))
            await self._emit_computer_event("browser_click", params, result)
            return result
        except Exception as e:
            logger.error("浏览器点击失败: %s", e)
            return {"error": f"浏览器点击失败: {str(e)}"}

    async def _execute_browser_type(self, params: Dict) -> Dict:
        """向页面输入框填写文本"""
        selector = str(params.get("selector") or "").strip()
        text = params.get("text")
        if not selector:
            return {"error": "缺少 selector 参数"}
        if text is None or str(text) == "":
            return {"error": "缺少 text 参数"}
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = self._normalize_browser_result(await manager.browser_type(selector, str(text)))
            await self._emit_computer_event("browser_type", params, result)
            return result
        except Exception as e:
            logger.error("浏览器输入失败: %s", e)
            return {"error": f"浏览器输入失败: {str(e)}"}

    async def _execute_browser_screenshot(self, params: Dict) -> Dict:
        """截取当前页面；完整截图走 computer_action 事件，不进 LLM 消息"""
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            raw = await manager.browser_screenshot()
            shot_b64 = getattr(raw, "screenshot", None)
            result = self._normalize_browser_result(raw)
            if result.get("success") and shot_b64:
                result.setdefault("format", "png")
            await self._emit_computer_event("browser_screenshot", params, result, screenshot_base64=shot_b64)
            return result
        except Exception as e:
            logger.error("浏览器截图失败: %s", e)
            return {"error": f"浏览器截图失败: {str(e)}"}

    async def _execute_browser_extract_text(self, params: Dict) -> Dict:
        """提取当前页面正文文本"""
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            raw = await manager.browser_extract_text()
            result = self._normalize_browser_result(raw)
            data = result.get("data")
            if isinstance(data, str) and len(data) > 8000:
                # 超长正文截断后再进 LLM 上下文
                result["data"] = data[:8000] + "…[已截断]"
                result["truncated"] = True
            await self._emit_computer_event("browser_extract_text", params, result)
            return result
        except Exception as e:
            logger.error("页面文本提取失败: %s", e)
            return {"error": f"页面文本提取失败: {str(e)}"}

    async def _execute_browser_dom_snapshot(self, params: Dict) -> Dict:
        """获取 aria 可访问性树快照（观察优先：先快照拿 role+name，再 role 定位交互）"""
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            generation = params.get("generation")
            result = self._normalize_browser_result(
                await manager.browser_dom_snapshot(generation=int(generation) if generation is not None else None)
            )
            data = result.get("data")
            if isinstance(data, str) and len(data) > 8000:
                # 超长 aria 树截断后再进 LLM 上下文
                result["data"] = data[:8000] + "…[已截断]"
                result["truncated"] = True
            await self._emit_computer_event("browser_dom_snapshot", params, result)
            return result
        except Exception as e:
            logger.error("页面快照失败: %s", e)
            return {"error": f"页面快照失败: {str(e)}"}

    async def _execute_browser_click_role(self, params: Dict) -> Dict:
        """按 ARIA role + accessible name 定位点击（从 dom_snapshot 的快照事实取参）"""
        role = str(params.get("role") or "").strip()
        name = params.get("name")
        generation = params.get("generation")
        if not role:
            return {"error": "缺少 role 参数（先调用 browser_dom_snapshot 从快照获取 role+name）"}
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = self._normalize_browser_result(
                await manager.browser_click_role(
                    role, str(name) if name is not None else None,
                    generation=int(generation) if generation is not None else None,
                )
            )
            await self._emit_computer_event("browser_click_role", params, result)
            return result
        except Exception as e:
            logger.error("role 点击失败: %s", e)
            return {"error": f"role 点击失败: {str(e)}"}

    async def _execute_browser_fill_role(self, params: Dict) -> Dict:
        """按 ARIA role + accessible name 定位输入框填写"""
        role = str(params.get("role") or "").strip()
        name = params.get("name")
        text = params.get("text")
        generation = params.get("generation")
        if not role:
            return {"error": "缺少 role 参数（先调用 browser_dom_snapshot 从快照获取 role+name）"}
        if text is None:
            return {"error": "缺少 text 参数（空串表示清空输入框）"}
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = self._normalize_browser_result(
                await manager.browser_fill_role(
                    role, str(name) if name is not None else None, str(text),
                    generation=int(generation) if generation is not None else None,
                )
            )
            await self._emit_computer_event("browser_fill_role", params, result)
            return result
        except Exception as e:
            logger.error("role 输入失败: %s", e)
            return {"error": f"role 输入失败: {str(e)}"}

    async def _execute_planning(self, params: Dict) -> Dict:
        """任务计划工具：7 个子命令（create/update/list/get/set_active/mark_step/delete）。

        三层隔离：调用者身份 (user_id, agent_id) 注入归属，计划按归属隔离。
        """
        command = str(params.get("command") or "").strip()
        if not command:
            return {"error": "缺少 command 参数"}
        try:
            from neurova.planning import PlanningTool, get_planning_store

            tool = PlanningTool(store=get_planning_store())
            try:
                caller_user_id, caller_agent_id = self._agent_identity()
            except Exception:
                caller_user_id, caller_agent_id = "default", "default"
            kwargs = {
                k: v for k, v in params.items() if k != "command" and v is not None
            }
            return await tool.run_command(
                command=command,
                owner_agent_id=caller_agent_id or "default",
                owner_user_id=caller_user_id or "default",
                **kwargs,
            )
        except Exception as e:
            logger.error("planning 工具执行失败: %s", e)
            return {"error": f"planning 工具执行失败: {str(e)}"}

    # ── Web Reach 平台直达（youtube/bilibili/rss/v2ex/social，共用分发）──

    async def _web_reach_call(self, tool_name: str, params: Dict) -> Dict:
        """Web Reach 统一分发。阻塞网络/子进程调用放线程池，避免卡事件循环。"""
        import asyncio as _asyncio

        params = params or {}
        try:
            from neurova.web_reach import (
                bilibili_search,
                rss_read,
                social_search,
                v2ex_hot,
                web_read,
                youtube_transcript,
            )

            if tool_name == "youtube_transcript":
                url = str(params.get("url") or "").strip()
                if not url:
                    return {"error": "缺少 url 参数"}
                return await _asyncio.to_thread(youtube_transcript, url)
            if tool_name == "bilibili_search":
                query = str(params.get("query") or "").strip()
                if not query:
                    return {"error": "缺少 query 参数"}
                return await _asyncio.to_thread(bilibili_search, query, int(params.get("limit", 5)))
            if tool_name == "rss_read":
                url = str(params.get("url") or "").strip()
                if not url:
                    return {"error": "缺少 url 参数"}
                return await _asyncio.to_thread(rss_read, url, int(params.get("limit", 10)))
            if tool_name == "v2ex_hot":
                return await _asyncio.to_thread(v2ex_hot, int(params.get("limit", 10)))
            if tool_name == "social_search":
                platform = str(params.get("platform") or "").strip()
                query = str(params.get("query") or "").strip()
                if not platform or not query:
                    return {"error": "缺少 platform 或 query 参数"}
                # 三层隔离：请求级登录用户（_current_user_id）作为凭据分桶主体
                user_id = getattr(self._agent, "_current_user_id", None) or "default"
                return await _asyncio.to_thread(
                    social_search, platform, query, user_id=user_id
                )
            return {"error": f"未知 web_reach 工具: {tool_name}"}
        except Exception as e:
            logger.error("web_reach 工具 %s 执行失败: %s", tool_name, e)
            return {"error": f"web_reach 工具执行失败: {str(e)}"}

    async def _execute_youtube_transcript(self, params: Dict) -> Dict:
        return await self._web_reach_call("youtube_transcript", params)

    async def _execute_bilibili_search(self, params: Dict) -> Dict:
        return await self._web_reach_call("bilibili_search", params)

    async def _execute_rss_read(self, params: Dict) -> Dict:
        return await self._web_reach_call("rss_read", params)

    async def _execute_v2ex_hot(self, params: Dict) -> Dict:
        return await self._web_reach_call("v2ex_hot", params)

    async def _execute_social_search(self, params: Dict) -> Dict:
        return await self._web_reach_call("social_search", params)

    async def _execute_emotion_analyze(self, params: Dict) -> Dict:
        """执行情感分析"""
        try:
            text = params.get("text", "")
            if not text:
                return {"error": "缺少分析文本"}

            # 优先使用 Agent 的 memory_manager 中的情感分析器
            emotion_analyzer = None
            if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                emotion_analyzer = getattr(self._agent.memory_manager, "_emotion_analyzer", None)

            # 如果没有，使用全局实例
            if not emotion_analyzer:
                try:
                    from neurova.cognitive_layers.memory_layer.emotion import get_emotion_analyzer_instance

                    emotion_analyzer = get_emotion_analyzer_instance()
                except ImportError:
                    logger.warning("情感分析器模块不可用，使用简化实现")
                    return self._fallback_emotion_analyze(text)

            # 执行情感分析
            result = emotion_analyzer.analyze(text)

            return {
                "success": True,
                "primary_emotion": result.get("primary_emotion", "neutral"),
                "confidence": result.get("confidence", 0.0),
                "emotions": result.get("emotions", {}),
                "tags": result.get("tags", []),
                "score": result.get("score", 0.0),
                "text": text,
            }
        except Exception as e:
            logger.error("情感分析执行失败: %s", e)
            return self._fallback_emotion_analyze(text)

    def _fallback_emotion_analyze(self, text: str) -> Dict:
        """简化情感分析回退实现"""
        text_lower = text.lower()

        # 简单关键词匹配
        emotion_keywords = {
            "happy": ["开心", "高兴", "快乐", "愉快", "欣喜", "happy", "joy", "glad"],
            "sad": ["伤心", "难过", "悲伤", "忧伤", "sad", "sorrow", "unhappy"],
            "angry": ["生气", "愤怒", "恼火", "angry", "furious", "mad"],
            "surprise": ["惊讶", "惊喜", "意外", "surprise", "amazed"],
            "fear": ["害怕", "恐惧", "担心", "afraid", "fear", "scared"],
            "disgust": ["厌恶", "讨厌", "恶心", "disgust", "dislike"],
        }

        detected_emotion = "neutral"
        max_score = 0.0

        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    score = 0.7 + (0.3 * (1.0 / (len(text) + 1)))
                    if score > max_score:
                        max_score = score
                        detected_emotion = emotion

        if detected_emotion == "neutral":
            return {
                "success": True,
                "primary_emotion": "neutral",
                "confidence": 0.5,
                "emotions": {"neutral": 1.0},
                "tags": ["neutral"],
                "score": 0.0,
                "text": text,
            }

        return {
            "success": True,
            "primary_emotion": detected_emotion,
            "confidence": max_score,
            "emotions": {detected_emotion: max_score, "neutral": 1.0 - max_score},
            "tags": [detected_emotion],
            "score": max_score - 0.5,
            "text": text,
        }

    # ── 语音工具执行体（修复漂移：schema 早已注册但分派链缺失）──

    async def _execute_asr_transcribe(self, params: Dict) -> Dict:
        """语音识别：Base64 音频 → 文本（经 agent.asr_manager）"""
        import base64

        audio_b64 = params.get("audio_data", "")
        if not audio_b64:
            return {"error": "缺少 audio_data 参数（Base64 编码音频）"}
        manager = getattr(self._agent, "asr_manager", None)
        if manager is None:
            return {"error": "ASR 未启用（asr_manager 不存在），请先在 Agent 配置中开启 asr"}

        try:
            audio_bytes = base64.b64decode(audio_b64, validate=True)
        except Exception as e:
            return {"error": f"audio_data 不是有效的 Base64: {e}"}

        try:
            if not getattr(manager, "is_initialized", False):
                await manager.initialize()
            result = await manager.transcribe(audio_bytes, language=params.get("language", "zh"))
        except Exception as e:
            return {"error": f"语音识别失败: {e}"}

        if isinstance(result, dict):
            if result.get("error") and not result.get("text"):
                return {"error": f"语音识别失败: {result['error']}"}
            return {
                "success": True,
                "text": result.get("text", ""),
                "language": result.get("language"),
                "duration_sec": result.get("duration_sec"),
            }
        return {"success": True, "text": str(result)}

    async def _execute_tts_synthesize(self, params: Dict) -> Dict:
        """语音合成：文本 → 音频文件（经 agent.tts_manager）

        音频写入临时文件，只回传路径与元信息——把 base64 音频塞进
        LLM 上下文会撑爆 token（与 computer_screenshot 只回元信息同理）。
        voice/engine 在 manager 初始化时已配置，且部分引擎的 synthesize
        签名不接受额外 kwargs，故不透传。
        """
        import os
        import tempfile

        text = params.get("text", "")
        if not text:
            return {"error": "缺少 text 参数"}
        manager = getattr(self._agent, "tts_manager", None)
        if manager is None:
            return {"error": "TTS 未启用（tts_manager 不存在），请先在 Agent 配置中开启 tts"}

        try:
            if not getattr(manager, "is_initialized", False):
                await manager.initialize()
            audio = await manager.synthesize(text)
        except Exception as e:
            return {"error": f"语音合成失败: {e}"}
        if not audio:
            return {"error": "语音合成失败: 引擎返回空数据"}

        # 按文件头识别音频格式
        suffix = ".bin"
        if audio.startswith(b"RIFF"):
            suffix = ".wav"
        elif audio.startswith(b"ID3") or audio[:1] == b"\xff":
            suffix = ".mp3"
        elif audio.startswith(b"OggS"):
            suffix = ".ogg"

        try:
            out_dir = os.path.join(tempfile.gettempdir(), "neurova_tts")
            os.makedirs(out_dir, exist_ok=True)
            fd, audio_path = tempfile.mkstemp(suffix=suffix, prefix="tts_", dir=out_dir)
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
        except OSError as e:
            return {"error": f"音频文件写入失败: {e}"}

        return {
            "success": True,
            "audio_path": audio_path,
            "bytes": len(audio),
            "format": suffix.lstrip("."),
            "text": text[:100],
        }

    async def _execute_voice_memory_search(self, params: Dict) -> Dict:
        """执行语音转写记忆搜索"""
        try:
            query = params.get("query", "")
            limit = params.get("limit", 5)

            if not query:
                return {"error": "缺少搜索查询"}

            # 获取 MemoryManager
            memory_manager = None
            if hasattr(self._agent, "memory_manager") and self._agent.memory_manager:
                memory_manager = self._agent.memory_manager
            else:
                try:
                    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

                    memory_manager = MemoryManager()
                except ImportError:
                    logger.warning("MemoryManager 模块不可用")
                    return {"results": [], "query": query, "count": 0}

            # 搜索语音转写记忆（使用 category 过滤）
            memories = memory_manager.recall(
                query=query,
                category="voice_transcription",  # 语音转写类别
                limit=limit,
            )

            # 格式化结果
            results = []
            for memory in memories:
                results.append(
                    {
                        "id": memory.get("id", ""),
                        "content": memory.get("content", ""),
                        "category": memory.get("category", ""),
                        "transcription": memory.get("metadata", {}).get("transcription", ""),
                        "timestamp": memory.get("created_at", ""),
                    }
                )

            return {
                "success": True,
                "results": results,
                "query": query,
                "count": len(results),
            }
        except Exception as e:
            logger.error("语音记忆搜索执行失败: %s", e)
            return {"error": f"语音记忆搜索执行失败: {str(e)}", "results": [], "count": 0}

    async def _execute_run_code(self, params: Dict) -> Dict:
        """
        执行代码（使用 ExecutionLayers Runtime 抽象）

        支持参数:
            code: 要执行的代码字符串
            language: 代码语言（python / shell），默认 python
            runtime_type: 运行时类型（local / docker），默认从 Agent 配置读取
            timeout: 超时秒数，默认 60
            env: 环境变量字典
            cwd: 工作目录
        """
        code = params.get("code", "")
        language = params.get("language", "python")
        timeout = params.get("timeout", 60)
        env = params.get("env")
        cwd = params.get("cwd")

        if not code:
            return {"error": "缺少 code 参数"}

        start_time = time.time()

        try:
            # 延迟导入避免循环依赖
            from neurova.execution_layers import (
                LocalExecutor,
                RuntimeManager,
                RuntimeType,
                get_runtime_manager,
            )

            # 确定运行时类型
            runtime_type_str = params.get("runtime_type", "local")
            runtime_type = RuntimeType.DOCKER if runtime_type_str == "docker" else RuntimeType.LOCAL

            # 尝试从 RuntimeManager 获取已有运行时，否则创建临时的
            runtime_manager = get_runtime_manager()
            runtime = None

            # 查找同类型且空闲的运行时
            for info_dict in runtime_manager.list_active():
                if info_dict.get("runtime_type") == runtime_type.value and info_dict.get("status") == "running":
                    runtime = runtime_manager.get_runtime(info_dict["runtime_id"])
                    break

            # 没有可用运行时，创建临时 LocalExecutor
            owns_runtime = False
            if runtime is None:
                if runtime_type == RuntimeType.DOCKER:
                    runtime = (
                        RuntimeManager.create_runtime_class(RuntimeType.DOCKER)
                        if hasattr(RuntimeManager, "create_runtime_class")
                        else None
                    )
                if runtime is None:
                    runtime = LocalExecutor(runtime_id=f"run_code_{int(time.time())}")
                owns_runtime = True
                await runtime.start()

            try:
                # 构建执行命令
                if language == "python":
                    command = "python"
                    args = ["-c", code]
                elif language in ("shell", "bash", "sh"):
                    command = "sh"
                    args = ["-c", code]
                else:
                    command = language
                    args = [code]

                exec_result = await runtime.exec(
                    command=command,
                    args=args,
                    env=env,
                    cwd=cwd,
                    timeout=timeout,
                )

                duration_ms = (time.time() - start_time) * 1000

                return {
                    "success": exec_result.success,
                    "stdout": exec_result.stdout,
                    "stderr": exec_result.stderr,
                    "exit_code": exec_result.exit_code,
                    "duration_ms": duration_ms,
                    "runtime_type": runtime_type.value,
                    "error": exec_result.error,
                }
            finally:
                if owns_runtime:
                    await runtime.stop()

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("代码执行失败: %s", e)
            return {
                "success": False,
                "error": f"代码执行失败: {str(e)}",
                "duration_ms": duration_ms,
            }

    def on_tool_executed(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user_input: str,
        success: bool,
        tool_source: str = "",
        execution_time: float = 0.0,
        result: Optional[Dict[str, Any]] = None,
    ):
        """工具执行后钩子 — 闭环学习关键入口

        作为公开接口被 agent_core._on_skill_post_execute 调用，
        将工具执行事件转发到 tool_memory (肌肉记忆) 和 tool_lifecycle (生命周期)。

        H3 修复: 新增 result 参数，传播工具执行结果到记忆/生命周期层。
        record_tool_usage 签名含 **kwargs，result 会被安全接收。

        Args:
            tool_name: 工具名称
            params: 工具参数 (不是执行结果)
            user_input: 触发工具的用户输入 (作为 problem_text)
            success: 是否成功
            tool_source: 工具来源 (skill_system / builtin / mcp 等)
            execution_time: 执行耗时 (秒)
            result: 工具执行结果 dict (H3，可 None)
        """
        # 记录工具使用统计 → 传播到肌肉记忆 L1/L2/L3
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    tool_name=tool_name,
                    success=success,
                    execution_time=execution_time,
                    problem_text=user_input,
                    tool_source=tool_source,
                    tool_params=params,
                    result=result,
                )
            except Exception:
                # H11: 不静默吞错，记录异常堆栈
                logger.exception("工具记忆记录失败: %s", tool_name)

        # 更新工具生命周期 (真实方法是 touch, 不是 update_usage)
        if self.tool_lifecycle:
            try:
                self.tool_lifecycle.touch(tool_name, success)
            except Exception:
                logger.exception("工具生命周期更新失败: %s", tool_name)

    def _get_builtin_tool_params(self, tool_name: str) -> Optional[Dict]:
        """
        获取内置工具参数

        Args:
            tool_name: 工具名称

        Returns:
            工具参数 schema
        """
        try:
            from neurova.builtin_tools import get_builtin_tool_params

            return get_builtin_tool_params(tool_name)
        except ImportError as e:
            logger.debug("get_builtin_tool_params 延迟导入失败: %s", e)
            return {}

    def get_tool_messages(self) -> List[Dict]:
        """获取工具消息列表。

        Bug N-4 修复: 消费者（chat_pipeline._collect_tool_messages、
        Agent.get_tool_messages）读取 agent._tool_messages_list，原代码返回
        self._messages_list（ToolExecutor 本地列表），属性名不匹配导致工具消息丢失。
        改为读 agent._tool_messages_list，与写入端（line 155, 217）一致。
        """
        agent_list = getattr(self._agent, "_tool_messages_list", None)
        if agent_list is None:
            return []
        return list(agent_list)

    def clear_tool_messages(self):
        """清空工具消息列表。

        Bug N-4 修复: 清空 agent._tool_messages_list（消费者读取的列表），
        而非 self._messages_list（本地列表，清空不影响消费者，导致跨轮次累积）。
        """
        agent_list = getattr(self._agent, "_tool_messages_list", None)
        if agent_list is not None:
            agent_list.clear()
