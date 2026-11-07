# -*- coding: utf-8 -*-
"""facts/图谱读面分类白名单契约（specs/2026-11-07 批 E）。

红灯判据（设计 §4 批 E）：
- GraphFactWalker：allowedCategories 非空 → 锚点段与递归段都只走白名单内
  category 的事实；空列表 → 零命中（受限无可见分类）；None → 行为不变（反向钉：
  未启用白名单时跨分类二跳照旧）；
- TemporalFactReader.forQuery：同口径；
- 白名单外的跨跳路径被掐断：走查不会"绕道"白名单外事实接出白名单内事实。

种子形状（walkFromQuery 只返回 hop ≥ 2 的行，单跳事实进不了结果集）：
  A(预算规模) -budget-> 一百万元(rnd) / 两百万元(other)      [hop1，仅 temporal 消费]
  A(预算规模) -scope-> B(研发中心)(rnd)                      [hop1 桥]
  B(研发中心) -head-> 张三(rnd) / 李四(other)                [hop2，walker 判别面]
"""

import pytest

from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader


@pytest.fixture()
def store(tmp_path):
    return KnowledgeFactStore(str(tmp_path / "facts.db"))


@pytest.fixture()
def seeded(store):
    subject_a = store.upsertSubject("agent_a", "预算规模", tenantId="dept_root")
    subject_b = store.upsertSubject("agent_a", "研发中心", tenantId="dept_root")
    hub = store.upsertSubject("agent_a", "项目周期", tenantId="dept_root")
    store.upsertFact("agent_a", subject_a, "pred.budget", "一百万元",
                     "预算一百万元", contentKey="ck:rnd", tenantId="dept_root",
                     category="rnd")
    store.upsertFact("agent_a", subject_a, "pred.budget", "两百万元",
                     "预算两百万元", contentKey="ck:other", tenantId="dept_root",
                     category="other")
    store.upsertFact("agent_a", subject_a, "pred.scope", "研发中心",
                     "预算规模属研发中心", contentKey="ck:bridge", tenantId="dept_root",
                     category="rnd")
    store.upsertFact("agent_a", subject_b, "pred.head", "张三",
                     "研发中心负责人张三", contentKey="ck:head_rnd",
                     tenantId="dept_root", category="rnd")
    store.upsertFact("agent_a", subject_b, "pred.head", "李四",
                     "研发中心前任负责人李四", contentKey="ck:head_other",
                     tenantId="dept_root", category="other")
    store.upsertFact("agent_a", hub, "pred.relates", "预算规模",
                     "项目周期关联预算规模", contentKey="ck:hub", tenantId="dept_root",
                     category="other")
    return store


def _walker(store):
    return GraphFactWalker(store, "agent_a")


def testWalkerFiltersToWhitelistedCategories(seeded):
    rows = _walker(seeded).walkFromQuery("预算规模", tenantId="dept_root",
                                         allowedCategories=["rnd"])
    objects = [row["object"] for row in rows]
    assert "张三" in objects, "白名单内二跳应命中"
    assert "李四" not in objects and "两百万元" not in objects


def testWalkerEmptyWhitelistYieldsNothing(seeded):
    assert _walker(seeded).walkFromQuery("预算规模", tenantId="dept_root",
                                         allowedCategories=[]) == []


def testWalkerNoneKeepsLegacyBehavior(seeded):
    """allowedCategories=None（未启用白名单）→ 跨分类二跳照旧（反向钉）。"""
    rows = _walker(seeded).walkFromQuery("预算规模", tenantId="dept_root")
    objects = [row["object"] for row in rows]
    assert "张三" in objects and "李四" in objects


def testWalkerCrossHopPathCutOutsideWhitelist(seeded):
    """锚点事实自身在白名单外（项目周期→other）→ 锚点段即排除。"""
    rows = _walker(seeded).walkFromQuery("项目周期", tenantId="dept_root",
                                         allowedCategories=["rnd"])
    assert rows == []


def testTemporalFiltersToWhitelistedCategories(seeded):
    reader = TemporalFactReader(seeded, "agent_a")
    rows = reader.forQuery("预算规模", tenantId="dept_root", allowedCategories=["rnd"])
    objects = [row["object"] for row in rows]
    assert "一百万元" in objects
    assert "两百万元" not in objects


def testTemporalEmptyWhitelistYieldsNothing(seeded):
    reader = TemporalFactReader(seeded, "agent_a")
    assert reader.forQuery("预算规模", tenantId="dept_root", allowedCategories=[]) == []


def testTemporalNoneKeepsLegacyBehavior(seeded):
    reader = TemporalFactReader(seeded, "agent_a")
    rows = reader.forQuery("预算规模", tenantId="dept_root")
    objects = [row["object"] for row in rows]
    assert "一百万元" in objects and "两百万元" in objects
