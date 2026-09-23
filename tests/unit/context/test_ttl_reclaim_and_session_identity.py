# -*- coding: utf-8 -*-
"""B6-10 批次 D：TTL 回收的真调用点 + 会话身份写入方收口（Issue #90 §5 / §10 B6）。

两条死线的判据类同族（`no_consumer`），根因也同族 —— **定义了、生产到不了**：

1. `ContextPool.cleanup_expired`。池类文档承诺「``ttl_seconds>0`` 时过期条目经
   ``cleanup_expired()`` / 查询过滤剔除（先归档再剔除）」，但生产侧零调用点：
   读面（``draw`` / ``query`` / ``get_contexts``）只做**惰性过滤**，过期条目永远
   留在常驻列表里，``archived_by_reason["ttl"]`` 恒 0 —— "TTL 生效"在内存规模上
   是一笔空账（视图看不到、内存不回收）。
   修法（根因侧，不在读面加判空）：把回收接到池的**唯一写入咽喉** ``add_context``
   —— 所有写入方（含 swarm / voice / 摘要回写等旁路）自动继承；生产构造档
   ``ttl_seconds=0``（永不丢失）时只多一次比较、零额外开销。

2. `ContextOrchestrator.set_session_id`。会话身份有**两个写入方**（构造期入参 +
   ``build_context`` 每轮以 ``chat_room_id or ctx.session_id`` 刷新），而这个 setter
   在生产零调用点 —— 第二写入方就是第二份事实源（审计 D2 的裁决即"退役它的裁剪职责"，
   裁剪已收口到 `_window_cache_slot` 上限；剩下的赋值语义与每轮刷新并存，故一并删净）。
   修法：身份写入方收口为 `build_context` 每轮刷新一处，构造期入参只做初值。

判据落在「真调用点」与「唯一写入方」上：把回收调用从 ``add_context`` 拿掉、
或把 setter 加回，本文件对应断言必须转红。
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from neurova.context.eviction_ledger_db import EvictionLedgerDB  # noqa: E402
from neurova.context.pool_models import ContextInput, ContextSource  # noqa: E402
from neurova.context_pool import ContextPool  # noqa: E402
from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

ORCHESTRATOR_SOURCE = PROJECT_ROOT / "neurova" / "context" / "orchestrator.py"
POOL_SOURCE = PROJECT_ROOT / "neurova" / "context_pool.py"
PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_ttl_reclaim_and_session_identity.py"


def _entry(content: str) -> ContextInput:
    return ContextInput(source=ContextSource.CONVERSATION, content=content)


def _stale(content: str, age_seconds: float = 3600.0) -> ContextInput:
    item = _entry(content)
    item.created_at = dt.datetime.now() - dt.timedelta(seconds=age_seconds)
    return item


class TestTtlReclaimHasARealCaller:
    """TTL 回收必须挂在有真实调用方的位置（写入咽喉），不是只留一个出口。"""

    def test_expired_entries_are_reclaimed_on_the_write_path(self):
        """写入路径即回收点：过期条目不得只在读面被过滤掉。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=60)
        pool.add_context(_stale("过期条目"))
        pool.add_context(_entry("新条目"))

        contents = [c.content for c in pool.get_contexts()]
        assert "过期条目" not in contents, "读面仍能看到过期条目"
        assert pool.resident_count() == 1, (
            "过期条目仍占常驻：`cleanup_expired` 在生产零调用点，"
            "TTL 只在读面被惰性过滤 —— 内存规模上回收是空账"
        )
        stats = pool.get_retention_stats()
        assert stats["archived_by_reason"]["ttl"] == 1, (
            "TTL 回收计数未增加：回收没有被任何生产调用方触发"
        )

    def test_reclaim_is_scoped_to_the_turn_scope_neutral_path(self):
        """多轮写入下每次只回收真正的过期项（不误伤未过期条目）。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=60)
        for index in range(3):
            pool.add_context(_stale(f"过期{index}"))
            pool.add_context(_entry(f"新鲜{index}"))
        assert pool.resident_count() == 3
        assert pool.get_retention_stats()["archived_by_reason"]["ttl"] == 3

    def test_ttl_disabled_pool_is_untouched(self):
        """生产构造档（``ttl_seconds=0`` = 永不丢失）：一条都不回收。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0)
        pool.add_context(_stale("久远条目"))
        pool.add_context(_entry("新条目"))
        assert pool.resident_count() == 2
        assert pool.get_retention_stats()["archived_by_reason"]["ttl"] == 0

    def test_reclaimed_entry_stays_recallable(self, tmp_path):
        """回收不等于丢失：过期条目仍可经台账召回（无损归档硬约束）。

        回收发生在**下一次写入**之前（回收入口挂在写入咽喉），故这里写第二条
        条目来触发它；被回收的是那条过期内容，且它必须仍可召回。
        """
        ledger = EvictionLedgerDB(
            db_path=tmp_path / "l.db", user_id="u1", agent_id="a1"
        )
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1",
            ttl_seconds=60, ledger_db=ledger,
        )
        pool.add_context(_stale("过期但可召回：上海天气讨论"))
        pool.add_context(_entry("新条目"))
        assert pool.resident_count() == 1, "过期条目未被回收"
        recalled = pool.recall_evicted(query="上海天气")
        assert recalled, "回收把内容丢掉了 —— 无损归档契约要求它仍可召回"
        assert "上海天气" in recalled[0].content


