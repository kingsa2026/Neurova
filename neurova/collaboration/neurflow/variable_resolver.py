"""
Neurflow 变量解析器 — 垂直切片 5
支持 $node、$input、$var、$agent 等前缀的变量解析
序列化阶段保留原始引用，执行阶段才解析
"""

from neurova.core.logger import get_logger
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

logger = get_logger(__name__)


@dataclass
class ResolutionContext:
    """变量解析上下文

    支持的外部系统引用：
    - memory_manager: 记忆管理器（支持 $memory 前缀）
    - context_pool: 上下文池（支持 $context 前缀）
    - emotion_module: 情感模块（支持 $emotion 前缀）
    - crystallizer: 结晶器（支持 $crystal 前缀）
    """

    workflow_id: str
    execution_id: str
    node_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    inputs: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    user_id: Optional[str] = None
    # 聊天会话 ID（蜂群 agent 节点的事件广播目标；画布/聊天联动用）
    session_id: Optional[str] = None
    # 外部系统引用（延迟注入）
    memory_manager: Optional[Any] = None
    context_pool: Optional[Any] = None
    emotion_module: Optional[Any] = None
    crystallizer: Optional[Any] = None


@dataclass
class ResolvedValue:
    """解析结果"""

    success: bool
    value: Any = None
    error: Optional[str] = None


# 变量引用正则：$prefix.path
# 使用 ASCII 模式避免匹配中文字符
# 路径部分支持字母数字下划线和点号分隔
_VAR_PATTERN = re.compile(r"\$([a-zA-Z_]\w*)(?:\.([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)*))?")


