# -*- coding: utf-8 -*-
"""T-11c 判据 4：顶概览**每轮常驻**且其 covers 触达会话起点（Issue #90 · §12.7 第 4 条）。

## 为什么单独立一条（它此前只有"未单独钉住"的登记）

台账 §27.5 第 3 条如实写着：T-11c 只保证了"多档 + 位置序"，**未**单独钉住
「连续 30 轮每轮都含触达起点的顶概览」。工单 §12.7 判据 4 的通过线是：
*"连续 30 轮每轮都含 L3 且其 covers 触达会话起点；出现『只剩尾部原文、
无任何概览』的轮次即红"*。

那条承诺此前既没有判据也没有探针读数 —— 它只写在工单里。"写在文档里"
与"有人守"是本仓反复收口的两种状态（教义第 2 条禁止的正是"看着像有门禁"）。

## 判据是什么（以及它**不是**什么）

判据取三件**客观事实**，都不自己算一遍：

1. 本轮**是否发生过折叠**（`_last_folded_hashes` 非空，编排器的事实）；
2. 视图里**是否有概览行**（`SUMMARY_PREFIX` 的行，装配器的产物）；
3. 这些行对应的池档，其 `covers.turn_range` 左端是否等于**本会话覆盖起点**
   （索引单点派生 `summaryLayers()`，起点 = 本会话各档左端的最小值）。

第 3 条取"本会话各档左端的最小值"而不是硬编码 `1`：轮次 id 由
`assign_turn_ids` 按 user 消息计数，**每会话各从 1 起算**（T-11c 的跨会话教训
同源），写成常数 `1` 会把"本会话起点是 5"的合法情形误判。

## 为什么这条判据会红（它不是恒真的）

正向路径上它**当前成立**，原因是覆盖账的语义：`cache["covered"]` 是**累积**
集合，每轮新档的 covers 都含自会话起点以来的全部 hash，故任一档都触达起点。
但这份成立是**被实现的性质**，不是被守住的性质 —— 一旦：

- 装配器只装最近 k 档而把最深（最早）那档挤出阶梯（`dropped_levels > 0` 的
  形态就是它），且遗留档的 covers 不触达起点；
- 或覆盖账被按"本轮增量"重建（每档只说本轮覆盖的那一段，那才是"越远越模糊"
  的自然读法）；

判据当场转红。故本文件带**反向控制**：喂一个 covers 不含会话起点的档，
判定必须报违规 —— 否则这条判据就是恒真断言（教义第 3 条明禁）。

## 与探针 P15 的分工

本文件是**常驻门禁**（受保护子集，每 CI 跑）；探针
`tests/manual/audit_context_chain_20260921.py` 的 P15 是**取证读数**
（手工跑、打印 30 轮逐轮明细）。两者取同一份判定 helper，不各写一份口径。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _TurnIdentityAgent(MagicMock):
    """与 `agent_core.Agent` 同型的替身：身份面转发 `core/turn_context` 的只读属性。"""

    @property
    def current_session_id(self):
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()


def _agent(agentId: str = "a-t11c-resident"):
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


def _orchestrator(agentId: str = "a-t11c-resident", budget: int = 8000):
    """预算 8000 ≈ §12.7 测量规程的"128k 档型号"（窗口份额形态与 P15 同源）。

    刻意用**同一份测量规程参数**（§12.7 明文固定）而不是随手一个预算：
    判据与探针取不到同一形状的读数，就会变成两个各自成立的结论。
    """
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id=f"sess-{agentId}"
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0  # 每轮都真摘要：判据打在装配器上而非防抖上
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条。" + "细节" * 120

    orch._window_summarizer = _summarize
    return orch


def _round(i: int) -> dict:
    """§12.7 测量规程的轨迹形态：三形态混合（中文散文 : 英文散文 : JSON = 4:4:2），
    每轮 ≥800 token；中文/英文/JSON 各占一轮的不同形态。"""
    kind = i % 5
    if kind in (0, 1):
        body = "本轮讨论产品演进路线与验收口径。" * 60
    elif kind in (2, 3):
        body = "This round reviews the roadmap and the acceptance criteria. " * 40
    else:
        body = '{"trace":["' + "a" * 1200 + '"],"ok":true}'
    return {"role": "user", "content": f"第{i}轮：{body}"}


async def _build(orch, history):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续", session_context=history, relevant_memories=[]
        )


def _overviewRows(view) -> list:
    """视图里的概览行（装配器产物；判定与探针共用同一取数口径）。"""
    from neurova.context.window_compactor import SUMMARY_PREFIX

    return [
        str(msg.get("content", ""))
        for msg in (view or [])
        if (msg or {}).get("role") == "system"
        and SUMMARY_PREFIX in str((msg or {}).get("content", ""))
    ]


def _sessionStart(orch) -> int | None:
    """本会话索引里的**覆盖起点**：各档 `covers.turn_range` 左端的最小值。

    取最小值而非常数 `1`：轮次 id 每会话各从 1 起算（T-11c 的跨会话教训同源），
    硬编码 `1` 会把"本会话起点是别的值"的合法情形误判成违规。
    """
    pool = orch.context_pool
    lefts = []
    for layer in pool.summaryLayers():
        if layer.get("session_id") != pool.session_id:
            continue
        span = (layer.get("covers") or {}).get("turn_range") or []
        if span:
            lefts.append(int(span[0]))
    return min(lefts) if lefts else None


def topOverviewReachesSessionStart(rows: list, layers: list, sessionKey, start) -> bool:
    """判定：给定视图概览行与池索引，是否存在一行触达会话起点。

    这是判据 4 的**唯一判定实现**——正向用例与反向控制都调它，反向控制因此
    证明它可证伪（不是恒真断言）。`rows` 与 `layers` 都是**实测**取来的，
    判定不重算 indices、不重算几何比。
    """
    from neurova.context.fold_index import parseCoversRef

    if start is None:
        return False
    bySeq = {
        layer["fold_seq"]: layer
        for layer in layers
        if layer.get("session_id") == sessionKey
    }
    for row in rows:
        parsed = parseCoversRef(row)
        if parsed is None:
            continue
        layer = bySeq.get(parsed[0])
        if layer is None:
            continue
        span = (layer.get("covers") or {}).get("turn_range") or []
        if span and int(span[0]) <= int(start):
            return True
    return False


class TestTopOverviewStaysResident:
    """§12.7 判据 4：连续 30 轮，每轮发生折叠时视图必含触达会话起点的概览。"""

    @pytest.mark.asyncio
    async def test_every_turn_keeps_a_top_overview_reaching_session_start(self):
        orch = _orchestrator()
        history = [_round(i) for i in range(14)]
        violations = []
        foldedTurns = 0
        for rnd in range(30):
            if rnd:
                history = history + [_round(100 + rnd - 1)]
            view = await _build(orch, history)

            folded = bool(getattr(orch, "_last_folded_hashes", None))
            if not folded:
                # 未折叠的轮次没有概览行是**正确**的（凭空造一行就是谎报
                # §12.5 第 2 条），因此不参与判定。
                continue
            foldedTurns += 1

            rows = _overviewRows(view)
            layers = orch.context_pool.summaryLayers()
            start = _sessionStart(orch)
            if not rows:
                violations.append((rnd + 1, "折叠发生但视图无任何概览行（只剩尾部原文）"))
            elif not topOverviewReachesSessionStart(
                rows, layers, orch.context_pool.session_id, start
            ):
                violations.append(
                    (rnd + 1, f"概览行未触达会话起点 {start}：{len(rows)} 行均不覆盖起点")
                )
        orch.context_pool.close()

        assert foldedTurns >= 10, (
            f"30 轮里只有 {foldedTurns} 轮发生了折叠 —— 本用例没打到装配路径"
        )
        assert not violations, (
            "存在「只剩尾部原文、无任何概览」或「概览不触达会话起点」的轮次"
            f"（工单 §12.7 判据 4）：{violations[:5]}"
        )

    @pytest.mark.asyncio
    async def test_judgement_rejects_a_layer_that_misses_the_session_start(self):
        """反向控制：喂一个 covers 不含会话起点的档，判定必须报违规。

        没有这条，上面那条就是恒真断言 —— 本仓把"恒真断言"列为禁止写法
        （教义第 3 条）。反向控制的靶点正是判据 4 的实质：**起点**是否被覆盖，
        而不是"有没有概览行"。
        """
        from neurova.context.fold_index import renderCoversRef

        rows = ["[早期对话摘要] 中段概览…\n(" + renderCoversRef(1, "sess-x") + ")"]
        layers = [
            {
                "fold_seq": 1,
                "level": 1,
                "session_id": "sess-x",
                # 只覆盖中段：起点 1 不在区间内
                "covers": {"turn_range": [5, 9], "hashes": ["h5", "h9"]},
            }
        ]
        assert not topOverviewReachesSessionStart(rows, layers, "sess-x", 1), (
            "判定对「档不覆盖会话起点」的形态返回了 True —— 判据 4 是恒真断言"
        )
        # 同一份索引，把起点放宽到区间内 → 判定必须转 True（两个方向都可证伪）
        assert topOverviewReachesSessionStart(rows, layers, "sess-x", 5), (
            "判定对「档覆盖了起点」的形态返回 False —— 判定方向反了"
        )

    @pytest.mark.asyncio
    async def test_judgement_ignores_another_session_layers(self):
        """反向控制（同族）：别的会话的档不得被当成"本会话触达起点"。

        与 T-11c 的跨会话教训同源 —— 索引读面按会话分组派生档号，
        判定若不过滤会话，就会把别人的层当成自己的概览。
        """
        from neurova.context.fold_index import renderCoversRef

        rows = ["[早期对话摘要] 他人的概览…\n(" + renderCoversRef(1, "sess-other") + ")"]
        layers = [
            {
                "fold_seq": 1,
                "level": 1,
                "session_id": "sess-other",
                "covers": {"turn_range": [1, 9], "hashes": ["h1"]},
            }
        ]
        assert not topOverviewReachesSessionStart(rows, layers, "sess-mine", 1), (
            "判定把别的会话的档当成了本会话的概览 —— 跨会话串档（T-11c 同族）"
        )
