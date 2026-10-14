"""引擎 flush 之后，同进程的取数面必须等于正文单源（§6-211 丙案的契约）。

缺陷形状：`_flushL0ToBody()` 只调 `persist_memory_batch()`，而后者只写盘、不动
`manager._memories`；固化/召回那 12 个调用档读的正是后者 ⇒ 引擎写进去的行要等下次
重启才进得来。修法不新造平行体系：仓里已有唯一对账口 `reload_memories()`
（`visibility.py:43` 那个"不重启就看见"的端点用的就是它），本批把它接到**制造分歧的
那一点**上。

因此这一族同时钉住两个不许越界的方向：对账只准发生在 flush 那一点（不是每次 store、
更不是每次取数都去扫盘——缓存退回加速层，不是退化成每次都全表读），以及 L0 里没 flush
的节点**不许**被倒灌进取数面（否则 L0 又变成第二个数据根）。
"""
from __future__ import annotations

from pathlib import Path

from tests.cognitive_body_store import bodyManager, cognitiveEngine

AGENT = "flush-converge"


def _nodes(MemoryType, UnifiedMemoryNode, marker: str, category: str = "general"):
    return UnifiedMemoryNode(
        content="取数面对账 %s" % marker,
        memory_type=MemoryType.SEMANTIC,
        category=category,
        temperature=55.0,
        metadata={"probe_marker": marker},
    )


def _counter(manager):
    """把唯一对账口包一层计数——只计数，不改行为。"""
    calls = {"reload": 0}
    original = manager.reload_memories

    def counted(*args, **kwargs):
        calls["reload"] += 1
        return original(*args, **kwargs)

    manager.reload_memories = counted  # type: ignore[method-assign]
    return calls


def test_engineFlushedRowIsVisibleToFetchFaceSameProcess(tmp_path: Path):
    """本批的主红：引擎 flush 完，同进程的 get_all_memories() 就该看见那一行。"""
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)
    engine.store(_nodes(MemoryType, UnifiedMemoryNode, "FLUSH-VISIBLE-A"))
    assert engine._flushL0ToBody() == 1

    contents = [m.get("content") or "" for m in manager.get_all_memories()]
    assert any("FLUSH-VISIBLE-A" in c for c in contents), (
        "引擎刚并进正文库的行在同进程取数面上一条都没有 ⇒ 固化与那 12 个调用档"
        "读到的是滞后一整个进程生命周期的快照（§6-211 的形状）：%s" % contents
    )


def test_managerOwnRememberStaysVisible(tmp_path: Path):
    """反空转：manager 自己那条写路本来就看得见——改动前后都必须绿。

    缺这一格，上面那条红可能被"把取数面整个换成别的口径"假实现骗过去。
    """
    manager = bodyManager(tmp_path, agentId=AGENT)
    manager.remember(content="manager 直写 KEEP-VISIBLE-B")
    contents = [m.get("content") or "" for m in manager.get_all_memories()]
    assert any("KEEP-VISIBLE-B" in c for c in contents)


def test_reconciledRowKeepsItsKeysAndMetadata(tmp_path: Path):
    """并进正文再取回来的行，键与 metadata 必须原样在（类别信息不许在盘上走一遭就丢）。"""
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)
    engine.store(UnifiedMemoryNode(
        content="推理链: 问题 → 答案 ROUND-TRIP-C",
        memory_type=MemoryType.EPISODIC,
        category="reasoning_trace",
        temperature=100.0,
        trace_id="round-trip-1",
        metadata={"steps_count": 3},
    ))
    engine._flushL0ToBody()

    rows = [m for m in manager.get_all_memories()
            if "ROUND-TRIP-C" in (m.get("content") or "")]
    assert len(rows) == 1
    row = rows[0]
    for key in ("id", "content", "temperature", "metadata"):
        assert key in row, "取数面返回的行缺键 %s ⇒ 12 个调用档里按键取值的那些要空转" % key
    meta = row.get("metadata") or {}
    assert meta.get("cse_category") == "reasoning_trace", (
        "类别没随正文往返 ⇒ 单源其实没带它走，§6-208 的可见性词汇在取数面上无从谈起：%s" % meta
    )


