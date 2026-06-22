"""
ToolExecutor — 统一工具执行器

从 agent_core.py 提取 (P1 拆分)，负责：
- 文本工具调用解析与执行 (_execute_text_tool_calls)
- 肌肉记忆工具执行 (_execute_tool_from_memory)
- Skill/CLI/MCP 工具分派 (_execute_skill_tool, _execute_cli_tool)
- 集中化工具执行后钩子 (_on_tool_executed)
- 内置工具参数信息 (_get_builtin_tool_params)

设计原则：
- 依赖注入：通过 agent_ref 访问 Agent 实例的属性
- 可独立测试：不依赖 Agent 类的完整初始化
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ToolEngine 延迟导入（避免循环依赖）
_TOOL_ENGINE_AVAILABLE = False
_ToolEngine = None


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


class ToolExecutor:
    """统一工具执行器

    通过 agent_ref 访问 Agent 实例的：
    - _skill_registry, tool_router, tool_memory, tool_lifecycle, skill_packer
    - _tool_messages_list, config
    """

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
        for tool_name, args_str in matches:
            try:
                # 尝试解析 JSON 参数
                try:
                    arguments = json.loads(args_str) if args_str.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}

                result = await self._execute_single_tool(tool_name, arguments)
                results.append(f"\n\n**{tool_name} 结果**: {json.dumps(result, ensure_ascii=False)[:2000]}")
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
                try:
                    arguments = json.loads(arguments_str)
                except json.JSONDecodeError:
                    arguments = {}

                # 执行工具
                result = await self._execute_single_tool(tool_name, arguments)
                results.append(
                    {
                        "tool_call_id": tool_call.get("id", ""),
                        "name": tool_name,
                        "result": result,
                        "success": True,
                    }
                )

                # 记录到消息列表
                self._messages_list.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": json.dumps(result, ensure_ascii=False),
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

    async def execute_from_memory(self, tool_name: str, params: Dict, context: Optional[Dict] = None) -> Dict:
        """
        从肌肉记忆执行工具

        Args:
            tool_name: 工具名称
            params: 工具参数
            context: 上下文信息

        Returns:
            执行结果
        """
        # 检查工具记忆
        if self.tool_memory:
            try:
                # check_tool_memory 接受 user_input 字符串
                memory_result, _ = self.tool_memory.check_tool_memory(tool_name)
                if memory_result and memory_result.get("confidence", 0) > 0.8:
                    # 使用记忆中的结果
                    return memory_result.get("result", {})
            except Exception as e:
                logger.debug("工具记忆检查失败: %s", e)

        # 执行工具
        result = await self._execute_single_tool(tool_name, params)

        # 记录工具使用
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    tool_name=tool_name,
                    success=result is not None,
                    tool_params=params,
                )
            except Exception as e:
                logger.debug("工具记忆记录失败: %s", e)

        return result

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
            if args:
                # 将参数字典转换为命令行参数
                arg_parts = []
                for key, value in args.items():
                    if isinstance(value, bool):
                        if value:
                            arg_parts.append(f"--{key}")
                    else:
                        arg_parts.append(f"--{key}={value}")
                full_command = f"{command} {' '.join(arg_parts)}"
            else:
                full_command = command

            # 使用 ComputerUseManager 执行命令
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            result = manager.shell(full_command)

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

    async def _execute_single_tool(self, tool_name: str, params: Dict) -> Dict:
        """
        执行单个工具

        Args:
            tool_name: 工具名称
            params: 参数

        Returns:
            执行结果
        """
        # 优先使用 ToolEngine（如果可用）
        if self.tool_engine:
            try:
                # 获取 user_id 和 agent_id（如果可用）
                user_id = getattr(self._agent, "user_id", None)
                agent_id = getattr(self._agent, "agent_id", None)

                result = await self.tool_engine.execute_with_safeguards(
                    tool_name=tool_name, parameters=params, user_id=user_id, agent_id=agent_id
                )
                logger.debug("ToolEngine 执行成功: %s", tool_name)
                return result
            except ValueError as e:
                # 工具未注册或不可用，回退到其他方式
                logger.debug("ToolEngine 工具 %s 未注册或不可用: %s", tool_name, e)
            except Exception as e:
                logger.warning("ToolEngine 执行失败: %s, %s", tool_name, e)

        # 回退到原有逻辑
        # 内置工具
        builtin_tools = [
            "memory_search",
            "search",
            "web_search",
            "weather",
            "file_read",
            "file_write",
            "file_create",
            "file_delete",
            "file_edit",
            "computer_screenshot",
            "computer_click",
            "computer_type",
            "computer_scroll",
            "computer_shell",
            "emotion_analyze",
            "voice_memory_search",
            "run_code",
            "execute_code",
        ]

        if tool_name in builtin_tools:
            return await self._execute_builtin_tool(tool_name, params)

        # Skill 工具
        if self._skill_registry and self._skill_registry.has_skill(tool_name):
            return await self.execute_skill_tool(tool_name, params)

        # 通过工具路由器
        if self.tool_router:
            try:
                result = await self.tool_router.route(tool_name, params)
                return result
            except Exception as e:
                logger.debug("工具路由器执行失败: %s", e)

        return {"error": f"未知工具: {tool_name}"}

    async def _execute_builtin_tool(self, tool_name: str, params: Dict) -> Dict:
        """执行内置工具"""
        # 简单的内置工具实现
        if tool_name == "memory_search":
            return await self._execute_memory_search(params)
        elif tool_name in ("search", "web_search"):
            return await self._execute_web_search(params)
        elif tool_name == "weather":
            return await self._execute_weather(params)
        elif tool_name == "file_read":
            return await self._execute_file_read(params)
        elif tool_name == "file_write":
            return await self._execute_file_write(params)
        elif tool_name == "file_create":
            return await self._execute_file_create(params)
        elif tool_name == "file_delete":
            return await self._execute_file_delete(params)
        elif tool_name == "file_edit":
            return await self._execute_file_edit(params)
        elif tool_name == "computer_screenshot":
            return await self._execute_computer_screenshot(params)
        elif tool_name == "computer_click":
            return await self._execute_computer_click(params)
        elif tool_name == "computer_type":
            return await self._execute_computer_type(params)
        elif tool_name == "computer_scroll":
            return await self._execute_computer_scroll(params)
        elif tool_name == "computer_shell":
            return await self._execute_computer_shell(params)
        elif tool_name == "emotion_analyze":
            return await self._execute_emotion_analyze(params)
        elif tool_name == "voice_memory_search":
            return await self._execute_voice_memory_search(params)
        elif tool_name in ("run_code", "execute_code"):
            return await self._execute_run_code(params)
        else:
            return {"error": f"未知内置工具: {tool_name}"}

    async def _execute_web_search(self, params: Dict) -> Dict:
        """执行网页搜索"""
        query = params.get("query") or params.get("q") or params.get("keywords", "")
        if not query:
            return {"error": "缺少搜索查询"}
        try:
            import urllib.request
            import urllib.parse
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}&hl=zh-CN"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # 简单提取文本摘要
            import re
            snippets = re.findall(r'<div[^>]*class="[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
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
            import urllib.request
            import urllib.parse
            # 使用 wttr.in 天气服务
            url = f"https://wttr.in/{urllib.parse.quote(location)}?format=3&lang=zh"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                text = resp.read().decode("utf-8", errors="replace").strip()
            return {"location": location, "weather": text}
        except Exception as e:
            return {"location": location, "error": f"天气查询失败: {e}"}

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

    async def _execute_computer_screenshot(self, params: Dict) -> Dict:
        """执行屏幕截图"""
        try:
            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            screenshot_data = manager.screenshot()
            if screenshot_data:
                import base64

                b64_str = base64.b64encode(screenshot_data).decode("utf-8")
                return {"success": True, "image_base64": b64_str, "format": "png"}
            else:
                return {"error": "截图失败：无可用后端"}
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
            success = manager.click(int(x), int(y), button)

            if success:
                return {"success": True, "x": x, "y": y, "button": button}
            else:
                return {"error": "点击操作失败"}
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
            success = manager.type_text(text)

            if success:
                return {"success": True, "text": text, "length": len(text)}
            else:
                return {"error": "输入操作失败"}
        except Exception as e:
            logger.error("输入执行失败: %s", e)
            return {"error": f"输入执行失败: {str(e)}"}

    async def _execute_computer_scroll(self, params: Dict) -> Dict:
        """执行屏幕滚动"""
        try:
            scroll_x = params.get("scroll_x", 0)
            scroll_y = params.get("scroll_y", 0)

            # 计算点击位置（默认屏幕中心）
            import pyautogui

            screen_width, screen_height = pyautogui.size()
            x = screen_width // 2
            y = screen_height // 2

            from neurova.computer_use import get_computer_use_manager

            manager = get_computer_use_manager()
            # ComputerUseManager.scroll 只支持垂直滚动，这里我们简化实现
            success = manager.scroll(x, y, scroll_y)

            if success:
                return {"success": True, "scroll_x": scroll_x, "scroll_y": scroll_y}
            else:
                return {"error": "滚动操作失败"}
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
            result = manager.shell(command)

            return {
                "success": result.get("returncode", -1) == 0,
                "returncode": result.get("returncode", -1),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "command": command,
            }
        except Exception as e:
            logger.error("Shell 命令执行失败: %s", e)
            return {"error": f"Shell 命令执行失败: {str(e)}"}

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

    def _on_tool_executed(self, tool_name: str, result: Dict, success: bool):
        """
        工具执行后钩子

        Args:
            tool_name: 工具名称
            result: 执行结果
            success: 是否成功
        """
        # 记录工具使用统计
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    tool_name=tool_name,
                    success=success,
                    tool_params=result,
                )
            except Exception as e:
                logger.debug("工具记忆记录失败: %s", e)

        # 更新工具生命周期
        if self.tool_lifecycle:
            try:
                self.tool_lifecycle.update_usage(tool_name, success)
            except Exception as e:
                logger.debug("工具生命周期更新失败: %s", e)

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
        """获取工具消息列表"""
        return self._messages_list.copy()

    def clear_tool_messages(self):
        """清空工具消息列表"""
        self._messages_list.clear()
