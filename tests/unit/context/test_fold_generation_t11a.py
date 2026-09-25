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
    async def test_generation_stack_is_bounded_and_counted(self):
        """代际栈有上限且截断**可见**：不静默增长，也不静默丢弃。"""
        orch = _mk_orchestrator()
        calls, summarizer = _counting_summarizer()
        orch._window_summarizer = summarizer

        history = [_round(i) for i in range(14)]
        await orch._apply_window_budget(history, 600, cache_key="sess-generation")
        for rnd in range(orch._MAX_FOLD_GENERATIONS + 3):
            history = history + [_round(100 + rnd)]
            await orch._apply_window_budget(history, 600, cache_key="sess-generation")

        slot = orch._window_compaction_cache["sess-generation"]
        nodes = slot.get("generations") or []
        assert len(nodes) <= orch._MAX_FOLD_GENERATIONS, (
            f"代际栈无上限：{len(nodes)} > {orch._MAX_FOLD_GENERATIONS}"
        )
        readout = orch.get_context_health()["fold_layers"]
        assert readout["truncated"] > 0, (
            "截断过却没有读数 —— 静默丢弃正是协作红线点名的断点形态"
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
            "truncated": 0,
            "last_summary_chars": 0,
        }
