"""
SkillsManager - 轻量级技能管理模块

基于Hermes自进化Agent理念，实现技能自动沉淀与自我修补
优先使用规则驱动，仅在必要时调用LLM
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """技能状态"""

    ACTIVE = "active"  # 活跃
    INACTIVE = "inactive"  # 不活跃
    DEPRECATED = "deprecated"  # 已废弃
    DRAFT = "draft"  # 草稿


@dataclass
class Skill:
    """技能数据模型"""

    skill_id: str
    name: str
    description: str
    trigger_patterns: List[str] = field(default_factory=list)
    action_template: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    examples: List[Dict[str, Any]] = field(default_factory=list)
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    version: str = "1.0.0"

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "trigger_patterns": self.trigger_patterns,
            "action_template": self.action_template,
            "parameters": self.parameters,
            "examples": self.examples,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "usage_count": self.usage_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "metadata": self.metadata,
            "tags": self.tags,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        """从字典创建"""
        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data["description"],
            trigger_patterns=data.get("trigger_patterns", []),
            action_template=data.get("action_template", ""),
            parameters=data.get("parameters", {}),
            examples=data.get("examples", []),
            status=SkillStatus(data.get("status", "active")),
            created_at=datetime.datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.datetime.fromisoformat(data["updated_at"]),
            usage_count=data.get("usage_count", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            version=data.get("version", "1.0.0"),
        )


@dataclass
class SkillMatchResult:
    """技能匹配结果"""

    skill: Skill
    confidence: float
    matched_pattern: str
    matched_text: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "skill": self.skill.to_dict(),
            "confidence": self.confidence,
            "matched_pattern": self.matched_pattern,
            "matched_text": self.matched_text,
            "metadata": self.metadata,
        }


class SkillsManager:
    """技能管理器

    管理技能的注册、匹配、使用和自我修补。
    """

    def __init__(
        self,
        storage: Any = None,
        llm_client: Any = None,
        max_skills: int = 1000,
        auto_generate: bool = True,
    ):
        """初始化技能管理器

        Args:
            storage: 存储引擎
            llm_client: LLM客户端
            max_skills: 最大技能数
            auto_generate: 是否自动生成技能
        """
        self._storage = storage
        self._llm_client = llm_client
        self._max_skills = max_skills
        self._auto_generate = auto_generate

        # 技能索引
        self._skills: Dict[str, Skill] = {}
        self._pattern_index: Dict[str, List[str]] = defaultdict(list)  # pattern -> skill_ids
        self._tag_index: Dict[str, List[str]] = defaultdict(list)  # tag -> skill_ids

        # 线程安全
        self._lock = threading.RLock()

        # 统计信息
        self._stats = {
            "total_skills": 0,
            "total_matches": 0,
            "total_usage": 0,
            "auto_generated": 0,
        }

        # 加载技能
        self._load_skills()

        logger.info("SkillsManager 初始化完成")

    def _load_skills(self) -> None:
        """加载技能"""
        if self._storage is None:
            return

        try:
            if hasattr(self._storage, "fetch_all"):
                rows = self._storage.fetch_all("SELECT * FROM skills")

                for row in rows:
                    skill = self._row_to_skill(row)
                    if skill:
                        self._skills[skill.skill_id] = skill
                        self._index_skill(skill)
                        self._stats["total_skills"] += 1

                logger.info("加载了 %s 个技能", self._stats['total_skills'])
        except Exception as e:
            logger.warning("加载技能失败: %s", e)

    def _row_to_skill(self, row: Any) -> Optional[Skill]:
        """将数据库行转换为技能对象

        Args:
            row: 数据库行

        Returns:
            技能对象
        """
        try:
            if isinstance(row, dict):
                return Skill.from_dict(row)
            elif isinstance(row, (tuple, list)):
                # 假设列顺序：skill_id, name, description, trigger_patterns, action_template, parameters, examples, status, created_at, updated_at, usage_count, success_count, failure_count, metadata, tags, version
                return Skill(
                    skill_id=row[0],
                    name=row[1],
                    description=row[2],
                    trigger_patterns=json.loads(row[3]) if row[3] else [],
                    action_template=row[4] or "",
                    parameters=json.loads(row[5]) if row[5] else {},
                    examples=json.loads(row[6]) if row[6] else [],
                    status=SkillStatus(row[7]) if row[7] else SkillStatus.ACTIVE,
                    created_at=(
                        datetime.datetime.fromisoformat(row[8])
                        if row[8]
                        else datetime.datetime.now(datetime.timezone.utc)
                    ),
                    updated_at=(
                        datetime.datetime.fromisoformat(row[9])
                        if row[9]
                        else datetime.datetime.now(datetime.timezone.utc)
                    ),
                    usage_count=row[10] or 0,
                    success_count=row[11] or 0,
                    failure_count=row[12] or 0,
                    metadata=json.loads(row[13]) if row[13] else {},
                    tags=json.loads(row[14]) if row[14] else [],
                    version=row[15] or "1.0.0",
                )
            return None
        except Exception as e:
            logger.warning("转换技能行失败: %s", e)
            return None

    def _index_skill(self, skill: Skill) -> None:
        """索引技能

        Args:
            skill: 技能对象
        """
        # 索引触发模式
        for pattern in skill.trigger_patterns:
            self._pattern_index[pattern].append(skill.skill_id)

        # 索引标签
        for tag in skill.tags:
            self._tag_index[tag].append(skill.skill_id)

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词

        Args:
            text: 输入文本

        Returns:
            关键词列表
        """
        # 简单的关键词提取
        # 移除标点符号和特殊字符
        cleaned = re.sub(r"[^\w\s]", " ", text.lower())

        # 分词
        words = cleaned.split()

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
            "一个",
            "上",
            "也",
            "很",
            "到",
            "说",
            "要",
            "去",
            "你",
            "会",
            "着",
            "没有",
            "看",
            "好",
            "自己",
            "这",
            "他",
            "她",
            "它",
            "们",
            "那",
            "些",
            "什么",
            "怎么",
            "如何",
            "为什么",
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "being",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "can",
            "shall",
            "to",
            "of",
            "in",
            "for",
            "on",
            "with",
            "at",
            "by",
            "from",
            "as",
            "into",
            "through",
            "during",
            "before",
            "after",
            "above",
            "below",
            "between",
            "out",
            "off",
            "over",
            "under",
            "again",
            "further",
            "then",
            "once",
            "here",
            "there",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "because",
            "but",
            "and",
            "or",
            "if",
            "while",
            "about",
            "against",
            "up",
            "down",
            "this",
            "that",
            "these",
            "those",
            "i",
            "me",
            "my",
            "myself",
            "we",
            "our",
            "ours",
            "ourselves",
            "you",
            "your",
            "yours",
            "yourself",
            "yourselves",
            "he",
            "him",
            "his",
            "himself",
            "she",
            "her",
            "hers",
            "herself",
            "it",
            "its",
            "itself",
            "they",
            "them",
            "their",
            "theirs",
            "themselves",
            "what",
            "which",
            "who",
            "whom",
            "when",
            "where",
            "why",
            "how",
            "any",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "can",
            "will",
            "just",
            "don",
            "should",
            "now",
        }

        keywords = [word for word in words if word not in stop_words and len(word) > 2]

        return keywords

    def _save_skill(self, skill: Skill) -> None:
        """保存技能到存储

        Args:
            skill: 技能对象
        """
        if self._storage is None:
            return

        try:
            if hasattr(self._storage, "execute"):
                self._storage.execute(
                    """
                    INSERT OR REPLACE INTO skills 
                    (skill_id, name, description, trigger_patterns, action_template, parameters, examples, status, created_at, updated_at, usage_count, success_count, failure_count, metadata, tags, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        skill.skill_id,
                        skill.name,
                        skill.description,
                        json.dumps(skill.trigger_patterns),
                        skill.action_template,
                        json.dumps(skill.parameters),
                        json.dumps(skill.examples),
                        skill.status.value,
                        skill.created_at.isoformat(),
                        skill.updated_at.isoformat(),
                        skill.usage_count,
                        skill.success_count,
                        skill.failure_count,
                        json.dumps(skill.metadata),
                        json.dumps(skill.tags),
                        skill.version,
                    ),
                )
        except Exception as e:
            logger.warning("保存技能失败: %s", e)

    def auto_generate_skill(
        self,
        task_description: str,
        solution: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Skill]:
        """自动生成技能

        Args:
            task_description: 任务描述
            solution: 解决方案
            metadata: 附加元数据

        Returns:
            生成的技能，如果失败返回None
        """
        if not self._auto_generate:
            return None

        try:
            # 生成技能名称
            name = self._generate_skill_name(task_description)

            # 生成触发模式
            trigger_patterns = self._generate_trigger_patterns(task_description)

            # 检查是否已存在类似技能
            similar_skill = self._find_similar_skill(task_description)
            if similar_skill:
                # 更新现有技能
                similar_skill.usage_count += 1
                similar_skill.updated_at = datetime.datetime.now(datetime.timezone.utc)
                self._save_skill(similar_skill)
                return similar_skill

            # 创建新技能
            skill = Skill(
                skill_id=f"skill_{uuid.uuid4().hex[:8]}",
                name=name,
                description=task_description,
                trigger_patterns=trigger_patterns,
                action_template=solution,
                metadata=metadata or {},
                tags=self._extract_keywords(task_description),
            )

            # 添加到索引
            with self._lock:
                self._skills[skill.skill_id] = skill
                self._index_skill(skill)
                self._stats["total_skills"] += 1
                self._stats["auto_generated"] += 1

            # 保存到存储
            self._save_skill(skill)

            logger.info("自动生成技能: %s - %s", skill.skill_id, name)
            return skill
        except Exception as e:
            logger.error("自动生成技能失败: %s", e)
            return None

    def _generate_skill_name(self, task_description: str) -> str:
        """生成技能名称

        Args:
            task_description: 任务描述

        Returns:
            技能名称
        """
        # 提取前20个字符作为名称
        name = task_description[:20].strip()
        if len(task_description) > 20:
            name += "..."
        return name

    def _generate_trigger_patterns(self, task_description: str) -> List[str]:
        """生成触发模式

        Args:
            task_description: 任务描述

        Returns:
            触发模式列表
        """
        patterns = []

        # 提取关键词作为触发模式
        keywords = self._extract_keywords(task_description)

        # 添加关键词模式
        for keyword in keywords[:5]:  # 最多5个关键词
            patterns.append(keyword)

        # 添加短语模式
        if len(task_description) > 10:
            # 取前10个字符作为短语模式
            phrase = task_description[:10].strip()
            patterns.append(phrase)

        return patterns

    def _find_similar_skill(self, task_description: str) -> Optional[Skill]:
        """查找类似技能

        Args:
            task_description: 任务描述

        Returns:
            类似技能，如果没找到返回None
        """
        # 提取关键词
        keywords = set(self._extract_keywords(task_description))

        if not keywords:
            return None

        # 计算相似度
        best_match = None
        best_similarity = 0.0

        for skill in self._skills.values():
            if skill.status != SkillStatus.ACTIVE:
                continue

            # 提取技能关键词
            skill_keywords = set(self._extract_keywords(skill.description))

            if not skill_keywords:
                continue

            # 计算Jaccard相似度
            intersection = len(keywords & skill_keywords)
            union = len(keywords | skill_keywords)

            if union > 0:
                similarity = intersection / union

                if similarity > best_similarity and similarity > 0.3:  # 阈值
                    best_similarity = similarity
                    best_match = skill

        return best_match

    def match_skills(
        self,
        text: str,
        limit: int = 5,
        min_confidence: float = 0.3,
    ) -> List[SkillMatchResult]:
        """匹配技能

        Args:
            text: 输入文本
            limit: 返回数量限制
            min_confidence: 最小置信度

        Returns:
            匹配结果列表
        """
        with self._lock:
            results = []

            # 提取关键词
            keywords = set(self._extract_keywords(text))

            for skill in self._skills.values():
                if skill.status != SkillStatus.ACTIVE:
                    continue

                # 检查触发模式
                for pattern in skill.trigger_patterns:
                    # 正则表达式匹配
                    try:
                        if re.search(pattern, text, re.IGNORECASE):
                            # 计算置信度
                            confidence = self._calculate_match_confidence(text, pattern, keywords, skill)

                            if confidence >= min_confidence:
                                results.append(
                                    SkillMatchResult(
                                        skill=skill,
                                        confidence=confidence,
                                        matched_pattern=pattern,
                                        matched_text=text,
                                    )
                                )
                    except re.error:
                        # 如果正则表达式无效，使用简单字符串匹配
                        if pattern.lower() in text.lower():
                            confidence = self._calculate_match_confidence(text, pattern, keywords, skill)

                            if confidence >= min_confidence:
                                results.append(
                                    SkillMatchResult(
                                        skill=skill,
                                        confidence=confidence,
                                        matched_pattern=pattern,
                                        matched_text=text,
                                    )
                                )

            # 按置信度排序
            results.sort(key=lambda x: x.confidence, reverse=True)

            # 更新统计
            self._stats["total_matches"] += len(results)

            return results[:limit]

    def _calculate_match_confidence(
        self,
        text: str,
        pattern: str,
        keywords: Set[str],
        skill: Skill,
    ) -> float:
        """计算匹配置信度

        Args:
            text: 输入文本
            pattern: 匹配模式
            keywords: 关键词集合
            skill: 技能对象

        Returns:
            置信度 (0-1)
        """
        # 基础置信度
        base_confidence = 0.5

        # 关键词匹配加分
        skill_keywords = set(self._extract_keywords(skill.description))
        if skill_keywords:
            keyword_overlap = len(keywords & skill_keywords)
            keyword_total = len(keywords | skill_keywords)
            if keyword_total > 0:
                keyword_score = keyword_overlap / keyword_total
                base_confidence += keyword_score * 0.3

        # 使用历史加分
        if skill.usage_count > 0:
            usage_bonus = min(0.2, skill.usage_count * 0.01)
            base_confidence += usage_bonus

        # 成功率加分
        if skill.success_rate > 0:
            success_bonus = skill.success_rate * 0.1
            base_confidence += success_bonus

        return min(1.0, base_confidence)

    def self_patch(
        self,
        skill_id: str,
        error_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Skill]:
        """自我修补技能

        Args:
            skill_id: 技能ID
            error_description: 错误描述
            context: 上下文信息

        Returns:
            修补后的技能，如果失败返回None
        """
        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                logger.warning("技能不存在: %s", skill_id)
                return None

            try:
                # 生成修复步骤
                fix_step = self._generate_fix_step(skill, error_description, context)

                if fix_step:
                    # 更新技能
                    skill.action_template += f"\n\n修复步骤:\n{fix_step}"
                    skill.updated_at = datetime.datetime.now(datetime.timezone.utc)
                    skill.metadata["last_patch"] = {
                        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "error": error_description,
                        "fix": fix_step,
                    }

                    # 保存到存储
                    self._save_skill(skill)

                    logger.info("技能已修补: %s", skill_id)
                    return skill
                else:
                    logger.warning("无法生成修复步骤: %s", skill_id)
                    return None
            except Exception as e:
                logger.error("自我修补失败: %s", e)
                return None

    def _generate_fix_step(
        self,
        skill: Skill,
        error_description: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """生成修复步骤

        Args:
            skill: 技能对象
            error_description: 错误描述
            context: 上下文信息

        Returns:
            修复步骤，如果失败返回None
        """
        # 如果有LLM客户端，使用LLM生成修复步骤
        if self._llm_client:
            try:
                prompt = f"""
                技能名称: {skill.name}
                技能描述: {skill.description}
                错误描述: {error_description}
                上下文: {json.dumps(context or {}, ensure_ascii=False)}
                
                请分析错误原因并提供修复步骤。
                """

                response = self._llm_client.generate(prompt)
                return response
            except Exception as e:
                logger.warning("使用LLM生成修复步骤失败: %s", e)

        # 简单的规则生成
        return f"检查错误: {error_description}\n参考技能描述: {skill.description}"

    def use_skill(
        self,
        skill_id: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """使用技能

        Args:
            skill_id: 技能ID
            success: 是否成功
            metadata: 附加元数据
        """
        with self._lock:
            skill = self._skills.get(skill_id)
            if not skill:
                return

            # 更新统计
            skill.usage_count += 1
            if success:
                skill.success_count += 1
            else:
                skill.failure_count += 1

            skill.updated_at = datetime.datetime.now(datetime.timezone.utc)

            if metadata:
                skill.metadata.update(metadata)

            # 保存到存储
            self._save_skill(skill)

            # 更新统计
            self._stats["total_usage"] += 1

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """获取技能

        Args:
            skill_id: 技能ID

        Returns:
            技能对象
        """
        with self._lock:
            return self._skills.get(skill_id)

    def get_all_skills(
        self,
        status: Optional[SkillStatus] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Skill]:
        """获取所有技能

        Args:
            status: 状态过滤
            tags: 标签过滤

        Returns:
            技能列表
        """
        with self._lock:
            skills = list(self._skills.values())

            if status:
                skills = [s for s in skills if s.status == status]

            if tags:
                tag_set = set(tags)
                skills = [s for s in skills if tag_set.intersection(s.tags)]

            return skills

    def get_skill_stats(self) -> Dict[str, Any]:
        """获取技能统计

        Returns:
            统计信息字典
        """
        with self._lock:
            active_skills = [s for s in self._skills.values() if s.status == SkillStatus.ACTIVE]

            return {
                **self._stats,
                "active_skills": len(active_skills),
                "inactive_skills": len([s for s in self._skills.values() if s.status == SkillStatus.INACTIVE]),
                "deprecated_skills": len([s for s in self._skills.values() if s.status == SkillStatus.DEPRECATED]),
                "avg_success_rate": (
                    sum(s.success_rate for s in active_skills) / len(active_skills) if active_skills else 0.0
                ),
            }

    def clear_cache(self) -> None:
        """清空缓存"""
        # 目前没有需要清空的缓存


# 全局实例管理
_skills_manager_instances: Dict[str, SkillsManager] = {}
_skills_manager_lock = threading.Lock()


def get_skills_manager(
    storage: Any = None,
    llm_client: Any = None,
    instance_id: str = "default",
) -> SkillsManager:
    """获取技能管理器单例

    Args:
        storage: 存储引擎
        llm_client: LLM客户端
        instance_id: 实例ID

    Returns:
        技能管理器实例
    """
    global _skills_manager_instances

    with _skills_manager_lock:
        if instance_id not in _skills_manager_instances:
            _skills_manager_instances[instance_id] = SkillsManager(
                storage=storage,
                llm_client=llm_client,
            )
        return _skills_manager_instances[instance_id]


def reset_skills_manager(instance_id: Optional[str] = None) -> None:
    """重置技能管理器单例

    Args:
        instance_id: 实例ID，为None时重置所有
    """
    global _skills_manager_instances

    with _skills_manager_lock:
        if instance_id is None:
            _skills_manager_instances.clear()
        elif instance_id in _skills_manager_instances:
            del _skills_manager_instances[instance_id]


def reset_all_skills_manager() -> None:
    """重置所有技能管理器单例"""
    reset_skills_manager(None)
