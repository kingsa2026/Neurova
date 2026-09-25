"""016 残留 · 同一根因在**技能漏斗账本**与**三态搬运点**上的命中点。

## 与既有守卫的分工（不重复造判据）

`test_turn_elapsed_accumulation.py`（上一批）已经把**耗时聚合**这条链钉齐：
标量 `ContextVar.set()` 在 `asyncio.gather` 子任务里落不到父上下文，以及
`has_turn_tool_measurement()` 区分"测到 0.0"与"没测到"。本文件**不重复**那些判据。

这里只补上一批未覆盖的三处，都是同一根因/同一契约的其它命中点：

1. **技能漏斗账本整本会丢**（同一根因，第二个账本）。
   `record_turn_skill_funnel` 的"拿不到就建一个再 `set`"在子任务里建的是
   **子任务自己的列表**，父轮次读到空账本（实测：在 `create_task` 里记一条，
   父读回 `[]`）。耗时那条链已有守卫，漏斗这条链此前零覆盖。

2. **三态在搬运点被折两次**（同一契约，另外两个方向）。
   `ExperienceRecord.from_dict` 的 `bool(data.get("success", False))` 把
   "键缺席"与"值为 None"两种未测量都折成 `False` 失败——**往返一次就把票面 004
   的三态洗成两态**；`context/builder.py` 的
   `item.metadata.get("success", True)` 则把"没记成败"演成成功。
   两处方向相反，说明"默认值"本身就是三态契约下的非法动作。

3. **渲染词汇出现被复制回去的风险**。
   记号与词汇的单源已是 `skills.models`（`outcomeMark` / `outcomeWord` /
   `outcomeState`）。本文件钉住三个消费方**不再自带字面量或第二份记号表**——
   上一批逐条改完折叠点之后，剩下的失效模式就是"每个人各写一份三元表达式"，
   那时同一个 NULL 会在界面显示 `unevidenced`、在 prompt 里显示 `✗`。

## 反向控制

把 `_skill_funnel_ledger()` 换回"惰性建列表再 set"、把 `outcomeState` 从
`from_dict` / `chat_pipeline` 撤掉、或把任一处渲染写回三元表达式，本文件立刻转红。
"""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from neurova.core import turn_context as tc
from neurova.skills.models import (
    OUTCOME_MARKS,
    ExperienceRecord,
    outcomeMark,
    outcomeState,
    outcomeWord,
)

#: 仓库根：本文件在 `tests/unit/evolution/experience/` 下，向上四层是根。
PROJECT_ROOT = Path(__file__).resolve().parents[4]


async def _child(write) -> None:
    """子任务形态的写入方（`create_task` / `gather` 的 worker 就是这个上下文）。"""
    write()


def runWithChildWrite(write, read):
    """父 context 绑账本 → 子任务写 → 父 context 读。"""

    async def scenario():
        read()  # 轮首的等价动作：父 context 先绑定账本
        await asyncio.create_task(_child(write))
        return read()

    return asyncio.run(scenario())


def readSource(rel_path: str) -> str:
    return io.open(PROJECT_ROOT / rel_path, encoding="utf-8").read()


