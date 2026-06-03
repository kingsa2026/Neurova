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

import re
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

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
        return getattr(self._agent, '_skill_registry', None)

    @property
    def tool_router(self):
        return getattr(self._agent, 'tool_router', None)

    @property
    def tool_memory(self):
        return getattr(self._agent, 'tool_memory', None)

    @property
    def tool_lifecycle(self):
        return getattr(self._agent, 'tool_lifecycle', None)

    @property
    def skill_packer(self):
        return getattr(self._agent, 'skill_packer', None)

    @property
    def config(self):
        return getattr(self._agent, 'config', None)

    def _ensure_messages_list(self):
        if not hasattr(self._agent, '_tool_messages_list'):
            self._agent._tool_messages_list = []
        return self._agent._tool_messages_list

    # ================================================================
    # 主入口：文本工具调用解析与执行
    # ================================================================

    async def execute_text_tool_calls(self, reply: str, user_input: str) -> str:
        """
        解析 LLM 回复中的 [TOOL_CALL:name(params)] 格式并执行工具
        API 不支持原生 function calling 的降级通路
        """
        pattern = r'\[TOOL_CALL:([\w:.\-]+)\((.+?)\)\]'
        matches = re.findall(pattern, reply)
        logger.info(
            f"[TOOL_PARSE] 检查回复中是否有工具调用: {len(matches)} 个匹配, "
            f"回复前100字: {reply[:100]}"
        )
        if not matches:
            return reply

        results = []
        for tool_name, params_str in matches:
            logger.info(f"🔧 解析到文本工具调用: {tool_name}({params_str})")
            params = self._parse_params(params_str)

            # 记录工具调用
            self._ensure_messages_list().append({
                "type": "tool_call",
                "tool_name": tool_name,
                "params": params,
                "timestamp": datetime.now().isoformat(),
            })

            # 执行工具
            try:
                # 1. SkillRegistry
                skill_exec_error = None
                if self._skill_registry:
                    skill = self._skill_registry.get_skill(tool_name)
                    if skill:
                        result = self._skill_registry.execute_skill(tool_name, **params)
                    if result.success:
                        result_str = json.dumps(result.data, ensure_ascii=False)
                        max_len = 8000
                        offset = int(params.get("offset", 0))
                        chunk = result_str[offset:offset + max_len]
                        total = len(result_str)
                        suffix = ""
                        if total > offset + max_len:
                            suffix = (
                                f"\n\n(已截断，共 {total} 字符，已显示 {offset}-{offset + len(chunk)}。"
                                f"使用 offset={offset + max_len} 继续获取后续内容)"
                            )
                        results.append(f"\n\n**{tool_name} 结果**: {chunk}{suffix}")
                        self._ensure_messages_list().append({
                            "type": "tool_result", "tool_name": tool_name,
                            "result": chunk + suffix,
                            "success": True, "timestamp": datetime.now().isoformat(),
                        })
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
                    user_id = getattr(self.config, 'user_id', 'default') if self.config else 'default'
                    router_result = await self.tool_router.execute(
                        tool_name=tool_name, params=params,
                        agent_id=self.config.agent_id if self.config else 'default',
                        user_id=user_id,
                    )
                    if router_result and router_result.success:
                        result_str = str(router_result.result)
                        results.append(f"\n\n**{tool_name} 结果**: {result_str[:8000]}")
                        self._ensure_messages_list().append({
                            "type": "tool_result", "tool_name": tool_name,
                            "result": result_str[:8000],
                            "success": True, "timestamp": datetime.now().isoformat(),
                        })
                        continue

                # 构建失败信息
                err_msg = (
                    f"执行失败: {skill_exec_error}" if skill_exec_error
                    else "工具注册但执行未找到处理器，请检查参数是否正确"
                )
                params_info = self._get_tool_params_info(tool_name)
                if params_info:
                    required = params_info.get("required", [])
                    hints = [f"{k}({'必填' if k in required else '可选'})" for k in params_info]
                    err_msg += f"。可用参数: {', '.join(hints)}"
                results.append(f"\n\n**{tool_name} 结果**: {err_msg}")
            except Exception as e:
                logger.warning(f"文本工具调用执行失败: {tool_name}, {e}")
                results.append(f"\n\n**{tool_name} 结果**: 执行出错: {e}")

        # 移除原文中的工具调用标记，追加结果
        clean_reply = re.sub(pattern, '', reply).strip()
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

        logger.info(f"🚀 自动执行工具: {tool_name} (来源: {tool_source})")

        self._ensure_messages_list().append({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_source": tool_source,
            "params": tool_params,
            "timestamp": datetime.now().isoformat(),
        })

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

            self._ensure_messages_list().append({
                "type": "tool_result",
                "tool_name": tool_name,
                "result": str(result)[:8000] if result else "执行失败",
                "success": result is not None,
                "timestamp": datetime.now().isoformat(),
            })

            return result

        except Exception as e:
            logger.error(f"工具自动执行失败: {tool_name}, 错误: {e}")
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

        logger.info(f"🚀 自动执行工具（异步）: {tool_name} (来源: {tool_source})")

        self._ensure_messages_list().append({
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_source": tool_source,
            "params": tool_params,
            "timestamp": datetime.now().isoformat(),
        })

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

            self._ensure_messages_list().append({
                "type": "tool_result",
                "tool_name": tool_name,
                "result": str(result)[:8000] if result else "执行失败",
                "success": success,
                "timestamp": datetime.now().isoformat(),
            })

            if success:
                return {"status": "success", "result": result, "tool_name": tool_name}
            else:
                return {"status": "failure", "error": "工具返回空结果", "tool_name": tool_name}

        except Exception as e:
            logger.error(f"工具自动执行失败: {tool_name}, 错误: {e}")
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
                logger.warning(f"技能未找到: {skill_name}")
                return None

            if hasattr(skill, 'execute') and callable(skill.execute):
                result = skill.execute(**skill_params)
                logger.info(f"✅ 技能执行成功: {skill_name}")
                return {"result": result, "skill_name": skill_name}
            else:
                logger.warning(f"技能没有 execute 方法: {skill_name}")
                return None

        except Exception as e:
            logger.error(f"技能执行异常: {skill_name}, 错误: {e}")
            return None

    def execute_cli_tool(
        self,
        tool_name: str,
        tool_params: Dict,
        user_input: str,
    ) -> Optional[Dict[str, Any]]:
        """执行 CLI/MCP 工具（同步版本，向后兼容）"""
        logger.info(f"CLI工具执行（模拟）: {tool_name}, 参数: {tool_params}")

        if self.tool_router:
            import asyncio as _asyncio
            try:
                loop = _asyncio.get_running_loop()
                # 已有 event loop 在运行，用 nest_asyncio 或直接创建新 loop
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    result = pool.submit(
                        _asyncio.run,
                        self.tool_router.execute(
                            tool_name=tool_name,
                            params=tool_params,
                            agent_id=self.config.agent_id if self.config else 'default',
                            user_id=getattr(self.config, 'user_id', 'default') if self.config else 'default',
                        )
                    ).result()
            except RuntimeError:
                # 没有运行中的 event loop
                result = _asyncio.run(
                    self.tool_router.execute(
                        tool_name=tool_name,
                        params=tool_params,
                        agent_id=self.config.agent_id if self.config else 'default',
                        user_id=getattr(self.config, 'user_id', 'default') if self.config else 'default',
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
        logger.info(f"CLI工具执行（异步）: {tool_name}, 参数: {tool_params}")

        if self.tool_router:
            result = await self.tool_router.execute(
                tool_name=tool_name,
                params=tool_params,
                agent_id=self.config.agent_id if self.config else 'default',
                user_id=getattr(self.config, 'user_id', 'default') if self.config else 'default',
            )
            if result.success:
                return {"result": result.result, "tool_name": tool_name, "status": "success"}
            else:
                return {"result": f"执行失败: {tool_name}", "tool_name": tool_name, "status": "failure", "error": str(result.error) if hasattr(result, 'error') else "未知错误"}

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
        """集中化工具执行后钩子 — 记忆记录 + 生命周期 + 技能打包"""
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
                logger.warning(f"记录工具使用失败: {e}")

        # 2. 工具生命周期记录 (P0: ToolLifecycleManager)
        if self.tool_lifecycle:
            try:
                self.tool_lifecycle.touch(tool_name)
            except Exception as e:
                logger.warning(f"工具生命周期记录失败: {e}")

        # 3. 技能打包器观察 (AutoSkillBuilder)
        if self.skill_packer:
            try:
                self.skill_packer.observe(
                    tool_sequence=[tool_name],
                    context=user_input[:100],
                    success=success,
                )
            except Exception as e:
                logger.warning(f"技能打包器记录失败: {e}")

    # ================================================================
    # 辅助方法
    # ================================================================

    def _parse_params(self, params_str: str) -> Dict[str, Any]:
        """解析工具参数（支持 JSON 和 key=value 格式）"""
        params_str = params_str.strip()
        params = {}

        if not params_str:
            return params

        if params_str.startswith('{'):
            try:
                return json.loads(params_str)
            except json.JSONDecodeError:
                logger.warning(f"JSON参数解析失败: {params_str}")
                return params

        # key=value 格式
        for pair in params_str.split(','):
            pair = pair.strip()
            if '=' in pair:
                k, v = pair.split('=', 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v.lower() == 'true':
                    params[k] = True
                elif v.lower() == 'false':
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
            if sk and hasattr(sk, '_get_parameters'):
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
