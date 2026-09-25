# -*- coding: utf-8 -*-
"""T-11a 折叠改分代：产出新节点，旧摘要降一层而非被覆盖（Issue #90 工单 §12.4）。

## 根因（不是"少存一份摘要"）

折叠摘要此前是**一个字符串**：`cache["summary"] = compaction.summary`。
每轮折叠都把上一轮的摘要原地覆盖，于是：

- 全部被压缩的历史**永远只塌成一个节点**（池内 SUMMARY 节点数实测 0，
  摘要只活在 `_window_compaction_cache` 这个进程内易失的字符串里）；
- 分辨率梯度（工单 §12.1 的 C2）在数据上**不可能存在** ——
  只有一个层，就谈不上"越远的位置分辨率越低"；
- 层即索引（C4）也无从落地：没有多节点，就没有可解析的 `covers` 可供下钻。

## 本票的契约（T-11b 的 `level`/`covers` 索引建立在此之上）

- 新折叠产出一个**新节点**（最新一代，`level` = 1）；
- 上一代摘要**降一层**保留（`level` = 2），文本原样、不被就地改写；
- 更早的代际依次再降一层 —— "旧摘要降一层"由此在每轮折叠上成立。

代际栈的**唯一写入点**是编排器的分代推进方法，自动折叠与手动 `/compact`
共用它（同一契约两处各写一遍必漂移）。

未闭环（登记台账，不在本票假装修掉）：把代际节点写进池并加 `covers` 索引属
T-11b；视图按档装配（1:4:16 几何退避）属 T-11c；多层后台 rollup 属 T-11e。
"""

import pytest
from unittest.mock import MagicMock

from neurova.context.orchestrator import ContextOrchestrator


def _mk_orchestrator(budget: int = 600):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False, session_id="sess-generation")
    orch._window_token_budget = budget
    # 防抖让"每轮都真摘要"，判据才打在分代行为上（而不是防抖复用上）
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


def _round(i: int, chars: int = 400):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _counting_summarizer():
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    return calls, _summarize


