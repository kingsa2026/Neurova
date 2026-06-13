"""
上下文构建门面

提供统一的上下文构建接口，简化ContextOrchestrator的复杂接口。

设计模式: Facade
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """上下文构建结果"""
    messages: List[Dict[str, Any]]  # 上下文消息列表
    system_prompt: str  # 系统提示
    tools: List[Dict[str, Any]]  # 工具列表
    token_budget: Dict[str, Any]  # Token预算信息
    metadata: Dict[str, Any]  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "messages": self.messages,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "token_budget": self.token_budget,
            "metadata": self.metadata,
        }


class ContextFacade:
    """
    上下文构建门面
    
    提供简单的上下文构建接口，内部协调ContextOrchestrator。
    
    使用示例:
        facade = ContextFacade(agent)
        result = await facade.build_context("user input")
        # 使用 result.messages 传给 LLM
    """
    
    def __init__(self, agent_ref):
        """
        初始化门面
        
        Args:
            agent_ref: Agent实例引用
        """
        self._agent = agent_ref
        self._orchestrator = None
        
        # 延迟初始化orchestrator
        if hasattr(agent_ref, 'context_orchestrator'):
            self._orchestrator = agent_ref.context_orchestrator
        
        logger.debug("ContextFacade初始化")
    
    async def build_context(
        self,
        user_input: str,
        relevant_memories: Optional[List] = None,
        crystallized_patterns: Optional[List] = None,
        voice_context: Optional[Dict] = None,
        **kwargs,
    ) -> ContextResult:
        """
        构建对话上下文
        
        Args:
            user_input: 用户输入
            relevant_memories: 相关记忆列表
            crystallized_patterns: 结晶经验列表
            voice_context: 语音上下文
            
        Returns:
            ContextResult: 上下文构建结果
        """
        if not self._orchestrator:
            return ContextResult(
                messages=[],
                system_prompt="",
                tools=[],
                token_budget={},
                metadata={"error": "Orchestrator not available"},
            )
        
        try:
            # 构建上下文消息
            messages = await self._orchestrator.build_context(
                user_input=user_input,
                relevant_memories=relevant_memories,
                crystallized_patterns=crystallized_patterns,
                voice_context=voice_context,
                **kwargs,
            )
            
            # 构建系统提示
            system_prompt = await self._orchestrator.build_system_prompt()
            
            # 构建工具列表
            tools = await self._orchestrator.build_tools_for_llm()
            
            # 获取Token预算
            token_budget = {}
            if hasattr(self._orchestrator, 'context_pool') and self._orchestrator.context_pool:
                token_budget = {
                    "max_tokens": self._orchestrator.context_pool.max_tokens,
                    "used_tokens": getattr(self._orchestrator.context_pool, '_used_tokens', 0),
                }
            
            return ContextResult(
                messages=messages,
                system_prompt=system_prompt,
                tools=tools,
                token_budget=token_budget,
                metadata={"user_input": user_input[:100]},
            )
            
        except Exception as e:
            logger.error("上下文构建失败: %s", e)
            return ContextResult(
                messages=[],
                system_prompt="",
                tools=[],
                token_budget={},
                metadata={"error": str(e)},
            )
    
    async def build_system_prompt(
        self,
        tools_description: str = "",
        memory_context: str = "",
        constitution: str = "",
    ) -> str:
        """
        构建系统提示
        
        Args:
            tools_description: 工具描述
            memory_context: 记忆上下文
            constitution: 行为准则
            
        Returns:
            str: 系统提示
        """
        if not self._orchestrator:
            return ""
        
        try:
            return await self._orchestrator.build_system_prompt()
        except Exception as e:
            logger.error("系统提示构建失败: %s", e)
            return ""
    
    async def build_tools_for_llm(self) -> List[Dict[str, Any]]:
        """
        构建工具列表（OpenAI格式）
        
        Returns:
            List[Dict]: 工具列表
        """
        if not self._orchestrator:
            return []
        
        try:
            return await self._orchestrator.build_tools_for_llm()
        except Exception as e:
            logger.error("工具列表构建失败: %s", e)
            return []
    
    def get_token_budget(self) -> Dict[str, Any]:
        """
        获取当前Token预算
        
        Returns:
            Dict: Token预算信息
        """
        if not self._orchestrator:
            return {}
        
        if hasattr(self._orchestrator, 'context_pool') and self._orchestrator.context_pool:
            return {
                "max_tokens": self._orchestrator.context_pool.max_tokens,
                "used_tokens": getattr(self._orchestrator.context_pool, '_used_tokens', 0),
            }
        
        return {}
    
    def compress_context(
        self,
        context: List[Dict[str, Any]],
        target_tokens: int,
    ) -> List[Dict[str, Any]]:
        """
        压缩上下文到目标Token数
        
        Args:
            context: 上下文消息列表
            target_tokens: 目标Token数
            
        Returns:
            List[Dict]: 压缩后的上下文
        """
        # 简单实现：截断到目标长度
        if not context:
            return context
        
        # 估算Token数（简化：1个token ≈ 4个字符）
        total_chars = sum(len(str(m.get("content", ""))) for m in context)
        estimated_tokens = total_chars // 4
        
        if estimated_tokens <= target_tokens:
            return context
        
        # 截断到目标长度
        truncated = []
        current_chars = 0
        target_chars = target_tokens * 4
        
        for msg in context:
            content = str(msg.get("content", ""))
            if current_chars + len(content) <= target_chars:
                truncated.append(msg)
                current_chars += len(content)
            else:
                # 截断最后一条消息
                remaining = target_chars - current_chars
                if remaining > 0:
                    truncated.append({
                        **msg,
                        "content": content[:remaining] + "...",
                    })
                break
        
        return truncated
    
    def convert_format(
        self,
        context: List[Dict[str, Any]],
        target_format: str,
    ) -> List[Dict[str, Any]]:
        """
        格式转换
        
        Args:
            context: 上下文消息列表
            target_format: 目标格式 (openai/anthropic/gemini)
            
        Returns:
            List[Dict]: 转换后的上下文
        """
        if target_format == "openai":
            return self._to_openai_format(context)
        elif target_format == "anthropic":
            return self._to_anthropic_format(context)
        elif target_format == "gemini":
            return self._to_gemini_format(context)
        else:
            logger.warning("不支持的格式: %s, 返回原始格式", target_format)
            return context
    
    def _to_openai_format(self, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换为OpenAI格式"""
        # OpenAI格式已经是标准格式，直接返回
        return context
    
    def _to_anthropic_format(self, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换为Anthropic格式"""
        # Anthropic格式类似OpenAI，但有一些差异
        # 这里简化处理
        return context
    
    def _to_gemini_format(self, context: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换为Gemini格式"""
        # Gemini格式有不同的结构
        # 这里简化处理
        return context


# 全局单例
_facade_instance: Optional[ContextFacade] = None


def get_context_facade(agent_ref=None) -> ContextFacade:
    """
    获取上下文门面单例
    
    Args:
        agent_ref: Agent实例引用
        
    Returns:
        ContextFacade: 门面实例
    """
    global _facade_instance
    if _facade_instance is None and agent_ref is not None:
        _facade_instance = ContextFacade(agent_ref)
    return _facade_instance


def reset_context_facade():
    """重置门面单例（用于测试）"""
    global _facade_instance
    _facade_instance = None
