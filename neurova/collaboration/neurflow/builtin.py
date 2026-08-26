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
from neurova.core.logger import get_logger
from typing import Any, Callable, Dict, List

from .agent_manager import get_agent_manager
from .models import NodeDefinition

logger = get_logger(__name__)


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
    {
        "type": "builtin:text_input",
        "label": "文本输入",
        "icon": "📝",
        "category": "input",
        "description": "提供纯文本值给工作流（支持 ${node.output} 变量引用）",
        "sub_blocks": [
            {"id": "value", "title": "文本内容", "type": "textarea"},
        ],
        "inputs": [],
        "outputs": [{"id": "text", "label": "文本"}],
        "source": "builtin",
    },
    {
        "type": "builtin:media_input",
        "label": "媒体输入",
        "icon": "🖼️",
        "category": "input",
        "description": "提供富媒体载荷（URL / data-url / base64 / 远程 / 上传，不内联二进制）",
        "sub_blocks": [
            {
                "id": "media_type",
                "title": "媒体类型",
                "type": "select",
                "default_value": "file",
                "options": [
                    {"label": "图片", "value": "image"},
                    {"label": "音频", "value": "audio"},
                    {"label": "视频", "value": "video"},
                    {"label": "文件", "value": "file"},
                ],
            },
            {
                "id": "source",
                "title": "来源",
                "type": "select",
                "default_value": "url",
                "options": [
                    {"label": "URL", "value": "url"},
                    {"label": "Data URL", "value": "data-url"},
                    {"label": "Base64", "value": "base64"},
                    {"label": "远程资源", "value": "remote"},
                    {"label": "上传", "value": "upload"},
                ],
            },
            {"id": "source_format", "title": "远程形态", "type": "input"},
            {"id": "value", "title": "载荷值（URL / data-url / base64，不内联二进制）", "type": "textarea"},
        ],
        "inputs": [],
        "outputs": [{"id": "media", "label": "媒体"}],
        "source": "builtin",
    },
    {
        "type": "builtin:file_input",
        "label": "文件输入",
        "icon": "📄",
        "category": "input",
        "description": "提供文件载荷（上传 / 远程 URL），标记文件种类供下游分派",
        "sub_blocks": [
            {
                "id": "source",
                "title": "来源",
                "type": "select",
                "default_value": "url",
                "options": [
                    {"label": "上传", "value": "upload"},
                    {"label": "远程 URL", "value": "url"},
                ],
            },
            {"id": "file_types", "title": "文件种类", "type": "input"},
            {"id": "value", "title": "远程文件地址", "type": "input"},
        ],
        "inputs": [],
        "outputs": [{"id": "file", "label": "文件"}],
        "source": "builtin",
    },
    {
        "type": "builtin:knowledge_base",
        "label": "知识库检索",
        "icon": "📚",
        "category": "input",
        "description": "从本地记忆库或远程知识库 API 检索内容",
        "sub_blocks": [
            {
                "id": "kb_type",
                "title": "知识库类型",
                "type": "select",
                "default_value": "local",
                "options": [
                    {"label": "本地记忆库", "value": "local"},
                    {"label": "飞书知识库", "value": "feishu"},
                    {"label": "IMA 知识库", "value": "ima"},
                ],
            },
            {"id": "query", "title": "检索词", "type": "input", "required": True},
            {"id": "limit", "title": "返回条数", "type": "slider", "default_value": 5, "min": 1, "max": 50},
            {"id": "api_url", "title": "API 地址（远程）", "type": "input"},
            {"id": "api_key", "title": "API Key（远程）", "type": "input"},
            {"id": "dataset_id", "title": "数据集 ID（远程）", "type": "input"},
        ],
        "inputs": [],
        "outputs": [{"id": "results", "label": "检索结果"}],
        "source": "builtin",
    },
    {
        "type": "builtin:remote_api",
        "label": "远程 API",
        "icon": "🌐",
        "category": "input",
        "description": "调用远程 HTTP API（GET/POST），透传响应",
        "sub_blocks": [
            {
                "id": "method",
                "title": "方法",
                "type": "select",
                "default_value": "GET",
                "options": [
                    {"label": "GET", "value": "GET"},
                    {"label": "POST", "value": "POST"},
                ],
            },
            {"id": "url", "title": "URL", "type": "input", "required": True},
            {"id": "headers", "title": "请求头（JSON）", "type": "textarea"},
            {"id": "body", "title": "请求体（JSON）", "type": "textarea"},
        ],
        "inputs": [],
        "outputs": [{"id": "response", "label": "响应"}],
        "source": "builtin",
    },
    {
        "type": "builtin:output",
        "label": "输出节点",
        "icon": "📤",
        "category": "output",
        "description": "工作流输出（文本 / 文件引用）",
        "sub_blocks": [
            {
                "id": "output_type",
                "title": "输出类型",
                "type": "select",
                "default_value": "text",
                "options": [
                    {"label": "文本", "value": "text"},
                    {"label": "文件", "value": "file"},
                ],
            },
            {"id": "file_kind", "title": "文件种类（file 时）", "type": "input"},
            {"id": "name", "title": "输出名称", "type": "input"},
        ],
        "inputs": [{"id": "input", "label": "输入"}],
        "outputs": [{"id": "output", "label": "输出"}],
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


def _get_multi_model_client():
    """获取多模型客户端实例（用于按 {provider, model} 路由 LLM 调用）"""
    try:
        from neurova.llm.multi_model_client import get_multi_model_client

        return get_multi_model_client()
    except ImportError:
        logger.debug("MultiModelClient 未可用")
        return None


def _extract_llm_text(response: Any) -> str:
    """从多种响应形状中安全提取文本内容"""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                return str(message.get("content", ""))
        return str(response)
    # OpenAI 风格对象：choices[0].message.content
    try:
        if hasattr(response, "choices") and response.choices:
            message = response.choices[0].message
            if hasattr(message, "content"):
                return str(message.content)
    except Exception:
        pass
    return str(response)


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
    """条件分支节点执行器（安全 DSL 求值，无 eval）

    表达式可用变量：$input（工作流输入）、$var（工作流变量）、$node（节点结果）、
    $current（loop 迭代值，循环体内）、$iteration（当前轮次，循环体内）。
    语法：比较（== != >= <= > < in）、逻辑（and or not）、len/str/int/float/bool。
    """
    from .safe_eval import safe_eval_condition

    expression = config.get("expression", "True")

    context = {
        "$input": ctx.get("inputs", {}),
        "$var": ctx.get("variables", {}),
        "$node": ctx.get("node_results", {}),
    }

    result = safe_eval_condition(expression, context)
    branch = "true" if result else "false"

    return {
        "status": "success",
        "output": {"branch": branch, "result": result},
    }


async def exec_loop(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """循环节点执行器（占位兜底）

    [引擎级循环] 真实的循环执行由 WorkflowExecutor 主循环拦截 builtin:loop
    节点并驱动 body 子图迭代（见 execution_engine._run_loop），本执行器
    仅在脱离引擎直接调用注册表时兜底，返回配置回显。
    """
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
    """LLM 调用节点执行器

    - 显式指定 model_provider != 'auto' 且 model_name 时，经多模型客户端
      对指定 Provider + 模型真正发起调用（支持可联通模型下拉选择）。
    - 否则回退 Agent.chat()（保持向后兼容）。
    """
    provider = config.get("model_provider", "auto")
    model_name = config.get("model_name", "")
    explicit_model = provider and provider != "auto" and model_name

    prompt = config.get("prompt", "")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 4096)
    system_prompt = config.get("system_prompt", "")

    # 变量解析已在执行引擎层完成（resolve_config），
    # 但作为防御性编程，如果 prompt 中仍含未解析的变量引用，
    # 使用 ctx 中的 variable_resolver 进行兜底解析（异常时回退原值）
    var_resolver = ctx.get("variable_resolver")
    if var_resolver and ctx.get("resolution_context"):
        import re

        if re.search(r"\$[a-zA-Z_]\w*", prompt) or re.search(r"\$[a-zA-Z_]\w*", system_prompt):
            res_ctx = ctx["resolution_context"]
            try:
                prompt = var_resolver.resolve_config(prompt, res_ctx)
                system_prompt = var_resolver.resolve_config(system_prompt, res_ctx)
            except Exception as e:
                logger.warning("LLM 节点变量解析失败，回退原值: %s", e)

    # ---------- 多模型路由路径 ----------
    if explicit_model:
        llm_client = _get_multi_model_client()
        if llm_client is not None:
            try:
                messages = [{"role": "user", "content": prompt}]
                if system_prompt:
                    messages.insert(0, {"role": "system", "content": system_prompt})

                result = await llm_client.chat(
                    messages,
                    model=model_name,
                    provider_id=provider,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if not result.get("success"):
                    return {
                        "status": "failed",
                        "error": result.get("error", "LLM 调用失败"),
                        "output": None,
                    }
                return {
                    "status": "success",
                    "output": {
                        "text": _extract_llm_text(result.get("response")),
                        "usage": {},
                    },
                    "provider": result.get("provider") or provider,
                    "model": result.get("model") or model_name,
                }
            except Exception as e:
                logger.error("LLM 模型路由调用失败: %s", e)
                return {
                    "status": "failed",
                    "error": str(e),
                    "output": None,
                }
        # 客户端不可用则继续回退 Agent.chat()

    # ---------- Agent.chat 回退路径 ----------
    agent = _get_agent()
    if agent is None:
        return {
            "status": "failed",
            "error": "Agent 未初始化",
            "output": None,
        }

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
    """Agent 调用节点执行器（蜂群分派）

    通过 SwarmManager 真实分派到 agent_id 对应的 Agent 实例（独立人设/记忆/
    模型配置），执行过程广播 SUBAGENT_* 事件，报告归档发起者上下文池。

    配置参数:
        agent_id: Agent ID（必需；不存在时回退 default）
        task: 任务描述（必需；支持 ${node_id.output} 引用上游输出，由
              variable_resolver 在引擎层解析）
        session_id: 可选，聊天会话 ID（事件广播目标，由引擎上下文透传）
    """
    agent_id = config.get("agent_id", "")
    task = config.get("task", "")

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

    # 从执行上下文提取会话/定位信息（引擎透传）
    resolution_context = ctx.get("resolution_context")
    session_id = getattr(resolution_context, "session_id", None) if resolution_context else None
    execution_id = getattr(resolution_context, "execution_id", None) if resolution_context else None

    try:
        from neurova.agent.swarm import get_swarm_manager

        swarm = get_swarm_manager()
        result = await swarm.spawn(
            task=task,
            agent_id=agent_id,
            session_id=session_id,
            background=False,
            origin="workflow",
            stream=True,
            node_id=ctx.get("node_id"),
            execution_id=execution_id,
        )
    except Exception as e:
        logger.error("Agent 节点分派失败: %s", e)
        return {
            "status": "failed",
            "error": str(e),
            "output": None,
        }

    if result.get("error"):
        return {
            "status": "failed",
            "error": result["error"],
            "output": None,
        }

    return {
        "status": "success",
        "output": {
            "agent_id": result.get("agent_id", agent_id),
            "resolved_agent_id": result.get("agent_id"),
            "subagent_id": result.get("subagent_id"),
            "task": task,
            "result": result.get("report", ""),
            "agent_name": result.get("agent_name", ""),
            "duration": result.get("duration", 0.0),
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

    优先从执行上下文取 context_pool（ResolutionContext 注入），
    兼容回退到全局 _get_context_pool()；同时适配 get_contexts()
    （ContextPool 条目对象）与旧式 get_context()（返回 dict）两种池接口。
    按来源过滤并应用 token 预算。
    """
    context_pool = ctx.get("context_pool")
    if context_pool is None:
        getter = globals().get("_get_context_pool")
        context_pool = getter() if callable(getter) else None
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

        # 获取所有上下文：新式 ContextPool（get_contexts → 条目对象列表）
        # 或旧式接口（get_context → dict 快照）。
        # 注意：不能用 hasattr 判定——MagicMock 会自动补全任意方法；
        # 以"get_contexts() 是否返回列表"作为运行时判据。
        all_contexts = None
        if hasattr(context_pool, "get_contexts"):
            try:
                candidate = context_pool.get_contexts()
                if isinstance(candidate, list):
                    all_contexts = candidate
            except Exception as e:  # noqa: BLE001
                logger.debug("get_contexts 调用失败，回退旧式接口: %s", e)

        if isinstance(all_contexts, list):
            # ---- 新式条目对象路径 ----
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

            filtered = [
                ctx_item
                for ctx_item in all_contexts
                if not source_enums or ctx_item.source in source_enums
            ]

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

        # ---- 旧式 dict 快照接口 ----
        snapshot = context_pool.get_context() or {}
        return {
            "status": "success",
            "output": snapshot,
            "metadata": {
                "snapshot_keys": list(snapshot.keys()),
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
        getter = globals().get("_get_emotion_module")
        emotion_module = getter() if callable(getter) else None
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
            # 方法适配：优先 analyze（部分 EmotionModule 实现），退化为
            # analyze_text_emotion；返回 dict 或对象均可。
            analyze_fn = getattr(emotion_module, "analyze", None) or getattr(
                emotion_module, "analyze_text_emotion", None
            )
            if analyze_fn is None:
                return {
                    "status": "failed",
                    "error": "emotion_module 缺少 analyze/analyze_text_emotion 方法",
                    "output": None,
                }
            emotion_state = analyze_fn(text)
            if isinstance(emotion_state, dict):
                return {
                    "status": "success",
                    "output": emotion_state,
                }
            return {
                "status": "success",
                "output": {
                    "primary_emotion": getattr(emotion_state.primary_emotion, "value", None)
                    or str(getattr(emotion_state, "primary_emotion", "")),
                    "intensity": getattr(emotion_state, "intensity", 0.0),
                    "valence": getattr(emotion_state, "valence", 0.0),
                    "arousal": getattr(emotion_state, "arousal", 0.0),
                    "secondary_emotions": (
                        {k.value: v for k, v in emotion_state.secondary_emotions.items()}
                        if getattr(emotion_state, "secondary_emotions", None)
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


def _resolve_value(value: str, ctx: Dict[str, Any]) -> str:
    """防御性变量解析：值中残留 ${node.output} / $var 引用时兜底解析（异常回退原值）"""
    var_resolver = ctx.get("variable_resolver")
    if var_resolver and ctx.get("resolution_context"):
        try:
            resolved = var_resolver.resolve_config(value, ctx["resolution_context"])
            return resolved if isinstance(resolved, str) else str(resolved)
        except Exception as e:  # noqa: BLE001
            logger.warning("输入节点变量解析失败，回退原值: %s", e)
    return value


async def exec_text_input(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """文本输入节点执行器

    把用户配置的纯文本值作为 {text} 输出给下游。
    值中的 ${node.output} 引用由引擎变量解析器解析后回填。
    """
    value = _resolve_value(str(config.get("value", "") or ""), ctx)
    return {"status": "success", "output": {"text": value}}


async def exec_media_input(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """媒体输入节点执行器

    输出结构化媒体载荷 {type, source, value}，仅透传引用/URL/base64 元数据，
    不加载二进制，避免塞爆节点 config 与存储。
    - source=url/data-url/base64：value 为对应字符串
    - source=remote：value 为远程地址（source_format 指明 url 等形态）
    - source=upload：upload_file 携带上传文件元数据 {name, dataUrl?...}
    缺省 media_type=file、source=url（覆盖最广的保守默认）。
    """
    media_type = str(config.get("media_type") or "file")
    source = str(config.get("source") or "url")

    if source == "remote":
        # 远程资源：归一化为其传输形态（url 等）
        source = str(config.get("source_format") or "url")
        value = _resolve_value(str(config.get("value", "") or ""), ctx)
    elif source == "upload":
        value = ""
    else:
        value = _resolve_value(str(config.get("value", "") or ""), ctx)

    media: Dict[str, Any] = {"type": media_type, "source": source, "value": value}
    if source == "upload":
        media["file"] = config.get("upload_file") or {}

    return {"status": "success", "output": {"media": media}}


async def exec_file_input(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """文件输入节点执行器

    输出 {file: {source, kind, value|file}}：
    - source=upload：upload_file 元数据透传（含 name/dataUrl）
    - source=url：value 为远程文件地址
    file_types 标记文件种类（pdf/docx/video/...），供下游分派。
    """
    source = str(config.get("source") or "url")
    kind = str(config.get("file_types") or "")

    if source == "upload":
        upload_file = config.get("upload_file") or {}
        file_payload: Dict[str, Any] = {
            "source": "upload",
            "kind": kind,
            "file": upload_file,
        }
    else:
        file_payload = {
            "source": "url",
            "kind": kind,
            "value": _resolve_value(str(config.get("value", "") or ""), ctx),
        }

    return {"status": "success", "output": {"file": file_payload}}


def _ssrf_allowlisted(host: str) -> bool:
    """SSRF 放行名单：NEUROVA_SSRF_ALLOWLIST（逗号分隔主机；"*" 关闭防护）"""
    import os

    raw = os.environ.get("NEUROVA_SSRF_ALLOWLIST", "")
    entries = {entry.strip().lower() for entry in raw.split(",") if entry.strip()}
    return "*" in entries or host.lower() in entries


def _validate_outbound_url(url: str) -> str:
    """出站 URL 的 SSRF 边界校验；违规抛 ValueError，通过则返回净化后的 URL。

    - 仅允许 http/https
    - 主机逐条解析为 IP 后判定：私网/环回/链路本地（含云元数据 169.254.0.0/16）/
      保留/组播/未指定地址一律拒绝，IPv4-mapped IPv6 折算后判定
    - NEUROVA_SSRF_ALLOWLIST 可显式放行主机（供纯内网/本机部署的合法调用）
    """
    from urllib.parse import urlparse
    import ipaddress
    import socket

    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"SSRF 防护: 不允许的协议 {parsed.scheme!r}（仅限 http/https）")
    host = parsed.hostname
    if not host:
        raise ValueError("SSRF 防护: URL 缺少主机名")
    if _ssrf_allowlisted(host):
        return str(url)

    candidates = []
    try:
        candidates.append(ipaddress.ip_address(host))
    except ValueError:
        pass  # 域名，走解析
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        for info in socket.getaddrinfo(host, port):
            addr = info[4][0]
            try:
                candidates.append(ipaddress.ip_address(str(addr).split("%")[0]))
            except ValueError:
                continue
    except OSError as e:
        raise ValueError(f"SSRF 防护: 域名解析失败 {host}: {e}") from e

    checked = set()
    for ip in candidates:
        if ip.version == 6 and getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped  # ::ffff:x.y.z.w 按嵌入 IPv4 判定
        if ip in checked:
            continue
        checked.add(ip)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"SSRF 防护: 目标 {host} 解析到受限地址 {ip}")

    # 全部解析地址均在允许边界内
    return str(url)


class _OutboundResponse:
    """requests.Response 的最小兼容层（ok / status_code / json() / text / url）"""

    def __init__(self, status_code: int, body: bytes, url: str):
        self.status_code = status_code
        self._body = body
        self.url = url
        self.text = body.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        import json as _json

        return _json.loads(self.text)


def _safe_request(method: str, url: str, **kwargs) -> "_OutboundResponse":
    """流程节点出站 HTTP 唯一通道（SSRF 防护收敛点）。

    1. _validate_outbound_url 先行校验：协议白名单 + 解析后 IP 边界判定
    2. 以禁用重定向的 opener 发起请求 —— 任何 3xx 不跟随，杜绝二次跳转绕过边界
    3. 残余风险：DNS rebinding 的 TOCTOU；严格场景用 NEUROVA_SSRF_ALLOWLIST 圈定可信主机
    """
    import json as _json
    from urllib import request as _urlrequest
    from urllib.error import HTTPError as _HTTPError
    from urllib.error import URLError as _URLError

    safe_url = _validate_outbound_url(url)

    headers = {str(k): str(v) for k, v in (kwargs.get("headers") or {}).items()}
    payload = kwargs.get("json")
    data = None
    if payload is not None:
        data = _json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    class _NoRedirectHandler(_urlrequest.HTTPRedirectHandler):
        """3xx 一律不跟随（返回 None 使 urlopen 抛 HTTPError）"""

        def redirect_request(self, req, fp, code, msg, hdrs, newurl):
            return None

    req = _urlrequest.Request(safe_url, data=data, headers=headers, method=method.upper())
    timeout = float(kwargs.get("timeout", 30))
    try:
        opener = _urlrequest.build_opener(_NoRedirectHandler())
        with opener.open(req, timeout=timeout) as raw:
            status = int(raw.status)
            body = raw.read()
            final_url = raw.geturl()
    except _HTTPError as e:  # 含"重定向被拒绝"的 3xx 响应
        status = int(e.code)
        body = e.read() if hasattr(e, "read") else b""
        final_url = getattr(e, "url", "") or safe_url
    except _URLError as e:
        raise ConnectionError(f"出站请求失败: {e}") from e

    return _OutboundResponse(status, body, final_url)


async def exec_knowledge_base(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """知识库检索节点执行器

    - kb_type=local：从 memory_manager.search 检索本地记忆库
    - kb_type=feishu/ima/...：POST 到远程知识库 API（api_url + api_key + dataset_id）
    """
    kb_type = str(config.get("kb_type") or "local")
    query = str(config.get("query", "") or "")
    limit = int(config.get("limit", 5) or 5)

    if kb_type == "local":
        memory_manager = ctx.get("memory_manager")
        if memory_manager is None:
            return {
                "status": "failed",
                "error": "本地知识库不可用：ctx 中缺少 memory_manager",
                "output": None,
            }
        try:
            items = memory_manager.search(query=query, limit=limit)
            results = [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in (items or [])
            ]
        except Exception as e:  # noqa: BLE001
            return {"status": "failed", "error": str(e), "output": None}
        return {
            "status": "success",
            "output": {"kb_type": "local", "results": results},
        }

    # 远程知识库
    api_url = str(config.get("api_url", "") or "")
    if not api_url:
        return {
            "status": "failed",
            "error": f"远程知识库({kb_type})缺少 api_url",
            "output": None,
        }

    headers: Dict[str, Any] = {}
    api_key = str(config.get("api_key", "") or "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "query": query,
        "dataset_id": config.get("dataset_id"),
        "top_k": limit,
    }

    try:
        resp = _safe_request("POST", api_url, json=payload, headers=headers, timeout=30)
        data = resp.json() if getattr(resp, "ok", False) else {}
        results = data.get("results", [])
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": str(e), "output": None}

    return {
        "status": "success",
        "output": {"kb_type": kb_type, "results": results},
    }


async def exec_remote_api(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """远程 API 调用节点执行器（GET / POST）

    输出 {status_code, body}；url 缺失或请求异常返回 failed。
    """
    import json as _json

    method = str(config.get("method", "GET") or "GET").upper()
    url = str(config.get("url", "") or "")
    if not url:
        return {"status": "failed", "error": "缺少 url", "output": None}

    try:
        headers = _json.loads(config.get("headers") or "{}")
    except Exception:  # noqa: BLE001
        headers = {}
    try:
        body = _json.loads(config.get("body") or "{}")
    except Exception:  # noqa: BLE001
        body = {}

    try:
        resp = _safe_request(method, url, json=body, headers=headers, timeout=30)
        ok = getattr(resp, "ok", False)
        try:
            data = resp.json() if ok else {}
        except ValueError:
            data = {"text": resp.text[:2000]}
    except Exception as e:  # noqa: BLE001
        return {"status": "failed", "error": str(e), "output": None}

    return {
        "status": "success",
        "output": {"status_code": resp.status_code, "body": data},
    }


async def exec_output(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """输出节点执行器（文件 / 文本）。

    从 ctx.inputs["input"] 取上游内容：
    - output_type=file：内容为 {path...} 结构时原样透传为 content
    - output_type=text：非字符串内容 JSON 序列化
    """
    import json as _json

    output_type = str(config.get("output_type", "text") or "text")
    inputs = ctx.get("inputs") or {}
    upstream = inputs.get("input")
    name = str(config.get("name", "") or "")

    if output_type == "file":
        if isinstance(upstream, dict):
            content: Any = upstream
        else:
            content = {"path": str(upstream or "")}
        return {
            "status": "success",
            "output": {
                "output_type": "file",
                "file_kind": str(config.get("file_kind", "") or ""),
                "name": name,
                "content": content,
            },
        }

    if isinstance(upstream, str):
        text = upstream
    elif upstream is None:
        text = ""
    else:
        text = _json.dumps(upstream, ensure_ascii=False)

    return {
        "status": "success",
        "output": {"output_type": "text", "name": name, "text": text},
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
BUILTIN_EXECUTORS: Dict[str, Callable] = {
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
    "builtin:text_input": exec_text_input,
    "builtin:media_input": exec_media_input,
    "builtin:file_input": exec_file_input,
    "builtin:knowledge_base": exec_knowledge_base,
    "builtin:remote_api": exec_remote_api,
    "builtin:output": exec_output,
}


def get_builtin_executors() -> Dict[str, Callable]:
    """
    获取所有内置节点执行器

    Returns:
        执行器字典 {node_type: executor_function}
    """
    return dict(BUILTIN_EXECUTORS)


# ==================== 注册函数 ====================


def register_builtin_nodes(registry) -> None:
    """
    将所有内置节点注册到注册表

    Args:
        registry: NodeRegistry 实例
    """
    for node_def in BUILTIN_NODES:
        # 获取对应的执行器
        executor = BUILTIN_EXECUTORS.get(node_def["type"])

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
    "exec_text_input",
    "exec_media_input",
    "exec_file_input",
    "exec_knowledge_base",
    "exec_remote_api",
    "exec_output",
    "exec_approval",
]
