"""睡眠固化的输入面必须认得"已退役"：soft-forget 之后源记忆仍是行，不许每轮再合一次。

实测形状（本批开工前的活体读数）：两个源被合并、写回把它们的 `lifecycle_stage` 标成
`forgotten`（soft forget 不删行，这是设计）；下一轮 `get_all_memories()` 照旧把这两行喂进
`run_sleep_cycle` ⇒ 同一批源**再合并一次**，盘上稳定 +1 行/轮（2026-09-05 全库翻倍那笔账的
线性版）。根因有两击，必须一起修：
  ① `MemoryRecord.from_dict()` 读的是 `data.get("is_archived")`，而 `Memory.to_dict()`
     **根本没有这个键**（真键是 `lifecycle_stage`）⇒ 状态事实在跨界那一刻就丢了；
  ② `consolidate()` 把传进来的记录全量拿去聚类，从不看状态 ⇒ 只修①的话聚类照旧收它们。
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

AGENT = "sleep-retired"
SAME_EMB = [1.0, 0.5, 0.25]
OTHER_EMB = [0.0, 0.0, 1.0]


def _symbols():
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )
    from tests.cognitive_body_store import bodyManager

    return MemoryRecord, SleepConsolidation, write_back_consolidation_result, bodyManager


def _diskRows(tmp_path: Path):
    db = tmp_path / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % os.path.abspath(db).replace("\\", "/"), uri=True)
    try:
        return con.execute("select id, lifecycle_stage from memories order by id").fetchall()
    finally:
        con.close()


def _stageById(rows, memoryId: str):
    for rid, stage in rows:
        if rid == memoryId:
            return str(stage)
    return None


def _seedTwoSimilarManager(tmp_path: Path):
    """真 manager + 两条真行：内容**近等价**（短者是长者的子串）且同嵌入 ⇒ 按甲3（§6-219）必同簇。

    夹具原样是"…第一例 / …第二例"——两条互不包含的不同事实，那正是 §6-218 证明会丢内容的
    形状；本档问的是"退役行还进不进聚类"，用一对合法重复即可，不必借旧规则。
    """
    _, _, _, bodyManager = _symbols()
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="登录页验证码在弱网下加载超时")
    manager.remember(content="登录页验证码在弱网下加载超时，用户已提交投诉")
    manager.remember(content="本周会议纪要讨论了排期与预算分配")
    return manager


def _records(manager, MemoryRecord):
    out = []
    for m in manager.get_all_memories():
        rec = MemoryRecord.from_dict(m)
        rec.embedding = OTHER_EMB if "会议纪要" in (m.get("content") or "") else SAME_EMB
        out.append(rec)
    return out


def test_fromDictCarriesLifecycleStage(tmp_path: Path):
    """红①：跨界转换必须认得真键。`lifecycle_stage` 是退役与否的唯一出处。"""
    MemoryRecord, _, _, _ = _symbols()

    forgotten = MemoryRecord.from_dict({
        "id": "mem_x", "content": "c", "lifecycle_stage": "forgotten",
    })
    assert forgotten.is_archived is True, (
        "soft-forget 的行经 from_dict 后 is_archived 仍是 False ⇒ 状态事实在进入固化时就没了"
    )
    archived = MemoryRecord.from_dict({
        "id": "mem_y", "content": "c", "lifecycle_stage": "archived",
    })
    assert archived.is_archived is True
    active = MemoryRecord.from_dict({
        "id": "mem_z", "content": "c", "lifecycle_stage": "active",
    })
    assert active.is_archived is False, "活跃行被判成退役 ⇒ 固化整轮空转，反向也要钉"
    # 兼容既有形状：MemoryRecord.to_dict() 自己写出的 is_archived 仍要认
    selfCarried = MemoryRecord.from_dict({
        "id": "mem_w", "content": "c", "is_archived": True,
    })
    assert selfCarried.is_archived is True


def test_secondCycleDoesNotReMergeRetiredSources(tmp_path: Path):
    """红②主格：第一轮合并后，第二轮盘上不得再多出一行合并产物。"""
    MemoryRecord, SleepConsolidation, writeBack, _ = _symbols()
    manager = _seedTwoSimilarManager(tmp_path)
    sleep = SleepConsolidation(memory_manager=manager)

    res1 = sleep.run_sleep_cycle(_records(manager, MemoryRecord), phase="deep_sleep")
    writeBack(manager, res1)
    rowsAfterFirst = _diskRows(tmp_path)

    res2 = sleep.run_sleep_cycle(_records(manager, MemoryRecord), phase="deep_sleep")
    # 聚类面：已退役的两个源不许再被拉进同一个簇
    clusters = [sorted(getattr(r, "source_ids", []) or []) for r in (res2.get("merge_results") or [])]
    retiredIds = [rid for rid, stage in rowsAfterFirst if str(stage) == "forgotten"]
    assert retiredIds, "前置塌了：第一轮没把任何源标成 forgotten，下面那条断言是空转"
    for cluster in clusters:
        assert not set(cluster) <= set(retiredIds), (
            "第二轮把已被合并、已 soft-forget 的源**又合并了一次**：簇=%s 全在退役集 %s 里 ⇒ "
            "每轮巩固稳定 +1 行（2026-09-05 翻倍账的线性版）" % (cluster, retiredIds)
        )
    writeBack(manager, res2)
    rowsAfterSecond = _diskRows(tmp_path)
    assert len(rowsAfterSecond) == len(rowsAfterFirst), (
        "第二轮让正文库多了一行：%s → %s" % (rowsAfterFirst, rowsAfterSecond)
    )


def test_retiredRowsAreNotRewrittenEveryCycle(tmp_path: Path):
    """红③：写回侧不该每轮对已退役的行发 update（既虚报 updated，又把状态卷进固化）。"""
    MemoryRecord, SleepConsolidation, writeBack, _ = _symbols()
    manager = _seedTwoSimilarManager(tmp_path)
    sleep = SleepConsolidation(memory_manager=manager)

    res1 = sleep.run_sleep_cycle(_records(manager, MemoryRecord), phase="deep_sleep")
    writeBack(manager, res1)
    retiredIds = {rid for rid, stage in _diskRows(tmp_path) if str(stage) == "forgotten"}
    assert retiredIds, "前置塌了：第一轮没产生退役行"

    touched = []
    originalUpdate = manager.update_memory

    def spy(**kwargs):
        touched.append(kwargs.get("memory_id"))
        return originalUpdate(**kwargs)

    manager.update_memory = spy  # type: ignore[method-assign]
    res2 = sleep.run_sleep_cycle(_records(manager, MemoryRecord), phase="deep_sleep")
    stats2 = writeBack(manager, res2)
    manager.update_memory = originalUpdate  # type: ignore[method-assign]

    hit = sorted(set(touched) & retiredIds)
    assert not hit, (
        "第二轮仍对已退役的源发 update（%s 条）⇒ 固化把退役行当活跃记忆重算一遍，"
        "并把 stats['updated'] 虚报成 %s" % (hit, stats2.get("updated"))
    )


def test_firstRealMergeStillLandsAndForgetsBothSources(tmp_path: Path):
    """反证本批没把合并本身弄坏：真合并（≥2 源）照旧被识别，两个源照旧 soft-forget。"""
    MemoryRecord, SleepConsolidation, writeBack, _ = _symbols()
    manager = _seedTwoSimilarManager(tmp_path)
    sleep = SleepConsolidation(memory_manager=manager)

    res = sleep.run_sleep_cycle(_records(manager, MemoryRecord), phase="deep_sleep")
    clusters = [sorted(getattr(r, "source_ids", []) or []) for r in (res.get("merge_results") or [])]
    realMerges = [c for c in clusters if len(c) >= 2]
    assert len(realMerges) == 1, "前置塌了：两条相近记录没聚成簇，下面的断言没有对象：%s" % clusters

    stats = writeBack(manager, res)
    assert stats["added"] == 1, "≥2 源的簇没被写回新增 ⇒ 合并闭环断了"
    rowsAfter = _diskRows(tmp_path)
    forgottenAfter = {rid for rid, stage in rowsAfter if str(stage) == "forgotten"}
    assert set(realMerges[0]) <= forgottenAfter, (
        "合并产物落了，源记忆却没被 soft-forget（退役集=%s，簇=%s）⇒ 同一内容双份留在库里，"
        "下一轮必然再合一次" % (sorted(forgottenAfter), realMerges[0])
    )