class TestReclaimCallSiteIsWiredIntoTheWriteThroat:
    """回收的调用必须写在写入咽喉里（源码级判据，不只靠运行时行为）。"""

    def test_add_context_calls_the_reclaim_helper(self):
        import ast

        tree = ast.parse(POOL_SOURCE.read_text(encoding="utf-8"))
        pool_cls = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ContextPool"
        )
        methods = {
            node.name: node for node in pool_cls.body if isinstance(node, ast.FunctionDef)
        }

        def calls(node, attr):
            return any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == attr
                for inner in ast.walk(node)
            )

        assert "add_context" in methods, "ContextPool.add_context 不见了"
        assert calls(methods["add_context"], "_reclaimExpiredOnWrite"), (
            "写入咽喉 `add_context` 不再触发 TTL 回收 —— 回收又回到"
            "「定义了没人调」的形态（本批修的正是这条断链）。"
        )
        assert "cleanup_expired" in methods, "ContextPool.cleanup_expired 不见了"
        assert calls(methods["_reclaimExpiredOnWrite"], "cleanup_expired"), (
            "`_reclaimExpiredOnWrite` 没有落到 `cleanup_expired` —— 回收判据与实际"
            "执行脱节，计数与常驻规模都会说谎。"
        )


class TestSessionIdentityHasASingleWriter:
    """会话身份的写入方只允许一处：`build_context` 每轮刷新。"""

    def test_setter_is_gone_from_the_orchestrator(self):
        source = ORCHESTRATOR_SOURCE.read_text(encoding="utf-8")
        assert not re.search(r"^\s*def set_session_id\b", source, re.M), (
            "`ContextOrchestrator.set_session_id` 回来了 —— 会话身份于是有两个写入方"
            "（构造期入参 + 每轮刷新），第二份事实源必然漂移。"
        )

    def test_identity_property_is_read_only(self):
        """读面仍在（`session_id` 属性），且没有可写通道。"""
        from neurova.context.orchestrator import ContextOrchestrator

        assert isinstance(
            getattr(ContextOrchestrator, "session_id"), property
        ), "会话身份读面丢失 —— 收口写入方不等于砍掉读面"
        assert getattr(ContextOrchestrator.session_id, "fset", None) is None, (
            "`session_id` 仍是可写属性：写入方又变成两处"
        )


class TestLedgerCarriesTheFinalDisposal:
    """台账必须与机器判据咬合：这两条的处置不再是「待处置」。

    判据口径取 `scripts/ci/context_deadline_ledger.py`（单一事实源），
    本守卫不另写一份扫描逻辑，只断言"终局已落到台账、且与实测判据同类"。
    """

    def test_expired_reclaim_is_wired(self):
        entry = ledger.readLedger()["cleanup_expired"]
        assert entry["disposal"] == ledger.DISPOSAL_WIRED, (
            f"`cleanup_expired` 的台账处置是 {entry['disposal']} —— 本批已把回收"
            "接到写入咽喉，处置必须与实况一致。"
        )
        fact = {str(r["symbol"]): r for r in ledger.facts()}["cleanup_expired"]
        assert fact["judge"] == ledger.JUDGE_SELF_LOOP, (
            f"`cleanup_expired` 的判据类是 {fact['judge']}（{fact['classify']['rule']}）——"
            "接线后消费点应落在池自己的定义文件内（self_loop）。"
        )

    def test_second_identity_writer_is_retired(self):
        entry = ledger.readLedger()["set_session_id"]
        assert entry["disposal"] == ledger.DISPOSAL_RETIRED, (
            f"`set_session_id` 的台账处置是 {entry['disposal']} —— 第二写入方已删净。"
        )
        fact = {str(r["symbol"]): r for r in ledger.facts()}["set_session_id"]
        assert fact["judge"] == ledger.JUDGE_ABSENT, (
            f"`set_session_id` 的判据类是 {fact['judge']} —— 符号应已从生产侧消失，"
            "否则处置只是口号。"
        )

    def test_reconcile_reports_no_conflict(self):
        problems = ledger.reconcile()["judge_conflict"]
        assert not problems, (
            "台账判据类与机器取数不一致：\n  "
            + "\n  ".join(f"{p['symbol']}: 台账 {p['ledger']} / 实测 {p['computed']}"
                            for p in problems)
        )


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in PROTECTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行"
        )
