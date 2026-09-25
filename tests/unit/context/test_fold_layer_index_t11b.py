# -*- coding: utf-8 -*-
"""T-11b 层节点索引：池内层节点带 `level` + `covers`，covers 可解析、可跨重启读回。

## 根因（不是"少写两个字段"）

T-11a 让折叠**分代**了，但代际栈只活在 `_window_compaction_cache`（进程内易失）
里：池内 `ContextSource.SUMMARY` 节点数实测 **0**，折叠路径从不把摘要写进池
（`archive_summary` 只被溢出恢复路径调用），节点 metadata 里也只有一个
`source_summary` 文本、没有 `covers`。

于是工单 §12.1 的 **C4 层即索引**在数据上不可能成立：

- 没有池内节点，"整个轨迹可寻址"没有落点（进程内缓存一重启即空）；
- 没有 `covers`，下钻（T-11d）无从知道一个摘要覆盖了哪些原文条目；
- 没有 `level`，视图装配器（T-11c）无法按分辨率档装配。

## 本票契约

- 折叠推进时把新代节点写进池（SUMMARY 源，走池的唯一写入咽喉 → 自动继承
  T-02 的会话作用域）；
- 节点 metadata 带 `covers`（turn 区间 + 被覆盖条目 hash 列表）与 `level`
  （档号，由 covers 派生，不另算一份事实）；
- covers 的数据源**复用 T-03 激活的 covered 集合**（工单 §12.3：不另算一份 hash）；
- 索引有唯一读面 `ContextPool.summaryLayers()`，解析失败率必须为 0，读数并进
  `get_context_health()["fold_index"]`（生产读者 = /metrics），不留"写了没人读"的断点；
- 索引随 T-07 持久层跨重启可读回（工单 §12.3：covers 不得只留在进程内缓存）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.pool_models import ContextInput, ContextSource


class _TurnIdentityAgent(MagicMock):
    """与 `agent_core.Agent` **同型**的替身：身份面转发 `core/turn_context` 的只读属性。

    会话隔离类判据必须走这条形状 —— 替身若把身份实现成普通可写字段，用例就会
    伪造出与生产不同的身份来源（T-03b 被 74 个 context 用例漏过的正是这一点）。
    """

    @property
    def current_session_id(self):
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()


def _agent(agentId: str = "a1"):
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
    """数据根注入（唯一注入口）：本票的折叠路径会写穿持久台账。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _round(i: int, chars: int = 400):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _counting_summarizer():
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    return calls, _summarize


def _orchestrator(agentId: str = "a1", budget: int = 600):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id="sess-layer-index"
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0  # 每轮都真摘要，判据打在层节点上而非防抖上
    return orch


def _identityOrchestrator(agentId: str = "a-identity"):
    """生产构造形状：**不传** session_id，身份走每轮单源（`agent.current_session_id`）。

    会话隔离类判据必须走这条形状 —— 手工传 session_id 会让 `_resolveTurnSessionId`
    在第 2 条就返回，测的是"构造期覆盖"而不是"每轮身份"，正是 T-03b 被 74 个
    用例漏过的那种假通过。
    """
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(_agent(agentId), use_pool=True, auto_tag=False)
    orch._window_token_budget = 1200
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


def _layerNodes(pool):
    return [
        c for c in pool.get_contexts() if c.source == ContextSource.SUMMARY
    ]




async def _build(orch, *, user_input, history, collab=False, room_id=""):
    """走生产构造面；摘要器按 `_window_summarizer` 注入（与既有两个 T-11 判据同形）。"""
    _, summarizer = _counting_summarizer()
    orch._window_summarizer = summarizer
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


def _longRound(i: int):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * 200}


async def _foldTwice(orch):
    """两轮长历史 → 两次折叠（走生产构造面：归档 → 折叠）。"""
    history = [_longRound(i) for i in range(14)]
    await _build(orch, user_input="继续", history=history)
    history = history + [_longRound(i) for i in range(14, 30)]
    await _build(orch, user_input="继续", history=history)
    return history


