"""TemporalReasoner 单元测试 — TDD 红灯阶段

覆盖:
    - 时序关系提取 (before, after, during, same_time)
    - 传递性推理 (A→B→C → A→C)
    - 时序矛盾检测 (A→B 且 B→A)
    - 时间约束推理 (deadline, duration)
    - 时序排序 (按时间排序实体)
"""

import pytest
from datetime import datetime, timedelta, timezone

from neurova.cognitive_layers.memory_layer.temporal_reasoner import (
    TemporalRelation,
    TemporalConstraint,
    TemporalFactTR,
    TemporalReasoner,
)


# ═══════════════════════════════════════════════════════
# TemporalRelation 枚举
# ═══════════════════════════════════════════════════════


class TestTemporalRelation:
    """时序关系枚举测试"""

    def test_relation_values(self):
        assert TemporalRelation.BEFORE.value == "before"
        assert TemporalRelation.AFTER.value == "after"
        assert TemporalRelation.DURING.value == "during"
        assert TemporalRelation.SAME_TIME.value == "same_time"
        assert TemporalRelation.OVERLAPS.value == "overlaps"


# ═══════════════════════════════════════════════════════
# TemporalFactTR 数据类
# ═══════════════════════════════════════════════════════


class TestTemporalFactTR:
    """时序事实数据类测试"""

    def test_creation(self):
        fact = TemporalFactTR(
            subject="A",
            relation=TemporalRelation.BEFORE,
            object_="B",
        )
        assert fact.subject == "A"
        assert fact.object_ == "B"
        assert fact.relation == TemporalRelation.BEFORE

    def test_inverted_relation(self):
        fact = TemporalFactTR(
            subject="A",
            relation=TemporalRelation.BEFORE,
            object_="B",
        )
        inverted = fact.invert()
        assert inverted.subject == "B"
        assert inverted.object_ == "A"
        assert inverted.relation == TemporalRelation.AFTER

    def test_inverted_same_time(self):
        fact = TemporalFactTR(
            subject="A",
            relation=TemporalRelation.SAME_TIME,
            object_="B",
        )
        inverted = fact.invert()
        assert inverted.relation == TemporalRelation.SAME_TIME


# ═══════════════════════════════════════════════════════
# 时序关系提取
# ═══════════════════════════════════════════════════════


class TestTemporalExtraction:
    """从文本中提取时序关系"""

    def test_extract_before(self):
        reasoner = TemporalReasoner()
        facts = reasoner.extract_from_text("部署在测试之前完成")
        assert any(
            f.relation == TemporalRelation.BEFORE
            and {"部署", "测试"}.issubset({f.subject, f.object_})
            for f in facts
        )

    def test_extract_after(self):
        reasoner = TemporalReasoner()
        facts = reasoner.extract_from_text("上线在部署之后")
        assert any(
            f.relation == TemporalRelation.AFTER
            for f in facts
        )

    def test_extract_same_time(self):
        reasoner = TemporalReasoner()
        facts = reasoner.extract_from_text("测试和部署同时进行")
        assert any(
            f.relation == TemporalRelation.SAME_TIME
            for f in facts
        )

    def test_extract_no_temporal(self):
        reasoner = TemporalReasoner()
        facts = reasoner.extract_from_text("今天天气很好")
        assert len(facts) == 0

    def test_extract_multiple(self):
        reasoner = TemporalReasoner()
        facts = reasoner.extract_from_text("设计在开发之前，开发在测试之前")
        before_count = sum(1 for f in facts if f.relation == TemporalRelation.BEFORE)
        assert before_count >= 2


# ═══════════════════════════════════════════════════════
# 传递性推理
# ═══════════════════════════════════════════════════════


