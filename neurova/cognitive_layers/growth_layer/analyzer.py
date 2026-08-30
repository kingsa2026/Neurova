"""
成长分析器模块

实现认知成长分析和能力评估功能。
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class GrowthDimension(str, Enum):
    """成长维度"""

    COGNITIVE = "cognitive"  # 认知能力
    MEMORY = "memory"  # 记忆能力
    REASONING = "reasoning"  # 推理能力
    LEARNING = "learning"  # 学习能力
    ADAPTATION = "adaptation"  # 适应能力
    CREATIVITY = "creativity"  # 创造力
    SOCIAL = "social"  # 社交能力
    EMOTIONAL = "emotional"  # 情感能力


class GrowthStatus(str, Enum):
    """成长状态"""

    INITIAL = "initial"  # 初始状态
    GROWING = "growing"  # 成长中
    STAGNANT = "stagnant"  # 停滞
    DECLINING = "declining"  # 下降
    MATURE = "mature"  # 成熟
    EXPERT = "expert"  # 专家


@dataclass
class GrowthRecord:
    """成长记录"""

    dimension: GrowthDimension
    timestamp: datetime.datetime
    score: float  # 成长分数 (0-100)
    learning_rate: float = 0.0  # 学习率
    improvement: float = 0.0  # 改进幅度
    task_type: str = ""  # 任务类型
    task_id: str = ""  # 任务ID
    description: str = ""  # 描述
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "timestamp": self.timestamp.isoformat(),
            "score": self.score,
            "learning_rate": self.learning_rate,
            "improvement": self.improvement,
            "task_type": self.task_type,
            "task_id": self.task_id,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GrowthRecord":
        return cls(
            dimension=GrowthDimension(data["dimension"]),
            timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
            score=data["score"],
            learning_rate=data.get("learning_rate", 0.0),
            improvement=data.get("improvement", 0.0),
            task_type=data.get("task_type", ""),
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
        )


class GrowthAnalyzer:
    """
    成长分析器

    分析认知成长和能力评估，提供：
    - 学习记录
    - 能力评估
    - 成长状态分析
    - 改进领域识别
    - 学习路径建议
    """

    # 维度权重
    _DIMENSION_WEIGHTS = {
        GrowthDimension.COGNITIVE: 0.15,
        GrowthDimension.MEMORY: 0.15,
        GrowthDimension.REASONING: 0.15,
        GrowthDimension.LEARNING: 0.15,
        GrowthDimension.ADAPTATION: 0.10,
        GrowthDimension.CREATIVITY: 0.10,
        GrowthDimension.SOCIAL: 0.10,
        GrowthDimension.EMOTIONAL: 0.10,
    }

    # 成长状态阈值
    _STATUS_THRESHOLDS = {
        GrowthStatus.INITIAL: (0, 20),
        GrowthStatus.GROWING: (20, 50),
        GrowthStatus.STAGNANT: (50, 60),
        GrowthStatus.DECLINING: (0, 40),
        GrowthStatus.MATURE: (60, 80),
        GrowthStatus.EXPERT: (80, 100),
    }

    def __init__(self, agent_id: str = "default", workspace_path: Optional[str] = None):
        """初始化成长分析器

        Args:
            agent_id: Agent标识符
            workspace_path: 可选持久化目录（须为绝对路径）。传入后把记录与能力
                分数写入 <workspace_path>/growth.json 并在重启后恢复
                （agent_core 传 workspace/memory/growth 目录）。
        """
        self._agent_id = agent_id

        # 成长记录
        self._records: Dict[GrowthDimension, List[GrowthRecord]] = {dim: [] for dim in GrowthDimension}

        # 当前能力分数
        self._capability_scores: Dict[GrowthDimension, float] = {dim: 0.0 for dim in GrowthDimension}

        # 统计信息
        self._stats = {
            "total_records": 0,
            "total_learning_sessions": 0,
            "dimension_updates": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        # P2-A: 恢复原设计意图——成长数据落盘（此前签名与 agent_core 调用双重
        # 错配，分数只存内存）。I/O 被限制在 workspace_path 这个允许目录内。
        self._storage_file: Optional[Path] = None
        if workspace_path:
            self._storage_file = self._validated_storage_target(workspace_path)
            self._load_from_storage()

        logger.info(
            "GrowthAnalyzer 初始化完成 (agent_id=%s, storage=%s)",
            agent_id,
            self._storage_file,
        )

    @staticmethod
    def _validated_storage_target(workspace_path: str) -> Path:
        """在允许目录内解析持久化文件路径（防路径穿越）

        仅接受绝对路径目录；拒绝含父目录穿越段；目标文件强制固定为目录下的
        growth.json，并用 is_relative_to 显式校验包含关系。
        """
        import os as _os

        base = Path(str(workspace_path)).expanduser()
        if not base.is_absolute():
            raise ValueError(f"workspace_path 必须为绝对路径: {workspace_path}")
        if _os.pardir in base.parts:
            raise ValueError(f"workspace_path 非法（含父目录穿越段）: {workspace_path}")
        allowed_root = base.resolve()
        target = (allowed_root / "growth.json").resolve()
        if not target.is_relative_to(allowed_root):
            raise ValueError(f"持久化目标越出允许目录: {target}")
        return target

    def _save_to_storage(self) -> None:
        """把记录与能力分数写盘（JSON，写穿）"""
        if not self._storage_file:
            return
        try:
            import json

            payload = {
                "agent_id": self._agent_id,
                "capability_scores": {dim.value: score for dim, score in self._capability_scores.items()},
                "records": {
                    dim.value: [r.to_dict() for r in records[-500:]]
                    for dim, records in self._records.items()
                    if records
                },
            }
            self._storage_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self._storage_file.with_name(self._storage_file.name + ".tmp").resolve()
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_file, self._storage_file)
        except Exception as e:
            logger.debug("成长数据写盘失败: %s", e)

    def _load_from_storage(self) -> None:
        """从磁盘恢复记录与能力分数"""
        if not self._storage_file or not self._storage_file.exists():
            return
        try:
            import json

            payload = json.loads(self._storage_file.read_text(encoding="utf-8"))
            for dim_value, records_data in (payload.get("records") or {}).items():
                try:
                    dim = GrowthDimension(dim_value)
                except ValueError:
                    continue
                for rdata in records_data:
                    try:
                        self._records[dim].append(GrowthRecord.from_dict(rdata))
                    except Exception:
                        continue
            for dim_value, score in (payload.get("capability_scores") or {}).items():
                try:
                    self._capability_scores[GrowthDimension(dim_value)] = float(score)
                except (ValueError, KeyError):
                    continue
            self._stats["total_records"] = sum(len(v) for v in self._records.values())
            logger.info("成长数据已恢复: %s 条记录", self._stats["total_records"])
        except Exception as e:
            logger.debug("成长数据恢复失败: %s", e)

    def record_learning(
        self,
        dimension: GrowthDimension,
        score: float,
        learning_rate: float = 0.1,
        task_type: str = "",
        task_id: str = "",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GrowthRecord:
        """记录学习

        Args:
            dimension: 成长维度
            score: 学习分数 (0-100)
            learning_rate: 学习率
            task_type: 任务类型
            task_id: 任务ID
            description: 描述
            metadata: 元数据

        Returns:
            成长记录
        """
        with self._lock:
            try:
                # 计算学习分数
                calculated_score = self._calculate_learning_score(dimension, score, learning_rate)

                # 计算改进幅度
                current_score = self._capability_scores.get(dimension, 0.0)
                improvement = calculated_score - current_score

                # 创建记录
                record = GrowthRecord(
                    dimension=dimension,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    score=calculated_score,
                    learning_rate=learning_rate,
                    improvement=improvement,
                    task_type=task_type,
                    task_id=task_id,
                    description=description,
                    metadata=metadata or {},
                )

                # 添加到记录
                self._records[dimension].append(record)

                # 限制记录数量
                if len(self._records[dimension]) > 1000:
                    self._records[dimension] = self._records[dimension][-1000:]

                # 更新能力分数
                self._capability_scores[dimension] = calculated_score

                # 更新统计
                self._stats["total_records"] += 1
                self._stats["total_learning_sessions"] += 1
                self._stats["dimension_updates"] += 1

                # P2-A: 配置了持久化目录时写穿
                self._save_to_storage()

                logger.debug("记录学习: %s, 分数=%.2f, 改进=%s", dimension.value, calculated_score, improvement)

                return record

            except Exception as e:
                logger.error("记录学习失败: %s", e)
                # 返回空记录
                return GrowthRecord(
                    dimension=dimension,
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                    score=0.0,
                )

    def _calculate_learning_score(
        self,
        dimension: GrowthDimension,
        raw_score: float,
        learning_rate: float,
    ) -> float:
        """计算学习分数

        Args:
            dimension: 成长维度
            raw_score: 原始分数
            learning_rate: 学习率

        Returns:
            计算后的分数
        """
        try:
            # 获取当前分数
            current_score = self._capability_scores.get(dimension, 0.0)

            # 使用指数移动平均计算新分数
            # new_score = current_score * (1 - learning_rate) + raw_score * learning_rate
            new_score = current_score * (1 - learning_rate) + raw_score * learning_rate

            # 应用学习曲线（边际收益递减）
            if new_score > current_score:
                # 进步时，应用边际收益递减
                improvement = new_score - current_score
                diminishing_factor = max(0.5, 1.0 - current_score / 200)
                new_score = current_score + improvement * diminishing_factor

            # 限制在 0-100 范围
            return max(0.0, min(100.0, new_score))

        except Exception as e:
            logger.warning("计算学习分数失败: %s", e)
            return raw_score

    def get_capability(self, dimension: Optional[GrowthDimension] = None) -> Dict[str, float]:
        """获取能力分数

        Args:
            dimension: 指定维度，为None时返回所有维度

        Returns:
            能力分数字典
        """
        with self._lock:
            if dimension is not None:
                return {dimension.value: self._capability_scores.get(dimension, 0.0)}

            return {dim.value: score for dim, score in self._capability_scores.items()}

    def get_growth_status(self, dimension: Optional[GrowthDimension] = None) -> Dict[str, Any]:
        """获取成长状态

        Args:
            dimension: 指定维度，为None时返回整体状态

        Returns:
            成长状态信息
        """
        with self._lock:
            try:
                if dimension is not None:
                    # 单个维度状态
                    score = self._capability_scores.get(dimension, 0.0)
                    status = self._determine_status(score, dimension)

                    return {
                        "dimension": dimension.value,
                        "score": score,
                        "status": status.value,
                        "record_count": len(self._records.get(dimension, [])),
                    }

                # 整体状态
                overall_score = self._calculate_overall_score()
                overall_status = self._determine_status(overall_score)

                # 各维度状态
                dimension_statuses = {}
                for dim in GrowthDimension:
                    score = self._capability_scores.get(dim, 0.0)
                    status = self._determine_status(score, dim)
                    dimension_statuses[dim.value] = {
                        "score": score,
                        "status": status.value,
                    }

                return {
                    "overall_score": overall_score,
                    "overall_status": overall_status.value,
                    "dimension_statuses": dimension_statuses,
                    "total_records": self._stats["total_records"],
                }

            except Exception as e:
                logger.error("获取成长状态失败: %s", e)
                return {"error": str(e)}

    def _determine_status(
        self,
        score: float,
        dimension: Optional[GrowthDimension] = None,
    ) -> GrowthStatus:
        """确定成长状态

        Args:
            score: 分数
            dimension: 维度

        Returns:
            成长状态
        """
        # 检查是否下降（如果有历史记录）
        if dimension and self._records.get(dimension):
            recent_records = self._records[dimension][-10:]
            if len(recent_records) >= 3:
                recent_scores = [r.score for r in recent_records]
                if all(recent_scores[i] > recent_scores[i + 1] for i in range(len(recent_scores) - 1)):
                    return GrowthStatus.DECLINING

        # 根据分数确定状态
        if score < 20:
            return GrowthStatus.INITIAL
        elif score < 50:
            return GrowthStatus.GROWING
        elif score < 60:
            return GrowthStatus.STAGNANT
        elif score < 80:
            return GrowthStatus.MATURE
        else:
            return GrowthStatus.EXPERT

    def _calculate_overall_score(self) -> float:
        """计算整体分数

        Returns:
            整体分数
        """
        try:
            total_weight = 0.0
            weighted_sum = 0.0

            for dim, weight in self._DIMENSION_WEIGHTS.items():
                score = self._capability_scores.get(dim, 0.0)
                weighted_sum += score * weight
                total_weight += weight

            if total_weight > 0:
                return weighted_sum / total_weight
            return 0.0

        except Exception as e:
            logger.warning("计算整体分数失败: %s", e)
            return 0.0

    def get_growth_report(self, days: int = 30) -> Dict[str, Any]:
        """获取成长报告

        Args:
            days: 报告时间范围（天）

        Returns:
            成长报告
        """
        with self._lock:
            try:
                cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

                # 统计各维度的记录
                dimension_stats = {}
                for dim in GrowthDimension:
                    records = [r for r in self._records[dim] if r.timestamp >= cutoff_date]

                    if records:
                        scores = [r.score for r in records]
                        improvements = [r.improvement for r in records]

                        dimension_stats[dim.value] = {
                            "record_count": len(records),
                            "avg_score": sum(scores) / len(scores),
                            "max_score": max(scores),
                            "min_score": min(scores),
                            "total_improvement": sum(improvements),
                            "avg_improvement": sum(improvements) / len(improvements),
                        }
                    else:
                        dimension_stats[dim.value] = {
                            "record_count": 0,
                            "avg_score": 0.0,
                            "max_score": 0.0,
                            "min_score": 0.0,
                            "total_improvement": 0.0,
                            "avg_improvement": 0.0,
                        }

                # 计算整体趋势
                overall_trend = self._calculate_trend(days)

                return {
                    "report_period_days": days,
                    "overall_score": self._calculate_overall_score(),
                    "overall_trend": overall_trend,
                    "dimension_stats": dimension_stats,
                    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

            except Exception as e:
                logger.error("获取成长报告失败: %s", e)
                return {"error": str(e)}

    def _calculate_trend(self, days: int) -> str:
        """计算成长趋势

        Args:
            days: 时间范围

        Returns:
            趋势描述
        """
        try:
            cutoff_date = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

            # 收集所有维度的近期记录
            all_records = []
            for dim in GrowthDimension:
                records = [r for r in self._records[dim] if r.timestamp >= cutoff_date]
                all_records.extend(records)

            if len(all_records) < 2:
                return "insufficient_data"

            # 按时间排序
            all_records.sort(key=lambda r: r.timestamp)

            # 计算前后半段的平均分数
            mid_point = len(all_records) // 2
            first_half = all_records[:mid_point]
            second_half = all_records[mid_point:]

            first_avg = sum(r.score for r in first_half) / len(first_half) if first_half else 0
            second_avg = sum(r.score for r in second_half) / len(second_half) if second_half else 0

            if second_avg > first_avg * 1.05:
                return "improving"
            elif second_avg < first_avg * 0.95:
                return "declining"
            else:
                return "stable"

        except Exception as e:
            logger.warning("计算趋势失败: %s", e)
            return "unknown"

    def identify_improvement_areas(self, top_n: int = 3) -> List[Dict[str, Any]]:
        """识别改进领域

        Args:
            top_n: 返回前N个改进领域

        Returns:
            改进领域列表
        """
        with self._lock:
            try:
                # 按分数排序维度
                sorted_dims = sorted(
                    self._capability_scores.items(),
                    key=lambda x: x[1],
                )

                improvement_areas = []
                for dim, score in sorted_dims[:top_n]:
                    # 计算改进潜力
                    potential = 100 - score

                    # 获取最近记录
                    recent_records = self._records.get(dim, [])[-5:]
                    recent_improvements = [r.improvement for r in recent_records]
                    avg_improvement = sum(recent_improvements) / len(recent_improvements) if recent_improvements else 0

                    improvement_areas.append(
                        {
                            "dimension": dim.value,
                            "current_score": score,
                            "improvement_potential": potential,
                            "recent_avg_improvement": avg_improvement,
                            "priority": "high" if score < 30 else "medium" if score < 60 else "low",
                        }
                    )

                return improvement_areas

            except Exception as e:
                logger.error("识别改进领域失败: %s", e)
                return []

    def suggest_learning_path(self, target_score: float = 80.0) -> Dict[str, Any]:
        """建议学习路径

        Args:
            target_score: 目标分数

        Returns:
            学习路径建议
        """
        with self._lock:
            try:
                # 识别需要改进的维度
                improvement_areas = self.identify_improvement_areas(top_n=5)

                # 生成学习路径
                learning_path = []

                for area in improvement_areas:
                    current_score = area["current_score"]
                    area["improvement_potential"]

                    if current_score < target_score:
                        # 计算需要的学习步骤
                        gap = target_score - current_score
                        steps = max(1, int(gap / 10))  # 每10分一个步骤

                        learning_path.append(
                            {
                                "dimension": area["dimension"],
                                "current_score": current_score,
                                "target_score": target_score,
                                "gap": gap,
                                "estimated_steps": steps,
                                "priority": area["priority"],
                                "suggested_activities": self._get_suggested_activities(
                                    GrowthDimension(area["dimension"]),
                                    current_score,
                                ),
                            }
                        )

                # 按优先级排序
                priority_order = {"high": 0, "medium": 1, "low": 2}
                learning_path.sort(key=lambda x: priority_order.get(x["priority"], 3))

                return {
                    "target_score": target_score,
                    "learning_path": learning_path,
                    "estimated_total_steps": sum(p["estimated_steps"] for p in learning_path),
                    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

            except Exception as e:
                logger.error("建议学习路径失败: %s", e)
                return {"error": str(e)}

    def _get_suggested_activities(
        self,
        dimension: GrowthDimension,
        current_score: float,
    ) -> List[str]:
        """获取建议活动

        Args:
            dimension: 成长维度
            current_score: 当前分数

        Returns:
            建议活动列表
        """
        activities = {
            GrowthDimension.COGNITIVE: [
                "解决复杂问题",
                "学习新概念",
                "进行逻辑推理练习",
                "阅读学术文章",
            ],
            GrowthDimension.MEMORY: [
                "使用记忆技巧",
                "定期复习",
                "进行记忆训练",
                "建立知识关联",
            ],
            GrowthDimension.REASONING: [
                "进行批判性思考",
                "分析因果关系",
                "解决谜题",
                "参与辩论",
            ],
            GrowthDimension.LEARNING: [
                "学习新技能",
                "探索新领域",
                "实践主动学习",
                "寻求反馈",
            ],
            GrowthDimension.ADAPTATION: [
                "面对新环境",
                "处理变化",
                "学习灵活性",
                "接受挑战",
            ],
            GrowthDimension.CREATIVITY: [
                "进行头脑风暴",
                "尝试新方法",
                "艺术创作",
                "创新思考",
            ],
            GrowthDimension.SOCIAL: [
                "参与团队合作",
                "练习沟通技巧",
                "建立人际关系",
                "学习共情",
            ],
            GrowthDimension.EMOTIONAL: [
                "进行情感反思",
                "练习情绪管理",
                "学习情感表达",
                "培养情感智慧",
            ],
        }

        base_activities = activities.get(dimension, ["持续学习和实践"])

        # 根据当前分数调整建议
        if current_score < 30:
            return ["从基础开始"] + base_activities[:2]
        elif current_score < 60:
            return base_activities[:3]
        else:
            return base_activities + ["指导他人", "深入研究"]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                **self._stats,
                "agent_id": self._agent_id,
                "capability_scores": {dim.value: score for dim, score in self._capability_scores.items()},
                "overall_score": self._calculate_overall_score(),
            }

    def clear(self) -> None:
        """清空所有数据"""
        with self._lock:
            for dim in GrowthDimension:
                self._records[dim].clear()
                self._capability_scores[dim] = 0.0

            self._stats = {
                "total_records": 0,
                "total_learning_sessions": 0,
                "dimension_updates": 0,
            }

            logger.info("GrowthAnalyzer 数据已清空 (agent_id=%s)", self._agent_id)


# 全局实例管理
_growth_analyzer_instances: Dict[str, GrowthAnalyzer] = {}
_growth_analyzer_lock = threading.Lock()


def get_growth_analyzer(agent_id: str = "default") -> GrowthAnalyzer:
    """获取成长分析器单例

    Args:
        agent_id: Agent标识符

    Returns:
        成长分析器实例
    """
    global _growth_analyzer_instances

    with _growth_analyzer_lock:
        if agent_id not in _growth_analyzer_instances:
            _growth_analyzer_instances[agent_id] = GrowthAnalyzer(agent_id=agent_id)
        return _growth_analyzer_instances[agent_id]


def reset_growth_analyzer(agent_id: Optional[str] = None) -> None:
    """重置成长分析器单例

    Args:
        agent_id: Agent标识符，为None时重置所有
    """
    global _growth_analyzer_instances

    with _growth_analyzer_lock:
        if agent_id is None:
            _growth_analyzer_instances.clear()
        elif agent_id in _growth_analyzer_instances:
            _growth_analyzer_instances[agent_id].clear()
            del _growth_analyzer_instances[agent_id]


def reset_all_growth_analyzers() -> None:
    """重置所有成长分析器单例"""
    reset_growth_analyzer(None)
