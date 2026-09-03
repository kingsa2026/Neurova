"""
Phase 2 P2-4: ToolGeneticEngine 基因编程测试

验证：
- 工具基因型定义（编码工具序列为可变异/交叉的基因）
- 交叉操作（合并两个高频协作工具）
- 变异操作（参数扩展、序列重排、降级嫁接）
- 沙箱验证（新工具在隔离环境验证 N 次）
- 适应度函数计算
"""
import pytest
from typing import List


# ============================================================
# P2-4.1 基因型定义
# ============================================================


class TestToolGenotype:
    """工具基因型"""

    def test_create_genotype_from_tool_sequence(self):
        """从工具序列创建基因型"""
        from neurova.evolution.genetic_engine import ToolGenotype

        genotype = ToolGenotype(
            tool_sequence=["browser_navigate", "browser_screenshot", "browser_click"],
            success_rate=0.85,
            execution_time_ms=1200.0,
            reuse_count=5,
        )

        assert genotype.tools == ["browser_navigate", "browser_screenshot", "browser_click"]
        assert genotype.success_rate == 0.85
        assert genotype.execution_time_ms == 1200.0
        assert genotype.reuse_count == 5
        assert genotype.generation == 1

    def test_genotype_defaults(self):
        """基因型默认值"""
        from neurova.evolution.genetic_engine import ToolGenotype

        genotype = ToolGenotype(tool_sequence=["a", "b"])

        assert genotype.success_rate == 0.5  # 默认中性
        assert genotype.execution_time_ms == 0.0
        assert genotype.reuse_count == 0

    def test_genotype_to_dict(self):
        """基因型导出为字典"""
        from neurova.evolution.genetic_engine import ToolGenotype

        genotype = ToolGenotype(
            tool_sequence=["screenshot", "visual_parse"],
            success_rate=0.92,
        )
        d = genotype.to_dict()
        assert d["tools"] == ["screenshot", "visual_parse"]
        assert d["success_rate"] == 0.92

    def test_genotype_fitness(self):
        """适应度计算"""
        from neurova.evolution.genetic_engine import ToolGenotype

        # 完美工具
        perfect = ToolGenotype(
            tool_sequence=["a"],
            success_rate=1.0,
            execution_time_ms=100.0,
            reuse_count=10,
        )
        assert perfect.fitness > 0.5

        # 失败工具
        failing = ToolGenotype(
            tool_sequence=["x"],
            success_rate=0.1,
            execution_time_ms=5000.0,
            reuse_count=0,
        )
        assert failing.fitness < 0.3, f"失败工具适应度应为低值: {failing.fitness}"


# ============================================================
# P2-4.2 交叉操作 (Crossover)
# ============================================================


class TestCrossover:
    """交叉操作"""

    def test_crossover_two_sequences(self):
        """交叉两个工具序列"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent_a = ToolGenotype(
            tool_sequence=["browser_navigate", "browser_screenshot", "browser_click"],
            success_rate=0.9,
        )
        parent_b = ToolGenotype(
            tool_sequence=["browser_navigate", "browser_type", "browser_screenshot"],
            success_rate=0.8,
        )

        child = engine.crossover(parent_a, parent_b)

        assert child is not None
        assert isinstance(child, ToolGenotype)
        assert child.generation == max(parent_a.generation, parent_b.generation) + 1

        # 子代应包含来自两个父代的工具
        all_tools = set(parent_a.tools) | set(parent_b.tools)
        assert any(t in child.tools for t in all_tools)
        assert len(child.tools) >= 2

    def test_crossover_preserves_common_prefix(self):
        """交叉保留共同前缀"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent_a = ToolGenotype(
            tool_sequence=["setup", "action_a", "verify"],
            success_rate=0.9,
        )
        parent_b = ToolGenotype(
            tool_sequence=["setup", "action_b", "verify"],
            success_rate=0.8,
        )

        child = engine.crossover(parent_a, parent_b)

        # "setup" 是共同前缀，应被保留
        assert child.tools[0] == "setup"


# ============================================================
# P2-4.3 变异操作 (Mutation)
# ============================================================


