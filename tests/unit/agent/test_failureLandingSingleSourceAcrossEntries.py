# -*- coding: utf-8 -*-
"""失败落点的单源性：四入口共用管线这一层，谁都不许绕过去各写一份。

扫荡由来（教义第 5 条：同一根因的攻击面要在所有命中点闭环）。§6-422 把失败落点
修在 `ChatPipeline.execute` 的异常路径上，选这一层的理由是它是**共用层**——本档
实测复核这条理由是否真的成立：

- `Agent.chat` 组装 `ChatContext` 后 `return await self.chat_pipeline.execute(ctx)`
  （`agent_core.py:1757`）；全仓 `chat_pipeline.execute(` 的生产调用点**只有这一处**。
- `Agent.chat_stream` 不另起管线：它委托 `self.chat(...)`（docstring 自陈"委托 self.chat()
  走完整管线（记忆/上下文/后处理不缺失）……chat() 异常透传不吞"），于是移动配对
  （`mobile_pairing.py:641` 用 `chat_stream`）与 HTTP 流式、网页 console 是同一条落点。
- 入口面逐个核：HTTP `/v1/chat`(`api/endpoints/chat.py:336`)、`/v1/chat/stream`(:519)、
  console SSE(`console.py:1035`)、console 推送位(:2381)、`agent.py:824`、
  渠道路由(`channels/channel_router.py:281`)、蜂群派生(`agent/swarm.py:695`)
  ——都经 `Agent.chat`/`chat_stream`，没有一个自持管线。

因此本批**不加第二处落点代码**（那正是 §6 禁止的平行体系），只把这个"单一收口"钉成
判据：将来谁新开旁路（自调 `_execute_steps`、或在端点里补一段"失败也写一条"），
这里当场红。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from .conftest import text_chunk
from neurova.session_repository import get_session_repository

SESSION = "sess-fail-landing-single-source"
USER_TEXT = "把这份清单逐条核对一遍再回我"
ERROR_TEXT = "Error code: 400 - Requested model not supported"


def _executeCallSites(root: str = "neurova") -> list:
    """生产代码里 `self.chat_pipeline.execute(...)` 的调用点。

    两条纪律合成一件事：
    - 按行匹配会被 docstring 里的路标句命中（本档初版就把 `objective_evidence.py`
      的 Args 段误当成第二个调用点）⇒ 走 AST；
    - 自写 `rglob + ast.parse` 会把判据与代码总量、机器速度捆绑（在册闸
      `test_no_unledgered_repo_wide_ast_scan` 当场拦下）⇒ 用共享入口
      `tests.ast_scan.callNodes` 带文本预筛，解析量从"代码总量"降到"命中面"。
    """
    from pathlib import Path

    from tests.ast_scan import callNodes

    hits = []
    for path, node in callNodes(Path(root), "execute", hints=("chat_pipeline.execute",)):
        inner = getattr(node.func, "value", None)
        if isinstance(inner, ast.Attribute) and inner.attr == "chat_pipeline":
            hits.append(f"{path}:{node.lineno}")
    return hits


def test_pipelineExecuteHasExactlyOneProductionCallSite():
    """回合只能有一个生产入口：`Agent.chat` 里那一处 `chat_pipeline.execute(`。

    多一处就意味着有一条绕过失败落点（以及绕过提前落 user、后处理）的旁路。
    """
    sites = _executeCallSites()
    assert len(sites) == 1, (
        f"`chat_pipeline.execute(` 的生产调用点应恰 1 处（在 `Agent.chat`），实得 {sites}——"
        "新增旁路会绕过失败落点与提前落盘，四入口共用同一层的理由就不成立了"
    )
    assert "agent_core.py" in sites[0], f"唯一收口不该换地方：{sites[0]}"


def testChatStreamDelegatesToChatInsteadOfOpeningASecondPipeline():
    """`Agent.chat_stream` 必须是委托，不是第二条管线（移动配对用的就是它）。

    本仓有**两个** `chat_stream`：`AgentLLMClient.chat_stream` 是 LLM 传输壳，
    与回合无关；判据只认 `class Agent` 里那一个（初版用 `next(...)` 抓到了前者，
    假红一场——选取范围本身也得精确）。
    """
    src = pathlib.Path("neurova/agent_core.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    agentCls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Agent"),
        None,
    )
    assert agentCls is not None, "`class Agent` 不在了"
    fn = next(
        (n for n in agentCls.body
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "chat_stream"),
        None,
    )
    assert fn is not None, "`Agent.chat_stream` 不在了——它去哪儿了？绕过落点的旁路？"
    delegates, opensOwn = False, False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        base = node.func.value
        if isinstance(base, ast.Name) and base.id == "self":
            if node.func.attr == "chat":
                delegates = True
            if node.func.attr in {"execute", "chat_stream"}:
                opensOwn = True
        if isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "chat_pipeline":
            opensOwn = True
    assert delegates and not opensOwn, (
        f"`Agent.chat_stream` 不再单纯委托 `self.chat()`（委托={delegates}、自起={opensOwn}）"
        "——它会绕开 `execute` 的失败落点，移动配对入口的失败轮就此又看不见终态"
    )


def _landingImpl() -> ast.AsyncFunctionDef:
    """落点实装的 AST 节点：整块已按 perf gate 的口径抽到独立模块。

    `chat_pipeline.py` 是每轮对话必经的热文件、尺寸受 `scripts/ci/perf_gate.py` 的
    `hot-path-file-size` 约束，门禁自己写的处置就是"新逻辑抽到独立模块后再接线"。
    抽走后热文件里只留同名薄委托，实现搬到 `neurova/agent/failed_turn_landing.py`；
    判据跟着实装走，否则这道常驻闸就再也看不见落点内部到底调了谁。
    """
    src = pathlib.Path("neurova/agent/failed_turn_landing.py").read_text(encoding="utf-8")
    node = next(
        (n for n in ast.walk(ast.parse(src))
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "landFailedTurn"),
        None,
    )
    assert node is not None, (
        "失败落点实装不在了（`agent/failed_turn_landing.py::landFailedTurn`）"
    )
    return node


def testFailedTurnLandingDoesNotOpenASecondSessionWriter():
    """落点必须复用既有单点，不许在失败路径上另写一份会话落盘代码。"""
    fn = _landingImpl()
    called = [
        getattr(n.func, "attr", "") or getattr(n.func, "id", "")
        for n in ast.walk(fn) if isinstance(n, ast.Call)
    ]
    assert "_step_save_session" in called, (
        f"落点没走单点 `_step_save_session`（实得 {sorted(set(called))}）"
    )
    banned = {"save_to_session", "save_message", "add_message", "saveUserMessage",
              "_write_session_file_unlocked", "_sessionWriteFrame"}
    assert not (banned & set(called)), (
        f"失败路径上出现了第二份写会话的调用 {sorted(banned & set(called))}——"
        "围栏、属主口径、去重分叉都只在单点里，抄一份必漂"
    )


@pytest.mark.asyncio
async def testChatStreamFailureStillLandsAssistant(loop_probe):
    agent = loop_probe.agent
    model = loop_probe.bind([[text_chunk("不会被用到的回复")]])

    async def failingChat(messages, **kwargs):
        raise RuntimeError(ERROR_TEXT)

    model.chat = failingChat

    chunks: list = []
    with pytest.raises(RuntimeError):
        async for piece in agent.chat_stream(USER_TEXT, session_id=SESSION):
            chunks.append(piece)

    history = get_session_repository().get_history(agent_id=agent.config.agent_id,
                                                   session_id=SESSION) or []
    assistants = [str(m.get("content") or "") for m in history if m.get("role") == "assistant"]
    assert any("未能生成回复" in t for t in assistants), (
        f"`chat_stream` 这一支失败后没有落点（实得 {assistants}）——"
        "移动配对入口的会话将和网页一样，只剩用户那句"
    )


@pytest.mark.asyncio
async def testSaveMemoryFalseTurnIntentionallyLandsNothing(loop_probe):
    """反向控制：`save_memory=False` 的轮不写会话——这条边界是设计，不是漏。

    蜂群子 Agent 等内部派生轮就以它为准；若哪天落点无视这个开关，内部轮会往
    无人读的会话里堆垃圾记录。
    """
    agent = loop_probe.agent
    model = loop_probe.bind([[text_chunk("不会被用到的回复")]])

    async def failingChat(messages, **kwargs):
        raise RuntimeError(ERROR_TEXT)

    model.chat = failingChat

    with pytest.raises(RuntimeError):
        await agent.chat(USER_TEXT, session_id=SESSION, save_memory=False)

    history = get_session_repository().get_history(agent_id=agent.config.agent_id,
                                                   session_id=SESSION) or []
    assert history == [], f"save_memory=False 仍落了盘（{history}）——边界被破"
