# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11d）：确定性下钻 —— 引用可解析、原文取回、跨重启仍成立。

链路（全部为生产对象，无手工调 `record()` / 无手工喂 hash）：
真 `ContextOrchestrator.build_context`（归档 → 折叠 → 代际推进 → 池索引）
→ 真视图摘要行（模型真读得到的那一行）→ 真 `ToolExecutor._execute_recall_context_span`
（工具面，含 schema/分派/白名单全链）→ 真 `ContextPool.drilldown`
→ 常驻 + 真 SQLite 台账双源直取 → 作用域闸门。

判据（六条都要过）：
1. 摘要行带可解析 `covers_ref`，且引用指向**真实存在**的档位（无悬空引用）；
2. 按引用取回的原文与 covers 逐条 hash 相等（工单 §12.7 判据 5 的 100% 对齐）；
3. 覆盖闭合：折叠侧登记的已覆盖 hash 全集 ⊆ ∪(各档 covers)（不静默漏）；
4. 取不回时如实点名原因，不伪装空成功；
5. 跨重启下钻一致（新进程/新池实例取回同一批原文 —— 直取面落在持久层）；
6. 作用域闸门同源：单聊轮按群聊档位下钻不得吐出房间原文，且过滤条数可见。

跑法：`PYTHONPATH=. python tests/manual/fold_span_drilldown_t11d_90.py`
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaT11dLive_"))

from neurova.context.fold_index import parseCoversRef  # noqa: E402
from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402
from neurova.tool_executor import ToolExecutor  # noqa: E402


def _agent(agentId: str, sessionId: str):
    from unittest.mock import MagicMock

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
    agent.current_session_id = sessionId
    return agent


def _orch(agentId: str, sessionId: str = "sess-t11d-live", budget: int = 1200):
    orch = ContextOrchestrator(
        _agent(agentId, sessionId), use_pool=True, auto_tag=False, session_id=sessionId
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0
    calls = {"n": 0}

    async def _summarize(dropped, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped)} 条"

    orch._window_summarizer = _summarize
    return orch


def _round(i: int):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * 200}


async def _build(orch, history, collab=False, room_id=""):
    from unittest.mock import AsyncMock, patch

    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续",
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


def _summaryLine(view):
    for msg in view or []:
        if msg.get("role") == "system" and "早期对话摘要" in str(msg.get("content", "")):
            return str(msg["content"])
    return ""


def _executor(orch):
    """真 ToolExecutor 实例（`__new__` 直构：只需 `_agent`，与既有工具面用例同形）。"""
    agent = orch._agent
    agent.context_orchestrator = orch
    ex = ToolExecutor.__new__(ToolExecutor)
    ex._agent = agent
    return ex


async def _foldTwice(orch, collab=False, room_id=""):
    history = [_round(i) for i in range(14)]
    view = await _build(orch, history, collab=collab, room_id=room_id)
    history = history + [_round(i) for i in range(14, 30)]
    view = await _build(orch, history, collab=collab, room_id=room_id)
    return view


async def main():
    orch = _orch("a-live-t11d")
    view = await _foldTwice(orch)
    line = _summaryLine(view)
    assert line, "视图里没有摘要行 —— 本链路没打到折叠路径"
    ref = parseCoversRef(line)
    assert ref is not None, f"摘要行不带 covers_ref（模型无确定性寻址手段）：{line[-100:]!r}"
    print(f"[1 引用] 摘要行尾部={line.strip().splitlines()[-1]!r} 解析={ref}")

    pool = orch.context_pool
    layers = pool.summaryLayers()
    assert any(l["fold_seq"] == ref[0] for l in layers), (
        f"引用 {ref[0]} 指向不存在的档位：{[l['fold_seq'] for l in layers]}"
    )
    print(f"[1 索引] 档位={[ (l['level'], l['fold_seq'], len(l['covers']['hashes'])) for l in layers ]}")

    # 判据 2：走**真工具面**下钻
    ex = _executor(orch)
    out = await ex._execute_recall_context_span({"covers_ref": line, "limit": 100})
    assert out.get("success"), f"工具面下钻失败：{out}"
    wanted = set(next(l for l in layers if l["fold_seq"] == ref[0])["covers"]["hashes"])
    got = {entry["hash"] for entry in out["originals"]}
    assert wanted == got, f"对齐率不足：缺 {sorted(wanted - got)[:2]} 多 {sorted(got - wanted)[:2]}"
    print(f"[2 下钻] 工具面取回 {out['count']} 条，covers {len(wanted)} 条，对齐率 100%")
    print(f"           样例 turn_id={out['originals'][0]['turn_id']} 内容前 20 字={out['originals'][0]['content'][:20]!r}")

    # 判据 3：覆盖闭合
    health = orch.get_context_health()["fold_index"]
    assert health["uncovered"] == 0, f"覆盖闭合被破坏：{health}"
    assert health["unparsable"] == 0, f"covers 解析失败率非 0：{health}"
    print(f"[3 读数] {health}")

    # 判据 4：取不回如实点名
    bogus = await ex._execute_recall_context_span({"covers_ref": "covers_ref=fold:99@sess-t11d-live"})
    assert bogus.get("error") and bogus.get("reason"), f"假引用没被如实拒绝：{bogus}"
    malformed = await ex._execute_recall_context_span({"covers_ref": "没有任何引用的普通文本"})
    assert malformed.get("error"), f"解析失败没被如实拒绝：{malformed}"
    print(f"[4 诚实] 假档位 reason={bogus['reason']}；无引用 error={malformed['error'][:24]}…")

    # 判据 5：跨重启
    before = {e["hash"] for e in out["originals"]}
    pool.close()
    fresh = _orch("a-live-t11d")
    after = await _executor(fresh)._execute_recall_context_span({"covers_ref": line, "limit": 100})
    assert after.get("success"), f"重启后下钻失败：{after}"
    assert {e["hash"] for e in after["originals"]} == before, (
        "重启后取回的原文与重启前不一致 —— 直取面没落在持久层"
    )
    print(f"[5 跨重启] 重启前 {len(before)} 条 → 重启后 {len(after['originals'])} 条，逐条 hash 相等")
    fresh.context_pool.close()

    # 判据 6：作用域闸门
    roomOrch = _orch("a-live-t11d-room")
    roomView = await _foldTwice(roomOrch, collab=True, room_id="project_roomLive")
    roomLine = _summaryLine(roomView)
    roomPool = roomOrch.context_pool
    roomOk = roomPool.drilldown(roomLine)
    assert roomOk["entries"], f"本群轮取不到本群档位原文：{roomOk}"
    roomPool.turn_scope = None
    direct = roomPool.drilldown(roomLine)
    assert not direct["entries"] and direct["filtered"], (
        f"单聊轮按群聊档位取到了房间原文（隔离被破）：{direct}"
    )
    print(f"[6 隔离] 本群轮取回 {len(roomOk['entries'])} 条；单聊轮取回 0 条、过滤 {direct['filtered']} 条")
    roomPool.close()

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        shutil.rmtree(os.environ["NEUROVA_DATA_DIR"], ignore_errors=True)