class TestTransitivity:
    """传递性推理测试"""

    def test_before_transitive(self):
        """A before B, B before C → A before C"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("设计", TemporalRelation.BEFORE, "开发")
        reasoner.add_fact("开发", TemporalRelation.BEFORE, "测试")

        # 推理: 设计 before 测试
        result = reasoner.infer_relation("设计", "测试")
        assert result is not None
        assert result.relation == TemporalRelation.BEFORE

    def test_after_transitive(self):
        """A after B, B after C → A after C"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("测试", TemporalRelation.AFTER, "开发")
        reasoner.add_fact("开发", TemporalRelation.AFTER, "设计")

        result = reasoner.infer_relation("测试", "设计")
        assert result is not None
        assert result.relation == TemporalRelation.AFTER

    def test_mixed_chain(self):
        """A before B, B after C → A before B 且 B after C（不能直接推出 A 和 C 的关系）"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("B", TemporalRelation.AFTER, "C")

        # A before B, B after C → C before B（反转）
        # 所以 A 和 C 都在 B 之前，但 A 和 C 之间不确定
        result = reasoner.infer_relation("A", "C")
        # 可能是 None（不确定），也可能有其他推理
        # 这里只要不报错即可

    def test_no_chain(self):
        """无传递链时返回 None"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("C", TemporalRelation.BEFORE, "D")

        result = reasoner.infer_relation("A", "D")
        assert result is None


# ═══════════════════════════════════════════════════════
# 时序矛盾检测
# ═══════════════════════════════════════════════════════


class TestTemporalContradiction:
    """时序矛盾检测测试"""

    def test_detect_contradiction(self):
        """A before B 且 A after B → 矛盾"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        conflicts = reasoner.add_fact("A", TemporalRelation.AFTER, "B")

        assert len(conflicts) > 0

    def test_no_contradiction(self):
        """A before B 且 B before C → 无矛盾"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        conflicts = reasoner.add_fact("B", TemporalRelation.BEFORE, "C")

        assert len(conflicts) == 0

    def test_same_time_contradiction(self):
        """A before B 且 A same_time B → 矛盾"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        conflicts = reasoner.add_fact("A", TemporalRelation.SAME_TIME, "B")

        assert len(conflicts) > 0

    def test_direct_cycle(self):
        """A before B 且 B before A → 直接循环矛盾"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        conflicts = reasoner.add_fact("B", TemporalRelation.BEFORE, "A")

        assert len(conflicts) > 0

    def test_indirect_cycle(self):
        """A before B, B before C, C before A → 间接循环矛盾"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("B", TemporalRelation.BEFORE, "C")
        conflicts = reasoner.add_fact("C", TemporalRelation.BEFORE, "A")

        assert len(conflicts) > 0


# ═══════════════════════════════════════════════════════
# 时间约束推理
# ═══════════════════════════════════════════════════════


class TestTemporalConstraints:
    """时间约束推理测试"""

    def test_deadline_constraint_satisfied(self):
        """任务在截止日期前完成"""
        reasoner = TemporalReasoner()
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(days=7)
        constraint = TemporalConstraint(
            entity="部署",
            constraint_type="deadline",
            deadline=deadline,
        )
        result = reasoner.check_constraint(constraint, task_time=now + timedelta(days=3))
        assert result["satisfied"] is True

    def test_deadline_constraint_violated(self):
        """任务超过截止日期"""
        reasoner = TemporalReasoner()
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(days=7)
        constraint = TemporalConstraint(
            entity="部署",
            constraint_type="deadline",
            deadline=deadline,
        )
        result = reasoner.check_constraint(constraint, task_time=now + timedelta(days=10))
        assert result["satisfied"] is False

    def test_order_constraint_satisfied(self):
        """A 必须在 B 之前完成"""
        reasoner = TemporalReasoner()
        now = datetime.now(timezone.utc)
        constraint = TemporalConstraint(
            entity="测试",
            constraint_type="order",
            required_before="上线",
        )
        result = reasoner.check_constraint(
            constraint,
            timestamps={"测试": now, "上线": now + timedelta(days=1)},
        )
        assert result["satisfied"] is True

    def test_order_constraint_violated(self):
        """A 在 B 之后完成（违反约束）"""
        reasoner = TemporalReasoner()
        now = datetime.now(timezone.utc)
        constraint = TemporalConstraint(
            entity="测试",
            constraint_type="order",
            required_before="上线",
        )
        result = reasoner.check_constraint(
            constraint,
            timestamps={"测试": now + timedelta(days=2), "上线": now + timedelta(days=1)},
        )
        assert result["satisfied"] is False


# ═══════════════════════════════════════════════════════
# 时序排序
# ═══════════════════════════════════════════════════════


class TestTemporalSorting:
    """时序排序测试"""

    def test_sort_linear_chain(self):
        """线性链排序: A before B before C → [A, B, C]"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("B", TemporalRelation.BEFORE, "C")

        sorted_entities = reasoner.sort_by_temporal_order(["A", "B", "C"])
        assert sorted_entities == ["A", "B", "C"]

    def test_sort_reverse_chain(self):
        """反向链排序: C before B before A → [C, B, A]"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("C", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("B", TemporalRelation.BEFORE, "A")

        sorted_entities = reasoner.sort_by_temporal_order(["A", "B", "C"])
        assert sorted_entities == ["C", "B", "A"]

    def test_sort_same_time(self):
        """同时实体不改变顺序"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.SAME_TIME, "B")

        sorted_entities = reasoner.sort_by_temporal_order(["A", "B"])
        # A 和 B 应该相邻
        assert set(sorted_entities) == {"A", "B"}

    def test_sort_partial_info(self):
        """部分时序信息时尽量排序"""
        reasoner = TemporalReasoner()
        reasoner.add_fact("A", TemporalRelation.BEFORE, "C")

        sorted_entities = reasoner.sort_by_temporal_order(["A", "B", "C"])
        assert sorted_entities.index("A") < sorted_entities.index("C")
        # B 的位置不确定，但不应该报错


