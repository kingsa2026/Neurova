# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11e）：rollup 后台化 —— 关键路径每轮 ≤1 次摘要调用。

链路：真 `ContextOrchestrator.build_context`（生产装配：归档 → 折叠 → 摘要）
→ 真 `compact_window`（成本上界入参）→ 真 `ContextRollupWorker`（后台补做）
→ 真池 `archive_summary`（唯一写入咽喉）→ 真 `get_context_health()["fold_rollup"]`
→ 真 `/metrics` 抓取路径（`observe_context_health`）。

判据（四条都要过）：
1. 摘要器**恒失败**时，单轮 `build_context` 的摘要 LLM 调用 ≤ 1（改前实测 4）；
2. 失败批次由 worker 后台补做；补做**成功**才写层节点、才推进覆盖账；
3. 补做抛异常被 worker 记账（点名 `RuntimeError`），不逃逸成未处理异常
   （工单 §12.5 第 4 条把"发后不管"列为假实现）；
4. 回退开关 `NEUROVA_CONTEXT_ROLLUP=0`：不装配 worker，读数全 0，视图保留静态桩。

跑法：`PYTHONPATH=. python tests/manual/fold_rollup_t11e_90.py`
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaT11eLive_"))

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402


def _agent(agentId: str = "a-live-t11e"):
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
    agent.agent_id = agentId
    return agent


def _round(i: int, chars: int = 900):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _orchestrator(agentId: str, sessionId: str):
    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id=sessionId
    )
    orch._window_token_budget = 2000
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


async def _build(orch, history):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续", session_context=history, relevant_memories=[]
        )


def _layerNodes(orch):
    from neurova.context.pool_models import ContextSource

    return [
        c
        for c in orch.context_pool.get_contexts()
        if c.source == ContextSource.SUMMARY and (c.metadata or {}).get("covers")
    ]


async def main() -> None:
    history = [_round(i) for i in range(30)]

    # ── 判据 1+2：恒失败形状的成本上界与后台补做 ──────────────────────────
    state = {"fail": True, "calls": 0}
    orch = _orchestrator("a-live-t11e", "sess-t11e-live")

    async def flaky(dropped, previous_summary=""):
        state["calls"] += 1
        if state["fail"]:
            return None
        return f"补做摘要：覆盖 {len(dropped)} 条"

    orch._window_summarizer = flaky
    before = state["calls"]
    await _build(orch, history)
    inTurn = state["calls"] - before
    print(f"[1 成本上界] 摘要器恒失败：单轮 build_context 的 LLM 调用 = {inTurn}（判据 ≤1）")
    assert inTurn <= 1, f"关键路径把重试/递进也算进去了：{inTurn} 次"

    worker = orch.foldRollupWorker()
    assert worker is not None, "rollup worker 未装配（断点）"
    readout = orch.get_context_health()["fold_rollup"]
    print(f"[1 派发] 读数={readout}")
    assert readout["dispatched"] >= 1, f"失败批次没有交给后台：{readout}"
    await worker.drain()
    afterFail = orch.get_context_health()["fold_rollup"]
    print(f"[2 补做失败] failed={afterFail['failed']} last_error={afterFail['last_error']!r}")
    assert afterFail["failed"] >= 1 and afterFail["last_error"], "补做失败未被记账（发后不管）"
    assert not _layerNodes(orch), "补做失败却写了层节点：索引指向不存在的摘要"

    # ── 判据 2：补做成功才推进（另开一个会话，避免与上面的失败账混淆）──
    state2 = {"fail": True, "calls": 0}
    orch2 = _orchestrator("a-live-t11e-ok", "sess-t11e-ok")

    async def flakyThenOk(dropped, previous_summary=""):
        state2["calls"] += 1
        if state2["fail"]:
            return None
        return f"补做摘要：覆盖 {len(dropped)} 条"

    orch2._window_summarizer = flakyThenOk
    await _build(orch2, history)
    worker2 = orch2.foldRollupWorker()
    state2["fail"] = False
    await worker2.drain()
    nodes = _layerNodes(orch2)
    print(f"[2 补做成功] 层节点 {len(nodes)} 档 | 读数={orch2.get_context_health()['fold_rollup']}")
    assert nodes, "后台补做成功却没有写层节点：补做路径是空转"

    # ── 判据 3：补做抛异常被 worker 记账（不是发后不管）──────────────────
    state3 = {"boom": True}
    orch3 = _orchestrator("a-live-t11e-boom", "sess-t11e-boom")

    async def exploding(dropped, previous_summary=""):
        if state3["boom"]:
            raise RuntimeError("LLM 网关 502")
        return "补做摘要"

    orch3._window_summarizer = exploding
    await _build(orch3, history)
    await orch3.foldRollupWorker().drain()
    boom = orch3.get_context_health()["fold_rollup"]
    print(f"[3 异常记账] failed={boom['failed']} last_error={boom['last_error']!r}")
    assert boom["last_error"] and "RuntimeError" in str(boom["last_error"]), (
        f"补做异常没人 await（发后不管）：{boom}"
    )

    # ── 判据 4：/metrics 抓取面（既有观测面，不新开端点）────────────────
    from types import SimpleNamespace

    from neurova.core.metrics import generate_metrics_text, get_metrics

    # AppState 在本判据上只被读一个字段（`agents` 字典）；fastapi 缺失时起不了真 app，
    # 用同形容器顶替该字段（与 T-10d 的 live-verify 同款，不伪造读面行为）。
    state = SimpleNamespace(agents={"a-live-t11e-ok": SimpleNamespace(context_orchestrator=orch2)})
    get_metrics().observe_context_health(state)
    text = generate_metrics_text()
    line = next(
        (
            l
            for l in text.splitlines()
            if l.startswith("neurova_context_health_value{") and "fold_rollup" in l
        ),
        None,
    )
    print(f"[4 抓取] {line.strip() if line else '（无）'}")
    assert line is not None, "rollup 读数没有出现在 /metrics 文本里（仍无生产读者）"

    # ── 判据 5：回退开关等式（§12.6）────────────────────────────────────
    os.environ["NEUROVA_CONTEXT_ROLLUP"] = "0"
    try:
        orchOff = _orchestrator("a-live-t11e-off", "sess-t11e-off")
        calls = {"n": 0}

        async def alwaysFail(dropped, previous_summary=""):
            calls["n"] += 1
            return None

        orchOff._window_summarizer = alwaysFail
        view = await _build(orchOff, history)
        offReadout = orchOff.get_context_health()["fold_rollup"]
        stubs = [m for m in view if "早期对话摘要" in str(m.get("content", ""))]
        print(
            f"[5 回退开关] worker={'None' if orchOff.foldRollupWorker() is None else '装配了'} "
            f"读数={offReadout} | 静态桩 {len(stubs)} 行"
        )
        assert orchOff.foldRollupWorker() is None, "开关关闭却仍装配 worker"
        assert offReadout["dispatched"] == 0 and offReadout["in_flight"] == 0, offReadout
        assert stubs, "开关关闭后失败形状丢了静态折叠桩（回退等式不成立）"
    finally:
        os.environ.pop("NEUROVA_CONTEXT_ROLLUP", None)

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    asyncio.run(main())
