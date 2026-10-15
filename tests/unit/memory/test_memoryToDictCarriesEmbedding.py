"""正文出口 `Memory.to_dict()` 必须把嵌入带得出去——跨界字典缺哪个键，下游就失明哪个事实。

实据：`Memory.from_dict()` 认 `embedding`（`:499` 那行注释写着"M-16: embedding 与
last_accessed_at 原先不回填, round-trip 即丢"），**但写侧 `to_dict()` 的 23 个键里没有它**
⇒ round-trip 单向丢。后果不止丢字段：睡眠固化的输入面是
`manager.get_all_memories()`（＝`to_dict()` 的列表）→ `MemoryRecord.from_dict()` →
`cluster_by_similarity` 只在两侧都有嵌入时才打分 ⇒ 嵌入恒 `[]` ⇒ **聚类恒单例、
"合并"在自动路上从未触发过**（§6-214 记的那张票）。

本档按形态集第 189 条的要求，除了键集合本身，还有一格**从生产出口取数**走完
"写 → 跨界 → 固化成簇"的闭环——只在转换之后补数据的判据，测的是逻辑，测不到这条路通不通。
"""
from __future__ import annotations

from pathlib import Path

AGENT = "to-dict-embedding"
EMB_A = [1.0, 0.5, 0.25, 0.0]
EMB_B = [0.98, 0.52, 0.24, 0.01]
EMB_OTHER = [0.0, 0.0, 0.0, 1.0]


def test_toDictCarriesEmbeddingValue():
    """主红：对象上有嵌入，出口就必须带得出去。"""
    from neurova.cognitive_layers.memory_layer.models import Memory

    mem = Memory(id="mem_e", content="c")
    mem.embedding = list(EMB_A)
    data = mem.to_dict()
    assert "embedding" in data, (
        "出口没有 embedding 键 ⇒ 任何经 `to_dict()` 的读面都失明这个事实；"
        "本轮键集合=%s" % sorted(data.keys())
    )
    assert list(data["embedding"]) == EMB_A


def test_toDictEmitsEmptyListNotMissingKeyNorNone():
    """形状锁：空嵌入也给 `[]`，不给 None、也不缺键——两头与 from_dict 对称。"""
    from neurova.cognitive_layers.memory_layer.models import Memory

    data = Memory(id="mem_none", content="c").to_dict()
    assert data.get("embedding", "缺键") == [], (
        "空嵌入时出口形状不统一（实得 %r）⇒ 下游要么判 None 要么判缺键，"
        "两处各写一套兜底就是第二个事实源" % (data.get("embedding", "缺键"),)
    )


def test_roundTripKeepsEmbedding():
    """闭环锁：写→to_dict→from_dict 之后嵌入还在（M-16 修了读侧，本格钉写侧配平）。"""
    from neurova.cognitive_layers.memory_layer.models import Memory

    mem = Memory(id="mem_rt", content="c")
    mem.embedding = list(EMB_B)
    back = Memory.from_dict(mem.to_dict())
    assert list(back.embedding or []) == EMB_B, (
        "round-trip 丢了嵌入（实得 %r）⇒ 任何走这份字典的持久化/恢复路径都会静默清零"
        % (back.embedding,)
    )


def test_embeddingReachesConsolidationThroughTheProductionFace(tmp_path: Path):
    """从生产出口取数走完整条路：有嵌入时，固化的两条**内容近等价**记忆要真聚成一簇。

    夹具原样是"…甲例 / …乙例"——那是"语义相近即同簇"的形状，而 §6-218 实测证明那条规则
    的代价是丢内容，§6-219 甲3 已把准入换成"余弦达下限 **且** 归一化后短者为长者子串"。
    故这里改成包含关系的一对（EMB_A 与 EMB_B 的余弦实测 0.9997，过得了下限）。
    """
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from tests.cognitive_body_store import bodyManager

    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="登录页验证码在弱网下超时")
    manager.remember(content="登录页验证码在弱网下超时，重试两次后恢复")

    # 模拟"以后写侧开始填嵌入"的形状：只给对象赋值，不碰任何转换函数——
    # 转换之后补数据就测不到这条路（形态集第 189 条）。
    with manager._lock:
        rows = list(manager._memories.values())
        for mem, emb in zip(rows, (EMB_A, EMB_B)):
            mem.embedding = list(emb)

    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    assert all(len(r.embedding) == 4 for r in records), (
        "经生产出口取到的记录嵌入是空的（实得 %s）⇒ 出口没把事实带出去，"
        "固化那条腿永远聚不成簇" % [len(r.embedding) for r in records]
    )

    sleep = SleepConsolidation(memory_manager=manager)
    clusters = sleep.cluster_by_similarity(records)
    sizes = sorted(len(c) for c in clusters)
    assert sizes == [2], (
        "两条近等价记忆没聚成一簇（簇尺寸=%s）⇒ 合并这条路经生产出口走不通" % sizes
    )


def test_noEmbeddingWrittenTodayMeansNoBehaviorChange(tmp_path: Path):
    """现量锁：写侧今天没人填嵌入 ⇒ 本批补键不会让"合并"当场开始真跑。

    落笔即绿；它的红由变异提供（M5：给 `remember()` 的产物偷偷补一个假嵌入 ⇒ 这格转红，
    说明它确实在盯"这条路今天是否开工"）。
    """
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from tests.cognitive_body_store import bodyManager

    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="会议纪要讨论了排期")
    manager.remember(content="会议纪要讨论了预算")

    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    assert all(list(r.embedding) == [] for r in records), (
        "写侧已经开始填嵌入（实得 %s）⇒ 甲上线即开工，本格的前提变了，"
        "要按『合并真开始跑』重新评估行为面" % [r.embedding[:2] for r in records]
    )
    clusters = SleepConsolidation(memory_manager=manager).cluster_by_similarity(records)
    assert all(len(c) == 1 for c in clusters)
