"""
进化系统门面

提供简化的进化系统接口，协调多个进化组件：
- AdaptiveToolWeights (工具权重)
- ToolLifecycleManager (工具生命周期)
- PatternMiner (模式挖掘)
- NLToolSynthesizer (工具合成)

设计模式: Facade
"""

from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class EvolutionResult:
    """进化操作结果"""
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "metadata": self.metadata,
        }


class EvolutionFacade:
    """
    进化系统门面
    
    提供简化的进化系统接口，内部协调EvolutionOrchestrator。
    
    使用示例:
        facade = EvolutionFacade(evolution_orchestrator)
        weight = facade.get_tool_weight("web_search")
        facade.update_tool_weight("web_search", success=True, latency=0.5)
    """
    
    def __init__(self, evolution_orchestrator=None):
        """
        初始化门面
        
        Args:
            evolution_orchestrator: EvolutionOrchestrator实例
        """
        self._orchestrator = evolution_orchestrator
        logger.debug("EvolutionFacade初始化")
    
    # ============ 工具权重 ============
    
    def get_tool_weight(self, tool_name: str) -> float:
        """
        获取工具权重
        
        Args:
            tool_name: 工具名称
            
        Returns:
            float: 工具权重
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'tool_weights'):
            return 1.0
        
        try:
            return self._orchestrator.tool_weights.get_effective_weight(tool_name)
        except Exception as e:
            logger.warning("获取工具权重失败: %s", e)
            return 1.0
    
    def update_tool_weight(
        self, 
        tool_name: str, 
        success: bool, 
        latency: float = 0.0,
    ):
        """
        更新工具权重
        
        Args:
            tool_name: 工具名称
            success: 是否成功
            latency: 执行延迟
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'tool_weights'):
            return
        
        try:
            self._orchestrator.tool_weights.update_weight(tool_name, success)
        except Exception as e:
            logger.warning("更新工具权重失败: %s", e)
    
    def rank_tools(self, tool_names: List[str]) -> List[str]:
        """
        按权重排序工具
        
        Args:
            tool_names: 工具名称列表
            
        Returns:
            List[str]: 排序后的工具名称列表
        """
        if not tool_names:
            return []
        
        # 按权重降序排序
        weighted = [(name, self.get_tool_weight(name)) for name in tool_names]
        weighted.sort(key=lambda x: x[1], reverse=True)
        
        return [name for name, _ in weighted]
    
    # ============ 工具生命周期 ============
    
    def get_tool_lifecycle_state(self, tool_name: str) -> str:
        """
        获取工具生命周期状态
        
        Args:
            tool_name: 工具名称
            
        Returns:
            str: 生命周期状态
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'tool_lifecycle'):
            return "active"
        
        try:
            state = self._orchestrator.tool_lifecycle.get_state(tool_name)
            return state.value if hasattr(state, 'value') else str(state) or "active"
        except Exception as e:
            logger.warning("获取工具生命周期状态失败: %s", e)
            return "active"
    
    def touch_tool(self, tool_name: str):
        """
        更新工具生命周期（记录使用）
        
        Args:
            tool_name: 工具名称
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'tool_lifecycle'):
            return
        
        try:
            self._orchestrator.tool_lifecycle.touch(tool_name)
        except Exception as e:
            logger.warning("更新工具生命周期失败: %s", e)
    
    # ============ 工具选择 ============
    
    def select_tools(
        self, 
        available_tools: List[str], 
        context: str = "",
    ) -> Dict[str, Any]:
        """
        选择工具（基于权重和上下文）
        
        Args:
            available_tools: 可用工具列表
            context: 上下文描述
            
        Returns:
            Dict: 工具选择结果
        """
        if not available_tools:
            return {"selected": [], "reason": "no_tools_available"}
        
        # 按权重排序
        ranked = self.rank_tools(available_tools)
        
        # 选择前3个
        selected = ranked[:3]
        
        return {
            "selected": selected,
            "weights": {tool: self.get_tool_weight(tool) for tool in selected},
            "context": context,
        }
    
    # ============ 经验处理 ============
    
    def record_experience(
        self, 
        text: str, 
        task: str, 
        tools: List[str], 
        success: bool,
    ) -> Dict[str, Any]:
        """
        记录经验
        
        Args:
            text: 经验文本
            task: 任务描述
            tools: 使用的工具列表
            success: 是否成功
            
        Returns:
            Dict: 经验记录结果
        """
        if not self._orchestrator:
            return {"success": False, "error": "Orchestrator not available"}
        
        try:
            result = self._orchestrator.on_experience_recorded(
                text=text,
                task=task,
                tools=tools,
                success=success,
            )
            return result
        except Exception as e:
            logger.warning("记录经验失败: %s", e)
            return {"success": False, "error": str(e)}
    
    # ============ 模式挖掘 ============
    
    def add_tool_sequence(
        self, 
        tools: List[str], 
        context: str = "",
    ):
        """
        添加工具序列（用于模式挖掘）
        
        Args:
            tools: 工具名称列表
            context: 上下文描述
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'pattern_miner'):
            return
        
        try:
            self._orchestrator.pattern_miner.add_sequence(tools, context=context)
        except Exception as e:
            logger.warning("添加工具序列失败: %s", e)
    
    def get_frequent_patterns(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        获取频繁模式
        
        Args:
            top_n: 返回前N个模式
            
        Returns:
            List[Dict]: 频繁模式列表
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'pattern_miner'):
            return []
        
        try:
            patterns = self._orchestrator.pattern_miner.get_frequent_patterns(top_n)
            return patterns if isinstance(patterns, list) else []
        except Exception as e:
            logger.warning("获取频繁模式失败: %s", e)
            return []
    
    # ============ 工具合成 ============
    
    def synthesize_tools(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """
        合成工具（基于频繁模式）

        Args:
            top_n: 合成前N个工具

        Returns:
            List[Dict]: 合成的工具列表
        """
        # Bug N-3 修复: 三重断裂
        # 1. 属性名: nl_synthesizer → tool_synthesizer（匹配 closed_loop.py:221）
        # 2. 方法名: synthesize → synthesize_from_patterns（匹配 PatternBasedToolSynthesizer）
        # 3. 签名: top_n= 已正确（synthesize_from_patterns 接受 top_n）
        if not self._orchestrator or not hasattr(self._orchestrator, 'tool_synthesizer'):
            return []

        try:
            tools = self._orchestrator.tool_synthesizer.synthesize_from_patterns(top_n=top_n)
            return tools if isinstance(tools, list) else []
        except Exception as e:
            logger.warning("合成工具失败: %s", e)
            return []
    
    # ============ 统计 ============
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取进化统计信息
        
        Returns:
            Dict: 统计信息
        """
        if not self._orchestrator:
            return {}
        
        try:
            return self._orchestrator.get_statistics()
        except Exception as e:
            logger.warning("获取统计信息失败: %s", e)
            return {}
    
    # ============ 兼容旧接口 ============
    
    def on_after_tool_execution(
        self, 
        tool_name: str, 
        success: bool, 
        context: str = "", 
        latency: float = 0.0,
    ):
        """
        兼容旧接口：工具执行后钩子
        
        Args:
            tool_name: 工具名称
            success: 是否成功
            context: 上下文
            latency: 延迟
        """
        self.update_tool_weight(tool_name, success, latency)
        self.touch_tool(tool_name)
    
    def on_experience_recorded_compat(
        self, 
        text: str, 
        task: str, 
        tools: List[str], 
        success: bool,
    ) -> Dict[str, Any]:
        """
        兼容旧接口：经验记录后钩子
        
        Args:
            text: 经验文本
            task: 任务描述
            tools: 使用的工具列表
            success: 是否成功
            
        Returns:
            Dict: 经验记录结果
        """
        return self.record_experience(text, task, tools, success)


# 全局单例
_facade_instance: Optional[EvolutionFacade] = None


def get_evolution_facade(
    evolution_orchestrator=None,
) -> EvolutionFacade:
    """
    获取进化门面单例
    
    Args:
        evolution_orchestrator: EvolutionOrchestrator实例
        
    Returns:
        EvolutionFacade: 门面实例
    """
    global _facade_instance
    if _facade_instance is None and evolution_orchestrator is not None:
        _facade_instance = EvolutionFacade(evolution_orchestrator)
    return _facade_instance


def reset_evolution_facade():
    """重置门面单例（用于测试）"""
    global _facade_instance
    _facade_instance = None
