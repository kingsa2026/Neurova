"""
ToolGeneticEngine v1.0.0 — 工具基因编程引擎

Phase 2 P2-4: 使用进化算法自动发现和优化工具组合。

核心概念:
  - ToolGenotype: 工具基因型（工具序列 + 成功率 + 适应度）
  - Crossover: 交叉操作 → 合并两个高频协作工具
  - Mutation:  变异操作 → 参数扩展、序列重排、降级嫁接
  - Selection: 精英选择 → 保留高适应度个体
  - Validation: 沙箱验证 → 新工具 N 次验证后通过率 > 阈值才注册
"""

from neurova.core.logger import get_logger
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class ToolGenotype:
    """工具基因型：编码工具序列为可变异/交叉的基因。"""

    tool_sequence: List[str]
    success_rate: float = 0.5
    execution_time_ms: float = 0.0
    reuse_count: int = 0
    generation: int = 1

    @property
    def tools(self) -> List[str]:
        """工具序列的别名，方便访问。"""
        return self.tool_sequence

    @property
    def fitness(self) -> float:
        """适应度计算：综合成功率、执行时间和复用次数。"""
        # 基础适应度基于成功率
        base_fitness = self.success_rate

        # 时间惩罚：执行时间越长，适应度越低（归一化到 0-1 范围）
        # 假设 1000ms 为基准，超过 1000ms 会降低适应度
        time_penalty = max(0.0, 1.0 - (self.execution_time_ms / 1000.0))

        # 复用奖励：复用次数越多，适应度越高（对数缩放）
        reuse_bonus = math.log1p(self.reuse_count) * 0.1

        # 综合适应度
        fitness = base_fitness * time_penalty + reuse_bonus

        # 确保在 0-1 范围内
        return max(0.0, min(1.0, fitness))

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典格式。"""
        return {
            "tools": self.tool_sequence,
            "success_rate": self.success_rate,
            "execution_time_ms": self.execution_time_ms,
            "reuse_count": self.reuse_count,
            "generation": self.generation,
            "fitness": self.fitness,
        }


@dataclass
class GeneticConfig:
    """遗传算法配置。"""

    population_size: int = 10
    elite_ratio: float = 0.2
    mutation_rate: float = 0.3
    crossover_rate: float = 0.7
    validation_threshold: float = 0.8
    max_generations: int = 100


class ToolGeneticEngine:
    """
    工具基因编程引擎：使用进化算法自动发现和优化工具组合。
    """

    def __init__(
        self,
        population_size: int = 10,
        validation_threshold: float = 0.8,
        mutation_rate: float = 0.3,
        crossover_rate: float = 0.7,
        elite_ratio: float = 0.2,
    ):
        """初始化遗传引擎。

        Args:
            population_size: 种群大小
            validation_threshold: 验证通过阈值
            mutation_rate: 变异率
            crossover_rate: 交叉率
            elite_ratio: 精英比例
        """
        self._population_size = population_size
        self._validation_threshold = validation_threshold
        self._mutation_rate = mutation_rate
        self._crossover_rate = crossover_rate
        self._elite_ratio = elite_ratio

        # 种群存储
        self._population: List[ToolGenotype] = []

        # 验证统计
        self._validated_count: int = 0

        # 可用工具池（用于变异）
        self._available_tools: List[str] = [
            "browser_navigate",
            "browser_screenshot",
            "browser_click",
            "browser_type",
            "browser_scroll",
            "browser_wait",
            "file_read",
            "file_write",
            "file_list",
            "memory_search",
            "memory_store",
            "memory_delete",
            "code_execute",
            "code_analyze",
            "code_format",
            "screenshot",
            "visual_parse",
            "smart_click",
            "api_call",
            "data_transform",
            "log_analysis",
        ]

    @property
    def population(self) -> List[ToolGenotype]:
        """获取当前种群。"""
        return self._population.copy()

    @property
    def validated_count(self) -> int:
        """获取已验证工具数量。"""
        return self._validated_count

    def add_to_population(self, genotype: ToolGenotype) -> None:
        """添加个体到种群。

        Args:
            genotype: 工具基因型
        """
        # 保持种群大小限制
        if len(self._population) >= self._population_size:
            # 移除适应度最低的个体
            self._population.sort(key=lambda g: g.fitness, reverse=True)
            self._population = self._population[: self._population_size - 1]

        self._population.append(genotype)
        logger.debug("Added genotype to population: %s", genotype.tools)

    def record_reuse(self, tool_sequence: List[str]) -> bool:
        """工具序列被执行时递增复用次数（reuse_count）。

        此前 reuse_count 全库只读从不递增，导致 reuse_bonus 恒为 0、
        fitness 永远压不上去，遗传产物注册为技能后无法形成正反馈闭环。
        返回是否命中种群中的某个基因型。
        """
        normalized = list(tool_sequence or [])
        for genotype in self._population:
            if list(genotype.tool_sequence) == normalized:
                genotype.reuse_count += 1
                return True
        return False

    def select_elite(self, n: int) -> List[ToolGenotype]:
        """精英选择：选择适应度最高的 n 个个体。

        Args:
            n: 选择数量

        Returns:
            精英个体列表
        """
        if not self._population:
            return []

        # 按适应度降序排序
        sorted_population = sorted(
            self._population,
            key=lambda g: g.fitness,
            reverse=True,
        )

        return sorted_population[:n]

    def evolve(self, generations: int = 1) -> List[ToolGenotype]:
        """进化指定代数。

        Args:
            generations: 进化代数

        Returns:
            最终种群
        """
        if len(self._population) < 2:
            logger.warning("Population too small to evolve")
            return self._population.copy()

        for gen in range(generations):
            logger.debug("Evolution generation %s/%s", gen + 1, generations)

            new_population = []

            # 精英保留
            elite_count = max(1, int(len(self._population) * self._elite_ratio))
            elite = self.select_elite(elite_count)
            new_population.extend(elite)

            # 生成新个体
            while len(new_population) < self._population_size:
                if random.random() < self._crossover_rate and len(self._population) >= 2:
                    # 交叉
                    parent_a, parent_b = random.sample(self._population, 2)
                    child = self.crossover(parent_a, parent_b)
                    if child:
                        new_population.append(child)

                elif random.random() < self._mutation_rate:
                    # 变异
                    parent = random.choice(self._population)
                    mutation_type = random.choice(["extend", "substitute", "reorder"])
                    child = self.mutate(parent, mutation_type)
                    if child:
                        new_population.append(child)

                else:
                    # 复制
                    parent = random.choice(self._population)
                    new_population.append(
                        ToolGenotype(
                            tool_sequence=parent.tool_sequence.copy(),
                            success_rate=parent.success_rate,
                            execution_time_ms=parent.execution_time_ms,
                            reuse_count=parent.reuse_count,
                            generation=parent.generation,
                        )
                    )

            # 更新种群
            self._population = new_population[: self._population_size]

        return self._population.copy()

    def crossover(self, parent_a: ToolGenotype, parent_b: ToolGenotype) -> Optional[ToolGenotype]:
        """交叉操作：合并两个父代的工具序列。

        Args:
            parent_a: 父代 A
            parent_b: 父代 B

        Returns:
            子代基因型，如果交叉失败则返回 None
        """
        if not parent_a.tools or not parent_b.tools:
            return None

        # 找到共同前缀
        common_prefix = []
        for i in range(min(len(parent_a.tools), len(parent_b.tools))):
            if parent_a.tools[i] == parent_b.tools[i]:
                common_prefix.append(parent_a.tools[i])
            else:
                break

        # 从父代中选择非共同部分
        remaining_a = parent_a.tools[len(common_prefix) :]
        remaining_b = parent_b.tools[len(common_prefix) :]

        # 随机选择交叉点
        if remaining_a and remaining_b:
            # 选择父代 A 的前半部分和父代 B 的后半部分
            crossover_point_a = random.randint(0, len(remaining_a))
            crossover_point_b = random.randint(0, len(remaining_b))

            child_sequence = common_prefix + remaining_a[:crossover_point_a] + remaining_b[crossover_point_b:]
        elif remaining_a:
            child_sequence = common_prefix + remaining_a
        elif remaining_b:
            child_sequence = common_prefix + remaining_b
        else:
            child_sequence = common_prefix

        # 去重但保持顺序
        seen = set()
        unique_sequence = []
        for tool in child_sequence:
            if tool not in seen:
                seen.add(tool)
                unique_sequence.append(tool)

        if len(unique_sequence) < 2:
            return None

        # 创建子代
        child = ToolGenotype(
            tool_sequence=unique_sequence,
            success_rate=(parent_a.success_rate + parent_b.success_rate) / 2,
            execution_time_ms=(parent_a.execution_time_ms + parent_b.execution_time_ms) / 2,
            reuse_count=min(parent_a.reuse_count, parent_b.reuse_count),
            generation=max(parent_a.generation, parent_b.generation) + 1,
        )

        logger.debug("Crossover created child: %s", child.tools)
        return child

    def mutate(self, parent: ToolGenotype, mutation_type: str = "extend") -> Optional[ToolGenotype]:
        """变异操作。

        Args:
            parent: 父代基因型
            mutation_type: 变异类型（extend, substitute, reorder, hybrid）

        Returns:
            变异后的基因型，如果变异失败则返回 None
        """
        if not parent.tools:
            return None

        if mutation_type == "extend":
            return self._mutate_extend(parent)
        elif mutation_type == "substitute":
            return self._mutate_substitute(parent)
        elif mutation_type == "reorder":
            return self._mutate_reorder(parent)
        elif mutation_type == "hybrid":
            return self._mutate_hybrid(parent)
        else:
            logger.warning("Unknown mutation type: %s", mutation_type)
            return None

    def _mutate_extend(self, parent: ToolGenotype) -> Optional[ToolGenotype]:
        """扩展变异：增加工具步骤。"""
        if len(parent.tools) >= 10:  # 限制最大长度
            return None

        # 选择新工具
        available = [t for t in self._available_tools if t not in parent.tools]
        if not available:
            return None

        new_tool = random.choice(available)

        # 随机插入位置
        insert_pos = random.randint(0, len(parent.tools))
        new_sequence = parent.tools[:insert_pos] + [new_tool] + parent.tools[insert_pos:]

        return ToolGenotype(
            tool_sequence=new_sequence,
            success_rate=parent.success_rate * 0.9,  # 新工具可能降低成功率
            execution_time_ms=parent.execution_time_ms,
            reuse_count=0,
            generation=parent.generation + 1,
        )

    def _mutate_substitute(self, parent: ToolGenotype) -> Optional[ToolGenotype]:
        """替换变异：替换问题工具。"""
        if not parent.tools:
            return None

        # 选择要替换的工具（优先替换成功率低的）
        replace_idx = random.randint(0, len(parent.tools) - 1)

        # 选择新工具
        available = [t for t in self._available_tools if t not in parent.tools]
        if not available:
            return None

        new_tool = random.choice(available)
        new_sequence = parent.tools.copy()
        new_sequence[replace_idx] = new_tool

        return ToolGenotype(
            tool_sequence=new_sequence,
            success_rate=parent.success_rate * 0.8,  # 替换可能大幅降低成功率
            execution_time_ms=parent.execution_time_ms,
            reuse_count=0,
            generation=parent.generation + 1,
        )

    def _mutate_reorder(self, parent: ToolGenotype) -> Optional[ToolGenotype]:
        """重排变异：调整工具顺序。"""
        if len(parent.tools) < 3:  # 需要至少 3 个工具才能重排
            return None

        new_sequence = parent.tools.copy()

        # 随机选择两个位置交换
        i, j = random.sample(range(len(new_sequence)), 2)
        new_sequence[i], new_sequence[j] = new_sequence[j], new_sequence[i]

        return ToolGenotype(
            tool_sequence=new_sequence,
            success_rate=parent.success_rate * 0.95,  # 重排可能略微降低成功率
            execution_time_ms=parent.execution_time_ms,
            reuse_count=parent.reuse_count,
            generation=parent.generation + 1,
        )

    def _mutate_hybrid(self, parent: ToolGenotype) -> Optional[ToolGenotype]:
        """混合变异：结合扩展和替换。"""
        if len(parent.tools) < 2:
            return None

        # 随机选择变异方式
        if random.random() < 0.5:
            # 先扩展再替换
            extended = self._mutate_extend(parent)
            if extended:
                return self._mutate_substitute(extended)
        else:
            # 先替换再扩展
            substituted = self._mutate_substitute(parent)
            if substituted:
                return self._mutate_extend(substituted)

        return None

    def validate(self, genotype: ToolGenotype, validation_results: List[bool]) -> bool:
        """沙箱验证：检查工具在验证测试中的表现。

        Args:
            genotype: 要验证的基因型
            validation_results: 验证结果列表（True/False）

        Returns:
            是否通过验证
        """
        if not validation_results:
            return False

        success_count = sum(validation_results)
        total_count = len(validation_results)
        success_rate = success_count / total_count

        passed = success_rate >= self._validation_threshold

        if passed:
            logger.info("Validation passed for %s: %.2f%%", genotype.tools, success_rate * 100)
        else:
            logger.info("Validation failed for %s: %.2f%%", genotype.tools, success_rate * 100)

        return passed

    def register_if_valid(self, genotype: ToolGenotype, validation_results: List[bool]) -> bool:
        """验证并注册：如果通过验证则添加到种群。

        Args:
            genotype: 要验证的基因型
            validation_results: 验证结果列表

        Returns:
            是否成功注册
        """
        if self.validate(genotype, validation_results):
            self.add_to_population(genotype)
            self._validated_count += 1
            logger.info("Registered validated tool: %s", genotype.tools)
            return True

        logger.info("Rejected tool: %s", genotype.tools)
        return False

    def register_to_skill_registry(self, registry, skill_service=None) -> int:
        """将高适应度的工具基因型注册到 SkillRegistry

        Bug A-6 修复 [MED]: 之前 ToolGeneticEngine 仅通过 register_if_valid
        把基因型塞进内部种群，**从不向 SkillRegistry 注册**。导致进化算法
        产生的高适应度工具组合永远停留在遗传引擎内部，下次对话时
        chat_pipeline._check_nl_synthesis 仍因 has_tool=False 触发重复合成。

        仿照 evolution/skill_encapsulation.py:441-487
        AutoSkillBuilder.register_to_skill_registry 实现：遍历种群，
        将 fitness >= validation_threshold 的个体转换为 Skill manifest
        注册到 SkillRegistry。

        断点 #2 修复（Skill 递归进化审计）：SkillRegistry._skills 为纯内存
        dict，genetic 技能重启即丢——演化史（generation/reuse_count）清零、
        前端技能页不可见、下轮重复合成。提供 skill_service 时经
        register_auto_skill 持久化到磁盘 manifest（与 _step_pattern_mining
        的 skill_packer 注册路径对齐）；None 保持原行为向后兼容。

        Args:
            registry: SkillRegistry 实例
            skill_service: 可选，SkillService 实例。提供则持久化到磁盘。

        Returns:
            int: 成功注册的技能数量
        """
        from neurova.skills.models import Skill, SkillSource

        registered_count = 0
        for genotype in self._population:
            # 仅注册高适应度个体
            if genotype.fitness < self._validation_threshold:
                logger.debug(
                    "跳过低适应度基因型 (fitness=%.3f < threshold=%.3f): %s",
                    genotype.fitness,
                    self._validation_threshold,
                    genotype.tools,
                )
                continue

            # 构建稳定的 skill id（基于工具序列）
            tool_sequence = list(genotype.tool_sequence)
            skill_id = "genetic_" + "_".join(tool_sequence)

            # 已存在则跳过（避免重复注册）
            if registry.has_skill(skill_id):
                logger.debug("进化工具 %s 已注册，跳过", skill_id)
                continue

            # 转换 ToolGenotype → Skill manifest
            skill = Skill(
                id=skill_id,
                name=skill_id,
                version="1.0.0",
                description=(
                    f"遗传进化工具组合（适应度 {genotype.fitness:.2f}）: "
                    f"{' → '.join(tool_sequence)}"
                ),
                author="genetic_engine",
                source=SkillSource.LOCAL,
                enabled=True,
                config={
                    "tool_sequence": tool_sequence,
                    "fitness": genotype.fitness,
                    "success_rate": genotype.success_rate,
                    "execution_time_ms": genotype.execution_time_ms,
                    "reuse_count": genotype.reuse_count,
                    "generation": genotype.generation,
                },
            )

            try:
                success = registry.register_skill(skill, None)
                if success:
                    registered_count += 1
                    logger.info(
                        "注册进化工具 %s 到 SkillRegistry (fitness=%.3f)",
                        skill_id,
                        genotype.fitness,
                    )
                    # 断点 #2：可选持久化到 SkillService（磁盘 manifest）
                    if skill_service is not None:
                        try:
                            skill_service.register_auto_skill(
                                skill_id=skill_id,
                                name=skill_id,
                                description=skill.description,
                                version="1.0.0",
                                config=dict(skill.config),
                            )
                        except Exception as svc_err:
                            logger.warning(
                                "持久化进化技能 %s 到 SkillService 失败: %s",
                                skill_id,
                                svc_err,
                            )
            except Exception as e:
                logger.warning("注册进化工具 %s 失败: %s", skill_id, e)

        return registered_count

    def _average_fitness(self) -> float:
        """计算种群平均适应度。"""
        if not self._population:
            return 0.0

        total_fitness = sum(g.fitness for g in self._population)
        return total_fitness / len(self._population)