class TestFoldProducesGenerations:
    """T-11a 的两条具名判据（工单 §12.4 逐字给的用例名）。"""

    @pytest.mark.asyncio
    async def test_fold_produces_new_node_not_overwrite(self):
        """新折叠产出新节点：上一代摘要原样保留，而不是被就地覆盖。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        first = [_round(i) for i in range(14)]
        await orch._apply_window_budget(first, 600, cache_key="sess-generation")
        assert calls["n"] == 1, "首轮未触发折叠摘要——本用例没打到分代路径"

        second = first + [_round(i) for i in range(14, 26)]
        await orch._apply_window_budget(second, 600, cache_key="sess-generation")
        assert calls["n"] >= 2, "次轮未触发新一轮摘要——本用例没打到分代路径"

        slot = orch._window_compaction_cache["sess-generation"]
        assert slot["summary"] == f"第{calls['n']}代摘要：覆盖 {slot['last_count']} 条" or (
            slot["summary"].startswith(f"第{calls['n']}代摘要")
        )

        nodes = slot.get("generations")
        assert nodes, (
            "折叠后没有代际节点：摘要仍是单个字符串，旧摘要被覆盖 —— "
            "分辨率梯度在数据上不可能存在（工单 §12.1 的 C2）"
        )
        texts = [n["summary"] for n in nodes]
        assert any(t.startswith("第1代摘要") for t in texts), (
            f"上一代摘要被新摘要吞掉了，代际节点={texts} —— 这不是分代，是覆盖"
        )
        assert texts[0].startswith(f"第{calls['n']}代摘要"), (
            f"栈顶不是最新一代：{texts} —— 代际栈必须最新在前"
        )

    @pytest.mark.asyncio
    async def test_previous_summary_survives_as_lower_level(self):
        """旧摘要降一层：其 level 大于新节点的 level，且文本原样。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        first = [_round(i) for i in range(14)]
        await orch._apply_window_budget(first, 600, cache_key="sess-generation")
        slot = orch._window_compaction_cache["sess-generation"]
        top_level_first = slot.get("level")

        second = first + [_round(i) for i in range(14, 26)]
        await orch._apply_window_budget(second, 600, cache_key="sess-generation")
        slot = orch._window_compaction_cache["sess-generation"]

        assert top_level_first == 1, (
            f"最新一代的 level 应为 1（最细分辨率档），实得 {top_level_first!r}"
        )
        assert slot.get("level") == 1, "新一轮摘要必须成为最新一代（level 1）"

        demoted = [n for n in (slot.get("generations") or []) if n["level"] == 2]
        assert demoted, (
            f"没有 level=2 的降层节点：代际栈={slot.get('generations')!r} —— "
            "旧摘要没有被降一层，而是被覆盖了"
        )
        assert demoted[0]["summary"].startswith("第1代摘要"), (
            f"降层节点的文本被改写了：{demoted[0]['summary']!r}（应为上一代原文）"
        )

    @pytest.mark.asyncio
    async def test_generation_stack_keeps_every_generation(self):
        """**判据已按负责人 2026-09-25 裁定改写**（原 `test_generation_stack_is_bounded_and_counted`
        锁的是"有上限 + 截断可见"）。上限删掉后同一条断言锁的是反面：一档都不许丢。

        改判据不改断言强度：原用例钉"截断必被记账"，本用例钉"截断必然为 0 且
        栈深 == 代数" —— 两者都要求"没有一代既不活也不被记账"。
        """
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(14)]
        await orch._apply_window_budget(history, 600, cache_key="sess-generation")
        for rnd in range(8):
            history = history + [_round(100 + rnd)]
            await orch._apply_window_budget(history, 600, cache_key="sess-generation")

        slot = orch._window_compaction_cache["sess-generation"]
        nodes = slot.get("generations") or []
        assert orch._MAX_FOLD_GENERATIONS is None, (
            f"上限仍在：{orch._MAX_FOLD_GENERATIONS!r} —— 档数不设上限（工单 §12.1）"
        )
        assert len(nodes) == calls["n"], (
            f"代际栈 {len(nodes)} 档 != 摘要 {calls['n']} 代：有一代被丢弃"
        )
        readout = orch.get_context_health()["fold_layers"]
        assert "truncated" not in readout, (
            f"无上限却仍有截断读数：{readout} —— 恒 0 的字段就是谎报面"
        )
        assert readout["levels"] == len(nodes), (
            f"读数 levels={readout['levels']} 与栈深 {len(nodes)} 不符"
        )

    @pytest.mark.asyncio
    async def test_manual_compact_shares_the_same_generation_advance(self):
        """放大视角（教义第 5 条）：`/compact` 与自动折叠共用同一处分代推进。"""
        orch = _mk_orchestrator(budget=4000)
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(30)]
        await orch.manual_compact(history)
        slot = orch._window_compaction_cache["sess-generation"]
        assert slot.get("level") == 1

        history = history + [_round(i) for i in range(30, 60)]
        await orch.manual_compact(history)
        slot = orch._window_compaction_cache["sess-generation"]
        levels = [n["level"] for n in (slot.get("generations") or [])]
        assert levels == [1, 2], (
            f"手动 `/compact` 未走同一处分代推进：代际栈档位={levels}"
            "（预期 [1, 2] = 最新一代 + 上一代降一层）"
        )


class TestGenerationReadout:
    """代际栈的读数面（`get_context_health()["fold_layers"]`）。"""

    def test_empty_shape_is_single_source(self):
        """尚未折叠时 0 档：读数不虚报梯度（"写了就该是事实"）。"""
        orch = _mk_orchestrator()
        readout = orch.get_context_health()["fold_layers"]
        assert readout == {
            "levels": 0,
            "demoted": 0,
            "last_summary_chars": 0,
        }, f"空形状与单源 `_emptyContextHealth()` 不一致：{readout}"


