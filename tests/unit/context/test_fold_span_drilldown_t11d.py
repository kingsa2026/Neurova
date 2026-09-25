# -*- coding: utf-8 -*-
"""T-11d 确定性下钻：摘要行内联 `covers_ref`，按引用取回被覆盖的原文（Issue #90）。

## 根因（不是"少一个工具"）

T-11b 让池内层节点带上了 `covers`（turn 区间 + 被覆盖条目 hash 列表），索引因此
**存在**；但整条链路上没有任何**消费方**：

- 视图里那行摘要（`[早期对话摘要] …`）不带任何可解析引用 —— 模型读到摘要，
  却没有任何确定性寻址手段，只能退回 `recall_history(query=…)` 的**相关性门槛
  碰运气**（工单 §12.5 第 3 条明列为假实现）；
- `covers` 的 hash 列表没有任何按 hash 直取的读面 —— 索引写进去就没人读，
  正是红线段"写出无人读的字段"的形态；
- 被折叠原文跨重启后只在持久台账里，而台账按**内容指纹**（content-only）去重，
  池侧 `covers` 用的是**池内容指纹**（source + content，`ContextInput.compute_hash`）
  —— 两个指纹域不通，重启后即使有索引也解析不回原文。

于是工单 §12.0 的承诺 A（**任何已归档内容都存在一条确定性回取路径**）在数据上
不成立：索引有了，"取回的到"没有。

## 本票契约

- 层节点的 `covers_ref` 由 `context/fold_index.py` **单点**派生与解析（写入侧派一次、
  读取侧解一次）；视图摘要行内联该引用，模型据此下钻；
- 新增工具 `recall_context_span(covers_ref)`，与 `recall_history` 同一寻址语义
  （硬地址直取，不猜子串、不走相关性门槛）；
- 直取面按 hash 精确解析：常驻命中优先、持久台账兜底（`pool_hash` 索引），
  返回条目的池指纹必须与请求的 covers hash **逐条相等**（对齐率 100%）；
- 判据只认"取回的到/取不回"两态：取不回必须点名原因（引用解析失败 / 档位不存在 /
  原文缺失），不许返回空成功；
- 作用域闸口与视图路径、`recall_evicted` 同源（`_allowedRecallItems`）—— 新读路径
  不得把 T-02/T-03 刚收口的隔离破掉。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool


class _TurnIdentityAgent(MagicMock):
    """与 `agent_core.Agent` 同型的替身：身份面转发 `core/turn_context` 的只读属性。"""

    @property
    def current_session_id(self):
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()


def _agent(agentId: str = "a-t11d"):
    agent = _TurnIdentityAgent()
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
    agent.agent_id = agentId
    return agent


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _counting_summarizer():
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    return calls, _summarize


def _orchestrator(agentId: str = "a-t11d"):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id="sess-t11d"
    )
    orch._window_token_budget = 1200
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


def _longRound(i: int):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * 200}


async def _foldOnce(orch, history, collab=False, room_id=""):
    _, summarizer = _counting_summarizer()
    orch._window_summarizer = summarizer
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续",
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


async def _foldTwice(orch, collab=False, room_id=""):
    history = [_longRound(i) for i in range(14)]
    ctx = await _foldOnce(orch, history, collab=collab, room_id=room_id)
    history = history + [_longRound(i) for i in range(14, 30)]
    ctx = await _foldOnce(orch, history, collab=collab, room_id=room_id)
    return ctx


def _summaryLine(view):
    """视图里那行摘要（折叠桩/摘要行），无则 None。"""
    for msg in view or []:
        if msg.get("role") == "system" and "早期对话摘要" in str(msg.get("content", "")):
            return str(msg["content"])
    return None


class TestCoversRefInline:
    """判据 A（确定性回取）的第一段：引用必须出现在**模型真读得到**的那一行上。"""

    @pytest.mark.asyncio
    async def test_covers_ref_parsable_from_summary_line(self):
        orch = _orchestrator()
        view = await _foldTwice(orch)

        line = _summaryLine(view)
        assert line is not None, f"视图里没有摘要行——本用例没打到折叠路径：{view[:2]}"

        from neurova.context.fold_index import parseCoversRef

        parsed = parseCoversRef(line)
        assert parsed is not None, (
            f"摘要行不带可解析的 covers_ref：{line[-120:]!r} —— 模型没有任何确定性"
            "寻址手段，只能退回相关性召回碰运气（工单 §12.5 第 3 条）"
        )
        foldSeq, sessionId = parsed
        assert sessionId == "sess-t11d", f"引用里的会话不匹配：{sessionId}"

        layers = orch.context_pool.summaryLayers()
        assert any(layer["fold_seq"] == foldSeq for layer in layers), (
            f"引用 {foldSeq} 指向不存在的档位：索引里只有 "
            f"{[layer['fold_seq'] for layer in layers]} —— 悬空引用比没有引用更坏"
        )


class TestDrilldownByRef:
    """判据 A 的第二段：按引用取回的原文必须**逐条 hash 对齐**（§12.7 判据 5）。"""

    @pytest.mark.asyncio
    async def test_drilldown_by_covers_ref_returns_originals(self):
        orch = _orchestrator()
        view = await _foldTwice(orch)
        line = _summaryLine(view)
        assert line is not None, "视图里没有摘要行——本用例没打到折叠路径"

        pool = orch.context_pool
        spans = pool.drilldown(line)
        assert spans.get("resolved"), f"下钻未解析：{spans}"

        layer = next(
            layer for layer in pool.summaryLayers()
            if layer["fold_seq"] == spans["fold_seq"]
        )
        wanted = set(layer["covers"]["hashes"])
        got = {entry["hash"] for entry in spans["entries"]}
        assert wanted, "covers 是空的——本用例没打到索引路径"
        assert got == wanted, (
            f"下钻取回的原文与 covers 不对齐：缺 {sorted(wanted - got)[:2]}，"
            f"多 {sorted(got - wanted)[:2]} —— 对齐率必须 100%"
        )
        assert spans["unresolved"] == [], f"有解析不到的覆盖原文：{spans['unresolved']}"

        # 取回的是**原文**，不是摘要：内容必须与折叠前那一批消息逐条相等
        folded = {m["content"] for m in [*[_longRound(i) for i in range(14)]]}
        contents = {entry["content"] for entry in spans["entries"]}
        assert contents & folded, "取回的内容里没有一条是折叠前的原文"

    @pytest.mark.asyncio
    async def test_drilldown_survives_restart(self):
        """跨重启下钻：索引与原文都得从持久层取回（§12.7 判据 5 的"新进程内取回"）。"""
        orch = _orchestrator(agentId="a-t11d-restart")
        view = await _foldTwice(orch)
        line = _summaryLine(view)
        assert line is not None, "视图里没有摘要行——本用例没打到折叠路径"
        before = orch.context_pool.drilldown(line)
        assert before.get("resolved") and before["entries"], f"重启前就下钻不到：{before}"
        orch.context_pool.close()

        from neurova.context.orchestrator import ContextOrchestrator

        fresh = ContextOrchestrator(
            _agent("a-t11d-restart"), use_pool=True, auto_tag=False, session_id="sess-t11d"
        )
        try:
            after = fresh.context_pool.drilldown(line)
            assert after.get("resolved"), f"重启后引用解析不了：{after}"
            assert {e["hash"] for e in after["entries"]} == {
                e["hash"] for e in before["entries"]
            }, (
                "重启后下钻取回的原文不一致 —— 原文只在常驻列表里，持久层没有按池指纹"
                "的直取面（covers 用的是池内容指纹，台账去重用的是内容指纹，两域不通）"
            )
        finally:
            fresh.context_pool.close()

    @pytest.mark.asyncio
    async def test_truncation_is_reported_not_silent(self):
        """`limit` 只约束返回条数，不得把"还有多少条没取"一起吞掉。

        covers 条数不设上限（T-11a 裁定），长轨迹上一档覆盖上千条是常态。
        截断静默发生 = 模型以为"这就是全部"（教义第 2 条禁止的谎报形态）。
        """
        orch = _orchestrator(agentId="a-t11d-trunc")
        await _foldTwice(orch)
        pool = orch.context_pool

        line = next(
            (l for l in pool.summaryLayers() if len(l["covers"]["hashes"]) > 2), None
        )
        assert line is not None, "本用例需要一个覆盖 >2 条的档位"
        from neurova.context.fold_index import renderCoversRef

        ref = renderCoversRef(line["fold_seq"], line["session_id"])
        partial = pool.drilldown(ref, limit=2)
        assert len(partial["entries"]) == 2, f"limit 未生效：{len(partial['entries'])}"
        assert partial["truncated"] == len(line["covers"]["hashes"]) - 2, (
            f"截断条数不可见：truncated={partial['truncated']}，"
            f"覆盖共 {len(line['covers']['hashes'])} 条"
        )

        full = pool.drilldown(ref, limit=len(line["covers"]["hashes"]) + 10)
        assert full["truncated"] == 0, f"未截断却报截断：{full['truncated']}"

    @pytest.mark.asyncio
    async def test_drilldown_miss_is_honest(self):
        """取不回必须点名原因，不许返回空成功（教义第 2 条）。"""
        orch = _orchestrator()
        await _foldTwice(orch)
        pool = orch.context_pool

        bogus = pool.drilldown("covers_ref=fold:99@sess-t11d")
        assert not bogus.get("resolved"), f"不存在的档位被当成成功：{bogus}"
        assert bogus.get("reason"), f"取不回却没点名原因：{bogus}"

        malformed = pool.drilldown("这段摘要里没有任何引用")
        assert not malformed.get("resolved"), f"解析失败被当成成功：{malformed}"
        assert malformed.get("reason"), f"解析失败却没点名原因：{malformed}"

    @pytest.mark.asyncio
    async def test_drilldown_respects_scope_gate(self):
        """新读路径与视图路径同源过闸：群聊档位在单聊轮不得原样吐出（放大视角）。"""
        orch = _orchestrator(agentId="a-t11d-scope")
        view = await _foldTwice(orch, collab=True, room_id="project_roomD")
        line = _summaryLine(view)
        assert line is not None, "视图里没有摘要行——本用例没打到折叠路径"

        pool = orch.context_pool
        roomTurn = pool.drilldown(line)
        assert roomTurn["entries"], (
            "本群轮下钻取不到本群档位的原文——作用域闸口把合法内容也挡了"
        )

        # 换成单聊轮：同一引用不得再吐出房间内容
        pool.turn_scope = None
        pool.session_id = "sess-t11d"
        directTurn = pool.drilldown(line)
        assert not directTurn["entries"], (
            f"单聊轮按群聊档位下钻取到了房间原文：{directTurn['entries'][:1]} —— "
            "新读路径绕过了作用域闸口（T-02 的隔离被破）"
        )
        assert directTurn["filtered"], (
            "被过滤的条数不可见：过滤静默发生等于无法判断闸口是否真的生效"
        )


class TestDrilldownToolWiring:
    """放大视角（教义第 5 条）：新工具的全部消费方一次性接齐，不留断点。"""

    def test_schema_has_dispatch_and_readonly_declarations(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS
        from neurova.agent.tool_coordinator import is_concurrency_safe
        from neurova.tool_executor import ToolExecutor

        name = "recall_context_span"
        assert name in _BUILTIN_SCHEMAS, "工具有执行体却没有 schema：LLM 永远看不到它"
        assert name in ToolExecutor._builtin_dispatch, "有 schema 无执行体：调用必失败"
        assert name in ToolExecutor._GOVERNANCE_FAILOPEN_READONLY_TOOLS, (
            "只读直取工具未进治理故障放行白名单"
        )
        assert is_concurrency_safe(name), "只读直取工具未声明并行安全"

    def test_roster_and_reproducibility(self):
        from neurova.builtin_tools import is_builtin_tool_reproducible
        from neurova.tool_layers.capability_graph import is_meta_retrieval_tool

        assert is_meta_retrieval_tool("recall_context_span"), (
            "下钻是元检索工具（结构上没有失败可能），不进名单会污染 RSI 反馈"
        )
        assert is_builtin_tool_reproducible("recall_context_span"), (
            "直取是纯读操作，被标成不可重现会让溢出策略对会话文件过度保守"
        )

class TestDrilldownSourceOfTruth:
    """教义第 6 条：池指纹与台账指纹是**两个域**，下钻不得把它们混用。

    这不是本票新造的差异，而是 T-11d 的根因：`covers` 里存的是**池内容指纹**
    （`ContextInput.compute_hash(source, content)`，带来源域），台账去重用的是
    **内容指纹**（`contentDigest(content)`，纯内容）。两个值不相等，所以即使索引
    齐全，重启后按 covers hash 去台账里查也必然落空 —— 直取面必须按**池指纹**
    建索引（写入侧一处派生），而不是让读侧去猜、去回退内容指纹。
    """

    def test_pool_hash_and_ledger_digest_are_distinct_domains(self):
        from neurova.context.eviction_ledger_db import contentDigest
        from neurova.context.pool_models import ContextInput as CI

        text = "同一段原文"
        poolHash = CI.compute_hash(ContextSource.CONVERSATION, text)
        ledgerDigest = contentDigest(text)
        assert poolHash != ledgerDigest, (
            "两个指纹域竟然相等：本票的根因描述作废，需重新定位"
        )
        assert poolHash == CI(source=ContextSource.CONVERSATION, content=text).hash

    def test_tool_call_entries_round_trip_by_pool_hash(self):
        """工具结果归档在 TOOL_CALL 域，直取面必须按同一域回得来。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s-t11d", ttl_seconds=0)
        pool.add_context(
            ContextInput(
                source=ContextSource.TOOL_CALL,
                content="工具输出正文",
                metadata={"role": "tool", "turn_id": "turn_1"},
            )
        )
        entry = pool.get_contexts()[0]
        assert pool.entriesByHash([entry.hash]), "池内按 hash 取不到刚归档的条目"
        assert pool.entriesByHash([entry.hash])[0].source == ContextSource.TOOL_CALL
        pool.close()