# ═══════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════


class TestTemporalReasonerIntegration:
    """时序推理器集成测试"""

    def test_full_pipeline(self):
        """完整流程: 提取 → 推理 → 矛盾检测 → 排序"""
        reasoner = TemporalReasoner()

        # 提取时序关系
        facts = reasoner.extract_from_text("设计在开发之前，开发在测试之前，测试在上线之前")
        for fact in facts:
            reasoner.add_fact(fact.subject, fact.relation, fact.object_)

        # 传递性推理
        result = reasoner.infer_relation("设计", "上线")
        assert result is not None
        assert result.relation == TemporalRelation.BEFORE

        # 排序
        sorted_entities = reasoner.sort_by_temporal_order(
            ["设计", "开发", "测试", "上线"]
        )
        assert sorted_entities == ["设计", "开发", "测试", "上线"]

    def test_contradiction_pipeline(self):
        """矛盾检测流程"""
        reasoner = TemporalReasoner()

        reasoner.add_fact("A", TemporalRelation.BEFORE, "B")
        reasoner.add_fact("B", TemporalRelation.BEFORE, "C")

        # 添加矛盾事实
        conflicts = reasoner.add_fact("C", TemporalRelation.BEFORE, "A")
        assert len(conflicts) > 0

        # 查询矛盾
        all_conflicts = reasoner.get_contradictions()
        assert len(all_conflicts) > 0

    def test_constraint_pipeline(self):
        """约束推理流程"""
        reasoner = TemporalReasoner()
        now = datetime.now(timezone.utc)

        # 添加时序关系
        reasoner.add_fact("设计", TemporalRelation.BEFORE, "开发")
        reasoner.add_fact("开发", TemporalRelation.BEFORE, "测试")

        # 添加约束
        constraint = TemporalConstraint(
            entity="测试",
            constraint_type="deadline",
            deadline=now + timedelta(days=30),
        )

        # 检查约束（假设测试在15天后完成）
        result = reasoner.check_constraint(
            constraint,
            task_time=now + timedelta(days=15),
        )
        assert result["satisfied"] is True
