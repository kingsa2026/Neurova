"""
Agent Loop 基类 - 定义标准接口

每个 Loop 实现特定的模型交互逻辑。
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from neurova.llm_client import LLMResponse

logger = logging.getLogger(__name__)

class BaseAgentLoop(ABC):
    """
    Agent Loop 基类

    每个 Loop 实现特定的模型交互逻辑。
    子类必须实现 predict_step() 方法。

    设计参考: cua-main 的 Agent Loop 系统
    """

    def __init__(self, agent: 'Agent'):
        """
        初始化 Loop

        参数:
            agent: Agent 实例，提供对记忆、技能等系统的访问
        """
        self.agent = agent
        self.llm_client = agent.llm_client

    @abstractmethod
    async def predict_step(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> Any:
        """
        执行一步预测 - 子类必须实现

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            **kwargs: 额外参数

        返回:
            LLMResponse 对象或原始响应
        """
        pass

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
        if not hasattr(self.agent, '_tool_messages_list'):
            self.agent._tool_messages_list = []

        for tool_call in tool_calls:
            # 每次迭代使用独立的变量名，防止跨迭代器状态污染
            _tc_function_name = tool_call["function"]["name"]
            _tc_arguments = json.loads(tool_call["function"]["arguments"])
            _tc_id = tool_call["id"]

            try:
                # 记录工具调用消息（用于前端展示）
                self.agent._tool_messages_list.append({
                    "type": "tool_call",
                    "tool_name": _tc_function_name,
                    "params": _tc_arguments,
                    "timestamp": datetime.now().isoformat(),
                })

                # 执行工具：优先 SkillRegistry → 失败则 fallback ToolRouter
                exec_result = None

                # 1. 尝试 SkillRegistry
                if self.agent.skill_registry:
                    skill_result = await self.agent.skill_registry.execute_skill(
                        _tc_function_name, **_tc_arguments
                    )
                    # SkillRegistry 找不到该 skill 时返回 None；找到但执行失败返回 success=False
                    if skill_result is not None and getattr(skill_result, 'success', False):
                        from types import SimpleNamespace
                        exec_result = SimpleNamespace(
                            success=True,
                            data=getattr(skill_result, 'data', None),
                            error=None,
                            metadata={},
                        )
                        logger.info(f"Tool executed via SkillRegistry: {_tc_function_name}")

                # 2. Fallback: ToolRouter（内置工具 + MCP 工具）
                if exec_result is None and hasattr(self.agent, 'tool_router') and self.agent.tool_router:
                    try:
                        user_id = getattr(self.agent.config, 'user_id', 'default')
                        router_result = await self.agent.tool_router.execute(
                            tool_name=_tc_function_name,
                            params=_tc_arguments,
                            agent_id=self.agent.config.agent_id,
                            user_id=user_id,
                        )
                        if router_result and router_result.success:
                            from types import SimpleNamespace
                            exec_result = SimpleNamespace(
                                success=True,
                                data=router_result.result,
                                error=None,
                                metadata={},
                            )
                            logger.info(f"Tool executed via ToolRouter: {_tc_function_name}")
                        else:
                            err = router_result.error if router_result else "ToolRouter 执行返回空"
                            exec_result = SimpleNamespace(success=False, data=None, error=err, metadata={})
                    except Exception as e:
                        logger.warning(f"ToolRouter fallback 失败: {_tc_function_name}, {e}")

                if exec_result:
                    # 构建 tool_result message
                    if exec_result.success:
                        content = json.dumps(exec_result.data) if exec_result.data is not None else "Success"
                    else:
                        content = json.dumps({"error": exec_result.error})

                    new_messages.append({
                        "role": "tool",
                        "tool_call_id": _tc_id,
                        "content": content,
                    })

                    # 记录工具执行结果（用于前端展示）
                    self.agent._tool_messages_list.append({
                        "type": "tool_result",
                        "tool_name": _tc_function_name,
                        "result": content[:500] if content else "执行完成",
                        "success": exec_result.success,
                        "timestamp": datetime.now().isoformat(),
                    })

                    logger.info(f"Tool executed: {_tc_function_name}, success={exec_result.success}")

                else:
                    logger.warning(f"工具执行失败（SkillRegistry+ToolRouter 均未能处理）: {_tc_function_name}")
                    err = f"工具 {_tc_function_name} 执行失败：SkillRegistry 和 ToolRouter 均未找到该工具"
                    new_messages.append({
                        "role": "tool",
                        "tool_call_id": _tc_id,
                        "content": json.dumps({"error": err}),
                    })
                    self.agent._tool_messages_list.append({
                        "type": "tool_result",
                        "tool_name": _tc_function_name,
                        "result": err,
                        "success": False,
                        "timestamp": datetime.now().isoformat(),
                    })

            except Exception as e:
                logger.error(f"Error executing tool {_tc_function_name}: {e}", exc_info=True)
                new_messages.append({
                    "role": "tool",
                    "tool_call_id": _tc_id,
                    "content": json.dumps({"error": str(e)}),
                })
                self.agent._tool_messages_list.append({
                    "type": "tool_result",
                    "tool_name": _tc_function_name,
                    "result": f"执行出错: {str(e)}",
                    "success": False,
                    "timestamp": datetime.now().isoformat(),
                })

                # 记录异常结果
                if hasattr(self.agent, '_tool_messages_list'):
                    self.agent._tool_messages_list.append({
                        "type": "tool_result",
                        "tool_name": tool_call.get('function', {}).get('name', 'unknown'),
                        "result": f"Error: {str(e)}",
                        "success": False,
                        "timestamp": datetime.now().isoformat(),
                    })

        return new_messages

    def _build_tools_from_skills(self) -> List[Dict]:
        """
        将 Agent 的 Skills 转换为 OpenAI Tool Schema

        返回:
            tools: OpenAI 兼容的 tool 列表
        """
        tools = []

        if not self.agent.skill_registry:
            return tools

        # 尝试使用 OpenAI Schema Adapter (如果存在)
        try:
            from neurova.skill_system.compat import OpenAISchemaAdapter
            use_adapter = True
        except ImportError:
            use_adapter = False

        for skill_name, skill in self.agent.skill_registry.skills.items():
            if use_adapter:
                tool_schema = OpenAISchemaAdapter.skill_to_tool_schema(skill)
            else:
                # 简化版：仅转换基本信息
                tool_schema = {
                    "type": "function",
                    "function": {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    }
                }

            tools.append(tool_schema)

        return tools
