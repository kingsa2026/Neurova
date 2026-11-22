"""U4 · Allen 区间代数引擎单测（先红后绿）。

红灯阶段：本文件先于 `neurova/knowledge/ontology/temporal_algebra.py` 落地，
模块尚不存在时收集即失败，实证红灯后再实现转绿。

覆盖：
- 13 关系判定真值表：每关系 ≥2 例，含端点相等的边界形态（meets/metBy/
  starts/startedBy/finishes/finishedBy/equal 全部以端点相等定义）
- 合成表：已知条目抽验（按 Allen 语义手推）+ 169 格全覆盖 + 端点全序独立
  枚举对拍 + 逆关系对称律 + 随机区间一致性
- relationsForFacts：3 条构造事实的两两判定，字段名对齐
  knowledge_facts._hydrate 实际返回（fact_id/valid_from/valid_until）
- 非法输入显式报错：倒置/零长区间、不可解析时间、未知关系名
"""

from __future__ import annotations

import itertools
import random

import pytest

from neurova.knowledge.ontology.temporal_algebra import (
    INTERVAL_RELATIONS,
    REL_AFTER,
    REL_BEFORE,
    REL_CONTAINS,
    REL_DURING,
    REL_EQUAL,
    REL_FINISHED_BY,
    REL_FINISHES,
    REL_MET_BY,
    REL_MEETS,
    REL_OVERLAPPED_BY,
    REL_OVERLAPS,
    REL_STARTED_BY,
    REL_STARTS,
    classifyIntervalRel,
    composeRelations,
    inverseRelation,
    relationsForFacts,
)

_RELATION_SET = frozenset(INTERVAL_RELATIONS)


class TestIntervalRelationsClosedSet:
    def test_thirteenRelationsUnique(self):
        assert len(INTERVAL_RELATIONS) == 13
        assert len(set(INTERVAL_RELATIONS)) == 13

    def test_classifyAlwaysYieldsClosedSetMember(self):
        """任意区间对恰好落到 13 关系之一（互斥且穷尽）。"""
        rng = random.Random(20261122)
        for _ in range(200):
            as_, ae, bs, be = sorted(rng.sample(range(0, 10_000), 4))
            assert classifyIntervalRel(as_, ae, bs, be) in _RELATION_SET


class TestClassifyIntervalRel:
    @pytest.mark.parametrize(
        "aStart,aEnd,bStart,bEnd,expected",
        [
            # before：a 整体在 b 之前且不搭接（ae < bs）
            (1000, 1010, 1020, 1030, REL_BEFORE),
            (1000, 1010, 1011, 1020, REL_BEFORE),  # 紧贴 meets 边界仍不搭接
            ("2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z",
             "2026-01-01T00:02:00Z", "2026-01-01T00:03:00Z", REL_BEFORE),
            # meets：aEnd == bStart（Allen 标准首尾搭接）
            (1000, 1010, 1010, 1020, REL_MEETS),
            (5, 10, 10, 15, REL_MEETS),
            # metBy：aStart == bEnd（b 搭接 a）
            (1010, 1020, 1000, 1010, REL_MET_BY),
            (15, 20, 10, 15, REL_MET_BY),
            # after：a 整体在 b 之后（as > be）
            (1020, 1030, 1000, 1010, REL_AFTER),
            (11, 12, 5, 10, REL_AFTER),
            # overlaps：as < bs < ae < be
            (1000, 1015, 1010, 1030, REL_OVERLAPS),
            (0, 10, 5, 20, REL_OVERLAPS),
            # overlappedBy：b 先起、a 后收
            (1010, 1030, 1000, 1015, REL_OVERLAPPED_BY),
            (5, 20, 0, 10, REL_OVERLAPPED_BY),
            # starts：同起点且 a 更早收
            (1000, 1005, 1000, 1010, REL_STARTS),
            (1000, 1009, 1000, 1010, REL_STARTS),
            # startedBy：同起点且 a 更晚收
            (1000, 1010, 1000, 1005, REL_STARTED_BY),
            (1000, 1010, 1000, 1009, REL_STARTED_BY),
            # during：a 严格落在 b 内部
            (1002, 1008, 1000, 1010, REL_DURING),
            (1000, 1010, 900, 2000, REL_DURING),
            # contains：b 严格落在 a 内部
            (1000, 1010, 1002, 1008, REL_CONTAINS),
            (900, 2000, 1000, 1010, REL_CONTAINS),
            # finishes：同终点且 a 更晚起
            (1005, 1010, 1000, 1010, REL_FINISHES),
            (1009, 1010, 1000, 1010, REL_FINISHES),
            # finishedBy：同终点且 a 更早起
            (1000, 1010, 1005, 1010, REL_FINISHED_BY),
            (1000, 1010, 1009, 1010, REL_FINISHED_BY),
            # equal：两端点分别相等（ISO 字符串与 date-only 入参同口径）
            (1000, 1010, 1000, 1010, REL_EQUAL),
            ("2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02", REL_EQUAL),
            ("2026-01-01T08:00:00+08:00", "2026-01-01T09:00:00+08:00",
             "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z", REL_EQUAL),
        ],
    )
    def test_truthTable(self, aStart, aEnd, bStart, bEnd, expected):
        assert classifyIntervalRel(aStart, aEnd, bStart, bEnd) == expected


