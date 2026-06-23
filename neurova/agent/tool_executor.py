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
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ToolExecutor:
    """统一工具执行器

    通过 agent_ref 访问 Agent 实例的：
    - _skill_registry, tool_router, tool_memory, tool_lifecycle, skill_packer
    - _tool_messages_list, config
    """

    def __init__(self, agent_ref):
        self._agent = agent_ref

    # ---- 属性代理（方便内部访问） ----
    @property
    def _skill_registry(self):
        return getattr(self._agent, "_skill_registry", None)

    @property
    def tool_router(self):
        return getattr(self._agent, "tool_router", None)

    @property
    def tool_memory(self):
        return getattr(self._agent, "tool_memory", None)

    @property
    def tool_lifecycle(self):
        return getattr(self._agent, "tool_lifecycle", None)

    @property
    def skill_packer(self):
        return getattr(self._agent, "skill_packer", None)

    @property
    def config(self):
        return getattr(self._agent, "config", None)

    def _ensure_messages_list(self):
        if not hasattr(self._agent, "_tool_messages_list"):
            self._agent._tool_messages_list = []
        return self._agent._tool_messages_list

    # ================================================================
    # 主入口：文本工具调用解析与执行
    # ================================================================

    async def execute_text_tool_calls(self, reply: str, user_input: str) -> str:
        """
        解析 LLM 回复中的文本工具调用并执行

        支持多种格式（按优先级尝试）:
        1. [TOOL_CALL:name(params)] — 系统指令格式
        2. ```json\n{"function": ...}\n``` — JSON 代码块格式
        3. ```\nTOOL_CALL:name(params)\n``` — 代码块中的系统格式
        4. function_name(arg1, arg2) — 自然函数调用格式
        """
        tool_calls = self._parse_tool_calls_multi_strategy(reply)
        logger.info("[TOOL_PARSE] 检查回复中是否有工具调用: %s 个匹配, " f"回复前100字: %s", len(tool_calls), reply[:100])
        if not tool_calls:
            return reply

        results = []
        for tc in tool_calls:
            tool_name = tc["name"]
            params = tc.get("params", {})
            logger.info("🔧 解析到文本工具调用: %s(%s)", tool_name, params)

            # 记录工具调用
            self._ensure_messages_list().append(
                {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "params": params,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # 执行工具
            try:
                # 1. SkillRegistry
                skill_exec_error = None
                if self._skill_registry:
                    skill = self._skill_registry.get_skill(tool_name)
                    if skill:
                        result = self._skill_registry.execute_skill(tool_name, params)
                        if result.success:
                            result_str = json.dumps(result.data, ensure_ascii=False)
                            max_len = 8000
                            offset = int(params.get("offset", 0))
                            chunk = result_str[offset : offset + max_len]
                            total = len(result_str)
                            suffix = ""
                            if total > offset + max_len:
                                suffix = (
                                    f"\n\n(已截断，共 {total} 字符，已显示 {offset}-{offset + len(chunk)}。"
                                    f"使用 offset={offset + max_len} 继续获取后续内容)"
                                )
                            results.append(f"\n\n**{tool_name} 结果**: {chunk}{suffix}")
                            self._ensure_messages_list().append(
                                {
                                    "type": "tool_result",
                                    "tool_name": tool_name,
                                    "result": chunk + suffix,
                                    "success": True,
                                    "timestamp": datetime.now().isoformat(),
                                }
                            )
                            # P0: 使用集中化钩子（记忆+生命周期+技能打包三合一）
                            self.on_tool_executed(
                                tool_name=tool_name,
                                params=params,
                                user_input=user_input,
                                success=True,
                                tool_source="skill_system",
                            )
                            continue
                        else:
                            skill_exec_error = result.error

                # 2. ToolRouter fallback
                if self.tool_router:
                    user_id = getattr(self.config, "user_id", "default") if self.config else "default"
                    router_result = await self.tool_router.execute(
                        tool_name=tool_name,
                        params=params,
                        agent_id=self.config.agent_id if self.config else "default",
                        user_id=user_id,
                    )
                    if router_result and router_result.success:
                        result_str = str(router_result.result)
                        results.append(f"\n\n**{tool_name} 结果**: {result_str[:8000]}")
                        self._ensure_messages_list().append(
                            {
                                "type": "tool_result",
                                "tool_name": tool_name,
                                "result": result_str[:8000],
                                "success": True,
                                "timestamp": datetime.now().isoformat(),
                            }
                        )
                        continue

                # 构建失败信息
                err_msg = (
                    f"执行失败: {skill_exec_error}"
                    if skill_exec_error
                    else "工具注册但执行未找到处理器，请检查参数是否正确"
                )
                params_info = self._get_tool_params_info(tool_name)
                if params_info:
                    required = params_info.get("required", [])
                    hints = [f"{k}({'必填' if k in required else '可选'})" for k in params_info]
                    err_msg += f"。可用参数: {', '.join(hints)}"
                results.append(f"\n\n**{tool_name} 结果**: {err_msg}")
            except Exception as e:
                logger.warning("文本工具调用执行失败: %s, %s", tool_name, e)
                results.append(f"\n\n**{tool_name} 结果**: 执行出错: {e}")

        # 移除原文中的工具调用标记，追加结果
        clean_reply = self._strip_tool_calls_from_text(reply).strip()
        if results:
            clean_reply += "\n".join(results)
        return clean_reply

    # ================================================================
    # 肌肉记忆工具执行
    # ================================================================

    def execute_from_memory(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """从肌肉记忆结果自动执行工具"""
        if not tool_memory_result:
            return None

        tool_name = tool_memory_result.get("tool_name")
        tool_source = tool_memory_result.get("tool_source")
        tool_params = tool_memory_result.get("tool_params", {})

        if not tool_name:
            logger.warning("ToolMemory 结果缺少 tool_name")
            return None

        logger.info("🚀 自动执行工具: %s (来源: %s)", tool_name, tool_source)

        self._ensure_messages_list().append(
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_source": tool_source,
                "params": tool_params,
                "timestamp": datetime.now().isoformat(),
            }
        )

        try:
            if tool_source == "skill_system" and self._skill_registry:
                result = self.execute_skill_tool(tool_name, tool_params, user_input)
            elif tool_source in ("cli", "mcp"):
                result = self.execute_cli_tool(tool_name, tool_params, user_input)
            else:
                result = self.execute_skill_tool(tool_name, tool_params, user_input)

            self.on_tool_executed(
                tool_name=tool_name,
                params=tool_params,
                user_input=user_input,
                success=result is not None,
                tool_source=tool_source or "unknown",
            )

            self._ensure_messages_list().append(
                {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "result": str(result)[:8000] if result else "执行失败",
                    "success": result is not None,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            return result

        except Exception as e:
            logger.error("工具自动执行失败: %s, 错误: %s", tool_name, e)
            self.on_tool_executed(
                tool_name=tool_name,
                params=tool_params,
                user_input=user_input,
                success=False,
                tool_source=tool_source or "unknown",
            )
            return None

    async def execute_from_memory_async(
        self,
        tool_memory_result: Dict[str, Any],
        user_input: str,
    ) -> Dict[str, Any]:
        """从肌肉记忆结果自动执行工具（异步版本，支持超时控制）

        Returns:
            {"status": "success"|"failure", "result": ..., "tool_name": ..., "error": ...}
        """
        if not tool_memory_result:
            return {"status": "failure", "error": "空的 tool_memory_result", "tool_name": ""}

        tool_name = tool_memory_result.get("tool_name")
        tool_source = tool_memory_result.get("tool_source")
        tool_params = tool_memory_result.get("tool_params", {})

        if not tool_name:
            return {"status": "failure", "error": "ToolMemory 结果缺少 tool_name", "tool_name": ""}

        logger.info("🚀 自动执行工具（异步）: %s (来源: %s)", tool_name, tool_source)

        self._ensure_messages_list().append(
            {
                "type": "tool_call",
                "tool_name": tool_name,
                "tool_source": tool_source,
                "params": tool_params,
                "timestamp": datetime.now().isoformat(),
            }
        )

        try:
            if tool_source == "skill_system" and self._skill_registry:
                result = self.execute_skill_tool(tool_name, tool_params, user_input)
            elif tool_source in ("cli", "mcp"):
                result = await self.execute_cli_tool_async(tool_name, tool_params, user_input)
            else:
                result = self.execute_skill_tool(tool_name, tool_params, user_input)

            success = result is not None
            self.on_tool_executed(
                tool_name=tool_name,
                params=tool_params,
                user_input=user_input,
                success=success,
                tool_source=tool_source or "unknown",
            )

            self._ensure_messages_list().append(
                {
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "result": str(result)[:8000] if result else "执行失败",
                    "success": success,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            if success:
                return {"status": "success", "result": result, "tool_name": tool_name}
            else:
                return {"status": "failure", "error": "工具返回空结果", "tool_name": tool_name}

        except Exception as e:
            logger.error("工具自动执行失败: %s, 错误: %s", tool_name, e)
            self.on_tool_executed(
                tool_name=tool_name,
                params=tool_params,
                user_input=user_input,
                success=False,
                tool_source=tool_source or "unknown",
                error_msg=str(e),
            )
            return {"status": "failure", "error": str(e), "tool_name": tool_name}

    # ================================================================
    # 工具分派
    # ================================================================

    def execute_skill_tool(
        self,
        skill_name: str,
        skill_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """执行技能工具"""
        if not self._skill_registry:
            logger.warning("SkillRegistry 未初始化，无法执行技能")
            return None

        try:
            skill = self._skill_registry.get_skill(skill_name)
            if not skill:
                logger.warning("技能未找到: %s", skill_name)
                return None

            if hasattr(skill, "execute") and callable(skill.execute):
                result = skill.execute(**skill_params)
                logger.info("✅ 技能执行成功: %s", skill_name)
                return {"result": result, "skill_name": skill_name}
            else:
                logger.warning("技能没有 execute 方法: %s", skill_name)
                return None

        except Exception as e:
            logger.error("技能执行异常: %s, 错误: %s", skill_name, e)
            return None

    def execute_cli_tool(
        self,
        tool_name: str,
        tool_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """执行 CLI/MCP 工具（同步版本，向后兼容）"""
        logger.info("CLI工具执行（模拟）: %s, 参数: %s", tool_name, tool_params)

        if self.tool_router:
            import asyncio

            try:
                asyncio.get_running_loop()
                # 已有 event loop 在运行，用 nest_asyncio 或直接创建新 loop
                from neurova.core.thread_pool import get_thread_pool

                pool = get_thread_pool()
                result = pool.submit(
                    asyncio.run,
                    self.tool_router.execute(
                        tool_name=tool_name,
                        params=tool_params,
                        agent_id=self.config.agent_id if self.config else "default",
                        user_id=getattr(self.config, "user_id", "default") if self.config else "default",
                    ),
                ).result()
            except RuntimeError:
                # 没有运行中的 event loop
                result = _asyncio.run(
                    self.tool_router.execute(
                        tool_name=tool_name,
                        params=tool_params,
                        agent_id=self.config.agent_id if self.config else "default",
                        user_id=getattr(self.config, "user_id", "default") if self.config else "default",
                    )
                )
            if result.success:
                return {"result": result.result, "tool_name": tool_name, "status": "success"}
            else:
                return {"result": f"模拟执行: {tool_name}", "tool_name": tool_name, "status": "simulated"}

        return {"result": f"模拟执行: {tool_name}", "tool_name": tool_name, "status": "simulated"}

    async def execute_cli_tool_async(
        self,
        tool_name: str,
        tool_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """执行 CLI/MCP 工具（异步版本，支持超时控制）"""
        logger.info("CLI工具执行（异步）: %s, 参数: %s", tool_name, tool_params)

        if self.tool_router:
            result = await self.tool_router.execute(
                tool_name=tool_name,
                params=tool_params,
                agent_id=self.config.agent_id if self.config else "default",
                user_id=getattr(self.config, "user_id", "default") if self.config else "default",
            )
            if result.success:
                return {"result": result.result, "tool_name": tool_name, "status": "success"}
            else:
                return {
                    "result": f"执行失败: {tool_name}",
                    "tool_name": tool_name,
                    "status": "failure",
                    "error": str(result.error) if hasattr(result, "error") else "未知错误",
                }

        return {"result": f"模拟执行: {tool_name}", "tool_name": tool_name, "status": "simulated"}

    # ================================================================
    # 集中化工具执行后钩子
    # ================================================================

    def on_tool_executed(
        self,
        tool_name: str,
        params: Dict[str, Any],
        user_input: str,
        success: bool,
        tool_source: str = "skill_system",
        execution_time: float = 0.0,
    ):
        """集中化工具执行后钩子 — 记忆记录 + 生命周期 + 技能打包 + 进化反馈"""
        # 1. 工具记忆记录（闭环学习核心）
        if self.tool_memory:
            try:
                self.tool_memory.record_tool_usage(
                    problem_text=user_input,
                    tool_name=tool_name,
                    tool_source=tool_source,
                    tool_params=params,
                    success=success,
                    execution_time=execution_time,
                )
            except Exception as e:
                logger.warning("记录工具使用失败: %s", e)

        # 2. 工具生命周期记录 (P0: ToolLifecycleManager)
        if self.tool_lifecycle:
            try:
                self.tool_lifecycle.touch(tool_name)
            except Exception as e:
                logger.warning("工具生命周期记录失败: %s", e)

        # 3. 技能打包器观察 (AutoSkillBuilder)
        if self.skill_packer:
            try:
                self.skill_packer.observe(
                    tool_sequence=[tool_name],
                    context=user_input[:100],
                    success=success,
                )
            except Exception as e:
                logger.warning("技能打包器记录失败: %s", e)

        # 4. 进化系统反馈（权重更新 + 生命周期评估）
        evolution = getattr(self._agent, "evolution", None)
        if evolution:
            try:
                from neurova.evolution.evolution_facade import EvolutionFacade
                facade = EvolutionFacade(evolution)
                facade.on_after_tool_execution(
                    tool_name=tool_name,
                    success=success,
                    context=user_input[:100],
                    latency=execution_time,
                )
            except Exception as e:
                logger.warning("进化系统反馈失败: %s", e)

    # ================================================================
    # 多策略文本工具调用解析
    # ================================================================

    def _parse_tool_calls_multi_strategy(self, text: str) -> List[Dict[str, Any]]:
        """多策略解析 LLM 回复中的工具调用

        按优先级尝试:
        1. [TOOL_CALL:name(params)] — 系统指令格式
        2. ```json\n{"function": ...}\n``` — JSON 代码块
        3. ```\nTOOL_CALL:name(params)\n``` — 代码块中的系统格式
        4. function_name(arg1, arg2) — 自然函数调用

        Returns:
            [{"name": "tool_name", "params": {...}}, ...]
        """
        results = []
        seen_names = set()

        # Strategy 1: [TOOL_CALL:name(params)]
        pattern1 = r"\[TOOL_CALL:([\w:.\-]+)\((.+?)\)\]"
        for m in re.finditer(pattern1, text):
            name, params_str = m.group(1), m.group(2)
            if name not in seen_names:
                results.append({"name": name, "params": self._parse_params(params_str)})
                seen_names.add(name)

        if results:
            return results

        # Strategy 2: ```json ... ``` blocks with {"function": ...}
        json_blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        for block in json_blocks:
            try:
                data = json.loads(block)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        # {"function": "name", "arguments": {...}}
                        if "function" in item:
                            func = item["function"]
                            if isinstance(func, str):
                                name = func
                                params = item.get("arguments", item.get("params", {}))
                            elif isinstance(func, dict):
                                name = func.get("name", "")
                                params = func.get("arguments", func.get("params", {}))
                            else:
                                continue
                            if name and name not in seen_names:
                                if isinstance(params, str):
                                    params = self._parse_params(params)
                                results.append({"name": name, "params": params or {}})
                                seen_names.add(name)
                        # {"tool": "name", "args": {...}}
                        elif "tool" in item:
                            name = item["tool"]
                            params = item.get("args", item.get("arguments", {}))
                            if name and name not in seen_names:
                                if isinstance(params, str):
                                    params = self._parse_params(params)
                                results.append({"name": name, "params": params or {}})
                                seen_names.add(name)
            except (json.JSONDecodeError, TypeError):
                continue

        if results:
            return results

        # Strategy 3: ``` ... TOOL_CALL:name(params) ... ``` (code blocks)
        code_blocks = re.findall(r"```\s*(.*?)\s*```", text, re.DOTALL)
        for block in code_blocks:
            for m in re.finditer(pattern1, block):
                name, params_str = m.group(1), m.group(2)
                if name not in seen_names:
                    results.append({"name": name, "params": self._parse_params(params_str)})
                    seen_names.add(name)

        if results:
            return results

        # Strategy 4: Natural function call — tool_name(arg1, arg2)
        # Only match known tool names to avoid false positives
        known_tools = self._get_known_tool_names()
        if known_tools:
            pattern4 = r"(?:^|\s)(" + "|".join(re.escape(t) for t in known_tools) + r")\(([^)]*)\)"
            for m in re.finditer(pattern4, text):
                name, params_str = m.group(1), m.group(2)
                if name not in seen_names:
                    results.append({"name": name, "params": self._parse_params(params_str)})
                    seen_names.add(name)

        return results

    def _strip_tool_calls_from_text(self, text: str) -> str:
        """从文本中移除所有已识别的工具调用标记"""
        # Remove [TOOL_CALL:...] patterns
        text = re.sub(r"\[TOOL_CALL:[\w:.\-]+\([^)]*\)\]", "", text)
        # Remove ```json ... ``` blocks that contained tool calls
        text = re.sub(r'```(?:json)?\s*\{[^`]*"function"[^`]*\}\s*```', "", text, flags=re.DOTALL)
        text = re.sub(r'```(?:json)?\s*\[[^`]*"function"[^`]*\]\s*```', "", text, flags=re.DOTALL)
        return text.strip()

    def _get_known_tool_names(self) -> List[str]:
        """获取已知工具名称列表（用于自然函数调用匹配）"""
        names = set()
        # SkillRegistry
        if self._skill_registry:
            try:
                for skill in self._skill_registry.list_skills():
                    names.add(skill.name)
            except Exception:
                pass
        # Built-in tools
        builtin = [
            "memory_search",
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
        ]
        names.update(builtin)
        return sorted(names)

    # ================================================================
    # 辅助方法
    # ================================================================

    def _parse_params(self, params_str: str) -> Dict[str, Any]:
        """解析工具参数（支持 JSON 和 key=value 格式）"""
        params_str = params_str.strip()
        params = {}

        if not params_str:
            return params

        if params_str.startswith("{"):
            try:
                return json.loads(params_str)
            except json.JSONDecodeError:
                logger.warning("JSON参数解析失败: %s", params_str)
                return params

        # key=value 格式
        for pair in params_str.split(","):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v.lower() == "true":
                    params[k] = True
                elif v.lower() == "false":
                    params[k] = False
                else:
                    try:
                        params[k] = int(v)
                    except ValueError:
                        try:
                            params[k] = float(v)
                        except ValueError:
                            params[k] = v
        return params

    def _get_tool_params_info(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取工具的参数信息（用于错误提示）"""
        # 1. SkillRegistry
        if self._skill_registry:
            sk = self._skill_registry.get_skill(tool_name)
            if sk and hasattr(sk, "_get_parameters"):
                return sk._get_parameters()

        # 2. 内置工具参数
        return self._get_builtin_tool_params(tool_name).get("parameters", {}).get("properties", {})

    def _get_builtin_tool_params(self, tool_name: str) -> Dict[str, Any]:
        """获取内置工具的参数定义"""
        builtin_schemas = {
            "memory_search": {
                "parameters": {
                    "properties": {
                        "query": {},
                        "category": {},
                        "limit": {},
                    },
                    "required": ["query"],
                }
            },
            "file_read": {
                "parameters": {
                    "properties": {
                        "file_path": {},
                        "offset": {},
                        "encoding": {},
                    },
                    "required": ["file_path"],
                }
            },
            "file_write": {
                "parameters": {
                    "properties": {
                        "file_path": {},
                        "content": {},
                        "encoding": {},
                    },
                    "required": ["file_path", "content"],
                }
            },
            "file_create": {
                "parameters": {
                    "properties": {"file_path": {}, "content": {}},
                    "required": ["file_path"],
                }
            },
            "file_delete": {
                "parameters": {
                    "properties": {"file_path": {}},
                    "required": ["file_path"],
                }
            },
            "file_edit": {
                "parameters": {
                    "properties": {"file_path": {}, "old_str": {}, "new_str": {}},
                    "required": ["file_path", "old_str", "new_str"],
                }
            },
            "computer_screenshot": {
                "parameters": {
                    "properties": {},
                    "required": [],
                }
            },
            "computer_click": {
                "parameters": {
                    "properties": {"x": {}, "y": {}, "button": {}},
                    "required": ["x", "y"],
                }
            },
            "computer_type": {
                "parameters": {
                    "properties": {"text": {}},
                    "required": ["text"],
                }
            },
            "computer_scroll": {
                "parameters": {
                    "properties": {"x": {}, "y": {}, "scroll_x": {}, "scroll_y": {}},
                    "required": [],
                }
            },
            "computer_shell": {
                "parameters": {
                    "properties": {"command": {}},
                    "required": ["command"],
                }
            },
            "emotion_analyze": {
                "parameters": {
                    "properties": {"text": {}},
                    "required": ["text"],
                }
            },
        }
        return builtin_schemas.get(tool_name, {"parameters": {"properties": {}, "required": []}})