class TestGenerationStackIsUncapped:
    """负责人 2026-09-25 裁定：**删掉上限** —— 档数不设上限（工单 §12.1）。

    改前本票给进程内代际栈设了 `_MAX_FOLD_GENERATIONS = 5`，理由写在台账 §23.1
    （"进程内易失状态不可只增"）。该理由不成立：代际栈**不是**只增的容器——
    每次折叠都是"+1 新代 / 既有代各降一层"的等量代换，本身有界；只增的是
    `demoted` / `truncated` 两个**计数**，而计数不占内存、正是读数的意义。
    上限真实代价是把当时最深的档**丢弃**，而"轨迹越长档数自然增长"（§12.1）
    正是分辨率梯度成立的前提。
    """

    @pytest.mark.asyncio
    async def test_stack_grows_beyond_previous_five_layer_cap(self):
        """轨迹继续变长时档数继续增长：此前第 6 代起会被静默丢弃。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(14)]
        await orch._apply_window_budget(history, 600, cache_key="sess-generation")
        # 跑满 8 轮折叠：此前上限 5，第 6 轮起的那几代会被丢
        for rnd in range(7):
            history = history + [_round(100 + rnd)]
            await orch._apply_window_budget(history, 600, cache_key="sess-generation")

        slot = orch._window_compaction_cache["sess-generation"]
        nodes = slot.get("generations") or []
        assert calls["n"] >= 6, f"摘要调用只有 {calls['n']} 次——本用例没打到多代路径"
        assert len(nodes) == calls["n"], (
            f"代际栈深度 {len(nodes)} != 摘要调用次数 {calls['n']} —— "
            "仍有一代被上限丢弃（档数必须不设上限，工单 §12.1）"
        )
        # 最深一档的文本必须是**第 1 代**的原文，而不是中途某代
        assert nodes[-1]["summary"].startswith("第1代摘要"), (
            f"栈底不是最早一代：{nodes[-1]['summary']!r} —— 最早的历史被丢掉了"
        )
        assert nodes[-1]["level"] == calls["n"], (
            f"最深一档的档号 {nodes[-1]['level']} 与代数 {calls['n']} 不符："
            "降层语义被上限截断过"
        )

    @pytest.mark.asyncio
    async def test_no_truncation_readout_when_uncapped(self):
        """上限删掉后不再有截断：读数里的 `truncated` 必须如实留在 0。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(14)]
        await orch._apply_window_budget(history, 600, cache_key="sess-generation")
        for rnd in range(9):
            history = history + [_round(100 + rnd)]
            await orch._apply_window_budget(history, 600, cache_key="sess-generation")

        readout = orch.get_context_health()["fold_layers"]
        assert "truncated" not in readout, (
            f"已删掉上限却仍有截断字段 {readout} —— 无上限即永不可能截断，"
            "恒 0 的字段就是谎报面"
        )
        assert readout["levels"] == calls["n"], (
            f"读数 levels={readout['levels']} 与摘要调用次数 {calls['n']} 不符"
        )
        assert readout["demoted"] == sum(range(calls["n"])), (
            f"累计降层数 {readout['demoted']} 与各代降层总和 "
            f"{sum(range(calls['n']))} 不符 —— 降层记账有漏"
        )
        # 上限常量本身必须消失：留着它，"上限没了"就只是注释里的一句话

    @pytest.mark.asyncio
    async def test_stack_memory_is_bounded_by_live_generations(self):
        """上限删掉不等于放任增长：每轮折叠都是等量代换，深度 == 活代数。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(14)]
        await orch._apply_window_budget(history, 600, cache_key="sess-generation")
        depths = []
        for rnd in range(5):
            history = history + [_round(100 + rnd)]
            await orch._apply_window_budget(history, 600, cache_key="sess-generation")
            slot = orch._window_compaction_cache["sess-generation"]
            depths.append(len(slot.get("generations") or []))

        assert depths == list(range(2, 6 + 1)) or depths == list(range(1, 5 + 1)) or depths == sorted(depths), (
            f"代际栈深度非单调：{depths}（栈必须随折叠单调加深，不掉代）"
        )
        slot = orch._window_compaction_cache["sess-generation"]
        assert len(slot["generations"]) == calls["n"], (
            f"深度 {len(slot['generations'])} != 代数 {calls['n']}：有代际既不活也不被记账"
        )
        texts = [n["summary"] for n in slot["generations"]]
        assert len(set(texts)) == len(texts), f"代际栈出现重复节点：{texts}"
