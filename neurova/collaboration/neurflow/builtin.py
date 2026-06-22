"""
Neurflow 内置节点定义模块 — 垂直切片 9

内置节点定义和执行器：
- 流程控制：start/end/condition/loop/parallel/merge/delay
- AI 能力：llm/agent/evolution/tdd
- 记忆系统：memory-load/memory-save/context/emotion
- 数据处理：variable/transform
- 人工输入：human_input/approval

架构理念：
- 内置节点是 Neurflow 的"原语"，提供最基础的工作流能力
- 执行器采用委托模式，调用 Neurova 核心能力
- 所有执行器返回统一格式 {"status": "success|failed", "output": ..., "error": ...}
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List

from .agent_manager import get_agent_manager
from .models import NodeDefinition

logger = logging.getLogger(__name__)


# ==================== 内置节点定义 ====================

# 所有内置节点的定义列表
# 使用 dict 格式，便于序列化和测试
BUILTIN_NODES: List[Dict[str, Any]] = [
    # ========== 流程控制节点 ==========
    {
        "type": "builtin:start",
        "label": "开始",
        "icon": "▶️",
        "category": "flow",
        "description": "工作流开始节点",
        "sub_blocks": [
            {"id": "inputs_schema", "title": "输入定义", "type": "json", "description": "定义工作流输入参数"}
        ],
        "inputs": [],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    {
        "type": "builtin:end",
        "label": "结束",
        "icon": "⏹️",
        "category": "flow",
        "description": "工作流结束节点",
        "sub_blocks": [{"id": "output_mapping", "title": "输出映射", "type": "json", "description": "映射最终输出"}],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [],
        "source": "builtin",
    },
    {
        "type": "builtin:condition",
        "label": "条件分支",
        "icon": "🔀",
        "category": "flow",
        "description": "根据条件表达式选择分支",
        "sub_blocks": [
            {
                "id": "expression",
                "title": "条件表达式",
                "type": "input",
                "required": True,
                "description": "Python 表达式，如: len($node.llm1.output) > 100",
            },
            {
                "id": "branches",
                "title": "分支列表",
                "type": "json",
                "description": '[{"label": "是", "condition": "true"}, {"label": "否", "condition": "false"}]',
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "true", "label": "真"}, {"id": "false", "label": "假"}],
        "source": "builtin",
    },
    {
        "type": "builtin:loop",
        "label": "循环",
        "icon": "🔁",
        "category": "flow",
        "description": "循环执行子流程",
        "sub_blocks": [
            {
                "id": "max_iterations",
                "title": "最大迭代次数",
                "type": "slider",
                "required": True,
                "default_value": 10,
                "min": 1,
                "max": 1000,
            },
            {"id": "break_condition", "title": "跳出条件", "type": "input", "description": "满足条件时跳出循环"},
        ],
        "inputs": [{"id": "input", "label": "输入"}, {"id": "loop_body", "label": "循环体"}],
        "outputs": [{"id": "loop_done", "label": "完成"}, {"id": "current", "label": "当前迭代"}],
        "source": "builtin",
    },
    {
        "type": "builtin:parallel",
        "label": "并行执行",
        "icon": "⚡",
        "category": "flow",
        "description": "并行执行多个分支",
        "sub_blocks": [
            {"id": "branches_count", "title": "分支数量", "type": "slider", "default_value": 2, "min": 2, "max": 10}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "branch_1", "label": "分支 1"},
            {"id": "branch_2", "label": "分支 2"},
            {"id": "branch_3", "label": "分支 3"},
        ],
        "source": "builtin",
    },
    {
        "type": "builtin:merge",
        "label": "合并",
        "icon": "🔗",
        "category": "flow",
        "description": "合并多个分支结果",
        "sub_blocks": [
            {
                "id": "strategy",
                "title": "合并策略",
                "type": "select",
                "default_value": "all",
                "options": [{"label": "全部完成", "value": "all"}, {"label": "第一个完成", "value": "first"}],
            }
        ],
        "inputs": [
            {"id": "input_1", "label": "输入 1"},
            {"id": "input_2", "label": "输入 2"},
            {"id": "input_3", "label": "输入 3"},
        ],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    {
        "type": "builtin:delay",
        "label": "延时等待",
        "icon": "⏰",
        "category": "flow",
        "description": "等待指定时间后继续",
        "sub_blocks": [
            {
                "id": "seconds",
                "title": "等待秒数",
                "type": "slider",
                "required": True,
                "default_value": 1,
                "min": 0.1,
                "max": 3600,
            }
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    # ========== AI 能力节点 ==========
    {
        "type": "builtin:llm",
        "label": "LLM 调用",
        "icon": "🤖",
        "category": "ai",
        "description": "调用大语言模型",
        "sub_blocks": [
            {"id": "prompt", "title": "提示词", "type": "textarea", "required": True},
            {
                "id": "model_provider",
                "title": "模型提供商",
                "type": "select",
                "options": [
                    {"label": "自动选择", "value": "auto"},
                    {"label": "OpenAI", "value": "openai"},
                    {"label": "Anthropic", "value": "anthropic"},
                    {"label": "Qwen", "value": "qwen"},
                ],
                "default_value": "auto",
            },
            {"id": "model_name", "title": "模型名称", "type": "model-selector", "provider_capability": "text"},
            {"id": "temperature", "title": "温度", "type": "slider", "default_value": 0.7, "min": 0.0, "max": 2.0},
            {
                "id": "max_tokens",
                "title": "最大 Tokens",
                "type": "slider",
                "default_value": 4096,
                "min": 100,
                "max": 128000,
            },
            {"id": "system_prompt", "title": "系统提示", "type": "textarea"},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}, {"id": "usage", "label": "Token 用量"}],
        "source": "builtin",
    },
    {
        "type": "builtin:agent",
        "label": "Agent 调用",
        "icon": "🧑‍💻",
        "category": "ai",
        "description": "调用 Agent 执行任务",
        "sub_blocks": [
            {"id": "agent_id", "title": "Agent ID", "type": "input", "required": True},
            {"id": "task", "title": "任务描述", "type": "textarea", "required": True},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    {
        "type": "builtin:evolution",
        "label": "进化能力",
        "icon": "🧬",
        "category": "ai",
        "description": "记录经验、评估性能、优化策略",
        "sub_blocks": [
            {
                "id": "mode",
                "title": "模式",
                "type": "select",
                "required": True,
                "options": [
                    {"label": "学习", "value": "learn"},
                    {"label": "评估", "value": "evaluate"},
                    {"label": "优化", "value": "optimize"},
                ],
            },
            {"id": "feedback_data", "title": "反馈数据", "type": "json"},
            {"id": "metric", "title": "评估指标", "type": "input"},
        ],
        "inputs": [{"id": "input", "label": "输入"}, {"id": "feedback", "label": "反馈"}],
        "outputs": [{"id": "output", "label": "结果"}, {"id": "score", "label": "评分"}],
        "source": "builtin",
    },
    {
        "type": "builtin:tdd",
        "label": "TDD 模式",
        "icon": "🧪",
        "category": "ai",
        "description": "测试驱动开发：先写测试，再实现，自动迭代优化",
        "sub_blocks": [
            {
                "id": "test_spec",
                "title": "测试规格",
                "type": "textarea",
                "required": True,
                "description": "描述期望行为，LLM 自动生成测试用例",
            },
            {"id": "implementation_prompt", "title": "实现提示", "type": "textarea"},
            {
                "id": "max_iterations",
                "title": "最大迭代次数",
                "type": "slider",
                "default_value": 5,
                "min": 1,
                "max": 20,
            },
            {
                "id": "pass_threshold",
                "title": "通过阈值",
                "type": "slider",
                "default_value": 1.0,
                "min": 0.5,
                "max": 1.0,
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "output", "label": "最终实现"},
            {"id": "tests", "label": "测试结果"},
            {"id": "iterations", "label": "迭代次数"},
        ],
        "source": "builtin",
    },
    # ========== 记忆系统节点 ==========
    {
        "type": "builtin:memory-load",
        "label": "加载记忆",
        "icon": "🧠",
        "category": "memory",
        "description": "从记忆系统检索信息",
        "sub_blocks": [
            {"id": "query", "title": "查询", "type": "input", "required": True},
            {"id": "limit", "title": "数量限制", "type": "slider", "default_value": 5, "min": 1, "max": 50},
            {
                "id": "memory_type",
                "title": "记忆类型",
                "type": "select",
                "default_value": "all",
                "options": [
                    {"label": "全部", "value": "all"},
                    {"label": "短期", "value": "short_term"},
                    {"label": "长期", "value": "long_term"},
                ],
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "记忆列表"}],
        "source": "builtin",
    },
    {
        "type": "builtin:memory-save",
        "label": "保存记忆",
        "icon": "💾",
        "category": "memory",
        "description": "保存信息到记忆系统",
        "sub_blocks": [
            {"id": "content", "title": "内容", "type": "textarea", "required": True},
            {"id": "importance", "title": "重要性", "type": "slider", "default_value": 0.5, "min": 0.0, "max": 1.0},
            {"id": "tags", "title": "标签", "type": "json"},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "保存结果"}],
        "source": "builtin",
    },
    {
        "type": "builtin:context",
        "label": "获取上下文",
        "icon": "🌐",
        "category": "memory",
        "description": "获取当前上下文信息",
        "sub_blocks": [
            {"id": "sources", "title": "上下文来源", "type": "json", "description": '["memory", "emotion", "crystal"]'},
            {
                "id": "token_budget",
                "title": "Token 预算",
                "type": "slider",
                "default_value": 4096,
                "min": 1024,
                "max": 32768,
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "上下文"}],
        "source": "builtin",
    },
    {
        "type": "builtin:emotion",
        "label": "情感分析",
        "icon": "😊",
        "category": "memory",
        "description": "分析文本情感、查询情感记忆或获取记忆情感状态",
        "sub_blocks": [
            {
                "id": "text",
                "title": "文本",
                "type": "textarea",
                "description": "analyze/query 模式下为待分析文本，state 模式下忽略",
            },
            {
                "id": "mode",
                "title": "模式",
                "type": "select",
                "default_value": "analyze",
                "options": [
                    {"label": "分析文本情感", "value": "analyze"},
                    {"label": "查询情感记忆", "value": "query"},
                    {"label": "获取记忆情感状态", "value": "state"},
                ],
            },
            {
                "id": "emotion_type",
                "title": "情感类型",
                "type": "select",
                "description": "query 模式下过滤特定情感类型",
                "options": [
                    {"label": "全部", "value": ""},
                    {"label": "喜悦", "value": "joy"},
                    {"label": "悲伤", "value": "sadness"},
                    {"label": "愤怒", "value": "anger"},
                    {"label": "恐惧", "value": "fear"},
                    {"label": "惊讶", "value": "surprise"},
                    {"label": "中性", "value": "neutral"},
                ],
            },
            {"id": "memory_id", "title": "记忆ID", "type": "input", "description": "state 模式下指定要查询的记忆ID"},
            {
                "id": "min_intensity",
                "title": "最低强度",
                "type": "slider",
                "default_value": 0.5,
                "min": 0.0,
                "max": 1.0,
                "description": "query 模式下过滤最低情感强度",
            },
            {
                "id": "limit",
                "title": "数量限制",
                "type": "slider",
                "default_value": 10,
                "min": 1,
                "max": 100,
                "description": "query 模式下最大返回数量",
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "情感状态"}],
        "source": "builtin",
    },
    # ========== 数据处理节点 ==========
    {
        "type": "builtin:variable",
        "label": "变量",
        "icon": "📦",
        "category": "data",
        "description": "定义或修改变量",
        "sub_blocks": [
            {"id": "name", "title": "变量名", "type": "input", "required": True},
            {"id": "value", "title": "变量值", "type": "json"},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    {
        "type": "builtin:transform",
        "label": "数据转换",
        "icon": "🔧",
        "category": "data",
        "description": "转换数据格式",
        "sub_blocks": [{"id": "expression", "title": "转换表达式", "type": "code", "language": "python"}],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    # ========== 人工输入节点 ==========
    {
        "type": "builtin:human_input",
        "label": "人工输入",
        "icon": "👤",
        "category": "input",
        "description": "等待人工输入",
        "sub_blocks": [
            {"id": "prompt", "title": "提示信息", "type": "textarea", "required": True},
            {
                "id": "timeout",
                "title": "超时时间（秒）",
                "type": "slider",
                "default_value": 300,
                "min": 10,
                "max": 3600,
            },
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin",
    },
    {
        "type": "builtin:approval",
        "label": "人工审批",
        "icon": "✅",
        "category": "input",
        "description": "等待人工审批",
        "sub_blocks": [
            {"id": "approver", "title": "审批人", "type": "input", "required": True},
            {"id": "message", "title": "审批说明", "type": "textarea"},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "approved", "label": "通过"}, {"id": "rejected", "label": "拒绝"}],
        "source": "builtin",
    },
]


# ==================== 服务获取函数（延迟加载） ====================


def _get_agent():
    """获取 Agent 实例"""
    try:
        from neurova.agent_core import Agent

        return Agent.get_instance()
    except (ImportError, AttributeError):
        logger.debug("Agent 未可用")
        return None


def _get_evolution():
    """获取 EvolutionOrchestrator 实例"""
    try:
        from neurova.evolution.closed_loop import get_evolution_orchestrator

        return get_evolution_orchestrator()
    except ImportError:
        logger.debug("EvolutionOrchestrator 未可用")
        return None


def _get_memory_manager():
    """获取 MemoryManager 实例"""
    try:
        from neurova.cognitive_layers.memory_layer.manager import get_memory_manager

        return get_memory_manager()
    except ImportError:
        logger.debug("MemoryManager 未可用")
        return None


def _get_emotion_module():
    """获取 EmotionModule 实例"""
    try:
        from neurova.cognitive_layers.memory_layer.modules.emotion_module import get_emotion_module

        return get_emotion_module()
    except ImportError:
        logger.debug("EmotionModule 未可用")
        return None


def _get_context_pool():
    """获取 ContextPool 实例"""
    try:
        from neurova.context_pool import get_context_pool

        return get_context_pool()
    except ImportError:
        logger.debug("ContextPool 未可用")
        return None


def _get_channel_manager():
    """获取 ChannelManager 实例"""
    try:
        from neurova.channels.manager import get_channel_manager

        return get_channel_manager()
    except ImportError:
        logger.debug("ChannelManager 未可用")
        return None


# ==================== 节点执行器 ====================


async def exec_start(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """开始节点执行器"""
    return {
        "status": "success",
        "output": ctx.get("inputs", {}),
    }


async def exec_end(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """结束节点执行器"""
    # 收集所有上游节点的输出
    node_results = ctx.get("node_results", {})
    final_output = {}
    for node_id, result in node_results.items():
        if isinstance(result, dict) and "output" in result:
            final_output[node_id] = result["output"]

    return {
        "status": "success",
        "output": final_output,
    }


async def exec_condition(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """条件分支节点执行器"""
    expression = config.get("expression", "True")

    # 安全的表达式求值（限制可用函数）
    safe_globals = {
        "True": True,
        "False": False,
        "None": None,
        "len": len,
        "str": str,
        "int": int,
        "float": float,
        "bool": bool,
        "abs": abs,
        "min": min,
        "max": max,
    }

    # 注入节点结果到上下文
    node_results = ctx.get("node_results", {})
    safe_globals["$node"] = node_results
    safe_globals["$input"] = ctx.get("inputs", {})
    safe_globals["$var"] = ctx.get("variables", {})

    try:
        result = eval(expression, {"__builtins__": {}}, safe_globals)
        branch = "true" if result else "false"
    except Exception as e:
        logger.warning("条件表达式求值失败: %s", e)
        branch = "false"
        result = False

    return {
        "status": "success",
        "output": {"branch": branch, "result": result},
    }


async def exec_loop(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """循环节点执行器"""
    max_iterations = config.get("max_iterations", 10)
    config.get("break_condition", "")

    # 安全限制
    if max_iterations > 1000:
        max_iterations = 1000

    return {
        "status": "success",
        "output": {
            "iterations": max_iterations,
            "completed": True,
        },
    }


async def exec_parallel(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """并行执行节点执行器"""
    branches_count = config.get("branches_count", 2)

    return {
        "status": "success",
        "output": {
            "branches_count": branches_count,
            "status": "ready",
        },
    }


async def exec_merge(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """合并节点执行器"""
    config.get("strategy", "all")
    node_results = ctx.get("node_results", {})

    # 根据策略合并结果
    merged = {}
    for node_id, result in node_results.items():
        if isinstance(result, dict) and "output" in result:
            merged[node_id] = result["output"]

    return {
        "status": "success",
        "output": merged,
    }


async def exec_delay(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """延时等待节点执行器"""
    seconds = config.get("seconds", 1)

    # 限制最大等待时间
    if seconds > 3600:
        seconds = 3600

    await asyncio.sleep(seconds)

    return {
        "status": "success",
        "output": {"waited_seconds": seconds},
    }


async def exec_llm(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 调用节点执行器"""
    agent = _get_agent()
    if agent is None:
        return {
            "status": "failed",
            "error": "Agent 未初始化",
            "output": None,
        }

    prompt = config.get("prompt", "")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 4096)
    system_prompt = config.get("system_prompt", "")

    # 变量解析已在执行引擎层完成（resolve_config），
    # 但作为防御性编程，如果 prompt 中仍含未解析的变量引用，
    # 使用 ctx 中的 variable_resolver 进行兜底解析
    var_resolver = ctx.get("variable_resolver")
    if var_resolver and ctx.get("resolution_context"):
        import re

        if re.search(r"\$[a-zA-Z_]\w*", prompt) or re.search(r"\$[a-zA-Z_]\w*", system_prompt):
            res_ctx = ctx["resolution_context"]
            prompt = var_resolver.resolve_config(prompt, res_ctx)
            system_prompt = var_resolver.resolve_config(system_prompt, res_ctx)

    try:
        response = await agent.chat(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            metadata={"history": []},
        )

        return {
            "status": "success",
            "output": {
                "text": response if isinstance(response, str) else str(response),
                "usage": {},  # TODO: 从 response 提取 usage
            },
        }
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_agent(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Agent 调用节点执行器

    通过 NeurflowAgentManager 验证 agent_id，然后调用 Agent.chat() 执行任务。

    配置参数:
        agent_id: Agent ID（必需）
        task: 任务描述（必需）
        temperature: 温度参数（可选，默认 0.7）
        max_tokens: 最大 token 数（可选，默认 4096）
    """
    agent_id = config.get("agent_id", "")
    task = config.get("task", "")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 4096)

    if not agent_id:
        return {
            "status": "failed",
            "error": "缺少 agent_id",
            "output": None,
        }

    if not task:
        return {
            "status": "failed",
            "error": "缺少 task",
            "output": None,
        }

    # 验证 agent_id 是否存在于 NeurflowAgentManager
    agent_manager = get_agent_manager()
    agent_info = agent_manager.get_agent(agent_id)

    if agent_info is None:
        logger.warning("Agent %s 不存在于 NeurflowAgentManager", agent_id)
        # 即使不存在，也尝试使用全局 Agent 执行
        # 这允许使用系统 Agent 而不仅仅是团队 Agent

    # 获取实际的 Agent 实例
    agent = _get_agent()
    if agent is None:
        return {
            "status": "failed",
            "error": "Agent 未初始化",
            "output": None,
        }

    try:
        # 调用 Agent.chat() 执行任务
        response = await agent.chat(
            task,
            temperature=temperature,
            max_tokens=max_tokens,
            metadata={"history": []},
        )

        # 提取响应内容
        if hasattr(response, "content"):
            result = response.content
        elif isinstance(response, str):
            result = response
        else:
            result = str(response)

        return {
            "status": "success",
            "output": {
                "agent_id": agent_id,
                "task": task,
                "result": result,
                "agent_info": {
                    "name": agent_info.name if agent_info else "系统 Agent",
                    "role": agent_info.role if agent_info else "assistant",
                },
            },
        }
    except Exception as e:
        logger.error("Agent 调用失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_evolution(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """进化能力节点执行器"""
    evolution = _get_evolution()
    if evolution is None:
        return {
            "status": "failed",
            "error": "EvolutionOrchestrator 未初始化",
            "output": None,
        }

    mode = config.get("mode", "learn")
    feedback_data = config.get("feedback_data", {})
    metric = config.get("metric", "default")

    try:
        if mode == "learn":
            # 解包 feedback_data 为4个独立参数
            text = feedback_data.get("text", "")
            task = feedback_data.get("task", "")
            tools = feedback_data.get("tools", [])
            success = feedback_data.get("success", False)

            from neurova.evolution.evolution_facade import EvolutionFacade
            facade = EvolutionFacade(evolution)
            facade.record_experience(text=text, task=task, tools=tools, success=success)
            return {
                "status": "success",
                "output": {"status": "learned", "mode": mode},
            }
        elif mode == "evaluate":
            # TODO: 实现评估逻辑
            return {
                "status": "success",
                "output": {"score": 0.0, "mode": mode, "metric": metric},
            }
        elif mode == "optimize":
            # TODO: 实现优化逻辑
            return {
                "status": "success",
                "output": {"status": "optimized", "mode": mode},
            }
        else:
            return {
                "status": "failed",
                "error": f"未知模式: {mode}",
                "output": None,
            }
    except Exception as e:
        logger.error("进化节点执行失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_tdd(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """TDD 模式节点执行器"""
    config.get("max_iterations", 5)
    test_spec = config.get("test_spec", "")
    implementation_prompt = config.get("implementation_prompt", "")

    # TODO: 实现完整的 TDD 循环
    # 暂时返回模拟结果
    return {
        "status": "success",
        "output": {
            "test_spec": test_spec,
            "implementation": implementation_prompt,
            "iterations": 1,
            "pass_rate": 1.0,
        },
    }


async def exec_memory_load(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """记忆加载节点执行器"""
    memory_manager = ctx.get("memory_manager") or _get_memory_manager()
    if memory_manager is None:
        return {
            "status": "failed",
            "error": "MemoryManager 未初始化（ctx.memory_manager 和全局实例均不可用）",
            "output": None,
        }

    query = config.get("query", "")
    limit = config.get("limit", 5)

    try:
        results = memory_manager.search(query, limit=limit)
        memories = []
        for m in results:
            if hasattr(m, "to_dict"):
                memories.append(m.to_dict())
            elif isinstance(m, dict):
                memories.append(m)
            else:
                memories.append({"content": str(m)})

        return {
            "status": "success",
            "output": memories,
        }
    except Exception as e:
        logger.error("记忆加载失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_memory_save(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """记忆保存节点执行器"""
    memory_manager = ctx.get("memory_manager") or _get_memory_manager()
    if memory_manager is None:
        return {
            "status": "failed",
            "error": "MemoryManager 未初始化（ctx.memory_manager 和全局实例均不可用）",
            "output": None,
        }

    content = config.get("content", "")
    importance = config.get("importance", 0.5)
    tags = config.get("tags", [])

    try:
        memory_manager.remember(
            content=content,
            importance=importance,
            tags=tags if isinstance(tags, list) else [],
        )

        return {
            "status": "success",
            "output": {"saved": True, "content": content},
        }
    except Exception as e:
        logger.error("记忆保存失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_context(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """获取上下文节点执行器

    从执行上下文中获取 context_pool，按来源过滤并应用 token 预算。
    """
    context_pool = ctx.get("context_pool")
    if context_pool is None:
        return {
            "status": "failed",
            "error": "context_pool 未注入到执行上下文（ResolutionContext.context_pool 为 None）",
            "output": None,
        }

    sources_str = config.get("sources", '["memory", "emotion"]')
    token_budget = config.get("token_budget", 4096)

    try:
        # 解析 sources（支持 JSON 字符串或列表）
        if isinstance(sources_str, str):
            import json

            sources = json.loads(sources_str)
        else:
            sources = sources_str

        # 获取所有上下文
        all_contexts = context_pool.get_contexts()

        # 按来源过滤
        from neurova.context_pool import ContextSource

        source_enum_map = {
            "memory": ContextSource.MEMORY,
            "emotion": ContextSource.EMOTION,
            "conversation": ContextSource.CONVERSATION,
            "experience": ContextSource.EXPERIENCE,
            "reflection": ContextSource.REFLECTION,
            "tool_call": ContextSource.TOOL_CALL,
            "multimodal": ContextSource.MULTIMODAL,
            "system_instruction": ContextSource.SYSTEM_INSTRUCTION,
            "developer_instruction": ContextSource.DEVELOPER_INSTRUCTION,
            "user_input": ContextSource.USER_INPUT,
        }

        source_enums = set()
        for s in sources:
            if s in source_enum_map:
                source_enums.add(source_enum_map[s])

        if source_enums:
            filtered = [ctx_item for ctx_item in all_contexts if ctx_item.source in source_enums]
        else:
            filtered = all_contexts

        # 应用 token 预算截断
        result = []
        total_tokens = 0
        for ctx_item in filtered:
            item_tokens = ctx_item.tokens or len(ctx_item.content) // 4
            if total_tokens + item_tokens > token_budget:
                break
            result.append(
                {
                    "source": ctx_item.source.value if hasattr(ctx_item.source, "value") else str(ctx_item.source),
                    "content": ctx_item.content,
                    "priority": ctx_item.priority,
                    "tokens": item_tokens,
                }
            )
            total_tokens += item_tokens

        return {
            "status": "success",
            "output": result,
            "metadata": {
                "total_contexts": len(all_contexts),
                "filtered_count": len(result),
                "total_tokens": total_tokens,
                "token_budget": token_budget,
            },
        }
    except Exception as e:
        logger.error(f"获取上下文失败: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_emotion(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """情感分析节点执行器

    支持三种模式：
    - analyze: 分析文本情感（调用 analyze_text_emotion）
    - query: 查询情感记忆（调用 get_emotional_memories）
    - state: 获取当前情感状态（从 emotion_module 读取）
    """
    emotion_module = ctx.get("emotion_module")
    if emotion_module is None:
        return {
            "status": "failed",
            "error": "emotion_module 未注入到执行上下文（ResolutionContext.emotion_module 为 None）",
            "output": None,
        }

    text = config.get("text", "")
    mode = config.get("mode", "analyze")

    try:
        if mode == "analyze":
            # 调用 EmotionModule.analyze_text_emotion 分析文本情感
            emotion_state = emotion_module.analyze_text_emotion(text)
            return {
                "status": "success",
                "output": {
                    "primary_emotion": emotion_state.primary_emotion.value,
                    "intensity": emotion_state.intensity,
                    "valence": emotion_state.valence,
                    "arousal": emotion_state.arousal,
                    "secondary_emotions": (
                        {k.value: v for k, v in emotion_state.secondary_emotions.items()}
                        if emotion_state.secondary_emotions
                        else {}
                    ),
                },
            }
        elif mode == "query":
            # 查询带有特定情感的记忆
            emotion_type_str = config.get("emotion_type")
            min_intensity = config.get("min_intensity", 0.5)
            limit = config.get("limit", 10)

            from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionType

            emotion_type = None
            if emotion_type_str:
                try:
                    emotion_type = EmotionType(emotion_type_str)
                except ValueError:
                    pass

            memory_ids = emotion_module.get_emotional_memories(
                emotion_type=emotion_type,
                min_intensity=min_intensity,
                limit=limit,
            )
            return {
                "status": "success",
                "output": memory_ids,
            }
        elif mode == "state":
            # 获取特定记忆的情感状态
            memory_id = config.get("memory_id", "")
            if memory_id:
                emotion_state = emotion_module.get_emotion(memory_id)
                if emotion_state:
                    return {
                        "status": "success",
                        "output": {
                            "primary_emotion": emotion_state.primary_emotion.value,
                            "intensity": emotion_state.intensity,
                            "valence": emotion_state.valence,
                            "arousal": emotion_state.arousal,
                        },
                    }
                return {
                    "status": "success",
                    "output": None,
                    "message": f"记忆 {memory_id} 无情感标注",
                }
            return {
                "status": "failed",
                "error": "state 模式需要提供 memory_id",
                "output": None,
            }
        else:
            return {
                "status": "failed",
                "error": f"未知模式: {mode}，支持: analyze, query, state",
                "output": None,
            }
    except Exception as e:
        logger.error(f"情感分析失败: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_variable(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """变量节点执行器"""
    name = config.get("name", "")
    value = config.get("value")

    if not name:
        return {
            "status": "failed",
            "error": "缺少变量名",
            "output": None,
        }

    # 设置变量到上下文
    variables = ctx.get("variables", {})
    variables[name] = value

    return {
        "status": "success",
        "output": {"name": name, "value": value},
    }


async def exec_transform(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """数据转换节点执行器"""
    expression = config.get("expression", "")

    if not expression:
        return {
            "status": "failed",
            "error": "缺少转换表达式",
            "output": None,
        }

    # 安全的表达式求值
    safe_globals = {
        "input": ctx.get("input"),
        "str": str,
        "int": int,
        "float": float,
        "len": len,
        "list": list,
        "dict": dict,
    }

    try:
        result = eval(expression, {"__builtins__": {}}, safe_globals)
        return {
            "status": "success",
            "output": result,
        }
    except Exception as e:
        logger.error("数据转换失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_human_input(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """人工输入节点执行器"""
    prompt = config.get("prompt", "请输入")
    config.get("timeout", 300)

    # TODO: 实现真正的人工输入等待机制
    # 暂时返回超时
    return {
        "status": "timeout",
        "output": {"prompt": prompt, "user_input": None},
    }


async def exec_approval(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    审批节点执行器

    通过 ChannelManager 发送审批通知，等待审批人回复。
    支持飞书/钉钉/企业微信等渠道。

    配置参数:
        approver: 审批人标识（用户ID或群组ID）
        channel: 渠道类型（feishu/dingtalk/wecom）
        message: 审批说明
        timeout: 超时时间（秒），默认 3600
        chat_id: 目标聊天ID（可选，默认使用 approver）
    """
    approver = config.get("approver", "")
    channel = config.get("channel", "")
    message = config.get("message", "")
    timeout = config.get("timeout", 3600)
    chat_id = config.get("chat_id", approver)

    # 获取 ChannelManager
    channel_manager = _get_channel_manager()
    if not channel_manager:
        logger.warning("ChannelManager 未可用，返回待审批状态")
        return {
            "status": "pending",
            "output": {"approver": approver, "message": message, "approved": None},
        }

    # 构建审批消息
    approval_id = ctx.get("execution_id", "unknown")
    node_id = ctx.get("node_id", "unknown")
    approval_message = f"""📋 工作流审批请求

审批ID: {approval_id}
节点: {node_id}
说明: {message}

请回复：
- 批准: approve 或 同意
- 拒绝: reject 或 拒绝"""

    # 发送审批通知
    try:
        if channel:
            # 指定渠道发送
            msg_id = await channel_manager.send_message(
                channel_type=channel, chat_id=chat_id, content=approval_message, message_type="text"
            )
        else:
            # 广播到所有已连接渠道
            results = await channel_manager.broadcast_message(content=approval_message, message_type="text")
            msg_id = list(results.values())[0] if results else None

        if not msg_id:
            logger.error("发送审批通知失败")
            # 返回 pending 状态，允许工作流继续
            return {
                "status": "pending",
                "output": {"approver": approver, "message": message, "approved": None},
            }

        logger.info("审批通知已发送: %s", msg_id)

    except Exception as e:
        logger.exception("发送审批通知异常: %s", e)
        return {
            "status": "failed",
            "error": f"发送审批通知异常: {str(e)}",
            "output": {"approver": approver, "message": message},
        }

    # 等待审批回复
    # 使用线程安全的 threading.Event 替代 asyncio.Event，解决跨事件循环问题
    import threading

    approval_event = threading.Event()
    approval_result = {"approved": None, "reason": ""}

    # 获取当前事件循环，用于线程安全调度
    loop = asyncio.get_event_loop()

    # 注册审批回调
    def on_approval_reply_sync(message_content: str) -> bool:
        """同步处理审批回复（从线程安全回调调用）"""
        content_lower = message_content.lower().strip()

        # 批准关键词
        approve_keywords = ["approve", "批准", "同意", "通过", "ok", "yes", "是"]
        # 拒绝关键词
        reject_keywords = ["reject", "拒绝", "驳回", "不通过", "no", "否"]

        for keyword in approve_keywords:
            if keyword in content_lower:
                approval_result["approved"] = True
                approval_event.set()
                return True

        for keyword in reject_keywords:
            if keyword in content_lower:
                approval_result["approved"] = False
                # 提取拒绝原因
                for kw in reject_keywords:
                    content_lower = content_lower.replace(kw, "").strip()
                approval_result["reason"] = content_lower or "未说明原因"
                approval_event.set()
                return True

        return False

    # 异步包装器，用于 ChannelManager 的异步处理器
    async def on_approval_reply_async(message_content: str) -> bool:
        """异步处理审批回复"""
        return on_approval_reply_sync(message_content)

    # 将回调注册到消息处理器（使用多处理器模式，避免覆盖其他处理器）
    async def message_handler(message):
        """消息处理器 — 过滤审批回复"""
        # 只处理来自审批人的消息
        if hasattr(message, "sender_id") and message.sender_id == approver:
            # 尝试解析审批回复
            content = message.content if hasattr(message, "content") else str(message)
            await on_approval_reply_async(content)
        return None  # 不自动回复

    # 使用 add_message_handler 而不是 set_message_handler，避免覆盖其他处理器
    handler_id = channel_manager.add_message_handler(message_handler, priority=10)
    logger.info("等待审批回复: %s, handler_id=%s", approval_id, handler_id)

    try:
        # 等待审批事件，带超时
        # 使用 run_in_executor 将 threading.Event.wait() 包装为异步操作
        # threading.Event.wait(timeout) 返回 True（事件已设置）或 False（超时）
        event_set = await loop.run_in_executor(None, approval_event.wait, timeout)

        # 移除消息处理器
        channel_manager.remove_message_handler(handler_id)

        if not event_set:
            # threading.Event.wait 返回 False 表示超时
            logger.warning("审批超时: %s", approval_id)
            return {
                "status": "timeout",
                "output": {
                    "approver": approver,
                    "message": message,
                    "approved": None,
                    "reason": "审批超时",
                },
            }

        # 返回审批结果
        if approval_result["approved"]:
            return {
                "status": "success",
                "output": {
                    "approver": approver,
                    "message": message,
                    "approved": True,
                    "reason": "审批通过",
                },
            }
        else:
            return {
                "status": "success",
                "output": {
                    "approver": approver,
                    "message": message,
                    "approved": False,
                    "reason": approval_result["reason"],
                },
            }

    except Exception:
        # 移除消息处理器
        channel_manager.remove_message_handler(handler_id)
        logger.warning("审批异常: %s", approval_id)
        return {
            "status": "timeout",
            "output": {
                "approver": approver,
                "message": message,
                "approved": None,
                "reason": "审批超时",
            },
        }


# ==================== 执行器注册 ====================

# 执行器映射表
_EXECUTORS: Dict[str, Callable] = {
    "builtin:start": exec_start,
    "builtin:end": exec_end,
    "builtin:condition": exec_condition,
    "builtin:loop": exec_loop,
    "builtin:parallel": exec_parallel,
    "builtin:merge": exec_merge,
    "builtin:delay": exec_delay,
    "builtin:llm": exec_llm,
    "builtin:agent": exec_agent,
    "builtin:evolution": exec_evolution,
    "builtin:tdd": exec_tdd,
    "builtin:memory-load": exec_memory_load,
    "builtin:memory-save": exec_memory_save,
    "builtin:context": exec_context,
    "builtin:emotion": exec_emotion,
    "builtin:variable": exec_variable,
    "builtin:transform": exec_transform,
    "builtin:human_input": exec_human_input,
    "builtin:approval": exec_approval,
}


def get_builtin_executors() -> Dict[str, Callable]:
    """
    获取所有内置节点执行器

    Returns:
        执行器字典 {node_type: executor_function}
    """
    return dict(_EXECUTORS)


# ==================== 注册函数 ====================


def register_builtin_nodes(registry) -> None:
    """
    将所有内置节点注册到注册表

    Args:
        registry: NodeRegistry 实例
    """
    for node_def in BUILTIN_NODES:
        # 获取对应的执行器
        executor = _EXECUTORS.get(node_def["type"])

        # 注册节点定义
        registry.register(
            NodeDefinition(
                type=node_def["type"],
                label=node_def["label"],
                icon=node_def["icon"],
                category=node_def["category"],
                description=node_def["description"],
                sub_blocks=node_def.get("sub_blocks", []),
                inputs=node_def.get("inputs", []),
                outputs=node_def.get("outputs", []),
                source=node_def.get("source", "builtin"),
            ),
            executor=executor,
        )


# ==================== 便捷导出 ====================

__all__ = [
    "BUILTIN_NODES",
    "register_builtin_nodes",
    "get_builtin_executors",
    # 执行器
    "exec_start",
    "exec_end",
    "exec_condition",
    "exec_loop",
    "exec_parallel",
    "exec_merge",
    "exec_delay",
    "exec_llm",
    "exec_agent",
    "exec_evolution",
    "exec_tdd",
    "exec_memory_load",
    "exec_memory_save",
    "exec_context",
    "exec_emotion",
    "exec_variable",
    "exec_transform",
    "exec_human_input",
    "exec_approval",
]
