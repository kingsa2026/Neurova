"""
技能自动封装 (AutoSkillBuilder)

从 Agent 的成功经验中自动提取可复用的工具组合模式，
当同一模式重复出现足够多次后，自动封装为"技能(Skill)"。

技能本质 = 工具序列 + 上下文匹配 + 成功率统计

流程:
  工具执行序列 ──▶ 提取 ToolPattern
       │
       ▼
  模式出现 N 次 ──▶ 封装为 SkillTemplate
       │
       ▼
  上下文匹配 ──▶ 推荐技能
"""

import datetime
import hashlib
from neurova.core.logger import get_logger
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class ToolPattern:
    """工具执行模式"""

    pattern_id: str = ""
    tool_sequence: List[str] = field(default_factory=list)
    context_keywords: List[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    total_uses: int = 0
    avg_duration: float = 0.0
    first_seen: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_seen: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.pattern_id and self.tool_sequence:
            content = ":".join(self.tool_sequence)
            self.pattern_id = hashlib.md5(content.encode()).hexdigest()[:12]

    @property
    def success_rate(self) -> float:
        return self.success_count / max(1, self.total_uses)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "tool_sequence": self.tool_sequence,
            "context_keywords": self.context_keywords,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_uses": self.total_uses,
            "avg_duration": self.avg_duration,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class SkillTemplate:
    """技能模板"""

    template_id: str = ""
    name: str = ""
    description: str = ""
    pattern: Optional[ToolPattern] = None
    tool_sequence: List[str] = field(default_factory=list)
    parameter_hints: Dict[str, Any] = field(default_factory=dict)
    context_template: str = ""
    success_rate: float = 0.0
    usage_count: int = 0
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    last_used: Optional[datetime.datetime] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "tool_sequence": self.tool_sequence,
            "parameter_hints": self.parameter_hints,
            "context_template": self.context_template,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "is_active": self.is_active,
        }


@dataclass
class ObservationRecord:
    """观察记录"""

    tool_sequence: List[str] = field(default_factory=list)
    context: str = ""
    success: bool = False
    duration: float = 0.0
    timestamp: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


# ────── 主类 ──────


