"""甲3（§6-219 裁定）：睡眠合并的准入从「语义相近」改成「内容近等价」。

§6-218 的实测把话说死了：`merge_cluster` 的策略是取最长、其余 soft-forget，而它吃的判据
是余弦 —— 于是 `IMP-探针`(5 字) 与 `DB-探针`(4 字) 这种**余弦 1.0 但内容不同**的两条，
和 kai 那 4 条互不相同的真对话回合（0.71~0.88，一口气并成一簇），都会把独有正文退役掉。
调阈值治不了它：0.7 提到 0.9 只决定"误伤多少"，不改变"误伤的方式是丢内容"。

所以合并的准入换成两条同时成立：**余弦 ≥ 近等价下限**（0.98，且不许被 `similarity_threshold`
调低拉穿）**且归一化后短者为长者的子串**（走全仓唯一的 `content_identity.normalized_key()`，
不另写第二份归一化）。逐字重复照合，语义相近不合。

另两格钉的是"合并真开始跑之后不许丢事实"：产物行必须活着并带上来源
（`metadata.merged_from`，§6-218 点名的断点），且不许在跨界字典里把分类弄丢。
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from tests.cognitive_body_store import bodyManager

AGENT = "mergegate"

#: 归一化后互为子串的一对（短的是长的前缀），且两条内容键不同 ⇒ 写侧内容门不会提前吞掉
SHORT = "登录页验证码在弱网下加载超时"
LONG = "登录页验证码在弱网下加载超时，重试两次后恢复"

#: §6-218 的反例形状：内容互不包含，余弦却打满
PROBE_A = "IMP-探针"
PROBE_B = "DB-探针"

#: kai 那类真实对话回合（内容互不相同）
TURN_A = "助手: 冯先生，我明白你在说什么。"
TURN_B = "用户: 所以，你不必害怕。"

UNIT = [1.0, 0.0, 0.0, 0.0]


def _tilted(cosine: float) -> list:
    """与 UNIT 的余弦恰为 `cosine` 的单位向量（把余弦项钉成可算的量，不靠巧合）。"""
    return [cosine, math.sqrt(max(0.0, 1.0 - cosine * cosine)), 0.0, 0.0]


def _record(rid: str, content: str, embedding: list, categories: list | None = None):
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

    return MemoryRecord(
        id=rid,
        content=content,
        embedding=list(embedding),
        categories=list(categories or ["conversation"]),
        temperature=60.0,
        importance=60.0,
    )


def _mergeGroups(consolidation, records) -> list:
    """跑固化内核，返回真正发生合并的簇（≥2 个来源才算，与写回侧同一口径）。"""
    _, merge_results = consolidation.consolidate(records)
    return [sorted(mr.source_ids) for mr in merge_results if len(mr.source_ids or []) >= 2]


# ═══════════════════════════════════════════════════════════
# 判据本体：什么算"重复"
# ═══════════════════════════════════════════════════════════


def test_verbatimDuplicateStillMerges():
    """正例·逐字重复照合：两条内容相同、方向相同的记忆仍要并（这是合并这条腿仅剩的本意）。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    merged = _mergeGroups(engine, [
        _record("d1", SHORT, UNIT),
        _record("d2", SHORT, UNIT),
    ])
    assert merged == [["d1", "d2"]], f"逐字重复没被合并（实得 {merged}）⇒ 这条腿空转到了不该停的地方"