class TestLayerNodeIndex:
    """工单 §12.4 的两条具名判据（T-11b）。"""

    @pytest.mark.asyncio
    async def test_summary_node_carries_level_and_covers(self):
        """折叠产出的池内 SUMMARY 节点带可解析 covers，读面给出档号（T-11b）。

        **与工单 §12.4 原话的一处偏离（如实记录）**：原话是 metadata 增
        `level` + `covers`。实现存的键是 `fold_seq`（该次折叠的层序，不可变事实），
        **档号由读面派生**。理由是档号随新代产生而整体下移 —— 写进归档实体就要
        每次折叠就地改写已归档节点（与 T-04「归档实体永不原地改写」正面冲突），
        且会把每一代都写成 `level=1`（写它那一刻它确实是最新一档），
        于是"档号"退化成恒 1 的谎报面。层序是事实，档号是它的确定性函数。
        """
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        nodes = _layerNodes(orch.context_pool)
        assert nodes, (
            "折叠后池内没有任何 SUMMARY 层节点：代际栈仍只活在进程内折叠缓存里"
            "（工单 §12.3：covers 不得只留在 _window_compaction_cache）"
        )
        layered = [n for n in nodes if (n.metadata or {}).get("covers")]
        assert layered, f"层节点没有 covers：{[n.metadata for n in nodes]}"

        for node in layered:
            covers = node.metadata["covers"]
            assert isinstance(covers, dict) and covers, (
                f"层节点没有可解析的 covers：{node.metadata} —— 没有索引就不是层"
            )
            assert covers.get("hashes"), f"covers 缺 hash 列表：{covers}"
            turn_range = covers.get("turn_range")
            assert isinstance(turn_range, (list, tuple)) and len(turn_range) == 2, (
                f"covers 缺 turn 区间：{covers}"
            )
            assert int(turn_range[0]) <= int(turn_range[1]), f"turn 区间倒序：{turn_range}"
            assert isinstance(node.metadata.get("fold_seq"), int), (
                f"层节点缺层序（档号的派生基准）：{node.metadata.keys()}"
            )

        layers = orch.context_pool.summaryLayers()
        assert [layer["level"] for layer in layers] == list(range(1, len(layers) + 1)), (
            f"读面档号应为 1..N（最新一代 1，越早越大）：{[l['level'] for l in layers]}"
        )
        assert layers[0]["fold_seq"] > layers[-1]["fold_seq"], (
            "读面顺序不对：档号 1 应对应最新层序"
        )

    @pytest.mark.asyncio
    async def test_covers_hashes_resolve_to_archived_entries(self):
        """covers 的每个 hash 都能解析到池内已归档条目（解析失败率 = 0）。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        pool = orch.context_pool
        nodes = [n for n in _layerNodes(pool) if (n.metadata or {}).get("covers")]
        assert nodes, "没有带 covers 的层节点——本用例没打到索引路径"

        for node in nodes:
            hashes = list(node.metadata["covers"].get("hashes") or [])
            resolved = {getattr(e, "hash", None) for e in pool.entriesByHash(hashes)}
            missing = [h for h in hashes if h not in resolved]
            assert not missing, (
                f"层节点 covers 里有 {len(missing)} 个 hash 在池内解析不到："
                f"{missing[:2]} —— 索引指向不存在的原文，下钻必然取空"
            )

    @pytest.mark.asyncio
    async def test_layer_nodes_inherit_turn_scope(self):
        """放大视角（教义第 5 条）：层节点走池的唯一写入咽喉，自动继承会话作用域。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        history = [_longRound(i) for i in range(14)]
        await _build(
            orch, user_input="继续", history=history, collab=True, room_id="project_roomZ"
        )

        nodes = _layerNodes(orch.context_pool)
        assert nodes, "群轮折叠后没有层节点——本用例没打到写入路径"
        scopes = {(n.metadata or {}).get("chat_scope") for n in nodes}
        assert scopes == {"room:project_roomZ"}, (
            f"层节点未继承会话作用域：{scopes} —— 群聊摘要会在单聊轮可见"
        )

    @pytest.mark.asyncio
    async def test_layer_index_read_face_reports_no_unparsable(self):
        """索引唯一的读面 + 读数（生产读者 = /metrics 的 context_health 快照）。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        layers = orch.context_pool.summaryLayers()
        assert layers, "summaryLayers() 读不到层节点——索引写了没人读（断点）"
        assert all(layer.get("covers") for layer in layers), (
            f"读面返回的层节点缺 covers：{layers}"
        )
        assert all(layer.get("level") for layer in layers), (
            f"读面返回的层节点缺 level：{layers}"
        )

        readout = orch.get_context_health()["fold_index"]
        assert readout["nodes"] == len(layers), (
            f"读数 nodes={readout['nodes']} 与索引 {len(layers)} 不符"
        )
        assert readout["unparsable"] == 0, (
            f"covers 解析失败率必须为 0，实得 {readout['unparsable']}"
        )
        assert readout["uncovered"] == 0, (
            f"覆盖闭合被破坏：{readout['uncovered']} 个已折叠 hash 不在任何档的 covers 里"
        )
        assert readout["last_error"] is None, f"读数点名了失败原因：{readout['last_error']}"


class TestLayerIndexPersists:
    """T-07 已让池归档跨重启为真：索引必须随同一条通路落库（工单 §12.3）。"""

    @pytest.mark.asyncio
    async def test_layer_nodes_readable_after_restart(self):
        orch = _orchestrator(agentId="a-restart-t11b")
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        before = orch.context_pool.summaryLayers()
        assert before, "折叠后没有层节点——本用例没打到索引路径"
        orch.context_pool.close()

        from neurova.context.orchestrator import ContextOrchestrator

        fresh = ContextOrchestrator(
            _agent("a-restart-t11b"),
            use_pool=True,
            auto_tag=False,
            session_id="sess-layer-index",
        )
        after = fresh.context_pool.summaryLayers()
        assert [layer["covers"] for layer in after] == [
            layer["covers"] for layer in before
        ], (
            "层节点索引活不过一次重启：covers 只留在进程内缓存/常驻列表里，"
            f"重启后读到 {len(after)} 档（改前 {len(before)} 档）"
        )
        fresh.context_pool.close()


class TestCoversSingleSource:
    """教义第 6 条：covers 只有一份事实源，不留第二份 hash 清单。"""

    @pytest.mark.asyncio
    async def test_covers_reuse_the_covered_set(self):
        """covers 的 hash 数据源复用折叠缓存的 `covered` 集合（工单 §12.3）。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        slot = orch._window_compaction_cache["sess-layer-index"]
        covered = set(slot.get("covered") or set())
        assert covered, "折叠缓存没有 covered 集合——本用例没打到覆盖路径"

        node_hashes = set()
        for node in [n for n in _layerNodes(orch.context_pool) if n.metadata.get("covers")]:
            node_hashes |= set(node.metadata["covers"].get("hashes") or [])
        assert node_hashes, "层节点没有 covers hash"
        assert node_hashes <= covered, (
            "层节点 covers 里有折叠缓存 `covered` 集合之外的 hash："
            f"{sorted(node_hashes - covered)[:2]} —— 索引另算了一份覆盖事实（第二份事实源）"
        )

    @pytest.mark.asyncio
    async def test_layer_nodes_do_not_duplicate_across_folds(self):
        """同一代的层节点只入池一次：重复入池会让索引里出现两行同一档。"""
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        layers = orch.context_pool.summaryLayers()
        keys = [(layer["level"], tuple(layer["covers"]["hashes"])) for layer in layers]
        assert len(set(keys)) == len(keys), f"索引出现重复层节点：{keys}"