class VariableResolver:
    """
    变量解析器

    支持的前缀：
    - $input.xxx      — 用户输入变量
    - $var.xxx        — 工作流变量
    - $node.xxx.yyy   — 节点输出
    - $agent.xxx      — Agent 信息
    - $memory.xxx     — 记忆检索（需要 memory_manager）
    - $context.xxx    — 当前上下文（需要 context_pool）
    - $emotion.xxx    — 情感状态（需要 emotion_module）
    - $crystal.xxx    — 结晶经验（需要 crystallizer）

    使用方式：
    1. 序列化阶段：保留原始 $node.xxx 引用
    2. 执行阶段：调用 resolve() 解析为实际值
    """

    def __init__(self):
        """初始化解析器"""
        self._prefix_handlers: Dict[str, Callable] = {
            "input": self._resolve_input,
            "var": self._resolve_var,
            "node": self._resolve_node,
            "agent": self._resolve_agent,
            "memory": self._resolve_memory,
            "context": self._resolve_context,
            "emotion": self._resolve_emotion,
            "crystal": self._resolve_crystal,
        }

    def register_prefix(self, prefix: str, handler: Callable) -> None:
        """
        注册自定义前缀解析器

        Args:
            prefix: 前缀名（不含 $）
            handler: 处理函数 (key: str, context: ResolutionContext) -> Any
        """
        self._prefix_handlers[prefix] = handler

    def resolve(self, text: str, context: ResolutionContext) -> ResolvedValue:
        """
        解析字符串中的变量引用

        Args:
            text: 包含变量引用的字符串
            context: 解析上下文

        Returns:
            ResolvedValue 解析结果
        """
        if context is None:
            raise ValueError("解析上下文不能为 None")

        if not text:
            return ResolvedValue(success=True, value="")

        # 如果整个字符串是一个变量引用，直接返回解析值（保持类型）
        single_match = _VAR_PATTERN.fullmatch(text)
        if single_match:
            prefix = single_match.group(1)
            path = single_match.group(2)
            return self._resolve_single(prefix, path, context)

        # 字符串中嵌入变量引用：逐个替换
        def replacer(match: re.Match) -> str:
            prefix = match.group(1)
            path = match.group(2)
            result = self._resolve_single(prefix, path, context)
            if result.success:
                return str(result.value)
            return match.group(0)  # 解析失败保留原样

        resolved_text = _VAR_PATTERN.sub(replacer, text)
        return ResolvedValue(success=True, value=resolved_text)

    def resolve_config(self, config: Union[Dict, List, str, Any], context: ResolutionContext) -> Any:
        """
        批量解析配置中的所有变量引用

        Args:
            config: 配置值（支持嵌套字典/列表）
            context: 解析上下文

        Returns:
            解析后的配置值
        """
        if isinstance(config, str):
            result = self.resolve(config, context)
            return result.value if result.success else config

        if isinstance(config, dict):
            return {k: self.resolve_config(v, context) for k, v in config.items()}

        if isinstance(config, list):
            return [self.resolve_config(item, context) for item in config]

        return config

    def _resolve_single(self, prefix: str, path: Optional[str], context: ResolutionContext) -> ResolvedValue:
        """解析单个变量引用"""
        handler = self._prefix_handlers.get(prefix)
        if handler is None:
            return ResolvedValue(success=False, error=f"未知的变量前缀: ${prefix}")

        try:
            value = handler(path, context)
            if value is None:
                return ResolvedValue(success=False, error=f"变量 ${prefix}.{path} 未找到")
            return ResolvedValue(success=True, value=value)
        except Exception as e:
            return ResolvedValue(success=False, error=f"解析 ${prefix}.{path} 失败: {str(e)}")

    def _resolve_input(self, path: Optional[str], context: ResolutionContext) -> Any:
        """解析 $input.xxx"""
        if not path:
            return context.inputs
        return self._traverse_dict(context.inputs, path)

    def _resolve_var(self, path: Optional[str], context: ResolutionContext) -> Any:
        """解析 $var.xxx"""
        if not path:
            return context.variables
        return self._traverse_dict(context.variables, path)

    def _resolve_node(self, path: Optional[str], context: ResolutionContext) -> Any:
        """解析 $node.xxx.yyy"""
        if not path:
            return context.node_results

        parts = path.split(".", 1)
        node_id = parts[0]

        if node_id not in context.node_results:
            return None

        if len(parts) == 1:
            return context.node_results[node_id]

        node_data = context.node_results[node_id]
        return self._traverse_dict(node_data, parts[1])

    def _resolve_agent(self, path: Optional[str], context: ResolutionContext) -> Any:
        """解析 $agent.xxx"""
        agent_data = {
            "agent_id": context.agent_id,
            "user_id": context.user_id,
        }

        if not path:
            return agent_data
        return self._traverse_dict(agent_data, path)

    def _resolve_memory(self, path: Optional[str], context: ResolutionContext) -> Any:
        """
        解析 $memory.xxx

        支持的用法：
        - $memory.query_text — 搜索记忆
        - $memory.get.memory_id — 获取特定记忆
        - $memory — 返回 memory_manager 对象
        """
        if context.memory_manager is None:
            logger.warning("memory_manager 未注入，无法使用 $memory 前缀")
            return None

        if not path:
            return context.memory_manager

        # 解析路径
        parts = path.split(".", 1)
        action = parts[0]
        query = parts[1] if len(parts) > 1 else None

        if action == "get" and query:
            # 获取特定记忆
            # 尝试调用 get_memory 方法，如果不存在则回退到 get 方法
            if hasattr(context.memory_manager, "get_memory"):
                return context.memory_manager.get_memory(query)
            elif hasattr(context.memory_manager, "get"):
                return context.memory_manager.get(query)
            else:
                logger.warning("memory_manager 没有 get_memory 或 get 方法")
                return None
        else:
            # 默认为搜索
            # 尝试调用 search_memories 方法，如果不存在则回退到 search 方法
            if hasattr(context.memory_manager, "search_memories"):
                return context.memory_manager.search_memories(path)
            elif hasattr(context.memory_manager, "search"):
                return context.memory_manager.search(path)
            else:
                logger.warning("memory_manager 没有 search_memories 或 search 方法")
                return None

    def _resolve_context(self, path: Optional[str], context: ResolutionContext) -> Any:
        """
        解析 $context.xxx

        支持的用法：
        - $context — 获取完整上下文
        - $context.system_prompt — 获取系统提示
        - $context.recent_messages.0 — 获取第一条最近消息
        """
        if context.context_pool is None:
            logger.warning("context_pool 未注入，无法使用 $context 前缀")
            return None

        # 获取上下文数据
        ctx_data = None
        if hasattr(context.context_pool, "get_context"):
            ctx_data = context.context_pool.get_context()
        elif hasattr(context.context_pool, "get_contexts"):
            # get_contexts 返回列表，取第一个元素的字典
            contexts = context.context_pool.get_contexts()
            if contexts:
                # 假设 ContextInput 有 to_dict 方法
                if hasattr(contexts[0], "to_dict"):
                    ctx_data = contexts[0].to_dict()
                else:
                    ctx_data = contexts[0]
            else:
                ctx_data = {}
        else:
            logger.warning("context_pool 没有 get_context 或 get_contexts 方法")
            return None

        if not path:
            return ctx_data

        return self._traverse_dict(ctx_data, path)

    def _resolve_emotion(self, path: Optional[str], context: ResolutionContext) -> Any:
        """
        解析 $emotion.xxx

        支持的用法：
        - $emotion — 获取完整情感状态
        - $emotion.valence — 获取情感效价
        - $emotion.primary_emotion — 获取主要情感
        """
        if context.emotion_module is None:
            logger.warning("emotion_module 未注入，无法使用 $emotion 前缀")
            return None

        # 获取情感数据
        emotion_data = None
        if hasattr(context.emotion_module, "current"):
            emotion_data = context.emotion_module.current()
        elif hasattr(context.emotion_module, "get_emotional_memories"):
            # 获取情感记忆，返回记忆ID列表
            memory_ids = context.emotion_module.get_emotional_memories(limit=1)
            if memory_ids and len(memory_ids) > 0:
                memory_id = memory_ids[0]
                # 如果返回的是字符串（记忆ID），尝试获取情感状态
                if isinstance(memory_id, str) and hasattr(context.emotion_module, "get_emotion"):
                    emotion_state = context.emotion_module.get_emotion(memory_id)
                    if emotion_state and hasattr(emotion_state, "to_dict"):
                        emotion_data = emotion_state.to_dict()
                    elif isinstance(emotion_state, dict):
                        emotion_data = emotion_state
                    else:
                        emotion_data = {"primary_emotion": "neutral", "valence": 0.0}
                else:
                    # 假设返回的是字典列表
                    emotion_state = memory_id.get("emotion", {}) if isinstance(memory_id, dict) else {}
                    if hasattr(emotion_state, "to_dict"):
                        emotion_data = emotion_state.to_dict()
                    elif isinstance(emotion_state, dict):
                        emotion_data = emotion_state
                    else:
                        emotion_data = {"primary_emotion": "neutral", "valence": 0.0}
            else:
                emotion_data = {"primary_emotion": "neutral", "valence": 0.0}
        elif hasattr(context.emotion_module, "get_stats"):
            stats = context.emotion_module.get_stats()
            # 从统计信息中构建情感数据
            distribution = stats.get("emotion_distribution", {})
            if distribution:
                # 选择最常见的 emotion
                primary_emotion = max(distribution.items(), key=lambda x: x[1])[0] if distribution else "neutral"
                emotion_data = {"primary_emotion": primary_emotion, "valence": 0.0}
            else:
                emotion_data = {"primary_emotion": "neutral", "valence": 0.0}
        else:
            logger.warning("emotion_module 没有 current、get_emotional_memories 或 get_stats 方法")
            return None

        if not path:
            return emotion_data

        return self._traverse_dict(emotion_data, path)

    def _resolve_crystal(self, path: Optional[str], context: ResolutionContext) -> Any:
        """
        解析 $crystal.xxx

        支持的用法：
        - $crystal.pattern_name — 检索结晶经验
        - $crystal — 返回 crystallizer 对象
        """
        if context.crystallizer is None:
            logger.warning("crystallizer 未注入，无法使用 $crystal 前缀")
            return None

        if not path:
            return context.crystallizer

        return context.crystallizer.retrieve(path)

    def _traverse_dict(self, data: Dict[str, Any], path: str) -> Any:
        """沿路径遍历字典"""
        parts = path.split(".")
        current = data

        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    return None
                current = current[part]
            elif isinstance(current, (list, tuple)):
                try:
                    current = current[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                return None

        return current


# 单例
_variable_resolver: Optional[VariableResolver] = None


def get_variable_resolver() -> VariableResolver:
    """获取变量解析器单例"""
    global _variable_resolver
    if _variable_resolver is None:
        _variable_resolver = VariableResolver()
    return _variable_resolver


__all__ = ["ResolutionContext", "ResolvedValue", "VariableResolver", "get_variable_resolver"]
