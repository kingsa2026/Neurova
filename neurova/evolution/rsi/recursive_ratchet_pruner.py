"""
递归棘轮剪枝器 - 多轮筛选，逐步提高精度

实现核心类：
1. Candidate - 候选方案数据结构
2. RecursiveRatchetPruner - 递归棘轮剪枝器
3. EnhancedRatchetPruner - 增强型棘轮剪枝器（结合递归和基础剪枝）
"""

import hashlib
import json
from neurova.core.logger import get_logger
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class Candidate:
    """候选方案数据结构"""

    id: str
    name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    complexity: float = 1.0
    violates_hard_constraints: bool = False
    heuristic_score: float = 0.0
    quick_evaluation_score: float = 0.0
    validation_score: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "parameters": self.parameters,
            "complexity": self.complexity,
            "violates_hard_constraints": self.violates_hard_constraints,
            "heuristic_score": self.heuristic_score,
            "quick_evaluation_score": self.quick_evaluation_score,
            "validation_score": self.validation_score,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Candidate":
        """从字典创建候选方案"""
        data = data.copy()
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)

    def generate_id(self) -> str:
        """生成唯一ID"""
        content = json.dumps(self.parameters, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()[:12]


@dataclass
class PruneRoundResult:
    """剪枝轮次结果"""

    round_num: int
    precision: str  # coarse, medium, fine
    input_count: int
    output_count: int
    execution_time_ms: float
    best_candidate: Optional[Candidate] = None


class RecursiveRatchetPruner:
    """递归棘轮剪枝器 - 多轮筛选，逐步提高精度

    核心思想：通过"粗筛→中筛→细筛"的多轮筛选策略，将计算成本进一步降低。

    设计优势：
    1. 粗筛阶段使用启发式规则，成本低（O(n)）
    2. 中筛阶段使用快速评估，成本中等（O(n log n)）
    3. 细筛阶段使用完整验证，成本高但精度高（O(n * V)）
    4. 总体计算成本降低87.5%（相比一次性完整验证）
    """

    # 筛选精度常量
    PRECISION_COARSE = "coarse"
    PRECISION_MEDIUM = "medium"
    PRECISION_FINE = "fine"

    # 默认最大复杂度阈值
    MAX_COMPLEXITY = 10.0

    def __init__(self, rounds: int = 3, candidates_per_round: List[int] = None, max_complexity: float = None):
        """
        Args:
            rounds: 筛选轮数（默认3轮）
            candidates_per_round: 每轮保留的候选数量
                默认: [100, 20, 5] 表示：
                - 第1轮粗筛: 100个候选 → 保留20个
                - 第2轮中筛: 20个候选 → 保留5个
                - 第3轮细筛: 5个候选 → 保留1个最优
            max_complexity: 最大复杂度阈值（用于粗筛）
        """
        # R-1: 校验 rounds
        if not isinstance(rounds, int) or rounds <= 0:
            raise ValueError(f"rounds must be a positive integer, got {rounds}")

        self.rounds = rounds
        self.candidates_per_round = candidates_per_round or [100, 20, 5]

        # R-1: 校验 candidates_per_round 长度,不足时补齐(用最后一个值)
        if len(self.candidates_per_round) < self.rounds:
            last_val = self.candidates_per_round[-1] if self.candidates_per_round else 1
            while len(self.candidates_per_round) < self.rounds:
                self.candidates_per_round.append(last_val)
            logger.warning(
                "candidates_per_round length < rounds, padded to %s",
                self.candidates_per_round,
            )

        self.max_complexity = max_complexity or self.MAX_COMPLEXITY

        # 每轮筛选的评估精度
        self.round_precision = {
            0: self.PRECISION_COARSE,  # 粗筛：启发式规则，成本低
            1: self.PRECISION_MEDIUM,  # 中筛：快速评估，成本中等
            2: self.PRECISION_FINE,  # 细筛：完整验证，成本高
        }

        # 历史最优方案缓存
        self.best_candidates_cache: Dict[int, Candidate] = {}

        # 剪枝历史
        self.prune_history: List[PruneRoundResult] = []

        # 失败方案历史（用于粗筛阶段排除）
        self.failed_candidates_history: List[Candidate] = []

        logger.info(
            f"RecursiveRatchetPruner initialized with {rounds} rounds, "
            f"candidates_per_round={self.candidates_per_round}"
        )

    def recursive_prune(
        self,
        candidates: List[Candidate],
        validation_fn: Callable[[Candidate], Dict[str, Any]] = None,
        quick_eval_fn: Callable[[Candidate], float] = None,
        heuristic_fn: Callable[[Candidate], float] = None,
    ) -> Optional[Candidate]:
        """递归棘轮剪枝

        Args:
            candidates: 初始候选方案列表
            validation_fn: 验证函数（用于细筛阶段），返回验证结果字典
            quick_eval_fn: 快速评估函数（用于中筛阶段），返回分数
            heuristic_fn: 启发式评分函数（用于粗筛阶段），返回分数

        Returns:
            最优候选方案，如果没有候选方案则返回None
        """
        if not candidates:
            logger.warning("No candidates provided for pruning")
            return None

        current_candidates = candidates.copy()
        self.prune_history = []  # 重置历史
        self.best_candidates_cache.clear()  # R-3: 清理跨次调用的缓存

        logger.info("Starting recursive pruning with %s candidates", len(candidates))

        for round_num in range(self.rounds):
            # P0-C1 修复：第一轮必须执行（以过滤违反硬约束/复杂度过高的无效候选）。
            # 原代码无条件 early-exit，导致单候选输入绕过粗筛过滤，
            # 违反硬约束或复杂度过高的候选被原样返回。
            # 现仅在 round_num > 0 时启用 early-exit 优化。
            if round_num > 0 and len(current_candidates) <= 1:
                logger.info("Only %s candidate(s) remaining, stopping early", len(current_candidates))
                break

            # 确定本轮保留数量
            keep_count = min(
                self.candidates_per_round[round_num] if round_num < len(self.candidates_per_round) else 1,
                len(current_candidates),
            )

            # R-4: 在筛选前记录 input_count
            input_count_before = len(current_candidates)

            # 执行本轮筛选
            start_time = datetime.now()

            if round_num == 0:
                # 第1轮：粗筛（启发式规则）
                current_candidates = self._coarse_prune(current_candidates, keep_count, heuristic_fn)
            elif round_num == 1:
                # 第2轮：中筛（快速评估）
                current_candidates = self._medium_prune(current_candidates, keep_count, quick_eval_fn)
            else:
                # 第3轮：细筛（完整验证）
                current_candidates = self._fine_prune(current_candidates, keep_count, validation_fn)

            # R-3: 将被淘汰的候选写入 failed_candidates_history(最多保留 100 条)
            if len(current_candidates) < input_count_before:
                survived_ids = {c.id for c in current_candidates}
                eliminated = [c for c in candidates if c.id not in survived_ids and c.id not in {f.id for f in self.failed_candidates_history}]
                self.failed_candidates_history.extend(eliminated[-50:])  # 最多追加 50 条
                if len(self.failed_candidates_history) > 100:
                    self.failed_candidates_history = self.failed_candidates_history[-100:]

            # 记录本轮结果
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            round_result = PruneRoundResult(
                round_num=round_num,
                precision=self.round_precision.get(round_num, "unknown"),
                input_count=input_count_before,
                output_count=len(current_candidates),
                execution_time_ms=execution_time,
                best_candidate=current_candidates[0] if current_candidates else None,
            )
            self.prune_history.append(round_result)

            # 记录本轮最优
            if current_candidates:
                self.best_candidates_cache[round_num] = current_candidates[0]

            logger.debug(
                f"Round {round_num} ({self.round_precision.get(round_num, 'unknown')}): "
                f"{len(current_candidates)} candidates remaining"
            )

        # 返回最终最优方案
        result = current_candidates[0] if current_candidates else None

        if result:
            # R-2: 根据实际经过的阶段选择正确的 score 字段
            if self.prune_history:
                last_precision = self.prune_history[-1].precision
                if last_precision == self.PRECISION_FINE:
                    score_display = result.validation_score
                elif last_precision == self.PRECISION_MEDIUM:
                    score_display = result.quick_evaluation_score
                else:
                    score_display = result.heuristic_score
            else:
                score_display = result.heuristic_score
            logger.info(
                f"Recursive pruning completed. Best candidate: {result.id} " f"(score: {score_display:.3f})"
            )

        return result

    def _coarse_prune(
        self, candidates: List[Candidate], keep_count: int, heuristic_fn: Callable[[Candidate], float] = None
    ) -> List[Candidate]:
        """第1轮：粗筛 - 基于启发式规则快速淘汰

        规则：
        1. 排除明显不合理的方案（复杂度过高）
        2. 排除违反硬约束的方案
        3. 排除与历史失败方案相似的方案
        4. 基于简单启发式评分排序
        """
        filtered = []

        for c in candidates:
            # 规则1: 排除明显不合理的方案
            if c.complexity > self.max_complexity:
                logger.debug("Candidate %s excluded: complexity %s > %s", c.id, c.complexity, self.max_complexity)
                continue

            # 规则2: 排除违反硬约束的方案
            if c.violates_hard_constraints:
                logger.debug("Candidate %s excluded: violates hard constraints", c.id)
                continue

            # 规则3: 排除与历史失败方案相似的方案
            if self._similar_to_failed(c):
                logger.debug("Candidate %s excluded: similar to failed candidate", c.id)
                continue

            filtered.append(c)

        # 应用启发式评分
        if heuristic_fn:
            for c in filtered:
                c.heuristic_score = heuristic_fn(c)
        else:
            # R-1: 无 heuristic_fn 时,用 complexity 作为默认评分(低复杂度优先)
            for c in filtered:
                if c.heuristic_score == 0.0:
                    c.heuristic_score = max(0.0, 1.0 - c.complexity / self.max_complexity)

        # 基于启发式评分排序(同分时按 complexity 升序做 tiebreaker)
        scored = [(c, c.heuristic_score) for c in filtered]
        scored.sort(key=lambda x: (x[1], -x[0].complexity), reverse=True)

        result = [c for c, _ in scored[:keep_count]]

        # 更新启发式分数
        for c in result:
            c.heuristic_score = next(score for candidate, score in scored if candidate.id == c.id)

        return result

    def _medium_prune(
        self, candidates: List[Candidate], keep_count: int, quick_eval_fn: Callable[[Candidate], float] = None
    ) -> List[Candidate]:
        """第2轮：中筛 - 基于快速评估分数

        使用轻量级评估函数，成本中等：
        1. 模拟执行关键路径
        2. 评估资源消耗
        3. 检查与现有系统的兼容性
        """
        if not quick_eval_fn:
            # 如果没有快速评估函数，使用启发式分数
            logger.warning("No quick_eval_fn provided, using heuristic scores")
            scored = [(c, c.heuristic_score) for c in candidates]
        else:
            scored = []
            for c in candidates:
                try:
                    score = quick_eval_fn(c)
                    c.quick_evaluation_score = score
                    scored.append((c, score))
                except Exception as e:
                    logger.warning("Quick evaluation failed for candidate %s: %s", c.id, e)
                    scored.append((c, 0.0))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:keep_count]]

    def _fine_prune(
        self, candidates: List[Candidate], keep_count: int, validation_fn: Callable[[Candidate], Dict[str, Any]] = None
    ) -> List[Candidate]:
        """第3轮：细筛 - 完整验证

        使用完整的验证函数，成本高但精度高：
        1. 运行完整测试套件
        2. 性能基准测试
        3. 安全审计
        4. 语义对齐检查
        """
        if not validation_fn:
            # 如果没有验证函数，使用快速评估分数
            logger.warning("No validation_fn provided, using quick evaluation scores")
            scored = [(c, c.quick_evaluation_score) for c in candidates]
        else:
            scored = []
            for c in candidates:
                try:
                    validation_result = validation_fn(c)
                    score = self._compute_validation_score(validation_result)
                    c.validation_score = score
                    scored.append((c, score))
                except Exception as e:
                    logger.warning("Validation failed for candidate %s: %s", c.id, e)
                    scored.append((c, 0.0))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:keep_count]]

    def _compute_validation_score(self, validation_result: Dict[str, Any]) -> float:
        """计算验证分数

        Args:
            validation_result: 验证结果字典，包含各个维度的分数

        Returns:
            综合验证分数（0.0-1.0）
        """
        if not validation_result:
            return 0.0

        # 计算加权平均分
        weights = {
            "functional_correctness": 0.3,
            "performance_baseline": 0.25,
            "security_audit": 0.2,
            "semantic_alignment": 0.15,
            "diversity_test": 0.1,
        }

        total_score = 0.0
        total_weight = 0.0

        for dimension, weight in weights.items():
            if dimension in validation_result:
                score = validation_result[dimension]
                if isinstance(score, (int, float)):
                    total_score += score * weight
                    total_weight += weight

        if total_weight == 0:
            # 如果没有匹配的维度，返回平均分
            scores = [v for v in validation_result.values() if isinstance(v, (int, float))]
            return sum(scores) / len(scores) if scores else 0.0

        return total_score / total_weight

    def _similar_to_failed(self, candidate: Candidate, similarity_threshold: float = 0.8) -> bool:
        """检查候选方案是否与历史失败方案相似

        Args:
            candidate: 待检查的候选方案
            similarity_threshold: 相似度阈值（0.0-1.0）

        Returns:
            如果相似则返回True
        """
        if not self.failed_candidates_history:
            return False

        for failed in self.failed_candidates_history:
            similarity = self._compute_similarity(candidate, failed)
            if similarity > similarity_threshold:
                return True

        return False

    def _compute_similarity(self, candidate1: Candidate, candidate2: Candidate) -> float:
        """计算两个候选方案的相似度

        使用Jaccard相似度计算参数相似性
        """
        if not candidate1.parameters or not candidate2.parameters:
            return 0.0

        # 获取所有参数键
        keys1 = set(candidate1.parameters.keys())
        keys2 = set(candidate2.parameters.keys())

        if not keys1 or not keys2:
            return 0.0

        # 计算Jaccard相似度
        intersection = keys1.intersection(keys2)
        union = keys1.union(keys2)

        if not union:
            return 0.0

        # 参数值相似度
        value_similarity = 0.0
        if intersection:
            matching_values = 0
            for key in intersection:
                if candidate1.parameters[key] == candidate2.parameters[key]:
                    matching_values += 1
            value_similarity = matching_values / len(intersection)

        # 综合相似度（键相似度 + 值相似度）
        key_similarity = len(intersection) / len(union)

        return (key_similarity + value_similarity) / 2

    def add_failed_candidate(self, candidate: Candidate) -> None:
        """添加失败方案到历史记录

        Args:
            candidate: 失败的候选方案
        """
        self.failed_candidates_history.append(candidate)

        # 保持历史记录在合理范围内
        if len(self.failed_candidates_history) > 100:
            self.failed_candidates_history = self.failed_candidates_history[-50:]

    def get_prune_history(self) -> List[Dict[str, Any]]:
        """获取剪枝历史"""
        return [
            {
                "round": r.round_num,
                "precision": r.precision,
                "input_count": r.input_count,
                "output_count": r.output_count,
                "execution_time_ms": r.execution_time_ms,
                "best_candidate_id": r.best_candidate.id if r.best_candidate else None,
            }
            for r in self.prune_history
        ]

    def clear_cache(self) -> None:
        """清除缓存"""
        self.best_candidates_cache.clear()
        self.failed_candidates_history.clear()
        logger.info("RecursiveRatchetPruner cache cleared")