class TestInverseRelation:
    def test_pairingAndInvolution(self):
        pairs = {
            REL_BEFORE: REL_AFTER,
            REL_MEETS: REL_MET_BY,
            REL_OVERLAPS: REL_OVERLAPPED_BY,
            REL_STARTS: REL_STARTED_BY,
            REL_DURING: REL_CONTAINS,
            REL_FINISHES: REL_FINISHED_BY,
            REL_EQUAL: REL_EQUAL,
        }
        for relation, inverted in pairs.items():
            assert inverseRelation(relation) == inverted
            assert inverseRelation(inverted) == relation

    def test_classifyMirrorConsistency(self):
        """判定与逆关系互锁：rel(b, a) == inverse(rel(a, b))。"""
        rng = random.Random(42)
        for _ in range(200):
            as_, ae, bs, be = sorted(rng.sample(range(0, 1000), 4))
            forward = classifyIntervalRel(as_, ae, bs, be)
            backward = classifyIntervalRel(bs, be, as_, ae)
            assert backward == inverseRelation(forward)


class TestComposeRelations:
    def test_knownEntries(self):
        # 以下条目均按 Allen 合成语义手推复核：
        # a<b 且 b<c ⇒ a<c；a 搭 b 且 b 搭 c ⇒ ae=bs<be=cs ⇒ a<c。
        assert composeRelations(REL_BEFORE, REL_BEFORE) == frozenset({REL_BEFORE})
        assert composeRelations(REL_BEFORE, REL_MEETS) == frozenset({REL_BEFORE})
        assert composeRelations(REL_MEETS, REL_BEFORE) == frozenset({REL_BEFORE})
        assert composeRelations(REL_MEETS, REL_MEETS) == frozenset({REL_BEFORE})
        # a 在 b 内部、b 在 c 之前 ⇒ ae < be < cs ⇒ a 只能在 c 之前
        assert composeRelations(REL_DURING, REL_BEFORE) == frozenset({REL_BEFORE})
        # a 领先 b、b 领先 c，a 与 c 的相对位置只可能是领先/搭接/交叠
        assert composeRelations(REL_OVERLAPS, REL_OVERLAPS) == frozenset(
            {REL_BEFORE, REL_MEETS, REL_OVERLAPS})
        # a 与 b 同起点、b 在 c 内部 ⇒ cs < as=bs 且 ae < be < ce ⇒ a 在 c 内部
        assert composeRelations(REL_STARTS, REL_DURING) == frozenset({REL_DURING})
        # a 包含 b、b 在 c 之前：as < bs < cs，ae 只受 > be 约束，可落在
        # cs 之前/之上/之后，也可越过 ce——即 {<, m, o, di, fi}
        assert composeRelations(REL_CONTAINS, REL_BEFORE) == frozenset(
            {REL_BEFORE, REL_MEETS, REL_OVERLAPS, REL_CONTAINS, REL_FINISHED_BY})
        # a<b 且 c<b：c 可落在 a 的任意相对位置，13 关系全可达
        assert composeRelations(REL_BEFORE, REL_AFTER) == _RELATION_SET

    def test_equalIsIdentityElement(self):
        for relation in INTERVAL_RELATIONS:
            assert composeRelations(REL_EQUAL, relation) == frozenset({relation})
            assert composeRelations(relation, REL_EQUAL) == frozenset({relation})

    def test_fullTableCoversAll169Cells(self):
        """13×13=169 格全覆盖：每格非空、且取值都在 13 关系闭集内。"""
        checked = 0
        for relA in INTERVAL_RELATIONS:
            for relB in INTERVAL_RELATIONS:
                result = composeRelations(relA, relB)
                assert isinstance(result, frozenset)
                assert result, "空合成格: %s∘%s" % (relA, relB)
                assert result <= _RELATION_SET
                checked += 1
        assert checked == 169

    def test_fullTableMatchesIndependentEnumeration(self):
        """对拍：独立枚举 6 端点的全部弱序（秩 0..5 允许并列，覆盖 meets/
        equal 等端点相等形态；区间内部仍要求 start<end），按语义定义
        comp(r1,r2)={rel(a,c) | rel(a,b)=r1 ∧ rel(b,c)=r2} 重算全表，
        与 composeRelations 逐格比对——能同时抓住缺格与错格。"""
        expected = {
            (r1, r2): set() for r1 in INTERVAL_RELATIONS for r2 in INTERVAL_RELATIONS
        }
        for as_, ae, bs, be, cs, ce in itertools.product(range(6), repeat=6):
            if as_ >= ae or bs >= be or cs >= ce:
                continue
            relAB = classifyIntervalRel(as_, ae, bs, be)
            relBC = classifyIntervalRel(bs, be, cs, ce)
            expected[(relAB, relBC)].add(classifyIntervalRel(as_, ae, cs, ce))
        for (relA, relB), relations in expected.items():
            assert composeRelations(relA, relB) == frozenset(relations), (relA, relB)

    def test_converseSymmetryOverFullTable(self):
        """逆对称律：(r1∘r2)⁻¹ == r2⁻¹∘r1⁻¹，169 格逐格验证。"""
        for relA in INTERVAL_RELATIONS:
            for relB in INTERVAL_RELATIONS:
                left = frozenset(inverseRelation(r) for r in composeRelations(relA, relB))
                right = composeRelations(inverseRelation(relB), inverseRelation(relA))
                assert left == right, (relA, relB)

    def test_randomIntervalTriplesConsistency(self):
        """随机三区间采样：rel(a,c) 必须落在 compose(rel(a,b), rel(b,c)) 之内。

        有放回取点使跨区间端点相等（meets/equal 等形态）也会被采到；
        零长区间是非法输入，遇到即跳过。"""
        rng = random.Random(20261122)
        checked = 0
        while checked < 2000:
            as_, ae, bs, be, cs, ce = sorted(rng.choices(range(0, 24), k=6))
            if as_ >= ae or bs >= be or cs >= ce:
                continue
            checked += 1
            relAB = classifyIntervalRel(as_, ae, bs, be)
            relBC = classifyIntervalRel(bs, be, cs, ce)
            relAC = classifyIntervalRel(as_, ae, cs, ce)
            assert relAC in composeRelations(relAB, relBC), (as_, ae, bs, be, cs, ce)


