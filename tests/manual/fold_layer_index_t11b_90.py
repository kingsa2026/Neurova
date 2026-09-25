# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11b）：层节点索引 —— covers 写得进、解得开、跨重启读得回。

链路：真 `ContextOrchestrator.build_context`（生产装配：归档 → 折叠 → 代际推进）
→ 真 `ContextPool.archive_summary`（唯一写入咽喉）→ 真池内 SUMMARY 节点
→ 真 `summaryLayers()`（含台账持久回读）→ 真 `/metrics` 抓取路径
（`observe_context_health()`，T-10d 接的既有观测面）。

判据（五条都要过）：
1. 池内**层节点**带 `covers`（turn 区间 + hash 列表）与层序，档号由读面派生且有序；
2. covers 的每个 hash 都能解析到池内条目 —— 解析失败率 0；
3. 覆盖闭合：折叠侧登记的已覆盖 hash 全集 ⊆ ∪(各档 covers)；
4. 层节点**不参加**概率性相关性召回（索引面与召回面的分工，§12.5 第 3 条）；
5. 索引跨重启读得回（关闭池实例 → 同库新实例 → 档号与 covers 逐条相等）。

跑法：`PYTHONPATH=. python tests/manual/fold_layer_index_t11b_90.py`
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaT11bLive_"))

from prometheus_client import REGISTRY  # noqa: E402

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402


class _TurnIdentityAgent(MagicMock):
    """与 `agent_core.Agent` 同型的替身：身份面转发 `core/turn_context` 的只读属性。"""

    @property
    def current_session_id(self):
        from neurova.core.turn_context import get_turn_session_id

        return get_turn_session_id()


def _agent(agentId: str = "a-live-t11b"):
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


def _round(i: int, chars: int = 900):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


async def _build(orch, *, user_input, history, collab=False, room_id=""):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


async def main() -> None:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False, session_id="sess-t11b-live")
    orch._window_token_budget = 3000
    orch._DELTA_RESUMMARY_MSGS = 0

    calls = {"n": 0}

    async def summarizer(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    orch._window_summarizer = summarizer

    history = [_round(i) for i in range(16)]
    for rnd in range(4):
        history = history + [_round(100 + rnd) for _ in range(3)]
        await _build(orch, user_input=f"第{rnd}轮追问", history=history)

    pool = orch.context_pool
    layers = pool.summaryLayers()
    print(f"[1 层索引] 摘要 LLM 调用 {calls['n']} 次 | 池内层节点 {len(layers)} 档")
    for layer in layers:
        covers = layer["covers"]
        print(
            f"           level={layer['level']} fold_seq={layer['fold_seq']} "
            f"turn={covers['turn_range']} hashes={len(covers['hashes'])} :: {layer['content']}"
        )
    assert layers, "池内没有层节点 —— 索引没落进池（代际栈仍只活在进程内缓存里）"

    # 判据 1：档号有序且从 1 起（最新一代 = 最细分辨率档）
    levels = [layer["level"] for layer in layers]
    assert levels == list(range(1, len(layers) + 1)), f"档号非 1..N：{levels}"
    assert all(layer["covers"]["turn_range"] for layer in layers), (
        f"有层节点缺 turn 区间：{[l['covers'] for l in layers]}"
    )
    assert all(layer["fold_seq"] for layer in layers), "有层节点缺层序"
    assert layers[0]["fold_seq"] > layers[-1]["fold_seq"], "档号 1 未对应最新层序"

    # 判据 2：covers 的 hash 全部解析得到（解析失败率 0）
    for layer in layers:
        hashes = list(layer["covers"]["hashes"])
        resolved = {getattr(e, "hash", None) for e in pool.entriesByHash(hashes)}
        missing = [h for h in hashes if h not in resolved]
        assert not missing, f"第{layer['level']}档 covers 有 {len(missing)} 个 hash 解析不到：{missing[:2]}"

    # 判据 3：覆盖闭合（折叠侧登记的已覆盖全集 ⊆ ∪ 各档 covers）
    health = orch.get_context_health()["fold_index"]
    print(
        f"[3 读数] nodes={health['nodes']} levels={health['levels']} "
        f"unparsable={health['unparsable']} uncovered={health['uncovered']} "
        f"last_error={health['last_error']}"
    )
    assert health["nodes"] == len(layers), f"读数 nodes={health['nodes']} 与索引 {len(layers)} 不符"
    assert health["unparsable"] == 0, f"covers 解析失败率非 0：{health['unparsable']}"
    assert health["uncovered"] == 0, f"覆盖闭合被破坏：{health['uncovered']} 条不在任何档 covers 内"
    assert health["last_error"] is None, f"读数点名了失败原因：{health['last_error']}"

    # 判据 4：层节点不参加概率性召回（对抗输入 = 节点原文本身）
    drawn = {c.content for c in pool.draw(need=layers[0]["content"], budget_tokens=8000)}
    leaked = [layer["content"] for layer in layers if layer["content"] in drawn]
    print(f"[4 召回分工] 以节点原文为 need 召回 {len(drawn)} 条；层节点泄漏 {len(leaked)} 条")
    assert not leaked, f"层节点被相关性召回捞走：{leaked[:2]}"

    # 判据 5：既有观测面可抓取（不新开端点）
    from neurova.core.metrics import get_metrics

    get_metrics().observe_context_health(
        SimpleNamespace(agents={"a-live-t11b": SimpleNamespace(context_orchestrator=orch)})
    )
    samples = [
        s
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == "neurova_context_health_value" and s.labels.get("kind") == "fold_index"
    ]
    assert samples, "fold_index 读数未出现在既有观测面（写了没人读 = 断点）"
    print(f"[5 抓取] fold_index 序列数={len(samples)}；样例={samples[0].labels} {samples[0].value}")

    # 判据 6：跨重启读回
    before = [(layer["level"], layer["fold_seq"], layer["covers"]) for layer in layers]
    pool.close()
    fresh = ContextOrchestrator(
        _agent(), use_pool=True, auto_tag=False, session_id="sess-t11b-live"
    )
    after = [
        (layer["level"], layer["fold_seq"], layer["covers"])
        for layer in fresh.context_pool.summaryLayers()
    ]
    fresh.context_pool.close()
    print(f"[6 跨重启] 重启前 {len(before)} 档 → 重启后 {len(after)} 档")
    assert after == before, (
        f"层索引活不过一次重启：重启前 {len(before)} 档 / 重启后 {len(after)} 档"
    )

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(os.environ["NEUROVA_DATA_DIR"], ignore_errors=True)