def test_containmentPairMergesKeepingLongestContent():
    """正例·包含关系：短者是长者的子串 ⇒ 合并，产物取最长 ⇒ 短者的正文一字不丢。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    records = [_record("c1", SHORT, UNIT), _record("c2", LONG, UNIT)]
    merged, merge_results = engine.consolidate(records)

    groups = [sorted(mr.source_ids) for mr in merge_results if len(mr.source_ids or []) >= 2]
    assert groups == [["c1", "c2"]], f"包含关系没被合并（实得 {groups}）"
    products = [m for m in merged if len(getattr(m, "merged_from", []) or []) >= 2]
    assert len(products) == 1, f"合并产物数量异常（实得 {len(products)}）"
    assert products[0].content == LONG, (
        "产物不是最长那条（实得 %r）⇒ 包含关系下'取最长'仍保证短者正文在产物里，这条不能退"
        % products[0].content
    )


def test_cosineOneButDifferentContentNoLongerMerges():
    """§6-218 主反例：余弦打满 ≠ 内容等价 —— `IMP-探针` 与 `DB-探针` 是两件事。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    groups = _mergeGroups(engine, [
        _record("p1", PROBE_A, UNIT),
        _record("p2", PROBE_B, UNIT),
    ])
    assert groups == [], (
        "余弦 1.0 就把两条不同内容并成一簇、独有正文随退役消失（实得 %s）⇒ 甲3 的判据没装上" % groups
    )


def test_midBandDialogueTurnsDoNotMergeEvenWhenContained():
    """kai 的形状：内容互不相同的对话回合永不进同簇；余弦低于近等价下限也不放行。

    这里刻意用一对**包含关系**的内容配 0.87 的余弦，单独钉住"余弦项仍在做决定"——
    内容项由 `test_cosineOneButDifferentContentNoLongerMerges` 单独钉。
    """
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    groups = _mergeGroups(engine, [
        _record("k1", SHORT, UNIT),
        _record("k2", LONG, _tilted(0.87)),
    ])
    assert groups == [], f"余弦 0.87 就批准合并（实得 %s）⇒ 近等价下限没生效" % groups


def test_kaiTurnsInProductionBandStaySeparate():
    """拿 §6-218 量到的现网值复现：默认阈值 0.7、kai 那 4 条互不相同的回合（0.71~0.88）。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation()  # 现网值：data/sleep_settings 缺位时构造默认 0.7
    assert engine.similarity_threshold == pytest.approx(0.7), "本格的前提是'现网生效阈值仍是 0.7'"
    groups = _mergeGroups(engine, [
        _record("t1", TURN_A, UNIT),
        _record("t2", TURN_B, _tilted(0.88)),
    ])
    assert groups == [], (
        "两条不同的对话回合被并成一条、另 1 条独有正文退役（实得 %s）⇒ §6-218 的误伤照旧" % groups
    )


def test_loweredThresholdCannotReopenSemanticMerging():
    """阈值调低不许把旧病放回来：0.3 也拦不住"内容不等价"——`max()` 那条下限是真门。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(similarity_threshold=0.3)
    groups = _mergeGroups(engine, [
        _record("l1", PROBE_A, UNIT),
        _record("l2", PROBE_B, UNIT),
    ])
    assert groups == [], (
        "把 similarity_threshold 调到 0.3 就重新按余弦批准合并（实得 %s）"
        "⇒ 阈值成了误伤的旁路，甲3 的门被调低拉穿了" % groups
    )


def test_thresholdStillTightensWithinTheEquivalentBand():
    """反向钉：阈值不许拉低下限，但**调高仍然真的收紧** —— 参数不是装饰。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    def _pair():
        # 每侧各取一份新对象：consolidate 会就地衰减温度，复用同一批会让退役
        # 状态串到下一次调用，"没合"就成了假绿。
        return [_record("h1", SHORT, UNIT), _record("h2", LONG, _tilted(0.99))]

    loose = SleepConsolidation(similarity_threshold=0.7)
    assert _mergeGroups(loose, _pair()) == [["h1", "h2"]], (
        "包含关系 + 余弦 0.99 没合 ⇒ 近等价的正例被门夹掉了"
    )

    strict = SleepConsolidation(similarity_threshold=0.995)
    assert _mergeGroups(strict, _pair()) == [], (
        "阈值 0.995 仍放行了余弦 0.99 的一对 ⇒ similarity_threshold 在这条腿上已经没有消费方"
    )


def test_blankContentIdentityNeverMerges():
    """空键＝无内容身份（纯标点/空白），不得互吞 —— 沿用 `content_identity` 的口径。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    groups = _mergeGroups(engine, [
        _record("b1", "！！！", UNIT),
        _record("b2", "？？？", UNIT),
    ])
    assert groups == [], f"两条没有内容身份的行被并成一条（实得 %s）⇒ 空写入互相吞没" % groups


