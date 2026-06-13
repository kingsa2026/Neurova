"""
统一推理引擎

整合对话规则 + 经验记忆 + 模式挖掘，提供统一推理接口。
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ReasoningResult:
    """推理结果"""
    causal_chains: List[str] = field(default_factory=list)
    tool_recommendations: List[str] = field(default_factory=list)
    risk_warnings: List[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "causal_chains": self.causal_chains,
            "tool_recommendations": self.tool_recommendations,
            "risk_warnings": self.risk_warnings,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "metadata": self.metadata,
        }


class UnifiedReasoningEngine:
    """
    统一推理引擎：对话规则 + 经验记忆 + 模式挖掘
    
    整合三路知识来源，提供统一推理接口：
    1. 对话规则图谱 (知识层)
    2. 经验记忆库 (行为层)
    3. 模式挖掘器 (统计层)
    """
    
    def __init__(
        self,
        cascade_engine: Any = None,
        experience_kb: Any = None,
        pattern_miner: Any = None,
    ):
        """
        初始化统一推理引擎
        
        Args:
            cascade_engine: 级联推理引擎
            experience_kb: 经验知识库
            pattern_miner: 模式挖掘器
        """
        self.cascade_engine = cascade_engine
        self.experience_kb = experience_kb
        self.pattern_miner = pattern_miner
        logger.info("UnifiedReasoningEngine 初始化完成")
    
    def reason(self, query: str, context: Dict[str, Any] = None) -> ReasoningResult:
        """
        执行推理
        
        Args:
            query: 查询文本
            context: 上下文信息
            
        Returns:
            ReasoningResult: 推理结果
        """
        context = context or {}
        
        # 1. 因果链推理
        causal_chains = []
        cascade_confidence = 0.0
        if self.cascade_engine:
            try:
                # 从查询中提取实体（简单实现）
                entity = self._extract_primary_entity(query)
                if entity:
                    result = self.cascade_engine.forward_cascade(entity)
                    causal_chains = [
                        f"{e.entity_id} ({e.effect_type})" 
                        for e in result.effects[:5]
                    ]
                    cascade_confidence = result.confidence
            except Exception as e:
                logger.warning("因果链推理失败: %s", e)
        
        # 2. 工具经验检索
        tool_experiences = []
        if self.experience_kb:
            try:
                experiences = self.experience_kb.find_similar(query)
                tool_experiences = [
                    {"tool": exp.get("tool", ""), "success_rate": exp.get("success_rate", 0)}
                    for exp in experiences[:5]
                ]
            except Exception as e:
                logger.warning("经验检索失败: %s", e)
        
        # 3. 工具序列推荐
        recommended_tools = []
        if self.pattern_miner:
            try:
                recommended_tools = self.pattern_miner.recommend(query)[:3]
            except Exception as e:
                logger.warning("模式挖掘失败: %s", e)
        
        # 4. 融合结果
        return self._fuse_results(
            causal_chains=causal_chains,
            tool_experiences=tool_experiences,
            recommended_tools=recommended_tools,
            cascade_confidence=cascade_confidence,
        )
    
    def _extract_primary_entity(self, query: str) -> Optional[str]:
        """从查询中提取主要实体"""
        # 简单实现：提取第一个名词
        # 实际应该使用NER模型
        words = query.split()
        for word in words:
            if len(word) >= 2:  # 简单过滤
                return word
        return None
    
    def _fuse_results(
        self,
        causal_chains: List[str],
        tool_experiences: List[Dict],
        recommended_tools: List[str],
        cascade_confidence: float = 0.0,
    ) -> ReasoningResult:
        """
        融合各组件结果
        
        Args:
            causal_chains: 因果链列表
            tool_experiences: 工具经验列表
            recommended_tools: 推荐工具列表
            cascade_confidence: 级联推理置信度
            
        Returns:
            ReasoningResult: 融合后的推理结果
        """
        # 工具推荐：合并经验推荐和模式推荐
        all_tools = set()
        for exp in tool_experiences:
            all_tools.add(exp.get("tool", ""))
        for tool in recommended_tools:
            all_tools.add(tool)
        tool_recommendations = [t for t in all_tools if t]
        
        # 风险警告：低成功率的工具
        risk_warnings = []
        for exp in tool_experiences:
            if exp.get("success_rate", 1.0) < 0.7:
                tool = exp.get("tool", "")
                rate = exp.get("success_rate", 0)
                risk_warnings.append(f"{tool} 成功率仅 {rate:.0%}")
        
        # 置信度计算
        confidence = cascade_confidence
        if tool_experiences:
            avg_success = sum(e.get("success_rate", 0) for e in tool_experiences) / len(tool_experiences)
            confidence = (confidence + avg_success) / 2 if confidence > 0 else avg_success
        
        # 证据收集
        evidence = []
        if causal_chains:
            evidence.append(f"因果链: {', '.join(causal_chains[:3])}")
        if tool_experiences:
            evidence.append(f"经验: {len(tool_experiences)}条")
        if recommended_tools:
            evidence.append(f"推荐: {', '.join(recommended_tools[:3])}")
        
        return ReasoningResult(
            causal_chains=causal_chains,
            tool_recommendations=tool_recommendations,
            risk_warnings=risk_warnings,
            confidence=min(1.0, confidence),
            evidence=evidence,
        )
