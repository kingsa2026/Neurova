"""乙＋甲（§6-223 那张三态票的执行序）：固化**按隔离作用域分桶**，写回**进源行自己的作用域**。

现网第一条合并真发生之后停住的原因不是判据，是一条归属事实（§6-223）：`default` 那只 agent 的
正文库里，行属 `(default, ne-alice, alice)` 与 `(default, 1, 1)`，而固化跑在没有请求边界的进程
作用域 `(default, default, default)` ⇒ 退役与温度两条腿被 P1-6 的归属校验整段拒
（`拒绝越权删除记忆: id=mem_000010 …`），写回统计成 `added=2 / forgotten=0` —— 合并名义上做了，
实际一点没收拢；更糟的是聚类吃的是 `get_all_memories()` 的全量行，**一只 agent 内跨 neuser/user
的行会被并进同一条**，alice 的事实变成 default 作用域的行。

裁定是 丙→乙→甲：
- 乙＝聚类按 `(agent_id, neuser_id, user_id)` 分桶，跨归属永不进同簇；
- 甲＝写回按源行归属进入 `manager.request_scope(...)` 再落——**不是**拿 `agent_wide=True` 把越权写成契约。
最后一格按代码形状钉住这一条（判据钉形态不钉词）。
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.cognitive_body_store import bodyManager

AGENT = "scopebucket"
DUP = "登录页验证码在弱网下加载超时"
DUP_LONG = "登录页验证码在弱网下加载超时，用户已提交投诉"
UNIT = [1.0, 0.0, 0.0]


def _record(rid: str, content: str, scope, embedding: list = UNIT):
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord

    agent_id, neuser_id, user_id = scope
    return MemoryRecord(
        id=rid,
        content=content,
        embedding=list(embedding),
        categories=["conversation"],
        temperature=60.0,
        importance=60.0,
        agent_id=agent_id,
        neuser_id=neuser_id,
        user_id=user_id,
    )


def _realMerges(merge_results) -> list:
    return [sorted(mr.source_ids) for mr in merge_results if len(mr.source_ids or []) >= 2]


# ═══════════════════════════════════════════════════════════
# 乙：跨归属永不进同簇
# ═══════════════════════════════════════════════════════════


def test_foreignScopesNeverShareACluster():
    """内容完全相同、余弦 1.0，但归属不同 ⇒ 不许合并（今天会被并成一条，产物落到进程默认作用域）。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    _merged, merge_results = engine.consolidate([
        _record("a1", DUP, (AGENT, "ne-alice", "alice")),
        _record("a2", DUP, (AGENT, "ne-bob", "bob")),
    ])
    groups = _realMerges(merge_results)
    assert groups == [], (
        "跨 neuser/user 的两条被并成一条（实得 %s）⇒ alice 的事实会变成别人的行，"
        "检索与可见性都跟着串" % groups
    )


