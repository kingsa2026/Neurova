"""
闭环进化系统 — 工具执行 → 进化更新 → 经验反哺 → 权重更新

实现四个核心类：
1. ToolLifecycleManager - 工具生命周期管理
2. AdaptiveToolWeights - 自适应权重管理
3. EvolutionOrchestrator - 进化编排器
4. PatternMiner/ToolGeneticEngine/NLToolSynthesizer - 占位符实现
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, UTC
import json
from pathlib import Path
import threading

logger = logging.getLogger(__name__)

@dataclass
class ToolWeight:
    """工具权重数据"""
    tool_name: str
    success_count: int = 0
    failure_count: int = 0
    total_latency: float = 0.0
    last_used: Optional[datetime] = None
    adaptive_multiplier: float = 1.0
    lifecycle_state: str = "active"  # active, degraded, archived, frozen

class ToolLifecycleManager:
    """工具生命周期管理器 — 记录工具使用状态"""

    def __init__(self):
        self._usage_counts: Dict[str, int] = {}
        self._last_used: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        logger.info("ToolLifecycleManager initialized")

    def touch(self, tool_name: str) -> None:
        """记录工具被使用一次"""
        with self._lock:
            self._usage_counts[tool_name] = self._usage_counts.get(tool_name, 0) + 1
            self._last_used[tool_name] = datetime.now(UTC)
            logger.debug(f"Tool touched: {tool_name} (count: {self._usage_counts[tool_name]})")

    def get_usage_count(self, tool_name: str) -> int:
        """获取工具使用次数"""
        return self._usage_counts.get(tool_name, 0)

    def get_last_used(self, tool_name: str) -> Optional[datetime]:
        """获取工具最后使用时间"""
        return self._last_used.get(tool_name)

    def evaluate(self, tool_name: str = None) -> Dict[str, Any]:
        """
        评估工具生命周期状态
        
        Args:
            tool_name: 工具名称，如果为 None 则评估所有工具
            
        Returns:
            评估结果字典
        """
        with self._lock:
            if tool_name:
                # 评估单个工具
                count = self._usage_counts.get(tool_name, 0)
                last_used = self._last_used.get(tool_name)
                return {
                    "tool_name": tool_name,
                    "usage_count": count,
                    "last_used": last_used.isoformat() if last_used else None,
                    "status": "active" if count > 0 else "unused",
                }
            else:
                # 评估所有工具
                results = {}
                for name in set(list(self._usage_counts.keys()) + list(self._last_used.keys())):
                    count = self._usage_counts.get(name, 0)
                    last_used = self._last_used.get(name)
                    results[name] = {
                        "usage_count": count,
                        "last_used": last_used.isoformat() if last_used else None,
                        "status": "active" if count > 0 else "unused",
                    }
                return results

class AdaptiveToolWeights:
    """自适应权重管理器 — 根据工具表现调整权重"""

    def __init__(self):
        self._weights: Dict[str, ToolWeight] = {}
        self._lock = threading.Lock()
        logger.info("AdaptiveToolWeights initialized")

    def get_weight(self, tool_name: str) -> Optional[ToolWeight]:
        """获取工具权重"""
        return self._weights.get(tool_name)

    def update_weight(self, tool_name: str, success: bool, latency: float = 0.0) -> None:
        """更新工具权重"""
        with self._lock:
            if tool_name not in self._weights:
                self._weights[tool_name] = ToolWeight(tool_name=tool_name)

            weight = self._weights[tool_name]
            if success:
                weight.success_count += 1
                # 成功时增加自适应乘数（最多增加50%）
                weight.adaptive_multiplier = min(1.5, weight.adaptive_multiplier * 1.05)
            else:
                weight.failure_count += 1
                # 失败时降低自适应乘数（最少降到30%）
                weight.adaptive_multiplier = max(0.3, weight.adaptive_multiplier * 0.95)

            weight.total_latency += latency
            weight.last_used = datetime.now(UTC)
            logger.debug(f"Weight updated for {tool_name}: success={success}, multiplier={weight.adaptive_multiplier:.3f}")

    def get_effective_weight(self, tool_name: str) -> float:
        """获取工具的有效权重（考虑自适应乘数）"""
        weight = self.get_weight(tool_name)
        if not weight:
            return 1.0

        # 基础权重基于成功率
        total = weight.success_count + weight.failure_count
        if total == 0:
            base_weight = 1.0
        else:
            base_weight = weight.success_count / total

        # 应用自适应乘数
        return base_weight * weight.adaptive_multiplier

    def get_ranked_tools(self, tool_names: List[str]) -> List[str]:
        """按权重对工具进行排序"""
        def sort_key(tool_name: str) -> float:
            return self.get_effective_weight(tool_name)

        return sorted(tool_names, key=sort_key, reverse=True)

class PatternMiner:
    """模式挖掘器 — 占位符实现"""

    def __init__(self):
        logger.info("PatternMiner initialized (placeholder)")

class ToolGeneticEngine:
    """工具基因编程引擎 — 占位符实现"""

    def __init__(self):
        logger.info("ToolGeneticEngine initialized (placeholder)")

class NLToolSynthesizer:
    """自然语言工具合成器 — 占位符实现"""

    def __init__(self, pattern_miner: Optional[PatternMiner] = None):
        self.pattern_miner = pattern_miner
        logger.info("NLToolSynthesizer initialized (placeholder)")

class EvolutionOrchestrator:
    """进化编排器 — 协调工具进化、权重更新和经验反哺"""

    def __init__(self):
        self.tool_weights = AdaptiveToolWeights()
        self.tool_lifecycle = ToolLifecycleManager()
        self.pattern_miner = PatternMiner()
        self.genetic_engine = ToolGeneticEngine()
        self.tool_synthesizer = NLToolSynthesizer(self.pattern_miner)

        # 工具注册表
        self._registered_tools: List[str] = []

        logger.info("EvolutionOrchestrator initialized")

    def register_tools(self, tool_names: List[str]) -> None:
        """注册工具列表"""
        self._registered_tools = tool_names.copy()
        logger.info(f"Registered {len(tool_names)} tools")

    def on_before_tool_selection(self, available_tools: List[str], context: str = "") -> Dict[str, Any]:
        """
        工具选择前钩子 — 返回按权重排序的工具列表

        Args:
            available_tools: 可用工具列表
            context: 上下文信息

        Returns:
            包含排序后工具列表的字典
        """
        # 按权重排序
        ranked_tools = self.tool_weights.get_ranked_tools(available_tools)

        return {
            "ranking": ranked_tools,
            "weights": {
                tool: self.tool_weights.get_effective_weight(tool)
                for tool in ranked_tools
            }
        }

    def on_after_tool_execution(self, tool_name: str, success: bool, context: str = "", latency: float = 0.0) -> None:
        """
        工具执行后钩子 — 更新工具权重和生命周期

        Args:
            tool_name: 工具名称
            success: 是否成功
            context: 上下文信息
            latency: 执行延迟
        """
        # 更新权重
        self.tool_weights.update_weight(tool_name, success, latency)

        # 更新生命周期
        self.tool_lifecycle.touch(tool_name)

        logger.debug(f"Tool execution recorded: {tool_name}, success={success}")

    def on_experience_recorded(self, text: str, task: str, tools: List[str], success: bool) -> Dict[str, Any]:
        """
        经验记录后钩子 — 从经验中提取洞察并更新权重

        Args:
            text: 经验文本
            task: 任务描述
            tools: 使用的工具列表
            success: 是否成功

        Returns:
            包含洞察信息的字典
        """
        insights_count = 0
        association = {}

        # 简单实现：为每个工具更新权重
        for tool in tools:
            if tool in self._registered_tools:
                # 根据成功与否调整权重
                self.tool_weights.update_weight(tool, success)
                insights_count += 1
                association[tool] = "positive" if success else "negative"

        logger.info(f"Experience recorded: task='{task}', tools={tools}, success={success}")

        return {
            "insights_count": insights_count,
            "association": association,
            "task": task,
            "success": success
        }

    def get_statistics(self) -> Dict[str, Any]:
        """获取进化统计信息"""
        return {
            "registered_tools": len(self._registered_tools),
            "tools_with_weights": len(self.tool_weights._weights),
            "tools_with_usage": len(self.tool_lifecycle._usage_counts),
        }