class TestSkillFunnelSurvivesTheTaskBoundary:
    """同一根因的第二个账本：技能质量漏斗。"""

    def test_funnel_written_in_a_child_task_reaches_the_parent(self):
        """父 context 已绑账本时，子任务的记录必须可见。"""
        tc.reset_turn_tool_messages()
        rows = runWithChildWrite(
            lambda: tc.record_turn_skill_funnel("demo-skill", applied=True, ok=True),
            tc.get_turn_skill_funnel,
        )
        assert rows == [
            {"skill_id": "demo-skill", "applied": True, "ok": True,
             "pool": "agent", "owner_key": ""}
        ], (
            "子任务里的技能派发记录没进父轮次账本："
            f"父读到 {rows!r}——整本漏斗账本会丢"
        )

    def test_child_write_reaches_a_parent_that_never_bound_a_ledger(self):
        """**父 context 从未绑定账本**时，子任务的记录同样必须回到父轮次。

        这条才是根因的正面判据，也是反向锁真正咬合的那一格：写入方
        （`_skill_funnel_ledger()`）此刻在父上下文里读到的还是 `None`。
        「读 `None` → 建列表 → `set`」这条路的 `set` 落在**子任务自己的**
        context 副本上，父轮次永远读不到；已被实测：父读到 `[]`，
        而子任务自己读得到那条记录（看起来一切正常）。

        上一版的用例先调了 `reset_turn_tool_messages()`（生产轮首必做，父会预先
        绑好列表），于是子任务 `get()` 直接命中父持有的对象——**判据在正确的
        实现与错误实现下都绿**，等于没钉住。反向锁（把写入改回惰性建列表）
        当时也是绿的，正是判据空转的自证。
        """
        tc.clear_turn_state()  # 父 context 里不留任何已绑账本
        async def scenario():
            async def child():
                tc.record_turn_skill_funnel("cold-parent", applied=True, ok=True)

            await asyncio.create_task(child())
            return tc.get_turn_skill_funnel()

        rows = asyncio.run(scenario())
        assert rows == [
            {"skill_id": "cold-parent", "applied": True, "ok": True,
             "pool": "agent", "owner_key": ""}
        ], (
            "写入方在父上下文未绑账本时于子任务内自建列表，父轮次读到空账本："
            f"父读到 {rows!r}"
        )

    def test_child_elapsed_reaches_a_parent_that_never_bound_a_ledger(self):
        """耗时累加器同一格的守卫（同根因、同形状，一并钉住）。"""
        tc.clear_turn_state()

        async def scenario():
            async def child():
                tc.add_turn_tool_elapsed(1.5)

            await asyncio.create_task(child())
            return tc.get_turn_tool_elapsed(), tc.has_turn_tool_measurement()

        elapsed, measured = asyncio.run(scenario())
        assert measured is True and abs(elapsed - 1.5) < 1e-9, (
            f"父未绑账本时子任务的耗时不回传：elapsed={elapsed!r} measured={measured!r}"
        )

    def test_reset_rebinds_a_fresh_funnel_ledger(self):
        """轮首换绑空账本：沿用旧列表会把上一轮的记录续进本轮。"""
        tc.record_turn_skill_funnel("stale", applied=True, ok=True)
        tc.reset_turn_tool_messages()
        assert tc.get_turn_skill_funnel() == [], "上一轮的漏斗记录残留到本轮"

    def test_funnel_read_is_a_copy_not_the_live_list(self):
        """读口给副本：调用方就地改读数不该改到轮级账本。"""
        tc.reset_turn_tool_messages()
        tc.record_turn_skill_funnel("y", applied=True, ok=True)
        rows = tc.get_turn_skill_funnel()
        rows.clear()
        assert len(tc.get_turn_skill_funnel()) == 1, "读口交出了活列表"


class TestThirdStateSurvivesTheCarriers:
    """同一契约的两个搬运点：往返与默认值都不得把三态洗成两态。"""

    def test_record_round_trip_keeps_the_third_state(self):
        assert ExperienceRecord.from_dict({"skill_name": "s"}).success is None, (
            "键缺席被折成失败——库里三态、往返一次就变两态"
        )
        assert ExperienceRecord.from_dict(
            {"skill_name": "s", "success": None}
        ).success is None, "显式 NULL 被折成失败"
        assert ExperienceRecord.from_dict({"skill_name": "s", "success": True}).success is True
        assert ExperienceRecord.from_dict({"skill_name": "s", "success": False}).success is False

    def test_state_normalises_legacy_int_form(self):
        """EKB 2.0 的 int 0/1 与三态兼容；无法解释的值落「未测量」。"""
        assert outcomeState(True) is True
        assert outcomeState(False) is False
        assert outcomeState(1) is True
        assert outcomeState(0) is False
        assert outcomeState(None) is None
        assert outcomeState("weird") is None

    def test_pool_extraction_defaults_to_the_third_state(self):
        """候选池里没记成败时，不得默认成「成功」。

        判据只认代码行：说明性注释刻意引用了旧写法，把注释也算进去等于判据空转。
        """
        offenders = [
            line.strip()
            for line in readSource("neurova/context/builder.py").splitlines()
            if "item.metadata.get(" in line
            and "True)" in line
            and not line.strip().startswith(("#", "旧写法"))
        ]
        assert not offenders, f"候选池抽取仍把「没记成败」默认成成功：{offenders}"