def test_sameScopeDuplicatesStillMerge():
    """反向钉：分桶不许把同归属的重复也挡掉（乙 只收"跨归属"这一刀）。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    _merged, merge_results = engine.consolidate([
        _record("s1", DUP, (AGENT, "ne-alice", "alice")),
        _record("s2", DUP_LONG, (AGENT, "ne-alice", "alice")),
    ])
    assert _realMerges(merge_results) == [["s1", "s2"]], (
        "同归属的近等价重复没合并 ⇒ 分桶收得比裁定更紧，这条腿又空转了"
    )


def test_productInheritsItsSourcesScope():
    """产物必须继承源行的归属三元组——今天 `consolidate` 在没有 isolation_context 时
    把产物硬设成 ("default","default","default")，alice 的合并产物因此落到别人的作用域。"""
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    engine = SleepConsolidation(memory_manager=None)
    merged, _results = engine.consolidate([
        _record("p1", DUP, (AGENT, "ne-alice", "alice")),
        _record("p2", DUP_LONG, (AGENT, "ne-alice", "alice")),
    ])
    products = [m for m in merged if len(getattr(m, "merged_from", []) or []) >= 2]
    assert len(products) == 1, f"前置：产物恰 1 条（实得 {len(products)}）"
    assert (products[0].agent_id, products[0].neuser_id, products[0].user_id) == (
        AGENT, "ne-alice", "alice"
    ), (
        "产物归属是 (%s,%s,%s) 而不是源行的 (%s,ne-alice,alice) ⇒ 合并把事实搬出原作用域"
        % (products[0].agent_id, products[0].neuser_id, products[0].user_id, AGENT)
    )


# ═══════════════════════════════════════════════════════════
# 甲：写回进源行自己的作用域（而不是绕过归属校验）
# ═══════════════════════════════════════════════════════════


def _seedForeignDupPair(tmp_path: Path):
    """在**外来作用域**里种一对真重复行，并从生产出口取数＋注入嵌入。

    嵌入仍要在记录面注入：现网写侧不填嵌入（§6-215 现量），而 `cluster_by_similarity`
    只在两侧都有嵌入时才打分——不注入就恒单例，本档会"全绿"却什么都没咬到（形态集第 189 条）。
    """
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    with manager.request_scope("ne-alice", "alice"):
        manager.remember(content=DUP, category="conversation")
        manager.remember(content=DUP_LONG, category="conversation")
        manager.remember(content="本周会议纪要讨论了排期与预算分配", category="conversation")

    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    for rec in records:
        if "会议纪要" not in rec.content:
            rec.embedding = list(UNIT)
        else:
            rec.embedding = [0.0, 0.0, 1.0]
    engine = SleepConsolidation(memory_manager=manager)
    cycle = engine.run_sleep_cycle(records, phase="sleep")
    stats = write_back_consolidation_result(manager, cycle)
    return manager, stats


def _dbRows(tmp_path: Path) -> list:
    import sqlite3

    db = tmp_path / "neurova_memories_persist.db"
    con = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("select * from memories order by id").fetchall()]
    finally:
        con.close()


def test_writeBackRetiresSourcesInTheirOwnScope(tmp_path: Path):
    """主格：源行属外来作用域时，退役那一腿必须真落地。

    现网形状（§6-223）：`added=2 / forgotten=0`，日志逐条"拒绝越权删除记忆" ⇒ 重复行照旧活跃，
    合并只复制不收拢。修法是写回时按源行归属 `request_scope(...)` 再 forget，而不是 agent_wide。
    """
    manager, stats = _seedForeignDupPair(tmp_path)
    rows = _dbRows(tmp_path)

    assert stats["forgotten"] == 2, (
        "退役那一腿没做成（实得 %s）⇒ 归属门把 soft-forget 整段拒了，合并只是复制" % stats
    )
    active = [r for r in rows if str(r["lifecycle_stage"]) not in ("archived", "forgotten")]
    assert len(active) == 2, (
        "活跃行应为「1 条产物 + 1 条无关单例」（实得 %s）"
        % [(r["id"], r["content"][:16], r["lifecycle_stage"]) for r in active]
    )
    product = next(r for r in active if str(r["id"]).startswith("merged_"))
    assert (product["neuser_id"], product["user_id"]) == ("ne-alice", "alice"), (
        "产物行落在了 (%s,%s)，而它的源行属 (ne-alice,alice) ⇒ 写回没进源行的作用域"
        % (product["neuser_id"], product["user_id"])
    )
    assert product["category"] == "conversation", (
        "产物分类是 %r ⇒ 跨界的分类又丢了" % product["category"]
    )


def test_writeBackPersistsTheDecayedTemperatureForForeignScope(tmp_path: Path):
    """温度腿同一段病灶：外来作用域的单例行，`update_memory` 也被归属门拒——
    而它不抛异常，只回 False，统计却照旧 `updated += 1`（**这个计数本身就是谎**）。
    本格不看计数，直接查盘上的温度有没有真的降下来。

    写回的读数来源只认一份：`consolidate` 里 `apply_sleep_decay` 已经走过
    `TemperatureEngine.on_decay`（衰减的唯一实现在 temperature.py）。写回侧原来另写了一套
    "按闲置天数线性降"的公式——那是同功能的第二份实现，且它读的 `last_accessed_at`
    **在 `MemoryRecord` 里根本没有这个字段**（`from_dict` 不映射、dataclass 没声明），
    于是 `days_idle` 恒 0、那套公式恒等于"原样写回"，从没减过任何东西（§6-223 现量：
    盘上 65.0 → 65.0）。本批按教义第 7 条把它并掉：写回只落引擎已经算好的那个温度。
    """
    from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation
    from neurova.cognitive_layers.memory_layer.sleep_writeback import (
        write_back_consolidation_result,
    )

    manager = bodyManager(tmp_path, agentId=AGENT)
    with manager.request_scope("ne-alice", "alice"):
        mid = manager.remember(content="本周会议纪要讨论了排期与预算分配", category="conversation")
        # 造一条"已经老了 30 天"的行：`apply_sleep_decay` 委托的 `TemperatureEngine.on_decay`
        # 按闲置时长算衰减量，新建的行 created_at≈now ⇒ 算出来就是 0 度、看不出腿有没有落地。
        # 生产里行本来就会随时间变老，这里只是把那一刻提前——直接改对象再持久化，
        # 与 §6-215 那档"在对象面上补生产今天还不填的字段"同一形。
        with manager._lock:
            row = manager._memories[mid]
            row.created_at = datetime.now(timezone.utc) - timedelta(days=30)
            manager._persist_memory(row)
        temperatureBefore = float(row.temperature)
    assert temperatureBefore > 20.0, "前置：温度得高到引擎会衰减的量级，否则『没降』无从判断"

    records = [MemoryRecord.from_dict(m) for m in manager.get_all_memories()]
    engine = SleepConsolidation(memory_manager=manager)
    cycle = engine.run_sleep_cycle(records, phase="sleep")
    stats = write_back_consolidation_result(manager, cycle)

    after = [r for r in _dbRows(tmp_path) if r["id"] == mid]
    assert after, "行没了（不该发生）"
    assert float(after[0]["temperature"]) < temperatureBefore, (
        "外来作用域的单例温度没被衰减（盘上 %s，原 %s）⇒ 温度腿同样被归属门拒，"
        "而统计里的 updated 把失败算成了成功" % (after[0]["temperature"], temperatureBefore)
    )
    assert stats["updated"] == 1, (
        "温度腿真落地了，计数却还是 %s ⇒ updated 统计的是调用次数，不是做成与否" % stats
    )


def test_writeBackDoesNotBypassTheOwnershipGate():
    """形状锁（反向钉）：修法是"进入源行归属的作用域再落"，**不许**改成
    `forget(..., agent_wide=True)` / `update_memory(..., agent_wide=True)` 把越权写成契约
    ——§6-223 那张票里 甲 之所以排在 乙 之后，就是为了先把"跨归属不该合并"钉死，
    再让写回按归属落；一旦允许 agent_wide，归属校验在这条腿上就永久没了。"""
    target = Path(__file__).resolve().parents[3] / "neurova" / "cognitive_layers" \
        / "memory_layer" / "sleep_writeback.py"
    assert target.exists(), "写回档不在 expected 处（%s）⇒ 这格会空转" % target
    tree = ast.parse(target.read_text(encoding="utf-8"))

    bypass = []
    scoped = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if "agent_wide" in [kw.arg for kw in node.keywords]:
            bypass.append("%s(agent_wide=…)" % getattr(callee, "attr", "?"))
        if isinstance(callee, ast.Attribute) and callee.attr == "request_scope":
            scoped += 1
    assert not bypass, "写回里出现了绕过归属校验的取法：%s" % bypass
    assert scoped >= 1, (
        "写回一次都没进过源行的作用域（`request_scope` 命中 0 处）⇒ 甲 那一腿没接上，"
        "跨归属的退役/温度照旧被拒"
    )