# ═══════════════════════════════════════════════════════════
# 写回闭环：合并真开始跑之后不许丢事实
# ═══════════════════════════════════════════════════════════


def _seedAndMerge(tmp_path: Path, contents: list, category: str | None):
    """经生产出口写两行 → 注入嵌入（现网写侧仍未填，理由见 §6-215）→ 跑固化 + 共享写回。"""
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    for content in contents:
        if category is None:
            manager.remember(content=content)
        else:
            manager.remember(content=content, category=category)

    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    source_ids = sorted(r.id for r in records)
    for rec in records:
        rec.embedding = list(UNIT)

    engine = SleepConsolidation(memory_manager=manager)
    cycle = engine.run_sleep_cycle(records, phase="sleep")
    stats = write_back_consolidation_result(manager, cycle)
    return manager, source_ids, stats


def _rows(manager) -> list:
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "stage": r.get("lifecycle_stage"),
            "category": r.get("category"),
            "merged_from": (r.get("metadata") or {}).get("merged_from"),
        }
        for r in manager.get_all_memories()
    ]


def test_mergedFactStaysRetrievableAfterWriteBack(tmp_path: Path):
    """合并的产物必须活着：实测（本轮现量）默认分类下 remember() 被内容门改道成"命中某条源"，
    随后那道源连同另一条一起被 soft-forget ⇒ 活跃库里这条事实**一条都不剩**。

    甲3 让"逐字/包含重复"成为合并的主路，这一击正是它要消灭的东西，不能带着它开这条腿。
    """
    manager, source_ids, _stats = _seedAndMerge(tmp_path, [SHORT, LONG], None)
    rows = _rows(manager)

    survivors = [r for r in rows if r["stage"] not in ("archived", "forgotten")]
    assert len(survivors) == 1, f"合并后活跃行应恰为 1 条产物（实得 {rows}）"
    assert survivors[0]["content"] == LONG, (
        "活跃产物行的正文不是最长那条（实得 %r）⇒ 独有内容被吞" % survivors[0]["content"]
    )
    assert sorted(r["id"] for r in rows if r["stage"] == "forgotten") == source_ids, (
        "退役的不是那两条源（实得 %s，源 %s）" % ([r["id"] for r in rows if r["stage"] == "forgotten"], source_ids)
    )


def test_productRowCarriesMergedFromProvenance(tmp_path: Path):
    """§6-218 点名的断点：`MergeResult.source_ids` 算出来了却没落到产物行上，
    "这条记忆是那几条合出来的"在库内不可回查（只在 sleep_logs.json 里）。纯接线，不需裁。"""
    manager, source_ids, _stats = _seedAndMerge(tmp_path, [SHORT, LONG], None)
    rows = _rows(manager)

    products = [r for r in rows if r["merged_from"]]
    assert len(products) == 1, f"带来源的产物行应恰为 1 条（实得 {rows}）"
    assert sorted(products[0]["merged_from"]) == source_ids, (
        "产物行的 merged_from 不等于被合并的来源（实得 %s，源 %s）"
        % (products[0]["merged_from"], source_ids)
    )


def test_mergeKeepsTheSourceCategory(tmp_path: Path):
    """`Memory.to_dict()` 只有单数 `category`，而 `MemoryRecord.from_dict()` 读的是复数
    `categories` ⇒ 经生产出口的每条记录分类恒空，写回时落到 `["general"]` 兜底，
    合并把 "conversation" 的事实挪到了另一个分类面（按分类过滤的检索再也看不见它）。"""
    manager, _source_ids, _stats = _seedAndMerge(tmp_path, [SHORT, LONG], "conversation")
    rows = _rows(manager)

    survivors = [r for r in rows if r["stage"] not in ("archived", "forgotten")]
    assert len(survivors) == 1, f"前置：活跃产物行恰 1 条（实得 {rows}）"
    assert survivors[0]["category"] == "conversation", (
        "合并产物的分类被挪走（原 conversation，实得 %r）⇒ 分类没跨过那道跨界字典"
        % survivors[0]["category"]
    )