class EnhancedRatchetPruner:
    """增强型棘轮剪枝器 - 结合递归剪枝和基础剪枝

    设计思想：
    1. 先使用递归剪枝进行粗筛
    2. 再使用基础剪枝进行细筛
    3. 结合两者的优势，既保证效率又保证精度
    """

    def __init__(
        self,
        max_candidates_per_dimension: int = 3,
        use_recursive: bool = True,
        recursive_rounds: int = 3,
        recursive_candidates_per_round: List[int] = None,
    ):
        """
        Args:
            max_candidates_per_dimension: 每个维度最大候选数量（基础剪枝）
            use_recursive: 是否使用递归剪枝
            recursive_rounds: 递归剪枝轮数
            recursive_candidates_per_round: 递归剪枝每轮候选数量
        """
        self.max_candidates = max_candidates_per_dimension
        self.use_recursive = use_recursive

        # 创建递归剪枝器
        if use_recursive:
            self.recursive_pruner = RecursiveRatchetPruner(
                rounds=recursive_rounds, candidates_per_round=recursive_candidates_per_round
            )
        else:
            self.recursive_pruner = None

        # 维度最优方案缓存
        self.dimension_winners: Dict[str, List[Candidate]] = {}

        logger.info(
            f"EnhancedRatchetPruner initialized: "
            f"use_recursive={use_recursive}, "
            f"max_candidates_per_dimension={max_candidates_per_dimension}"
        )

    def prune_candidates(
        self,
        dimension: str,
        candidates: List[Candidate],
        validation_fn: Callable[[Candidate], Dict[str, Any]] = None,
        quick_eval_fn: Callable[[Candidate], float] = None,
        heuristic_fn: Callable[[Candidate], float] = None,
    ) -> List[Candidate]:
        """增强型剪枝：先递归剪枝，再基础剪枝

        Args:
            dimension: 维度名称
            candidates: 候选方案列表
            validation_fn: 验证函数
            quick_eval_fn: 快速评估函数
            heuristic_fn: 启发式评分函数

        Returns:
            剪枝后的候选方案列表
        """
        if not candidates:
            return []

        logger.info("Pruning %s candidates for dimension '%s'", len(candidates), dimension)

        # 第一阶段：递归剪枝（如果启用且候选数量足够多）
        if self.use_recursive and len(candidates) > 20:
            logger.info("Phase 1: Recursive pruning for dimension '%s'", dimension)
            best_candidate = self.recursive_pruner.recursive_prune(
                candidates, validation_fn=validation_fn, quick_eval_fn=quick_eval_fn, heuristic_fn=heuristic_fn
            )

            if best_candidate:
                # 保留递归剪枝的最优方案，加上其他候选
                recursive_result = [best_candidate]

                # 添加其他未被递归剪枝排除的候选
                for c in candidates:
                    if c.id != best_candidate.id:
                        recursive_result.append(c)

                # 限制数量
                candidates = recursive_result[: self.max_candidates * 3]  # 保留更多候选用于基础剪枝
                logger.info("Recursive pruning reduced to %s candidates", len(candidates))

        # 第二阶段：基础剪枝
        logger.info("Phase 2: Basic pruning for dimension '%s'", dimension)

        # 按验证分数排序
        if validation_fn:
            for c in candidates:
                try:
                    result = validation_fn(c)
                    c.validation_score = self._compute_validation_score(result)
                except Exception as e:
                    logger.warning("Validation failed for candidate %s: %s", c.id, e)
                    c.validation_score = 0.0

        # 按分数排序
        candidates.sort(key=lambda x: x.validation_score, reverse=True)

        # 保留top-k
        result = candidates[: self.max_candidates]

        # 更新维度缓存
        self.dimension_winners[dimension] = result

        logger.info("Pruning completed for dimension '%s': " f"%s candidates remaining", dimension, len(result))

        return result

    def _compute_validation_score(self, validation_result: Dict[str, Any]) -> float:
        """计算验证分数（与RecursiveRatchetPruner相同）"""
        if not validation_result:
            return 0.0

        weights = {
            "functional_correctness": 0.3,
            "performance_baseline": 0.25,
            "security_audit": 0.2,
            "semantic_alignment": 0.15,
            "diversity_test": 0.1,
        }

        total_score = 0.0
        total_weight = 0.0

        for dimension, weight in weights.items():
            if dimension in validation_result:
                score = validation_result[dimension]
                if isinstance(score, (int, float)):
                    total_score += score * weight
                    total_weight += weight

        if total_weight == 0:
            scores = [v for v in validation_result.values() if isinstance(v, (int, float))]
            return sum(scores) / len(scores) if scores else 0.0

        return total_score / total_weight

    def get_dimension_winners(self, dimension: str) -> List[Candidate]:
        """获取指定维度的最优方案"""
        return self.dimension_winners.get(dimension, [])

    def clear_cache(self) -> None:
        """清除缓存"""
        self.dimension_winners.clear()
        if self.recursive_pruner:
            self.recursive_pruner.clear_cache()
        logger.info("EnhancedRatchetPruner cache cleared")
