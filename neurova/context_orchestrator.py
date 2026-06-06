"""
ContextOrchestrator — 统一上下文构建模块

从 agent_core.py 提取 (深度模块化重构)，负责：
- 上下文系统初始化 (init_context_system)
- 上下文构建 (build_context) — Phase 2-5
- 系统提示构建 (_build_system_prompt)
- 工具描述构建 (_get_tools_description)
- 工具列表构建 (_build_tools_for_llm)

设计原则：
- 深度模块：小接口，深实现
- 单一职责：只负责上下文构建，不涉及记忆管理或工具执行
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContextOrchestrator:
    """
    统一上下文构建器
    
    协调各种上下文源，构建发送给 LLM 的完整上下文。
    """
    
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        memory_manager: Optional[Any] = None,
        context_builder: Optional[Any] = None,
        tool_router: Optional[Any] = None,
        skill_registry: Optional[Any] = None,
        soul: Optional[Any] = None,
        personality: Optional[Any] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        growth_log_manager: Optional[Any] = None,
    ):
        self._config = config or {}
        self._memory_manager = memory_manager
        self._context_builder = context_builder
        self._tool_router = tool_router
        self._skill_registry = skill_registry
        self._soul = soul
        self._personality = personality
        self._conversation_history = conversation_history or []
        self._growth_log_manager = growth_log_manager
        self._lock = threading.RLock()
        self._initialized = False
    
    @property
    def config(self) -> Dict[str, Any]:
        """配置"""
        return self._config
    
    @property
    def memory_manager(self) -> Optional[Any]:
        """记忆管理器"""
        return self._memory_manager
    
    @memory_manager.setter
    def memory_manager(self, value: Any) -> None:
        self._memory_manager = value
    
    @property
    def context_builder(self) -> Optional[Any]:
        """上下文构建器"""
        return self._context_builder
    
    @context_builder.setter
    def context_builder(self, value: Any) -> None:
        self._context_builder = value
    
    @property
    def tool_router(self) -> Optional[Any]:
        """工具路由器"""
        return self._tool_router
    
    @tool_router.setter
    def tool_router(self, value: Any) -> None:
        self._tool_router = value
    
    @property
    def skill_registry(self) -> Optional[Any]:
        """技能注册表"""
        return self._skill_registry
    
    @skill_registry.setter
    def skill_registry(self, value: Any) -> None:
        self._skill_registry = value
    
    @property
    def soul(self) -> Optional[Any]:
        """灵魂/行为准则"""
        return self._soul
    
    @soul.setter
    def soul(self, value: Any) -> None:
        self._soul = value
    
    @property
    def personality(self) -> Optional[Any]:
        """人格"""
        return self._personality
    
    @personality.setter
    def personality(self, value: Any) -> None:
        self._personality = value
    
    @property
    def conversation_history(self) -> List[Dict[str, Any]]:
        """对话历史"""
        return self._conversation_history
    
    @conversation_history.setter
    def conversation_history(self, value: List[Dict[str, Any]]) -> None:
        self._conversation_history = value
    
    @property
    def growth_log_manager(self) -> Optional[Any]:
        """成长日志管理器"""
        return self._growth_log_manager
    
    @growth_log_manager.setter
    def growth_log_manager(self, value: Any) -> None:
        self._growth_log_manager = value
    
    def init_context_system(self) -> bool:
        """
        初始化上下文系统
        
        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True
        
        try:
            # 检查必要的组件
            if not self._context_builder:
                logger.warning("ContextBuilder not set, context system may not work properly")
            
            self._initialized = True
            logger.info("Context system initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize context system: {e}")
            return False
    
    def build_context(
        self,
        user_message: str,
        agent_id: str = "default",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        agent_emotion: Optional[Dict[str, Any]] = None,
        additional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        构建完整的对话上下文
        
        Args:
            user_message: 用户消息
            agent_id: Agent ID
            user_id: 用户ID
            session_id: 会话ID
            agent_emotion: Agent 情感状态
            additional_context: 额外上下文
            
        Returns:
            构建的上下文字典
        """
        context = {
            "user_message": user_message,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
        }
        
        # 1. 系统提示
        system_prompt = self.build_system_prompt(agent_id)
        context["system_prompt"] = system_prompt
        
        # 2. 对话历史
        context["conversation_history"] = self._conversation_history
        
        # 3. 记忆上下文
        if self._memory_manager:
            try:
                memory_context = self._get_memory_context(user_message, agent_id)
                context["memory_context"] = memory_context
            except Exception as e:
                logger.warning(f"Failed to get memory context: {e}")
        
        # 4. 工具信息
        if self._tool_router:
            try:
                tools_desc = self.get_tools_description(agent_id)
                context["tools_description"] = tools_desc
            except Exception as e:
                logger.warning(f"Failed to get tools description: {e}")
        
        # 5. 情感状态
        if agent_emotion:
            context["agent_emotion"] = agent_emotion
        
        # 6. 成长日志
        if self._growth_log_manager:
            try:
                growth_context = self._get_growth_context(agent_id)
                context["growth_context"] = growth_context
            except Exception as e:
                logger.warning(f"Failed to get growth context: {e}")
        
        # 7. 额外上下文
        if additional_context:
            context.update(additional_context)
        
        return context
    
    def build_system_prompt(self, agent_id: str = "default") -> str:
        """
        构建系统提示
        
        Args:
            agent_id: Agent ID
            
        Returns:
            系统提示文本
        """
        parts = []
        
        # 1. 灵魂/行为准则
        if self._soul:
            try:
                constitution = self._soul.get("constitution", "")
                if constitution:
                    parts.append(f"## 行为准则\n{constitution}")
            except Exception:
                pass
        
        # 2. 人格
        if self._personality:
            try:
                personality_desc = self._personality.get("description", "")
                if personality_desc:
                    parts.append(f"## 人格特征\n{personality_desc}")
            except Exception:
                pass
        
        # 3. 工具能力描述
        if self._tool_router:
            try:
                tools_desc = self.get_tools_description(agent_id)
                if tools_desc:
                    parts.append(f"## 可用工具\n{tools_desc}")
            except Exception:
                pass
        
        if not parts:
            return "你是一个智能助手。"
        
        return "\n\n".join(parts)
    
    def get_tools_description(self, agent_id: str = "default") -> str:
        """
        获取工具描述文本
        
        Args:
            agent_id: Agent ID
            
        Returns:
            工具描述文本
        """
        if not self._tool_router:
            return ""
        
        try:
            # 从 tool_router 获取工具列表
            if hasattr(self._tool_router, 'get_tools_description'):
                return self._tool_router.get_tools_description()
            
            # 从 skill_registry 获取技能描述
            if self._skill_registry and hasattr(self._skill_registry, 'get_skills_description'):
                return self._skill_registry.get_skills_description()
            
        except Exception as e:
            logger.warning(f"Failed to get tools description: {e}")
        
        return ""
    
    def build_tools_for_llm(self, agent_id: str = "default") -> List[Dict[str, Any]]:
        """
        构建 LLM 格式的工具列表
        
        Args:
            agent_id: Agent ID
            
        Returns:
            OpenAI function calling 格式的工具列表
        """
        tools = []
        
        # 从 tool_router 获取
        if self._tool_router and hasattr(self._tool_router, 'get_tools_for_llm'):
            try:
                tools.extend(self._tool_router.get_tools_for_llm())
            except Exception as e:
                logger.warning(f"Failed to get tools from router: {e}")
        
        # 从 skill_registry 获取
        if self._skill_registry and hasattr(self._skill_registry, 'get_tools_for_llm'):
            try:
                tools.extend(self._skill_registry.get_tools_for_llm())
            except Exception as e:
                logger.warning(f"Failed to get tools from skill registry: {e}")
        
        return tools
    
    def _get_memory_context(self, query: str, agent_id: str) -> str:
        """获取记忆上下文"""
        if not self._memory_manager:
            return ""
        
        try:
            if hasattr(self._memory_manager, 'recall'):
                memories = self._memory_manager.recall(query, limit=5)
                if memories:
                    return "\n".join([f"- {m}" for m in memories])
        except Exception as e:
            logger.warning(f"Failed to recall memories: {e}")
        
        return ""
    
    def _get_growth_context(self, agent_id: str) -> str:
        """获取成长日志上下文"""
        if not self._growth_log_manager:
            return ""
        
        try:
            if hasattr(self._growth_log_manager, 'get_recent_logs'):
                logs = self._growth_log_manager.get_recent_logs(limit=3)
                if logs:
                    return "\n".join([f"- {log}" for log in logs])
        except Exception as e:
            logger.warning(f"Failed to get growth logs: {e}")
        
        return ""


# 全局单例
_context_orchestrator: Optional[ContextOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_context_orchestrator(
    config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> ContextOrchestrator:
    """获取全局上下文编排器单例"""
    global _context_orchestrator
    if _context_orchestrator is None:
        with _orchestrator_lock:
            if _context_orchestrator is None:
                _context_orchestrator = ContextOrchestrator(config=config, **kwargs)
    return _context_orchestrator


def reset_context_orchestrator() -> None:
    """重置全局上下文编排器（用于测试）"""
    global _context_orchestrator
    with _orchestrator_lock:
        _context_orchestrator = None
