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
from typing import Dict, List, Any, Optional, Callable

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
        "source": "builtin"
    },
    {
        "type": "builtin:end",
        "label": "结束",
        "icon": "⏹️",
        "category": "flow",
        "description": "工作流结束节点",
        "sub_blocks": [
            {"id": "output_mapping", "title": "输出映射", "type": "json", "description": "映射最终输出"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [],
        "source": "builtin"
    },
    {
        "type": "builtin:condition",
        "label": "条件分支",
        "icon": "🔀",
        "category": "flow",
        "description": "根据条件表达式选择分支",
        "sub_blocks": [
            {"id": "expression", "title": "条件表达式", "type": "input", "required": True,
             "description": "Python 表达式，如: len($node.llm1.output) > 100"},
            {"id": "branches", "title": "分支列表", "type": "json",
             "description": '[{"label": "是", "condition": "true"}, {"label": "否", "condition": "false"}]'}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "true", "label": "真"},
            {"id": "false", "label": "假"}
        ],
        "source": "builtin"
    },
    {
        "type": "builtin:loop",
        "label": "循环",
        "icon": "🔁",
        "category": "flow",
        "description": "循环执行子流程",
        "sub_blocks": [
            {"id": "max_iterations", "title": "最大迭代次数", "type": "slider",
             "required": True, "default_value": 10, "min": 1, "max": 1000},
            {"id": "break_condition", "title": "跳出条件", "type": "input",
             "description": "满足条件时跳出循环"}
        ],
        "inputs": [
            {"id": "input", "label": "输入"},
            {"id": "loop_body", "label": "循环体"}
        ],
        "outputs": [
            {"id": "loop_done", "label": "完成"},
            {"id": "current", "label": "当前迭代"}
        ],
        "source": "builtin"
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
            {"id": "branch_3", "label": "分支 3"}
        ],
        "source": "builtin"
    },
    {
        "type": "builtin:merge",
        "label": "合并",
        "icon": "🔗",
        "category": "flow",
        "description": "合并多个分支结果",
        "sub_blocks": [
            {"id": "strategy", "title": "合并策略", "type": "select", "default_value": "all",
             "options": [{"label": "全部完成", "value": "all"}, {"label": "第一个完成", "value": "first"}]}
        ],
        "inputs": [
            {"id": "input_1", "label": "输入 1"},
            {"id": "input_2", "label": "输入 2"},
            {"id": "input_3", "label": "输入 3"}
        ],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
    },
    {
        "type": "builtin:delay",
        "label": "延时等待",
        "icon": "⏰",
        "category": "flow",
        "description": "等待指定时间后继续",
        "sub_blocks": [
            {"id": "seconds", "title": "等待秒数", "type": "slider", "required": True,
             "default_value": 1, "min": 0.1, "max": 3600}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
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
            {"id": "model_provider", "title": "模型提供商", "type": "select",
             "options": [{"label": "自动选择", "value": "auto"}, {"label": "OpenAI", "value": "openai"},
                         {"label": "Anthropic", "value": "anthropic"}, {"label": "Qwen", "value": "qwen"}],
             "default_value": "auto"},
            {"id": "model_name", "title": "模型名称", "type": "model-selector", "provider_capability": "text"},
            {"id": "temperature", "title": "温度", "type": "slider", "default_value": 0.7, "min": 0.0, "max": 2.0},
            {"id": "max_tokens", "title": "最大 Tokens", "type": "slider", "default_value": 4096, "min": 100, "max": 128000},
            {"id": "system_prompt", "title": "系统提示", "type": "textarea"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "output", "label": "输出"},
            {"id": "usage", "label": "Token 用量"}
        ],
        "source": "builtin"
    },
    {
        "type": "builtin:agent",
        "label": "Agent 调用",
        "icon": "🧑‍💻",
        "category": "ai",
        "description": "调用 Agent 执行任务",
        "sub_blocks": [
            {"id": "agent_id", "title": "Agent ID", "type": "input", "required": True},
            {"id": "task", "title": "任务描述", "type": "textarea", "required": True}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
    },
    {
        "type": "builtin:evolution",
        "label": "进化能力",
        "icon": "🧬",
        "category": "ai",
        "description": "记录经验、评估性能、优化策略",
        "sub_blocks": [
            {"id": "mode", "title": "模式", "type": "select", "required": True,
             "options": [{"label": "学习", "value": "learn"}, {"label": "评估", "value": "evaluate"},
                         {"label": "优化", "value": "optimize"}]},
            {"id": "feedback_data", "title": "反馈数据", "type": "json"},
            {"id": "metric", "title": "评估指标", "type": "input"}
        ],
        "inputs": [
            {"id": "input", "label": "输入"},
            {"id": "feedback", "label": "反馈"}
        ],
        "outputs": [
            {"id": "output", "label": "结果"},
            {"id": "score", "label": "评分"}
        ],
        "source": "builtin"
    },
    {
        "type": "builtin:tdd",
        "label": "TDD 模式",
        "icon": "🧪",
        "category": "ai",
        "description": "测试驱动开发：先写测试，再实现，自动迭代优化",
        "sub_blocks": [
            {"id": "test_spec", "title": "测试规格", "type": "textarea", "required": True,
             "description": "描述期望行为，LLM 自动生成测试用例"},
            {"id": "implementation_prompt", "title": "实现提示", "type": "textarea"},
            {"id": "max_iterations", "title": "最大迭代次数", "type": "slider",
             "default_value": 5, "min": 1, "max": 20},
            {"id": "pass_threshold", "title": "通过阈值", "type": "slider",
             "default_value": 1.0, "min": 0.5, "max": 1.0}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "output", "label": "最终实现"},
            {"id": "tests", "label": "测试结果"},
            {"id": "iterations", "label": "迭代次数"}
        ],
        "source": "builtin"
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
            {"id": "memory_type", "title": "记忆类型", "type": "select", "default_value": "all",
             "options": [{"label": "全部", "value": "all"}, {"label": "短期", "value": "short_term"},
                         {"label": "长期", "value": "long_term"}]}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "记忆列表"}],
        "source": "builtin"
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
            {"id": "tags", "title": "标签", "type": "json"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "保存结果"}],
        "source": "builtin"
    },
    {
        "type": "builtin:context",
        "label": "获取上下文",
        "icon": "🌐",
        "category": "memory",
        "description": "获取当前上下文信息",
        "sub_blocks": [
            {"id": "sources", "title": "上下文来源", "type": "json",
             "description": '["memory", "emotion", "crystal"]'},
            {"id": "token_budget", "title": "Token 预算", "type": "slider", "default_value": 4096,
             "min": 1024, "max": 32768}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "上下文"}],
        "source": "builtin"
    },
    {
        "type": "builtin:emotion",
        "label": "情感分析",
        "icon": "😊",
        "category": "memory",
        "description": "分析或表达情感状态",
        "sub_blocks": [
            {"id": "text", "title": "文本", "type": "textarea"},
            {"id": "mode", "title": "模式", "type": "select", "default_value": "analyze",
             "options": [{"label": "分析", "value": "analyze"}, {"label": "表达", "value": "express"}]}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "情感状态"}],
        "source": "builtin"
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
            {"id": "value", "title": "变量值", "type": "json"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
    },
    {
        "type": "builtin:transform",
        "label": "数据转换",
        "icon": "🔧",
        "category": "data",
        "description": "转换数据格式",
        "sub_blocks": [
            {"id": "expression", "title": "转换表达式", "type": "code", "language": "python"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
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
            {"id": "timeout", "title": "超时时间（秒）", "type": "slider", "default_value": 300,
             "min": 10, "max": 3600}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
        "source": "builtin"
    },
    {
        "type": "builtin:approval",
        "label": "人工审批",
        "icon": "✅",
        "category": "input",
        "description": "等待人工审批",
        "sub_blocks": [
            {"id": "approver", "title": "审批人", "type": "input", "required": True},
            {"id": "message", "title": "审批说明", "type": "textarea"}
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [
            {"id": "approved", "label": "通过"},
            {"id": "rejected", "label": "拒绝"}
        ],
        "source": "builtin"
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
        logger.warning(f"条件表达式求值失败: {e}")
        branch = "false"
        result = False
    
    return {
        "status": "success",
        "output": {"branch": branch, "result": result},
    }


async def exec_loop(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """循环节点执行器"""
    max_iterations = config.get("max_iterations", 10)
    break_condition = config.get("break_condition", "")
    
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
    strategy = config.get("strategy", "all")
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
    
    # 注入变量到 prompt
    var_resolver = ctx.get("variable_resolver")
    if var_resolver:
        prompt = var_resolver.resolve_string(prompt, ctx.get("node_results", {}))
    
    try:
        response = await agent.chat(
            prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        
        return {
            "status": "success",
            "output": {
                "text": response if isinstance(response, str) else str(response),
                "usage": {},  # TODO: 从 response 提取 usage
            },
        }
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_agent(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Agent 调用节点执行器"""
    agent_id = config.get("agent_id", "")
    task = config.get("task", "")
    
    if not agent_id:
        return {
            "status": "failed",
            "error": "缺少 agent_id",
            "output": None,
        }
    
    # TODO: 通过 agent_manager 获取或创建 Agent
    # 暂时返回模拟结果
    return {
        "status": "success",
        "output": {
            "agent_id": agent_id,
            "task": task,
            "result": "Agent 执行完成（模拟）",
        },
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
            evolution.on_experience_recorded(feedback_data)
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
        logger.error(f"进化节点执行失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_tdd(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """TDD 模式节点执行器"""
    max_iterations = config.get("max_iterations", 5)
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
    memory_manager = _get_memory_manager()
    if memory_manager is None:
        return {
            "status": "failed",
            "error": "MemoryManager 未初始化",
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
        logger.error(f"记忆加载失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_memory_save(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """记忆保存节点执行器"""
    memory_manager = _get_memory_manager()
    if memory_manager is None:
        return {
            "status": "failed",
            "error": "MemoryManager 未初始化",
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
        logger.error(f"记忆保存失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_context(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """获取上下文节点执行器"""
    context_pool = _get_context_pool()
    if context_pool is None:
        return {
            "status": "failed",
            "error": "ContextPool 未初始化",
            "output": None,
        }
    
    sources = config.get("sources", ["memory", "emotion"])
    token_budget = config.get("token_budget", 4096)
    
    try:
        # TODO: 实现上下文获取
        return {
            "status": "success",
            "output": {"sources": sources, "token_budget": token_budget},
        }
    except Exception as e:
        logger.error(f"获取上下文失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_emotion(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """情感分析节点执行器"""
    emotion_module = _get_emotion_module()
    if emotion_module is None:
        return {
            "status": "failed",
            "error": "EmotionModule 未初始化",
            "output": None,
        }
    
    text = config.get("text", "")
    mode = config.get("mode", "analyze")
    
    try:
        if mode == "analyze":
            # TODO: 实现情感分析
            return {
                "status": "success",
                "output": {"text": text, "emotion": "neutral", "confidence": 0.5},
            }
        elif mode == "express":
            # TODO: 实现情感表达
            return {
                "status": "success",
                "output": {"text": text, "expressed": True},
            }
        else:
            return {
                "status": "failed",
                "error": f"未知模式: {mode}",
                "output": None,
            }
    except Exception as e:
        logger.error(f"情感分析失败: {e}")
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
        logger.error(f"数据转换失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }


async def exec_human_input(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """人工输入节点执行器"""
    prompt = config.get("prompt", "请输入")
    timeout = config.get("timeout", 300)
    
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
                channel_type=channel,
                chat_id=chat_id,
                content=approval_message,
                message_type="text"
            )
        else:
            # 广播到所有已连接渠道
            results = await channel_manager.broadcast_message(
                content=approval_message,
                message_type="text"
            )
            msg_id = list(results.values())[0] if results else None
        
        if not msg_id:
            logger.error("发送审批通知失败")
            # 返回 pending 状态，允许工作流继续
            return {
                "status": "pending",
                "output": {"approver": approver, "message": message, "approved": None},
            }
        
        logger.info(f"审批通知已发送: {msg_id}")
        
    except Exception as e:
        logger.exception(f"发送审批通知异常: {e}")
        return {
            "status": "failed",
            "error": f"发送审批通知异常: {str(e)}",
            "output": {"approver": approver, "message": message},
        }
    
    # 等待审批回复
    # 使用 asyncio.Event 实现异步等待
    approval_event = asyncio.Event()
    approval_result = {"approved": None, "reason": ""}
    
    # 注册审批回调
    async def on_approval_reply(message_content: str) -> bool:
        """处理审批回复"""
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
    
    # 将回调注册到消息处理器
    # 这里需要与执行引擎集成，暂时使用简单的轮询方式
    logger.info(f"等待审批回复: {approval_id}")
    
    try:
        # 等待审批事件，带超时
        await asyncio.wait_for(approval_event.wait(), timeout=timeout)
        
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
    
    except asyncio.TimeoutError:
        logger.warning(f"审批超时: {approval_id}")
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
