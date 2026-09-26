# -*- coding: utf-8 -*-
"""T-11c 分辨率装配器：视图按距离装配 1:4:16 档间预算的分辨率梯度（Issue #90）。

## 根因（不是"视图里少一行摘要"）

T-11a/b/d/e 让折叠**分代**、层节点**带 covers 落池**、引用**可解析下钻**、
rollup **退回后台**。而**视图装配器**这一环从没改过：`build_context` 把
`compact_window` 产出的那一行摘要（= 代际栈顶）拼进 `context` 就结束了。

实测（真 `build_context` 连跑 6 轮，budget 1200）：池内 **6 档层节点**，
视图里 **1 行摘要**。于是工单 §12.1 的

- **C2 梯度**（视图内不同 `level` 数 ≥ 3、档间预算比 1:4:16）在数据上不成立；
- **§12.0 B 概览梯度常驻**（越远的位置分辨率越低）无落点 —— 只有一代，
  谈不上"越远"；
- §12.7 判据 1（梯度存在）、判据 2（单调性）与探针 **P15** 全红。

## 本票契约

1. 视图从池的层索引（`summaryLayers()`，唯一读面）按档号装配**多档**概览行：
   近档预算大、远档预算小，**至少三档**；顺序按位置由远及近（老→新）；
2. 档间 token 预算比 = **相邻比 4**（1 : 4 : 16 的几何阶梯），容差 ±25%；
   比由 `context/fold_resolution.py` **单点**定义，装配器与读数都取它；
3. **单调性**：按位置分辨率（每覆盖一轮的 token 数）**非递增**；
4. 每档行仍带 `covers_ref`（T-11d 的确定性寻址不得因截断失效）；
5. 截断必须**可见**：读数记 `truncated_chars`，行内补省略标记；
6. 回退开关 `NEUROVA_CONTEXT_FOLD_RESOLUTION=0` 时视图逐字回到本票之前的形状。

## 关于「1 : 4 : 16」的方向（单点解读，已登记进工单 §12.4）

规格把比写成按档号升序的数列，而 §12.0 B 与 §12.7 判据 2 要求**越远分辨率越低**。
二者只有在"档号升序 = 位置由近及远、预算由大到小"时同时成立：近档 16 份、
中档 4 份、远档 1 份（相邻比恒为 4，按距离升序读即 1 : 4 : 16）。
反向读（远档拿 16 份）会当场违反判据 2。故阶梯取**相邻比 4 的几何序列**。

## 判据测的是**实际授予的预算**，不是测试自算的数

档位预算从读数 `fold_resolution["level_budgets"]`（装配器本轮的真实决定，单源
`fold_resolution.ladderBudgets`）取；覆盖轮数从池索引 `covers.turn_range` 取。
测试**不自己算几何比**——自算一份就是把被测的算法抄进判据里，等于恒真断言。
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


def _agent(agentId: str = "a-t11c"):
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


def _longRound(i: int, chars: int = 1200):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _summarizerText(calls: dict, covered: int) -> str:
    """一代摘要的文本。长度取真实 LLM 摘要量级（数百 token），使预算判据有意义。"""
    return f"第{calls['n']}代摘要：覆盖 {covered} 条。" + "细节" * 120


def _orchestrator(agentId: str = "a-t11c", budget: int = 8000):
    """预算 8000 ≈ §12.7 测量规程的"128k 档型号"（窗口份额 0.6 → 47185 的同一形态：
    概览区远大于单条摘要长度，阶梯因此能长出多档）。"""
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id="sess-t11c"
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0  # 每轮都真摘要：判据打在装配器上而非防抖上
    return orch


def _summarizer():
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return _summarizerText(calls, len(dropped_msgs))

    return calls, _summarize


async def _build(orch, history, user_input="继续"):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input, session_context=history, relevant_memories=[]
        )


async def _foldMany(orch, rounds: int = 6):
    """连续多轮折叠（走生产构造面：归档 → 折叠 → 视图装配）。"""
    _, summarizer = _summarizer()
    orch._window_summarizer = summarizer
    history = [_longRound(i) for i in range(14)]
    view = await _build(orch, history)
    for rnd in range(rounds - 1):
        history = history + [_longRound(100 + rnd)]
        view = await _build(orch, history)
    return view


def _viewEntries(orch, view):
    """视图里的概览行 → `{level, content, tokens, layer}`（档号由池索引单点派生）。

    档号不在这里另算：引用由 `fold_index.parseCoversRef` 单点解析，档号由
    `summaryLayers()` 单点派生，本 helper 只做拼接。
    """
    from neurova.context.fold_index import parseCoversRef
    from neurova.context.token_estimator import estimate_tokens

    layers = {layer["fold_seq"]: layer for layer in orch.context_pool.summaryLayers()}
    entries = []
    for msg in view or []:
        content = str((msg or {}).get("content", ""))
        if (msg or {}).get("role") != "system" or "早期对话摘要" not in content:
            continue
        parsed = parseCoversRef(content)
        assert parsed is not None, (
            f"概览行不带可解析引用：{content[-80:]!r} —— 截断把地址吃掉了"
        )
        layer = layers.get(parsed[0])
        assert layer is not None, f"引用 {parsed[0]} 在索引里不存在（悬空引用）"
        entries.append(
            {
                "level": layer["level"],
                "content": content,
                "tokens": estimate_tokens(content),
                "layer": layer,
                "position": len(entries),
            }
        )
    return entries


class TestResolutionGradient:
    """§12.7 判据 1 + 判据 2（T-11c 的两条具名判据）。"""

    @pytest.mark.asyncio
    async def test_view_exposes_three_resolutions_in_geometric_budget(self):
        """视图内 `level` 档数 ≥ 3，且相邻档预算比 = 1:4:16（容差 ±25%）。"""
        orch = _orchestrator()
        view = await _foldMany(orch, rounds=6)

        layers = orch.context_pool.summaryLayers()
        assert len(layers) >= 3, (
            f"池内只有 {len(layers)} 档层节点 —— 本用例没打到分代路径（先修 T-11a/b）"
        )

        entries = _viewEntries(orch, view)
        levels = sorted({entry["level"] for entry in entries})
        assert len(levels) >= 3, (
            f"视图内只有 {len(levels)} 档概览（{levels}）—— 池里有 {len(layers)} 档，"
            "视图仍只装配栈顶一代：分辨率梯度在数据上不成立（工单 §12.1 C2）"
        )

        readout = orch.get_context_health()["fold_resolution"]
        budgets = list(readout["level_budgets"])[:3]
        assert len(budgets) >= 3, f"读数未给出三档预算：{readout}"
        for near, far in zip(budgets, budgets[1:]):
            ratio = near / far
            assert 4 * 0.75 <= ratio <= 4 * 1.25, (
                f"相邻档预算比 {near}:{far} = {ratio:.2f}，不在 1:4:16 的 ±25% 内"
            )

    @pytest.mark.asyncio
    async def test_farther_distance_never_higher_resolution(self):
        """按位置分辨率（每覆盖一轮的 token 数）非递增：更远的档不得更细。"""
        orch = _orchestrator()
        view = await _foldMany(orch, rounds=6)

        entries = _viewEntries(orch, view)
        assert len({entry["level"] for entry in entries}) >= 3, (
            f"视图档数不足三档，单调性无从判定：{sorted(e['level'] for e in entries)}"
        )
        # 位置序必须是**由远及近**（老→新），否则"位置"这件事没有被装配器表达出来
        assert [entry["level"] for entry in entries] == sorted(
            (entry["level"] for entry in entries), reverse=True
        ), (
            f"概览行未按位置由远及近排列：{[e['level'] for e in entries]} —— "
            "时间序被打乱，模型读到的是乱序历史"
        )

        readout = orch.get_context_health()["fold_resolution"]
        budgets = {
            level: budget
            for level, budget in zip(
                sorted({entry["level"] for entry in entries}),
                readout["level_budgets"],
            )
        }
        # 每覆盖一轮的 token 数（分辨率密度）；按档号升序 = 位置由近及远
        densities = []
        for entry in sorted(entries, key=lambda e: e["level"]):
            span = entry["layer"]["covers"]["turn_range"]
            covered = max(1, int(span[1]) - int(span[0]) + 1)
            densities.append((entry["level"], budgets[entry["level"]] / covered))
        for (nearLevel, nearDensity), (farLevel, farDensity) in zip(
            densities, densities[1:]
        ):
            assert nearDensity >= farDensity, (
                f"更远的档分辨率更高：level {farLevel} 每覆盖轮 {farDensity:.2f} token "
                f"> level {nearLevel} 的 {nearDensity:.2f}（工单 §12.7 判据 2）"
            )


class TestResolutionReadoutAndHonesty:
    """截断/丢弃必须可见；引用必须活在截断之后（T-11d 的寻址不得被截断吃掉）。"""

    @pytest.mark.asyncio
    async def test_readout_reports_levels_and_truncation(self):
        orch = _orchestrator()
        await _foldMany(orch, rounds=6)

        readout = orch.get_context_health()["fold_resolution"]
        assert readout["levels"] >= 3, f"读数未上报视图档数：{readout}"
        assert readout["budget_ratio"] == 4, f"档间预算比不是几何比 4：{readout}"
        assert readout["truncated_chars"] > 0, (
            f"远档预算小于其文本却报零截断：{readout} —— 截断不可见"
        )
        assert readout["last_error"] is None, f"读数点名了失败：{readout['last_error']}"

    @pytest.mark.asyncio
    async def test_reference_survives_truncation(self):
        """远档被裁到更小预算时：引用仍在行内，且**实测行内 token 不超其授予预算**。"""
        orch = _orchestrator()
        view = await _foldMany(orch, rounds=6)

        readout = orch.get_context_health()["fold_resolution"]
        entries = _viewEntries(orch, view)
        far = [entry for entry in entries if entry["level"] >= 2]
        assert far, "视图里没有远档 —— 本用例没打到装配路径"

        levels = sorted({entry["level"] for entry in entries})
        budgets = dict(zip(levels, readout["level_budgets"]))
        for entry in entries:
            assert entry["tokens"] <= budgets[entry["level"]], (
                f"level {entry['level']} 实测 {entry['tokens']} token 超出其授予预算 "
                f"{budgets[entry['level']]} —— 预算形同虚设"
            )
        # 截断必须真的发生过，否则本判据是恒真的
        assert any(entry["tokens"] < budgets[entry["level"]] for entry in far), (
            f"远档无一受预算约束：{[(e['level'], e['tokens']) for e in far]}"
        )


class TestRollbackEquality:
    """§12.6 回退等式：开关关闭时视图必须等价于 T-11c 之前的形状。"""

    @pytest.mark.asyncio
    async def test_switch_off_equals_pre_t11c_shape(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_CONTEXT_FOLD_RESOLUTION", "0")
        orch = _orchestrator(agentId="a-t11c-off")
        view = await _foldMany(orch, rounds=6)

        layers = orch.context_pool.summaryLayers()
        assert len(layers) >= 3, "池内档数不足 —— 本用例没打到分代路径"

        summaries = [
            m for m in view
            if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))
        ]
        assert len(summaries) == 1, (
            f"开关关闭时视图仍装配了 {len(summaries)} 行概览 —— 回退等式不成立"
            "（§12.6：关闭即回到本票之前的形状）"
        )
        readout = orch.get_context_health()["fold_resolution"]
        assert readout["enabled"] is False, f"开关关闭但读数未如实标注：{readout}"
        assert readout["levels"] == 1, f"开关关闭时不应装配多档：{readout}"


class TestIndexIsSessionScoped:
    """放大视角（教义第 5 条）：本票 A/B 咬出的**同根因命中点** —— 索引读面跨会话串档。

    根因不在装配器，而在 T-11b 的索引读面：`fold_seq`（层序）是**会话内**的事实，
    而 `summaryLayers()` 把同一 agent 台账库里的**全部会话**的 SUMMARY 行并成一个
    列表，再按**全局**最大层序派生档号。于是

    - 新会话的第一代（层序 1）会被别的会话/历史行把档号推到 21；
    - 档号 1 落到**别的会话**那一行上。

    改前这个缺陷是潜伏的（索引写进去没人按档号取用）。本票的装配器一按档号装配，
    它当场变成**跨会话摘要注入视图**（T-03/T-03b 刚收口的那类泄漏），并让四条
    既有用例转红。故按教义第 1 条在根因处修：索引按会话分组派生档号，
    装配器/下钻只取**本会话**的档。
    """

    @pytest.mark.asyncio
    async def test_layer_index_does_not_borrow_other_session_ordinals(self):
        """同一 agent 台账库里有两个会话时：索引不得把别的会话的层序当本会话基准。"""
        from neurova.context_pool import ContextPool

        poolA = ContextPool(user_id="u1", agent_id="a-t11c-scope", session_id="sess-A")
        for seq in range(1, 4):
            poolA.archive_summary(
                f"A会话第{seq}代摘要" * 4,
                covers={"turn_range": [1, 10 + seq], "hashes": [f"ha{seq}"]},
                foldSeq=seq,
            )
        poolA.close()

        poolB = ContextPool(user_id="u1", agent_id="a-t11c-scope", session_id="sess-B")
        poolB.archive_summary(
            "B会话第1代摘要" * 4,
            covers={"turn_range": [1, 5], "hashes": ["hb1"]},
            foldSeq=1,
        )

        mine = [layer for layer in poolB.summaryLayers() if layer["session_id"] == "sess-B"]
        assert mine, f"B 会话读不到自己的档：{poolB.summaryLayers()}"
        assert [layer["level"] for layer in mine] == [1], (
            f"B 会话唯一一代的档号是 {[l['level'] for l in mine]}，不是 1 —— "
            "档号按**全局**层序派生，被别的会话的层序推高了（层序是会话内事实）"
        )

    @pytest.mark.asyncio
    async def test_view_never_shows_another_session_summary(self):
        """装配器不得把别的会话的层节点装进本会话视图（T-03 的隔离不得被破）。"""
        from neurova.context_pool import ContextPool

        poolA = ContextPool(user_id="u1", agent_id="a-t11c-leak", session_id="sess-A")
        for seq in range(1, 4):
            poolA.archive_summary(
                f"甲会话机密第{seq}代" * 4,
                covers={"turn_range": [1, 10 + seq], "hashes": [f"ha{seq}"]},
                foldSeq=seq,
            )
        poolA.close()

        orch = _orchestrator(agentId="a-t11c-leak")
        orch._window_token_budget = 8000
        await _foldMany(orch, rounds=3)

        joined = "\n".join(str(m.get("content", "")) for m in await _foldMany(orch, rounds=3))
        assert "甲会话机密" not in joined, (
            "本会话视图里出现了别的会话的摘要 —— 索引跨会话串档，装配器按档号把"
            "别的会话的内容装了进来（P1-1/T-03 同族的泄漏）"
        )

class TestAssemblyWorkDoesNotScaleWithTrajectoryLength:
    """判据 6 延迟侧的**结构不变量**（常驻门禁；比值侧见 live-verify 脚本）。

    工单 §12.7 判据 6 的延迟口径是「视图构建延迟 p95 ≤ 关闭时基线 ×1.2」。
    本仓的既定纪律（`test_ci_wallclock_assertion_ledger` /
    `test_clock_caliber_ledger` 两份台账）是：**把结构性契约编码成墙钟阈值**
    会被负载判红、且误判方向是"越忙越红"，而那条捷径恰好放行真的尾延迟回归。

    故常驻门禁守**结构**：装配工作量由概览区额度界定，**不随索引档数增长** ——
    同一份窗口预算下，索引 5 档与 30 档装配出的档数必须相同、各档授予预算相同。
    真退化（"越长的轨迹装越多档"）在这条判据上当场咬合，与机器快慢无关。

    比值侧的可比读数由 live-verify 脚本留存（它打印同机 A/B 的 p50/p95），
    实测 p95 比 1.02–1.07、裕量 8–16% —— 裕量偏小，故不做常驻阈值判据。
    """

    @staticmethod
    def _sessionLayerCount(orch) -> int:
        pool = orch.context_pool
        return len(
            [layer for layer in pool.summaryLayers() if layer["session_id"] == pool.session_id]
        )

    @pytest.mark.asyncio
    async def test_assembly_work_does_not_scale_with_trajectory_length(self):
        """同一窗口预算下：索引档数从 5 涨到 30，装配档数与各档预算必须不变。"""
        shapes = {}
        for rounds in (5, 15, 30):
            orch = _orchestrator(agentId=f"a-t11c-scale-{rounds}")
            await _foldMany(orch, rounds=rounds)
            readout = orch.get_context_health()["fold_resolution"]
            shapes[rounds] = (
                self._sessionLayerCount(orch),
                readout["levels"],
                tuple(readout["level_budgets"]),
            )
            orch.context_pool.close()

        indexCounts = [shapes[r][0] for r in (5, 15, 30)]
        assert indexCounts == [5, 15, 30], (
            f"索引档数未随轨迹增长（{indexCounts}）—— 本用例没打到长轨迹形态，"
            "判据在空转"
        )
        assembled = {shapes[r][1] for r in (5, 15, 30)}
        budgets = {shapes[r][2] for r in (5, 15, 30)}
        assert len(assembled) == 1, (
            f"装配档数随索引档数增长：{ {r: shapes[r][1] for r in (5, 15, 30)} } —— "
            "工作量与轨迹长度挂钩（判据 6 的延迟侧会随会话变长劣化）"
        )
        assert len(budgets) == 1, (
            f"各档预算随轨迹长度漂移：{ {r: shapes[r][2] for r in (5, 15, 30)} } —— "
            "预算由概览区额度界定，不该受索引深度影响"
        )