class TestMutation:
    """变异操作"""

    def test_mutation_extend_adds_tool(self):
        """扩展变异：增加工具步骤"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent = ToolGenotype(
            tool_sequence=["browser_navigate", "browser_click"],
            success_rate=0.7,
        )

        child = engine.mutate(parent, mutation_type="extend")
        assert child is not None
        # extend 可能增加验证步骤
        assert len(child.tools) >= len(parent.tools)

    def test_mutation_substitute(self):
        """替换变异：替换问题工具"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent = ToolGenotype(
            tool_sequence=["browser_navigate", "browser_click", "browser_screenshot"],
            success_rate=0.3,  # 低成功率触发替换
        )

        child = engine.mutate(parent, mutation_type="substitute")

        if child:
            # 替换变异可能更改工具
            assert isinstance(child, ToolGenotype)
            assert child.generation == parent.generation + 1

    def test_mutation_reorder(self):
        """重排变异：调整工具顺序"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent = ToolGenotype(
            tool_sequence=["a", "b", "c", "d"],
            success_rate=0.6,
        )

        child = engine.mutate(parent, mutation_type="reorder")

        if child and len(parent.tools) >= 3:
            # 重排后工具集合不变
            assert set(child.tools) == set(parent.tools)

    def test_mutation_no_change_for_high_success(self):
        """高成功率工具不触发替换变异"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        parent = ToolGenotype(
            tool_sequence=["perfect_tool"],
            success_rate=0.95,
        )

        child = engine.mutate(parent, mutation_type="substitute")
        # 高成功率工具替换变异后不应有大变化
        if child:
            assert child.tools == parent.tools or len(child.tools) <= len(parent.tools) + 1


# ============================================================
# P2-4.4 遗传引擎
# ============================================================


class TestGeneticEngine:
    """遗传引擎整体行为"""

    def test_evolve_population(self):
        """种群进化"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine(population_size=5)

        # 初始种群
        engine.add_to_population(ToolGenotype(
            tool_sequence=["browser_navigate", "browser_screenshot"],
            success_rate=0.85,
        ))
        engine.add_to_population(ToolGenotype(
            tool_sequence=["browser_navigate", "browser_click", "browser_screenshot"],
            success_rate=0.75,
        ))
        engine.add_to_population(ToolGenotype(
            tool_sequence=["screenshot", "visual_parse", "smart_click"],
            success_rate=0.90,
        ))

        # 进化一代
        new_gen = engine.evolve(generations=1)

        assert len(new_gen) > 0
        # 进化后产生新个体
        assert any(g.generation > 1 for g in new_gen)

    def test_select_top_performers(self):
        """精英选择"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine()

        for i in range(5):
            engine.add_to_population(ToolGenotype(
                tool_sequence=[f"tool_{i}"],
                success_rate=0.5 + i * 0.1,  # 0.5, 0.6, 0.7, 0.8, 0.9
            ))

        top = engine.select_elite(n=2)
        assert len(top) == 2
        # 精英应该有最高的成功率
        assert top[0].success_rate >= top[1].success_rate

    def test_sandbox_validation(self):
        """沙箱验证：新工具需要通过验证才能进入生产"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine(validation_threshold=0.8)

        good = ToolGenotype(
            tool_sequence=["validated_tool"],
            success_rate=0.9,
        )
        # 模拟沙箱中 10 次验证，9 次成功
        result = engine.validate(good, validation_results=[True] * 9 + [False])
        assert result is True

    def test_sandbox_rejection(self):
        """沙箱拒绝不达标的工具"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine(validation_threshold=0.8)

        bad = ToolGenotype(
            tool_sequence=["unreliable_tool"],
            success_rate=0.5,
        )
        # 模拟沙箱中 10 次验证，仅 4 次成功
        result = engine.validate(bad, validation_results=[True] * 4 + [False] * 6)
        assert result is False

    def test_register_validated_tool(self):
        """验证通过的工具自动注册"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine(validation_threshold=0.7)

        genotype = ToolGenotype(
            tool_sequence=["new_capability"],
            success_rate=0.85,
        )

        # 模拟验证通过
        engine._validated_count = 0
        success = engine.register_if_valid(
            genotype,
            validation_results=[True] * 8 + [False] * 2,
        )
        assert success is True

    def test_invalid_tool_not_registered(self):
        """验证失败的工具不注册"""
        from neurova.evolution.genetic_engine import ToolGenotype, ToolGeneticEngine

        engine = ToolGeneticEngine(validation_threshold=0.7)

        genotype = ToolGenotype(
            tool_sequence=["broken_tool"],
            success_rate=0.3,
        )

        success = engine.register_if_valid(
            genotype,
            validation_results=[True] * 2 + [False] * 8,
        )
        assert success is False
