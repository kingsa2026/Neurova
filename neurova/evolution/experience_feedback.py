"""
经验反哺 (ExperienceFeedback)

从 Agent 的经验总结中提取工具使用洞察，并反哺到工具记忆系统。

流程:
  经验总结文本 ──▶ 提取工具提及 ──▶ 分类结果(成功/失败)
                                    │
                                    ▼
                              创建 ToolInsight
                                    │
                                    ▼
                    存储到任务-工具关联表
"""

from dataclasses import dataclass, field
import re
import time
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 工具名模式：下划线分隔的英文单词
_TOOL_NAME_PATTERN = re.compile(r'\b([a-z][a-z0-9]*_[a-z][a-z0-9_]*)\b')

# 结果关键词
_SUCCESS_KEYWORDS = {"成功", "完成", "成功完成", "顺利完成", "成功了", "success", "complete", "done"}
_FAILURE_KEYWORDS = {"失败", "错误", "异常", "出错", "失败了", "failure", "error", "exception", "failed"}
_PARTIAL_KEYWORDS = {"部分", "有些", "部分成功", "部分完成", "partial", "some"}


@dataclass
class ToolInsight:
    """工具使用洞察。"""
    
    tool_name: str
    outcome: str  # success, failure, partial
    context: str = ""
    confidence: float = 0.8
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "outcome": self.outcome,
            "context": self.context,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class TaskToolAssociation:
    """任务-工具关联记录。"""
    
    task_type: str
    tool_name: str
    success_count: int = 0
    failure_count: int = 0
    total_count: int = 0
    avg_confidence: float = 0.0
    last_used: float = field(default_factory=time.time)
    
    @property
    def success_rate(self) -> float:
        """成功率。"""
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "tool_name": self.tool_name,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
            "success_rate": self.success_rate,
            "avg_confidence": self.avg_confidence,
            "last_used": self.last_used,
        }


class ExperienceFeedback:
    """
    经验反哺系统：从经验中提取工具洞察并更新任务-工具关联。
    """
    
    def __init__(self, known_tools: Optional[List[str]] = None):
        """初始化经验反哺系统。
        
        Args:
            known_tools: 已知工具列表，用于精确匹配
        """
        self._known_tools: set = set(known_tools or [])
        
        # 任务-工具关联表：task_type -> tool_name -> TaskToolAssociation
        self._associations: Dict[str, Dict[str, TaskToolAssociation]] = {}
        
        # 洞察历史
        self._insights: List[ToolInsight] = []
        
        logger.debug("ExperienceFeedback initialized")
    
    def extract_tool_mentions(self, text: str) -> List[str]:
        """从文本中提取工具名。
        
        Args:
            text: 经验文本
            
        Returns:
            提取到的工具名列表
        """
        matches = _TOOL_NAME_PATTERN.findall(text)
        
        # 过滤：如果已知工具列表存在，只保留已知工具
        if self._known_tools:
            return [m for m in matches if m in self._known_tools]
        
        return list(set(matches))  # 去重
    
    def classify_outcome(self, text: str) -> str:
        """分类经验结果。
        
        Args:
            text: 经验文本
            
        Returns:
            结果分类：success, failure, partial
        """
        text_lower = text.lower()
        
        # 计算各类关键词出现次数
        success_score = sum(1 for kw in _SUCCESS_KEYWORDS if kw in text_lower)
        failure_score = sum(1 for kw in _FAILURE_KEYWORDS if kw in text_lower)
        partial_score = sum(1 for kw in _PARTIAL_KEYWORDS if kw in text_lower)
        
        if failure_score > success_score and failure_score > partial_score:
            return "failure"
        elif partial_score > 0 and success_score > 0:
            return "partial"
        elif success_score > 0:
            return "success"
        elif failure_score > 0:
            return "failure"
        else:
            return "success"  # 默认为成功
    
    def create_tool_insight(
        self,
        tool_name: str,
        outcome: str,
        context: str = "",
        confidence: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolInsight:
        """创建工具洞察。
        
        Args:
            tool_name: 工具名
            outcome: 结果
            context: 上下文
            confidence: 置信度
            metadata: 元数据
            
        Returns:
            工具洞察
        """
        insight = ToolInsight(
            tool_name=tool_name,
            outcome=outcome,
            context=context,
            confidence=confidence,
            metadata=metadata or {},
        )
        
        self._insights.append(insight)
        logger.debug(f"Created insight for {tool_name}: {outcome}")
        
        return insight
    
    def create_task_tool_association(
        self,
        task_type: str,
        tool_name: str,
        outcome: str,
        confidence: float = 0.8,
    ) -> TaskToolAssociation:
        """创建或更新任务-工具关联。
        
        Args:
            task_type: 任务类型
            tool_name: 工具名
            outcome: 结果
            confidence: 置信度
            
        Returns:
            任务-工具关联
        """
        if task_type not in self._associations:
            self._associations[task_type] = {}
        
        if tool_name not in self._associations[task_type]:
            self._associations[task_type][tool_name] = TaskToolAssociation(
                task_type=task_type,
                tool_name=tool_name,
            )
        
        assoc = self._associations[task_type][tool_name]
        
        # 更新计数
        assoc.total_count += 1
        if outcome == "success":
            assoc.success_count += 1
        elif outcome == "failure":
            assoc.failure_count += 1
        
        # 更新平均置信度
        assoc.avg_confidence = (
            (assoc.avg_confidence * (assoc.total_count - 1) + confidence)
            / assoc.total_count
        )
        
        assoc.last_used = time.time()
        
        return assoc
    
    def process_experience(
        self,
        experience_text: str,
        task_type: str = "general",
    ) -> Dict[str, Any]:
        """处理一条经验。
        
        Args:
            experience_text: 经验文本
            task_type: 任务类型
            
        Returns:
            处理结果
        """
        # 提取工具提及
        tools = self.extract_tool_mentions(experience_text)
        
        # 分类结果
        outcome = self.classify_outcome(experience_text)
        
        # 为每个工具创建洞察和关联
        insights = []
        associations = []
        
        for tool_name in tools:
            insight = self.create_tool_insight(
                tool_name=tool_name,
                outcome=outcome,
                context=experience_text[:200],
            )
            insights.append(insight)
            
            assoc = self.create_task_tool_association(
                task_type=task_type,
                tool_name=tool_name,
                outcome=outcome,
            )
            associations.append(assoc)
        
        result = {
            "tools_mentioned": tools,
            "outcome": outcome,
            "insights_created": len(insights),
            "associations_updated": len(associations),
            "task_type": task_type,
        }
        
        logger.debug(f"Processed experience: {result}")
        return result
    
    def _update_task_association(
        self,
        task_type: str,
        tool_name: str,
        outcome: str,
        confidence: float,
    ) -> None:
        """更新任务-工具关联。"""
        self.create_task_tool_association(
            task_type=task_type,
            tool_name=tool_name,
            outcome=outcome,
            confidence=confidence,
        )
    
    def get_task_tool_patterns(self, task_type: str) -> List[Dict[str, Any]]:
        """获取任务-工具模式。
        
        Args:
            task_type: 任务类型
            
        Returns:
            关联列表
        """
        if task_type not in self._associations:
            return []
        
        patterns = []
        for assoc in self._associations[task_type].values():
            patterns.append(assoc.to_dict())
        
        # 按成功率降序排序
        patterns.sort(key=lambda x: x["success_rate"], reverse=True)
        
        return patterns