def test_unflushedL0NodeStaysOutOfFetchFace(tmp_path: Path):
    """L0 不许被倒进取数面——否则刚收口的单源又长出第二个。"""
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)
    engine.store(_nodes(MemoryType, UnifiedMemoryNode, "L0-MUST-NOT-LEAK-D"))
    assert engine._l0_buffer, "前置塌了：这条压根没进 L0，下面的断言是空转"

    contents = [m.get("content") or "" for m in manager.get_all_memories()]
    assert not any("L0-MUST-NOT-LEAK-D" in c for c in contents), (
        "没 flush 的 L0 节点出现在取数面 ⇒ 等于把 L0 当第二份正文倒灌进快照"
    )


def test_reconcileHappensAtFlushPointNotPerStore(tmp_path: Path):
    """对账只准装在 flush 那一点：未到阈值的 store 一次也不触发，跨 flush 恰一次。"""
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    calls = _counter(manager)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)

    for i in range(3):
        engine.store(_nodes(MemoryType, UnifiedMemoryNode, "NO-FLUSH-%d" % i))
    assert calls["reload"] == 0, (
        "每次 store 都对账＝把 flush 的批量语义拆了（阈值本来就是为了省掉逐条落盘的开销）"
    )

    assert engine._flushL0ToBody() == 3
    assert calls["reload"] == 1, (
        "flush 之后一次也没对账 ⇒ 制造分歧的那一点仍没人收尾，"
        "引擎写的行照旧要等下次重启才进得来"
    )


def test_fetchFaceReadsDoNotScanBodyEveryCall(tmp_path: Path):
    """反向锁：读取数面不该扫盘——缓存退回的是加速层，不是每次全表读。"""
    manager = bodyManager(tmp_path, agentId=AGENT)
    calls = _counter(manager)
    manager.remember(content="只读不扫盘 E")
    for _ in range(10):
        manager.get_all_memories()
    assert calls["reload"] == 0, (
        "取数面每次读都对账＝把滞后换成每调用一次全表扫；库一大就把 12 个调用档"
        "（含五条检索通道，每查询都走）变成查询放大器"
    )


def test_failedBodyWriteKeepsL0AndSkipsReconcile(tmp_path: Path):
    """写盘没落地时：L0 与恢复文件都得留着，且**不许**去对账。

    对账口会回收"盘上没有"的快照行；若写侧静默失败还去对账，那条刚从 L0 清掉、
    又没落盘的行就只剩内存里这一份副本——回收即永久丢（M-11 那个"失败不清缓冲"
    的承诺，被 `persist_memory_batch` 自己吞异常从下面破掉了）。
    """
    from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
        MemoryType,
        UnifiedMemoryNode,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    calls = _counter(manager)
    engine = cognitiveEngine(tmp_path, agentId=AGENT, manager=manager)
    engine.store(_nodes(MemoryType, UnifiedMemoryNode, "WRITE-FAILED-F"))

    def _fail(_mems):
        return False

    manager.persist_memory_batch = _fail  # type: ignore[method-assign]
    assert engine._flushL0ToBody() == 0
    assert calls["reload"] == 0, "写盘没成功却对账＝让回收口删掉唯一那份内存副本"
    assert any("WRITE-FAILED-F" in n.content for n in engine._l0_buffer), (
        "写盘失败却清了 L0——节点再无落处"
    )
    assert "WRITE-FAILED-F" in engine._wal_path.read_text(encoding="utf-8"), (
        "写盘失败却收敛了恢复文件"
    )
    hits = [n for n in engine.retrieve("WRITE-FAILED-F", limit=10)]
    assert any("WRITE-FAILED-F" in n.content for n in hits), (
        "留在 L0 的行检索也该照样取到，否则「失败保缓冲」只是把丢数据推迟到查询那一步"
    )


def test_managerDoesNotImportEngineSoLockOrderIsOneWay():
    """锁序不变量：对账走 manager 的 RLock，装在引擎咽喉上才不互咬。

    成立的前提就是 manager 一侧不引引擎——反向一旦出现（manager 持自己的锁再取
    引擎的 WAL/L0 锁），与「引擎锁 → manager 锁」构成死锁序。这一格钉的是那条前提。
    """
    import re
    from pathlib import Path as _P

    source = (_P(__file__).resolve().parents[3]
              / "neurova" / "cognitive_layers" / "memory_layer" / "manager.py"
              ).read_text(encoding="utf-8")
    hits = re.findall(r"cognitive_storage_engine|CognitiveStorageEngine", source)
    assert hits == [], (
        "manager 反过来引了引擎（%d 处）⇒ 本批把对账装在引擎咽喉上的锁序前提失效，"
        "要先重定装点后" % len(hits)
    )
