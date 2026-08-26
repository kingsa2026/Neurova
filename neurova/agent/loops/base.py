"""
Agent Loop 基类 - 定义标准接口

每个 Loop 实现特定的模型交互逻辑。
"""

import asyncio
import json
from neurova.core.logger import get_logger
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = get_logger(__name__)


class BaseAgentLoop(ABC):
    """
    Agent Loop 基类

    每个 Loop 实现特定的模型交互逻辑。
    子类必须实现 predict_step() 方法。

    设计参考: cua-main 的 Agent Loop 系统
    """

    def __init__(self, agent: "Agent"):
        """
        初始化 Loop

        参数:
            agent: Agent 实例，提供对记忆、技能等系统的访问
        """
        self.agent = agent
        self.llm_client = agent.llm_client

    @abstractmethod
    async def predict_step(self, messages: List[Dict], tools: Optional[List[Dict]] = None, **kwargs) -> Any:
        """
        执行一步预测 - 子类必须实现

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            **kwargs: 额外参数

        返回:
            LLMResponse 对象或原始响应
        """

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 - 默认实现

        遍历 tool_calls，执行对应的 Skill，
        并将结果作为 tool 消息添加到 messages。

        参数:
            tool_calls: LLM 返回的工具调用列表
            messages: 当前对话历史

        返回:
            新的消息列表 (tool 消息)
        """
        new_messages = []

        # 初始化工具消息列表（如果不存在）
        if not hasattr(self.agent, "_tool_messages_list"):
            self.agent._tool_messages_list = []

        for tool_call in tool_calls:
            # 每次迭代使用独立的变量名，防止跨迭代器状态污染
            _tc_function_name = tool_call.get("function", {}).get("name", "unknown_tool")
            _tc_id = tool_call.get("id", f"call_{id(tool_call)}")

            # [TOOLROBUST-A] 参数 JSON 解析单独 try：
            # 原实现在 try 外 json.loads，一遇到某条工具参数是非法 JSON，
            # handle_tool_calls 整体抛异常 → 被 loop 当作"工具调用失败"降级/回退到
            # 无工具路径，本轮全部工具静默丢失。
            # 现在解析失败只把错误作为该工具的结果回传给 LLM，让它自行纠正参数格式。
            _tc_arguments = {}
            try:
                _raw_arguments = tool_call.get("function", {}).get("arguments", "{}")
                if isinstance(_raw_arguments, str):
                    _tc_arguments = json.loads(_raw_arguments) if _raw_arguments.strip() else {}
                elif isinstance(_raw_arguments, dict):
                    _tc_arguments = _raw_arguments
            except (json.JSONDecodeError, TypeError, ValueError) as _parse_err:
                _parse_error = f"工具 {_tc_function_name} 参数 JSON 解析失败: {_parse_err}"
                logger.warning(_parse_error)
                new_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tc_id,
                        "name": _tc_function_name,
                        "content": json.dumps({"error": _parse_error}),
                    }
                )
                self.agent._tool_messages_list.append(
                    {
                        "type": "tool_result",
                        "tool_name": _tc_function_name,
                        "result": _parse_error,
                        "success": False,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                continue

            try:
                # [TOOLBUG] 诊断日志：检查 SkillRegistry 和 ToolRouter 的初始化状态
                _sr = self.agent.skill_registry
                _tr = getattr(self.agent, "tool_router", None)
                logger.info(
                    "[TOOLBUG] skill_registry=%s (type=%s), tool_router=%s (type=%s), tool_name=%s",
                    _sr is not None, type(_sr).__name__ if _sr else "None",
                    _tr is not None, type(_tr).__name__ if _tr else "None",
                    _tc_function_name,
                )

                # 记录工具调用消息（用于前端展示）
                self.agent._tool_messages_list.append(
                    {
                        "type": "tool_call",
                        "tool_name": _tc_function_name,
                        "params": _tc_arguments,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

                # 执行工具：优先 SkillRegistry → 失败/异常则 fallback ToolRouter
                exec_result = None

                # 1. 尝试 SkillRegistry（异常时 fallback 到 ToolRouter，不直接报错）
                if self.agent.skill_registry:
                    try:
                        skill_result = await self.agent.skill_registry.execute_skill(_tc_function_name, _tc_arguments)
                        # SkillRegistry 找不到该 skill 时返回 None；找到但执行失败返回 success=False
                        if skill_result is not None and getattr(skill_result, "success", False):
                            from types import SimpleNamespace

                            exec_result = SimpleNamespace(
                                success=True,
                                data=getattr(skill_result, "data", None),
                                error=None,
                                metadata={},
                            )
                            logger.info("Tool executed via SkillRegistry: %s", _tc_function_name)
                    except Exception as skill_err:
                        # Bug B-4 修复: SkillRegistry 异常时 fallback 到 ToolRouter,不直接报错
                        logger.warning(
                            "SkillRegistry 执行 %s 抛异常,尝试 ToolRouter fallback: %s",
                            _tc_function_name, skill_err,
                        )

                # 2. Fallback: ToolRouter（内置工具 + MCP 工具）
                if exec_result is None and hasattr(self.agent, "tool_router") and self.agent.tool_router:
                    try:
                        user_id = getattr(self.agent.config, "user_id", "default")
                        # [TOOLROBUST] 兼容同步/异步 execute：
                        # 真实 ToolRouter 通常为 async，但测试/部分适配器可能同步返回结果。
                        # 只有返回 coroutine 时才 await，否则直接用同步结果。
                        _router_rv = self.agent.tool_router.execute(
                            tool_name=_tc_function_name,
                            params=_tc_arguments,
                            agent_id=getattr(self.agent.config, "agent_id", None),
                            user_id=user_id,
                        )
                        router_result = await _router_rv if asyncio.iscoroutine(_router_rv) else _router_rv
                        if router_result and router_result.success:
                            from types import SimpleNamespace

                            exec_result = SimpleNamespace(
                                success=True,
                                data=router_result.result,
                                error=None,
                                metadata={},
                            )
                            logger.info("Tool executed via ToolRouter: %s", _tc_function_name)
                        else:
                            err = router_result.error if router_result else "ToolRouter 执行返回空"
                            exec_result = SimpleNamespace(success=False, data=None, error=err, metadata={})
                    except Exception as e:
                        logger.warning("ToolRouter fallback 失败: %s, %s", _tc_function_name, e)

                if exec_result:
                    # 构建 tool_result message
                    if exec_result.success:
                        content = json.dumps(exec_result.data) if exec_result.data is not None else "Success"
                    else:
                        content = json.dumps({"error": exec_result.error})

                    new_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": _tc_id,
                            "name": _tc_function_name,
                            "content": content,
                        }
                    )

                    # 记录工具执行结果（用于前端展示）
                    self.agent._tool_messages_list.append(
                        {
                            "type": "tool_result",
                            "tool_name": _tc_function_name,
                            "result": content[:500] if content else "执行完成",
                            "success": exec_result.success,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

                    logger.info("Tool executed: %s, success=%s", _tc_function_name, exec_result.success)

                else:
                    logger.warning("工具执行失败（SkillRegistry+ToolRouter 均未能处理）: %s", _tc_function_name)
                    err = f"工具 {_tc_function_name} 执行失败：SkillRegistry 和 ToolRouter 均未找到该工具"
                    new_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": _tc_id,
                            "name": _tc_function_name,
                            "content": json.dumps({"error": err}),
                        }
                    )
                    self.agent._tool_messages_list.append(
                        {
                            "type": "tool_result",
                            "tool_name": _tc_function_name,
                            "result": err,
                            "success": False,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

            except Exception as e:
                logger.error(f"Error executing tool {_tc_function_name}: {e}", exc_info=True)
                new_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": _tc_id,
                        "name": _tc_function_name,
                        "content": json.dumps({"error": str(e)}),
                    }
                )
                self.agent._tool_messages_list.append(
                    {
                        "type": "tool_result",
                        "tool_name": _tc_function_name,
                        "result": f"执行出错: {str(e)}",
                        "success": False,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return new_messages

