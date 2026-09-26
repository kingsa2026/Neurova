# -*- coding: utf-8 -*-
"""B6-10 批次 F：池注册表的 session 分区读路径退场（Issue #90 §5 / 工单 B6-10）。

## 台账里的自述

`scripts/ci/contextDeadlines.txt` 对 `ContextPoolRegistry` 的处置一直是「待处置」，
依据写的是：

> 池的 session 分区读路径在对话主链从未被走。处置需先裁定「分区读是否有真需求」

本批把裁定做完。**结论：退。**

## 根因：它是被 T-02 取代的**第二套隔离机制**

注册表的多池机制（`get_or_create` 按 `(user, agent, session)` 造池 + `query_agent`
跨 session 分区调取）与 `ContextPool.isolation_key` 是**按池分会话**的隔离设计。
而 T-02/ADR-0015 交付的真设计是**单池 + 作用域标签**：池是"永不丢失"的归档，
`chat_scope` 随内容落进 metadata，隔离由 `filter_by_scope` 判，池归属不承担隔离。

两套机制并存的结果实测（2026-09-26，真 `ContextOrchestrator` 构造面）：

```
生产构造后登记池数: 1
登记键: [('u1', 'yi_ling', '')]        ← 一个 agent 一个池，session 段恒空
list_sessions: ['']
池自身 draw 取得: ['真归档']             ← 真读路径取得到
registry.query_agent 同身份: []          ← 分区读路径一条都取不回来
```

`query_agent` 的跨 session 模式按 `_list_sessions_locked()` 枚举 `''` 这个键，
再 `pool.query(session_id='')` —— 而池的 `session_id` 每轮由 `build_context`
刷成本轮身份（`_resolveTurnSessionId`），与注册表键里的 `''` 无因果。
于是「池里明明有内容，分区读路径取不回来」，且**返回空列表而不是报错**：
消费方分不出"没有"与"坏掉"——正是修复教义第 2 条点名的形态。

## 保留什么

`adopt` / `get_pool` 是 B6-3 / B6-4 **已接线**的真面：编排器构造池时就地登记，
端点与工作流节点按身份取同一个池。它们是真单池设计的读侧入口，**保留**。

## 本守卫钉什么

1. 多池机制在生产侧已退场（`get_or_create` / `query_agent` 等判据类为 `absent`）；
2. 已接线的单池读侧入口仍在（`adopt` / `get_pool` / `get_registry`）；
3. 反向控制：判据不得把「已接线的真面」一并算成退场。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ci import context_deadline_ledger as ledger  # noqa: E402

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"
GUARD_REL = "tests/unit/context/test_pool_registry_session_partition_retirement.py"

#: 退场的多池机制（第二套隔离设计）——拥有者级：`ContextPoolRegistry` 上不得再有。
RETIRED_MULTI_POOL = (
    "get_or_create",
    "query_agent",
    "list_sessions",
    "clear_session",
    "get_pool_count",
)

#: 其中判据类**不是** `absent` 的两条：裸名撞名（`get_or_create` 命中 mcp_oauth 的
#: 另一个接收者 → `self_loop`；`list_sessions` 命中 SessionRepository 等会话域方法
#: → `consumed`）。这是判据模块 docstring 预先点名的「按名字计数不可判别」形态，
#: 故这两条的终局证明走**拥有者级判据**（下面的 `hasattr` 断言），
#: 台账也据此显式记录判据轴收窄——不硬改台账去迎合一条读不到的判据。
NAME_COLLISION_EXPECTATIONS = {
    "get_or_create": ledger.JUDGE_SELF_LOOP,
    "list_sessions": ledger.JUDGE_CONSUMED,
}

#: 保留的已接线单池读侧入口（B6-3 / B6-4 交付）——反向控制，不得被一并算成退场。
WIRED_SINGLE_POOL = ("adopt", "get_pool", "get_registry")


def _facts() -> dict:
    return {str(row["symbol"]): row for row in ledger.facts()}


class TestMultiPoolMachineryIsRetired:
    def test_creator_face_is_gone_from_production(self):
        from neurova.context_pool_registry import ContextPoolRegistry

        offenders = [
            name for name in RETIRED_MULTI_POOL if hasattr(ContextPoolRegistry, name)
        ]
        assert not offenders, (
            f"注册表仍保留多池机制 {offenders} —— 它是被 T-02 的单池+作用域标签设计"
            "取代的第二套隔离机制。实测生产只登记一个池（键 session 段恒空），"
            "而 query_agent 的分区读路径按 '' 枚举、又用池每轮刷新的 session_id 取数，"
            "两者无因果 → 池里有内容也取不回来，且**返回空列表而不是报错**。"
        )

    def test_judge_classes_agree(self):
        """判据类与台账咬合：裸名撞名的两条**如实**记成它们的实测形态。

        `get_or_create` / `list_sessions` 在裸名轴上是别的接收者
        （mcp_oauth / SessionRepository），故分别报 `self_loop` / `consumed`。
        这不是"没删干净"，而是判据轴只算裸名的已知边界——终局由上面的
        `hasattr` 拥有者级断言给出。把台账硬改成 `absent` 去迎合读不到的判据，
        等于把判据降级成自述（B6-1 明令禁止）。
        """
        facts = _facts()
        problems = []
        for symbol in RETIRED_MULTI_POOL:
            fact = facts.get(symbol)
            if fact is None:
                problems.append(f"{symbol}: 不在登记符号表里，判据取不到数")
                continue
            expected = NAME_COLLISION_EXPECTATIONS.get(symbol, ledger.JUDGE_ABSENT)
            if fact["judge"] != expected:
                problems.append(
                    f"{symbol}: 判据类为 {fact['judge']}（{fact['classify']['rule']}），"
                    f"期望 {expected}"
                )
        assert not problems, (
            "退场的多池机制与机器判据不咬合：\n  " + "\n  ".join(problems)
        )

    def test_name_collision_rows_state_the_narrowed_axis(self):
        """撞名的两条必须在依据里显式写明「判据轴收窄」——不靠读表人猜。"""
        entries = ledger.readLedger()
        problems = [
            symbol
            for symbol in NAME_COLLISION_EXPECTATIONS
            if "判据轴收窄" not in entries.get(symbol, {}).get("basis", "")
        ]
        assert not problems, (
            f"撞名的条目没有写明判据轴收窄：{problems}\n"
            "读者会以为判据把别的接收者算成了本模块的消费点。"
        )


class TestSinglePoolReadFaceSurvives:
    """反向控制：已接线的真面不得被「一并清掉」的冲动带走。

    `adopt` / `get_pool` 是 B6-3 / B6-4 交付的读侧入口（端点取池、工作流节点取池、
    按身份取同一实例），`get_registry()` 是它们的入口。删多池机制时最容易连带
    删掉这个——那才是真正的能力净损失。
    """

    def test_wired_entrypoints_still_exist(self):
        from neurova import context_pool_registry as module

        missing = [
            name
            for name in ("adopt", "get_pool", "reset")
            if not hasattr(module.ContextPoolRegistry, name)
        ]
        assert not missing, f"已接线的单池读侧入口被连带删掉了：{missing}"
        assert callable(getattr(module, "get_registry", None)), (
            "`get_registry()` 是 adopt/get_pool 的唯一入口，不得删。"
        )

    def test_identity_take_and_lookup_still_work(self):
        """真链路自证：登记一个池 → 按身份取回同一个实例。"""
        from neurova.context_pool import ContextPool, get_context_pool
        from neurova.context_pool_registry import get_registry

        registry = get_registry()
        registry.reset()
        try:
            pool = ContextPool(user_id="u-f", agent_id="a-f", session_id=None)
            registry.adopt(pool)
            assert get_context_pool(user_id="u-f", agent_id="a-f") is pool, (
                "按身份取池取不回同一实例 —— B6-3/B6-4 的接线被破坏了"
            )
        finally:
            registry.reset()


class TestGuardIsInProtectedSubset:
    def test_listed_in_protected_tests(self):
        listed = {
            line.split("#", 1)[0].strip()
            for line in PROTECTED.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        assert GUARD_REL in listed, (
            f"{GUARD_REL} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
        )