class TestIndexNodesStayOutOfRelevanceRecall:
    """层节点由**确定性索引**寻址，不参加概率性相关性召回（工单 §12.5 第 3 条）。

    这条是本票开工后由 A/B 咬出来的：层节点入池后立刻被抽屉的相关性召回捞走，
    当场两个后果 —— ① 本会话摘要被再召回一次（与折叠桩重复注入）；
    ② 抽屉召回应跨会话（两个单聊会话作用域都是 `direct`），A 会话摘要泄进
    B 会话视图，把 T-03 刚收口的隔离又破掉。
    """

    @pytest.mark.asyncio
    async def test_layer_nodes_are_not_returned_by_draw(self):
        orch = _orchestrator()
        orch._window_token_budget = 1200
        await _foldTwice(orch)

        layers = orch.context_pool.summaryLayers()
        assert layers, "没有层节点——本用例没打到索引路径"

        # need 取层节点原文本身 = 该节点可能的最高相关性；它若参加召回，
        # 必然出现在视图里（这是最能证伪的输入，不是"碰运气"的输入）。
        drawn = orch.context_pool.draw(need=layers[0]["content"], budget_tokens=8000)
        drawn_contents = {c.content for c in drawn}
        leaked = [
            layer["content"] for layer in layers
            if layer["content"] in drawn_contents
        ]
        assert not leaked, (
            f"层节点被抽屉相关性召回捞进视图：{leaked[:2]} —— 索引节点必须由确定性"
            "索引寻址，混进召回面就会重复注入并与折叠桩打架"
        )

    @pytest.mark.asyncio
    async def test_layer_node_does_not_leak_across_direct_sessions(self):
        """B 会话轮不得把 A 会话的层节点召进视图（T-03 的隔离不得被本票破掉）。

        对抗输入取 A 节点原文本身（用户逐字复述摘要）：相关性门槛在它身上必然
        最高，所以"召回面把索引节点捞走"这条链在这里必定显形 —— 不是碰运气。
        两个单聊会话作用域都是 `direct`，靠作用域闸口挡不住这条，只能靠
        索引面/召回面的分工挡住。
        """
        from neurova.core.turn_context import set_turn_identity

        orch = _identityOrchestrator()
        try:
            set_turn_identity("继续", "sess_A", "u1")
            await _build(orch, user_input="继续", history=[_longRound(i) for i in range(14)])
            set_turn_identity("继续", "sess_B", "u1")
            await _build(
                orch, user_input="继续", history=[_longRound(i) for i in range(14, 30)]
            )
        finally:
            set_turn_identity("", None, None)

        a_layers = [
            layer["content"]
            for layer in orch.context_pool.summaryLayers()
            if layer["session_id"] == "sess_A"
        ]
        assert a_layers, "A 会话没有层节点——本用例没打到索引路径"

        drawn = {
            c.content
            for c in orch.context_pool.draw(need=a_layers[0], budget_tokens=8000)
        }
        leaked = [text for text in a_layers if text in drawn]
        assert not leaked, (
            f"B 会话轮按 A 的摘要原文召回，捞到了 A 的层节点：{leaked[:2]} —— "
            "索引节点必须由确定性索引寻址（工单 §12.5 第 3 条）"
        )
