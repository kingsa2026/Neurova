"""
进化系统门面

提供简化的进化系统接口，协调多个进化组件：
- AdaptiveToolWeights (工具权重)
- ToolLifecycleManager (工具生命周期)
- PatternMiner (模式挖掘)

设计模式: Facade
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, List

logger = get_logger(__name__)


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
    
    # ============ 经验处理 ============
    
    def record_experience(
        self,
        text: str,
        task: str,
        tools: List[str],
        success: bool,
        crystallizer=None,
    ) -> Dict[str, Any]:
        """
        记录经验

        Args:
            text: 经验文本
            task: 任务描述
            tools: 使用的工具列表
            success: 是否成功
            crystallizer: agent 自己的结晶器（agent 级隔离——单例上的
                crystallizer 会被多 agent last-writer-wins 覆盖）

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
                crystallizer=crystallizer,
            )
            return result
        except Exception as e:
            logger.warning("记录经验失败: %s", e)
            return {"success": False, "error": str(e)}
    
    def notify_pattern_crystallized(
        self,
        pattern_key: str,
        primary_tool: str,
        success_rate: float,
        sample_count: int,
    ) -> Dict[str, Any]:
        """结晶入库通报转发（工单 005：只通报，不投成败票）。"""
        if not self._orchestrator:
            return {"success": False, "error": "Orchestrator not available"}
        try:
            return self._orchestrator.on_pattern_crystallized(
                pattern_key=pattern_key,
                primary_tool=primary_tool,
                success_rate=success_rate,
                sample_count=sample_count,
            )
        except Exception as e:  # noqa: BLE001 - 通报失败不影响已入库的节点
            logger.warning("结晶入库通报失败: %s", e)
            return {"success": False, "error": str(e)}

    # ============ 模式挖掘 ============

    def get_frequent_patterns(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        获取频繁模式

        C4 断链修复（工具侧审计）：此前调用不存在的
        pattern_miner.get_frequent_patterns（实际方法名 get_top_patterns），
        异常被吞静默返回 []。现透传并映射为 dict 契约
        （{"tools", "support", "context", "success_rate"}），与 to_skill_template_list 对齐。

        Args:
            top_n: 返回前N个模式

        Returns:
            List[Dict]: 频繁模式列表
        """
        if not self._orchestrator or not hasattr(self._orchestrator, 'pattern_miner'):
            return []

        try:
            patterns = self._orchestrator.pattern_miner.get_top_patterns(k=top_n)
            return [
                {
                    "tools": list(p.tools),
                    "support": int(p.support),
                    "context": p.context or "",
                    "success_rate": p.success_rate,
                }
                for p in patterns
                if p is not None
            ]
        except Exception as e:
            logger.warning("获取频繁模式失败: %s", e)
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