class AutoSkillBuilder:
    """
    技能自动构建器

    观察工具执行序列，识别重复模式，自动封装为可复用的技能模板。
    """

    def __init__(
        self,
        min_pattern_occurrences: int = 3,
        min_success_rate: float = 0.7,
        max_patterns: int = 1000,
        similarity_threshold: float = 0.8,
    ):
        """
        初始化技能构建器

        参数:
            min_pattern_occurrences: 触发封装的最小模式出现次数
            min_success_rate: 最小成功率阈值
            max_patterns: 最大模式数量
            similarity_threshold: 模式相似度阈值
        """
        self._min_occurrences = min_pattern_occurrences
        self._min_success_rate = min_success_rate
        self._max_patterns = max_patterns
        self._similarity_threshold = similarity_threshold
        # C10 技能评审闸：默认开（产物 is_active=False 进 pending，需 approve_template
        # 才会被 register_to_skill_registry 注册）；NEUROVA_SKILL_REVIEW_GATE=0 恢复
        # 旧直通行为。自动产物未经人审即成模型可见工具面，是 OC Workshop 对照
        # 报告指出的治理缺口。
        import os as _os

        self._review_gate = _os.environ.get("NEUROVA_SKILL_REVIEW_GATE", "1") != "0"
        self._lock = threading.RLock()

        # 模式库
        self._patterns: Dict[str, ToolPattern] = {}

        # 技能模板库
        self._templates: Dict[str, SkillTemplate] = {}

        # 观察记录
        self._observations: List[ObservationRecord] = []
        self._max_observations = 10000

        logger.info("AutoSkillBuilder initialized")

    def observe(
        self,
        tool_sequence: List[str],
        context: str = "",
        success: bool = True,
        duration: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        观察工具执行序列

        参数:
            tool_sequence: 工具执行序列
            context: 上下文描述
            success: 是否成功
            duration: 执行时长
            metadata: 元数据
        """
        with self._lock:
            # 记录观察
            record = ObservationRecord(
                tool_sequence=tool_sequence,
                context=context,
                success=success,
                duration=duration,
                metadata=metadata or {},
            )
            self._observations.append(record)

            # 限制观察记录数量
            if len(self._observations) > self._max_observations:
                self._observations = self._observations[-self._max_observations :]

            # 提取或更新模式
            if len(tool_sequence) >= 2:  # 至少2个工具才算模式
                self._update_pattern(tool_sequence, context, success, duration)

    def _update_pattern(self, tool_sequence: List[str], context: str, success: bool, duration: float):
        """更新模式"""
        # 生成模式ID
        content = ":".join(tool_sequence)
        pattern_id = hashlib.md5(content.encode()).hexdigest()[:12]

        # 提取上下文关键词
        keywords = self._extract_keywords(context)

        if pattern_id in self._patterns:
            # 更新现有模式
            pattern = self._patterns[pattern_id]
            pattern.total_uses += 1
            pattern.last_seen = datetime.datetime.now(datetime.timezone.utc)

            if success:
                pattern.success_count += 1
            else:
                pattern.failure_count += 1

            # 更新平均时长
            pattern.avg_duration = (pattern.avg_duration * (pattern.total_uses - 1) + duration) / pattern.total_uses

            # 合并关键词
            for kw in keywords:
                if kw not in pattern.context_keywords:
                    pattern.context_keywords.append(kw)
        else:
            # 创建新模式
            pattern = ToolPattern(
                pattern_id=pattern_id,
                tool_sequence=tool_sequence,
                context_keywords=keywords,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
                total_uses=1,
                avg_duration=duration,
            )
            self._patterns[pattern_id] = pattern

        # 检查是否应该封装
        self._check_encapsulation(pattern)

    def _extract_keywords(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        if not text:
            return []

        # 简单分词
        words = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())

        # 过滤停用词
        stop_words = {
            "的",
            "了",
            "在",
            "是",
            "我",
            "有",
            "和",
            "就",
            "不",
            "人",
            "都",
            "一",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "have",
        }

        return [w for w in words if w not in stop_words and len(w) > 1][:10]

    def _check_encapsulation(self, pattern: ToolPattern):
        """检查是否应该封装为技能"""
        # 检查出现次数
        if pattern.total_uses < self._min_occurrences:
            return

        # 检查成功率
        if pattern.success_rate < self._min_success_rate:
            return

        # 检查是否已存在相似技能
        for template in self._templates.values():
            if self._pattern_skill_similarity(pattern, template) > self._similarity_threshold:
                return

        # 封装为技能模板
        self._encapsulate_pattern(pattern)

    def _pattern_skill_similarity(self, pattern: ToolPattern, template: SkillTemplate) -> float:
        """计算模式与技能模板的相似度"""
        # 工具序列相似度
        seq1 = set(pattern.tool_sequence)
        seq2 = set(template.tool_sequence)

        if not seq1 or not seq2:
            return 0.0

        intersection = len(seq1 & seq2)
        union = len(seq1 | seq2)

        return intersection / union if union > 0 else 0.0

    def _encapsulate_pattern(self, pattern: ToolPattern):
        """将模式封装为技能模板"""
        template_id = f"skill_{pattern.pattern_id}"

        # 生成技能名称
        name = self._generate_skill_name(pattern)

        # 生成描述
        description = self._generate_skill_description(pattern)

        template = SkillTemplate(
            template_id=template_id,
            name=name,
            description=description,
            pattern=pattern,
            tool_sequence=pattern.tool_sequence,
            context_template=" ".join(pattern.context_keywords[:5]),
            success_rate=pattern.success_rate,
            is_active=not self._review_gate,  # C10: 评审闸开启时产物先进 pending
        )

        self._templates[template_id] = template

        logger.info("Encapsulated pattern %s into skill %s", pattern.pattern_id, template_id)

    def _generate_skill_name(self, pattern: ToolPattern) -> str:
        """生成技能名称"""
        # 使用前两个工具名
        if len(pattern.tool_sequence) >= 2:
            return f"{pattern.tool_sequence[0]}_{pattern.tool_sequence[1]}_skill"
        return f"skill_{pattern.pattern_id}"

    def _generate_skill_description(self, pattern: ToolPattern) -> str:
        """生成技能描述"""
        tools = " → ".join(pattern.tool_sequence[:3])
        return f"自动封装的技能：执行 {tools}，成功率 {pattern.success_rate * 100:.0f}%%"

    def find_skills_for_context(self, context: str, tool_sequence: Optional[List[str]] = None) -> List[SkillTemplate]:
        """
        根据上下文查找匹配的技能

        参数:
            context: 上下文描述
            tool_sequence: 工具序列（可选）

        返回:
            List[SkillTemplate]: 匹配的技能模板列表
        """
        with self._lock:
            keywords = self._extract_keywords(context)
            results = []

            for template in self._templates.values():
                if not template.is_active:
                    continue

                # 计算匹配分数
                score = self._calculate_match_score(template, keywords, tool_sequence)

                if score > 0.3:  # 最低匹配阈值
                    results.append((template, score))

            # 按分数排序
            results.sort(key=lambda x: x[1], reverse=True)

            return [template for template, score in results]

    def _calculate_match_score(
        self, template: SkillTemplate, context_keywords: List[str], tool_sequence: Optional[List[str]] = None
    ) -> float:
        """计算匹配分数"""
        score = 0.0

        # 关键词匹配
        if template.pattern and template.pattern.context_keywords:
            common_keywords = set(template.pattern.context_keywords) & set(context_keywords)
            keyword_score = len(common_keywords) / max(1, len(template.pattern.context_keywords))
            score += keyword_score * 0.5

        # 工具序列匹配
        if tool_sequence and template.tool_sequence:
            seq1 = set(tool_sequence)
            seq2 = set(template.tool_sequence)
            if seq1 and seq2:
                intersection = len(seq1 & seq2)
                union = len(seq1 | seq2)
                seq_score = intersection / union if union > 0 else 0
                score += seq_score * 0.3

        # 成功率加成
        score += template.success_rate * 0.2

        return min(1.0, score)

    def get_pattern_statistics(self) -> Dict[str, Any]:
        """获取模式统计信息"""
        with self._lock:
            total_patterns = len(self._patterns)
            total_templates = len(self._templates)
            total_observations = len(self._observations)

            # 按成功率排序的 top 模式
            top_patterns = sorted(self._patterns.values(), key=lambda p: p.success_rate * p.total_uses, reverse=True)[
                :10
            ]

            return {
                "total_patterns": total_patterns,
                "total_templates": total_templates,
                "total_observations": total_observations,
                "top_patterns": [
                    {
                        "pattern_id": p.pattern_id,
                        "tool_sequence": p.tool_sequence,
                        "success_rate": p.success_rate,
                        "total_uses": p.total_uses,
                    }
                    for p in top_patterns
                ],
            }

    def get_template(self, template_id: str) -> Optional[SkillTemplate]:
        """获取技能模板"""
        return self._templates.get(template_id)

    def get_all_templates(self) -> List[SkillTemplate]:
        """获取所有技能模板"""
        return list(self._templates.values())

    def list_pending_templates(self) -> List[Dict[str, Any]]:
        """列出待审模板（C10 评审闸：is_active=False 的产物）。"""
        with self._lock:
            return [
                {
                    "template_id": t.template_id,
                    "name": t.name,
                    "description": t.description,
                    "tool_sequence": list(t.tool_sequence),
                    "success_rate": t.success_rate,
                }
                for t in self._templates.values()
                if not t.is_active
            ]

    def approve_template(self, template_id: str) -> bool:
        """批准待审模板（激活后可被 register_to_skill_registry 注册）。"""
        with self._lock:
            t = self._templates.get(template_id)
            if t is None:
                return False
            t.is_active = True
            logger.info("技能模板 %s 已批准", template_id)
            return True

    def reject_template(self, template_id: str) -> bool:
        """拒绝待审模板（删除）。"""
        with self._lock:
            if self._templates.pop(template_id, None) is None:
                return False
            logger.info("技能模板 %s 已拒绝", template_id)
            return True

    def register_to_skill_registry(self, registry, skill_service=None) -> int:
        """将封装的技能模板注册到 SkillRegistry (并可选持久化到 SkillService)

        桥接 AutoSkillBuilder（内存 dict）与 SkillRegistry（中央注册表），
        使自动封装的技能能在下次对话中被检索使用。

        s3 P0 #2: 新增 skill_service 参数. 提供时, 同步写入 SkillService 磁盘 manifest,
        使前端 GET /private 聚合 SkillService.list_skills() 时能展示自动技能.
        不提供时, 保留原行为 (仅写 registry), 向后兼容.

        Args:
            registry: SkillRegistry 实例
            skill_service: 可选, SkillService 实例. 提供则持久化到磁盘.

        Returns:
            int: 成功注册到 SkillRegistry 的技能数量
        """
        from neurova.skills.models import Skill, SkillSource

        registered_count = 0
        with self._lock:
            for template_id, template in self._templates.items():
                if not template.is_active:
                    continue

                # 转换 SkillTemplate → Skill
                skill = Skill(
                    id=template_id,
                    name=template.name,
                    version="1.0.0",
                    description=template.description,
                    author="auto_skill_builder",
                    source=SkillSource.LOCAL,
                    enabled=True,
                    config={
                        "tool_sequence": template.tool_sequence,
                        "context_template": template.context_template,
                        "success_rate": template.success_rate,
                        "parameter_hints": template.parameter_hints,
                    },
                )

                # 注册到 SkillRegistry（path 用占位符，自动技能无文件路径）
                try:
                    success = registry.register_skill(skill, None)
                    if success:
                        registered_count += 1
                        logger.info("自动注册技能 %s 到 SkillRegistry", template_id)
                except Exception as e:
                    logger.warning("注册技能 %s 失败: %s", template_id, e)

                # s3: 同步写入 SkillService 持久化 (如果提供)
                if skill_service is not None:
                    try:
                        skill_service.register_auto_skill(
                            skill_id=template_id,
                            name=template.name,
                            description=template.description,
                            version="1.0.0",
                            config={
                                "tool_sequence": template.tool_sequence,
                                "context_template": template.context_template,
                                "success_rate": template.success_rate,
                                "parameter_hints": template.parameter_hints,
                            },
                        )
                    except Exception as e:
                        logger.warning("持久化技能 %s 到 SkillService 失败: %s", template_id, e)

        return registered_count

    def deactivate_template(self, template_id: str) -> bool:
        """停用技能模板"""
        with self._lock:
            template = self._templates.get(template_id)
            if template:
                template.is_active = False
                return True
            return False

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        with self._lock:
            return {
                "patterns": {pid: p.to_dict() for pid, p in self._patterns.items()},
                "templates": {tid: t.to_dict() for tid, t in self._templates.items()},
                "config": {
                    "min_pattern_occurrences": self._min_occurrences,
                    "min_success_rate": self._min_success_rate,
                    "similarity_threshold": self._similarity_threshold,
                },
            }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutoSkillBuilder":
        """从字典反序列化"""
        config = data.get("config", {})
        instance = cls(**config)

        for pid, pdata in data.get("patterns", {}).items():
            pattern = ToolPattern(
                pattern_id=pdata["pattern_id"],
                tool_sequence=pdata.get("tool_sequence", []),
                context_keywords=pdata.get("context_keywords", []),
                success_count=pdata.get("success_count", 0),
                failure_count=pdata.get("failure_count", 0),
                total_uses=pdata.get("total_uses", 0),
                avg_duration=pdata.get("avg_duration", 0.0),
            )
            instance._patterns[pid] = pattern

        for tid, tdata in data.get("templates", {}).items():
            template = SkillTemplate(
                template_id=tdata["template_id"],
                name=tdata.get("name", ""),
                description=tdata.get("description", ""),
                tool_sequence=tdata.get("tool_sequence", []),
                context_template=tdata.get("context_template", ""),
                success_rate=tdata.get("success_rate", 0.0),
                usage_count=tdata.get("usage_count", 0),
                is_active=tdata.get("is_active", True),
            )
            instance._templates[tid] = template

        return instance


# ────── 单例管理 ──────

_builder_instance: Optional[AutoSkillBuilder] = None
_instance_lock = threading.Lock()


def get_skill_builder(**kwargs) -> AutoSkillBuilder:
    """获取技能构建器单例"""
    global _builder_instance
    if _builder_instance is None:
        with _instance_lock:
            if _builder_instance is None:
                _builder_instance = AutoSkillBuilder(**kwargs)
    return _builder_instance


def reset_skill_builder():
    """重置技能构建器单例"""
    global _builder_instance
    with _instance_lock:
        _builder_instance = None
