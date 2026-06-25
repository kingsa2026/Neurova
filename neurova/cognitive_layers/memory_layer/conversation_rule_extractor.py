"""
对话规则提取器

从对话中自动提取因果/条件/前置关系，注入 DependencyGraph。
"""

import json
from neurova.core.logger import get_logger
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class ExtractedRule:
    """提取的规则"""
    source_entity: str
    target_entity: str
    relation_type: str  # causal, conditional, prerequisite, temporal, support, hierarchical
    confidence: float
    evidence_text: str
    source_conversation_id: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source_entity": self.source_entity,
            "target_entity": self.target_entity,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "evidence_text": self.evidence_text,
            "source_conversation_id": self.source_conversation_id,
        }


class ConversationRuleExtractor:
    """从对话中提取因果/条件/前置关系"""
    
    EXTRACTION_PROMPT = """
从以下对话中提取实体间的因果、条件、前置关系。

输出 JSON 格式:
{{
  "rules": [
    {{
      "source": "实体A",
      "target": "实体B", 
      "relation": "causal|conditional|prerequisite|temporal|support|hierarchical",
      "confidence": 0.8,
      "evidence": "原文证据"
    }}
  ]
}}

注意：
- 只提取明确的关系，不要推测
- 置信度范围 0.0-1.0
- 关系类型必须是: causal, conditional, prerequisite, temporal, support, hierarchical

对话:
用户: {user_input}
助手: {reply}
"""
    
    def __init__(self, llm_client: Any, dependency_graph: Any):
        """
        初始化对话规则提取器
        
        Args:
            llm_client: LLM客户端
            dependency_graph: 依赖图谱实例
        """
        self.llm_client = llm_client
        self.graph = dependency_graph
        self.confidence_threshold = 0.6
        logger.info("ConversationRuleExtractor 初始化完成")
    
    async def extract(self, user_input: str, reply: str, conversation_id: str = "") -> List[ExtractedRule]:
        """
        从对话提取规则并注入图谱
        
        Args:
            user_input: 用户输入
            reply: 助手回复
            conversation_id: 对话ID（可选）
            
        Returns:
            提取的规则列表
        """
        # 1. 构建 prompt
        prompt = self.EXTRACTION_PROMPT.format(
            user_input=user_input[:500],
            reply=reply[:500]
        )
        
        # 2. LLM 提取
        try:
            response = await self.llm_client.generate(prompt)
            rules = self._parse_json_response(response)
        except Exception as e:
            logger.warning("LLM提取失败: %s", e)
            return []
        
        # 3. 置信度过滤
        valid_rules = [r for r in rules if r.confidence >= self.confidence_threshold]
        
        # 4. 注入图谱
        for rule in valid_rules:
            rule.source_conversation_id = conversation_id
            self._inject_to_graph(rule)
        
        logger.info("从对话提取到 %d 个规则 (有效: %d)", len(rules), len(valid_rules))
        return valid_rules
    
    def _parse_json_response(self, response: str) -> List[ExtractedRule]:
        """解析LLM的JSON响应"""
        try:
            # 尝试提取JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if not json_match:
                logger.warning("未找到JSON响应")
                return []
            
            data = json.loads(json_match.group())
            rules = []
            
            for rule_data in data.get("rules", []):
                rule = ExtractedRule(
                    source_entity=rule_data.get("source", ""),
                    target_entity=rule_data.get("target", ""),
                    relation_type=rule_data.get("relation", "hierarchical"),
                    confidence=float(rule_data.get("confidence", 0.5)),
                    evidence_text=rule_data.get("evidence", ""),
                )
                rules.append(rule)
            
            return rules
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("解析JSON响应失败: %s", e)
            return []
    
    def _inject_to_graph(self, rule: ExtractedRule):
        """将规则注入 DependencyGraph"""
        try:
            from neurova.cognitive_layers.memory_layer.dependency_graph import (
                DependencyGraph, DependencyEdge, DependencyType, EntityNode,
            )
            
            # 添加实体节点
            source_node = EntityNode(
                id=f"entity_{hash(rule.source_entity) % 100000}",
                name=rule.source_entity,
                entity_type="concept"
            )
            target_node = EntityNode(
                id=f"entity_{hash(rule.target_entity) % 100000}",
                name=rule.target_entity,
                entity_type="concept"
            )
            self.graph.add_entity(source_node)
            self.graph.add_entity(target_node)
            
            # 添加依赖边
            dep_type = DependencyType(rule.relation_type)
            edge = DependencyEdge(
                id=str(uuid.uuid4())[:16],
                source_id=source_node.id,
                target_id=target_node.id,
                dep_type=dep_type,
                confidence=rule.confidence,
                evidence=[rule.evidence_text]
            )
            self.graph.add_dependency(edge)
            
            logger.debug("规则已注入图谱: %s -> %s (%s)", 
                         rule.source_entity, rule.target_entity, rule.relation_type)
        except Exception as e:
            logger.warning("注入图谱失败: %s", e)


# 导入re模块
import re