class TestRenderSitesTakeTheVocabularyFromTheSingleSource:
    """三个消费方不得自带字面量或第二份记号表（防"每人各写一份"的回潮）。"""

    def test_mark_and_word_come_from_one_table(self):
        assert outcomeMark(None) == OUTCOME_MARKS[None]
        assert outcomeWord(None) == "unevidenced"
        assert outcomeMark(None) != outcomeMark(False), (
            "未测量与失败用了同一个符号——模型会把没测过的经验当成做错过的事"
        )
        assert outcomeWord(None) != outcomeWord(False)

    @pytest.mark.parametrize(
        "rel_path, marker",
        [
            ("neurova/agent/chat_pipeline.py", 'outcomeMark(hit.get("success"))'),
            ("neurova/context/injector.py", "outcomeMark(exp.get('success'))"),
            ("neurova/api/endpoints/experience_knowledge_api.py", "outcomeWord(success)"),
        ],
    )
    def test_render_sites_take_the_word_from_the_single_source(self, rel_path, marker):
        text = readSource(rel_path)
        assert marker in text, f"{rel_path} 没有取单源词汇（期望出现 {marker}）"
        assert '"✓" if exp' not in text and '"✓" if hit' not in text, (
            f"{rel_path} 仍留着三元表达式折叠三态——词汇只准从单源取"
        )
        assert "OUTCOME_MARKS" not in text, (
            f"{rel_path} 自带了第二份记号表——记号只准从 skills.models 取"
        )

    def test_api_vocabulary_is_the_shared_one(self):
        """API 面的 `unevidenced` 与 prompt 面的第三态同源，不是第二份词表。

        `fastapi` 是可选依赖（本仓约定：可选依赖一律惰性 import + fail-soft），
        缺席的环境点名跳过本格——缺席不是判据失败，但也不静默通过。
        """
        pytest.importorskip("fastapi")
        from neurova.api.endpoints.experience_knowledge_api import _outcome_word

        assert _outcome_word(None) == outcomeWord(None)
        assert _outcome_word(True) == outcomeWord(True)
        assert _outcome_word(False) == outcomeWord(False)


class TestReverseLocks:
    """反向锁：把根因恢复原状 ⇒ 判据必须转红（否则断言没有区分力）。"""

    def test_scalar_contextvar_would_lose_the_child_write(self):
        """证明「子任务 set 对父不可见」是真机制，而不是本文件的构造误差。"""
        from contextvars import ContextVar

        scalar: ContextVar = ContextVar("probe_scalar", default=0.0)

        async def scenario():
            async def child():
                scalar.set(scalar.get() + 1.5)

            scalar.set(0.5)
            await asyncio.create_task(child())
            return scalar.get()

        assert asyncio.run(scenario()) == 0.5, (
            "标量 ContextVar 的子任务写入本应对父不可见；读数变了说明探针失效"
        )

    def test_lazy_list_creation_in_a_child_loses_the_write(self):
        """证明「惰性建列表再 set」在子任务里确实丢写——判据有区分力。

        这正是 `record_turn_skill_funnel` 的旧写法：父未绑时 `get()` 是 `None`，
        子任务建列表并 `set`，父轮次读到空账本。把这条锁写进反向控制，
        「父未绑」那一格在旧实现下必然红。
        """
        from contextvars import ContextVar

        lazy: ContextVar = ContextVar("probe_lazy_funnel", default=None)

        async def scenario():
            async def child():
                current = lazy.get()
                if not isinstance(current, list):
                    current = []
                    lazy.set(current)
                current.append("record")

            await asyncio.create_task(child())
            return lazy.get()

        assert asyncio.run(scenario()) is None, (
            "惰性建列表的子任务写入本应丢在子任务上下文里；读数变了说明探针失效"
        )

    def test_eagerly_bound_list_would_keep_the_child_write(self):
        """同一个探针的"轮首先绑对象"形态：证明漏斗的修法方向是对的。"""
        from contextvars import ContextVar

        ledger_var: ContextVar = ContextVar("probe_funnel", default=None)
        ledger_var.set([])

        async def scenario():
            async def child():
                ledger_var.get().append("record")

            await asyncio.create_task(child())
            return ledger_var.get()

        assert asyncio.run(scenario()) == ["record"]