class TestRelationsForFacts:
    def test_threeFactsPairwise(self):
        facts = [
            {"id": "f1", "validFrom": "2026-01-01T00:00:00Z",
             "validUntil": "2026-01-01T02:00:00Z"},
            {"id": "f2", "validFrom": "2026-01-01T02:00:00Z",
             "validUntil": "2026-01-01T04:00:00Z"},
            {"id": "f3", "validFrom": "2026-01-01T01:00:00Z",
             "validUntil": "2026-01-01T03:00:00Z"},
        ]
        result = relationsForFacts(facts)
        assert [(r["aId"], r["bId"]) for r in result] == [
            ("f1", "f2"), ("f1", "f3"), ("f2", "f3")]
        byPair = {(r["aId"], r["bId"]): r["relation"] for r in result}
        assert byPair[("f1", "f2")] == REL_MEETS
        assert byPair[("f1", "f3")] == REL_OVERLAPS
        assert byPair[("f2", "f3")] == REL_OVERLAPPED_BY

    def test_acceptsKnowledgeFactsHydrateShape(self):
        """字段名对齐 _hydrate 实际返回：fact_id / valid_from / valid_until。"""
        facts = [
            {"fact_id": "a", "valid_from": 1000, "valid_until": 1010},
            {"fact_id": "b", "valid_from": 1010, "valid_until": 1020},
        ]
        result = relationsForFacts(facts)
        assert result == [{"aId": "a", "bId": "b", "relation": REL_MEETS}]

    def test_missingEndpointPairsAreSkipped(self):
        """NULL 有效期（任一端点缺失）的配对不产出结果，其余照常判定。"""
        facts = [
            {"id": "a", "validFrom": 1000, "validUntil": None},
            {"id": "b", "validFrom": 1000, "validUntil": 1010},
            {"id": "c", "validFrom": 1010, "validUntil": 1020},
        ]
        result = relationsForFacts(facts)
        assert [(r["aId"], r["bId"], r["relation"]) for r in result] == [
            ("b", "c", REL_MEETS)]

    def test_missingIdRaises(self):
        with pytest.raises(ValueError):
            relationsForFacts([{"validFrom": 1000, "validUntil": 1010}])


class TestInvalidInputs:
    def test_invertedIntervalRaises(self):
        with pytest.raises(ValueError):
            classifyIntervalRel(1010, 1000, 0, 10)
        with pytest.raises(ValueError):
            classifyIntervalRel(0, 10, 1010, 1000)

    def test_zeroLengthIntervalRaises(self):
        with pytest.raises(ValueError):
            classifyIntervalRel(1000, 1000, 0, 10)
        with pytest.raises(ValueError):
            classifyIntervalRel(0, 10, 1000, 1000)

    def test_unparseableTimeStringRaises(self):
        with pytest.raises(ValueError):
            classifyIntervalRel("不是时间", 1010, 0, 10)
        with pytest.raises(ValueError):
            classifyIntervalRel(1000, "2026-13-40T00:00:00Z", 0, 10)

    def test_unsupportedTypeRaises(self):
        with pytest.raises(ValueError):
            classifyIntervalRel(None, 10, 0, 10)
        with pytest.raises(ValueError):
            classifyIntervalRel([1000], 1010, 0, 10)

    def test_unknownRelationNameRaises(self):
        with pytest.raises(ValueError):
            composeRelations("不存在的", REL_BEFORE)
        with pytest.raises(ValueError):
            composeRelations(REL_BEFORE, "不存在的")
        with pytest.raises(ValueError):
            inverseRelation("不存在的")
