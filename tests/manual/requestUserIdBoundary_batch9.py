# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-11 批 9 / §6-121 (b) 乙案）：真实管线的上下文构建步不再抛 NameError，
且请求通道的属主在回合内不被换掉。

## 为什么这必须活体跑，单测全绿不够

两件事都是**装配级**的，桩件一替就看不见：

1. 批 3 把作用域口径接进 `chat_pipeline` 时，`_scopeCtx` 只在 `_retrieve_memories` 里算了，
   却在 `_step_retrieve_and_build_context` 的 `build_context(...)` 入参里被直接用——
   真实回合每次走到那里必抛 `NameError`。单元测试里这一步被各种替身替掉，红的是别的格子，
   于是这条链在 28 个在档格子上红了半天，而生产侧"每次对话都构建失败"没人读出来。
2. 请求通道（`neurova_request_user_id`）的属主由谁写、什么时候被覆盖——
   只有把**真管线**放进同一 task 上下文里跑一遍才算证实（`asyncio.run` 会把上下文复制进
   task，从外面读必然读不到，第一次探针就这么误判成"未被覆盖"）。

## 判据

1. `_step_retrieve_and_build_context` 全程不抛，编排器真收到 5 个 `chat_*` 作用域入参；
2. 那 5 个入参与 `turnScopeContext(metadata, session_id)` 的读数**逐字相等**（同源单点）；
3. 群聊 metadata 下，编排器收到的确实是群作用域（不是 direct）；
4. 请求通道先按"会话属主"写入，跑完真管线这一步之后**仍是属主**（乙案的核心：管线不再改写）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/requestUserIdBoundary_batch9.py`
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaIdentityBoundary9")

from neurova.agent.chat_pipeline import ChatContext, ChatPipeline  # noqa: E402
from neurova.collaboration.memory_scope import turnScopeContext  # noqa: E402
from neurova.core.identity_context import (  # noqa: E402
    get_request_user_id, set_request_user_id)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _StubAgent:
    """只造管线这一步真会读到的那几格；其余属性缺失就应当炸（不许静默兜过）。"""

    def __init__(self):
        self.config = SimpleNamespace(agent_id="kai", llm_model="test", owner_user_id="owner-77")
        self.id = "kai"
        self.trace_manager = None
        self.context_orchestrator = None
        self.crystallizer = None
        self.tool_synthesizer = None
        self.skill_manager = None
        self.memory_manager = None
        self.session_manager = None
        self.unified_retriever = None
        self.tool_memory = None
        self.loop = None
        self.soul = ""
        self.personality = ""
        self.conversation_history = []
        self.current_session_id = None
        self.llm_client = None
        self.memory_retrieval_chain = _Chain()


class _ChainResult:
    source = "stub"
    quality_level = SimpleNamespace(value="high")
    memories = [{"memory_id": "m1", "content": "旧内容", "score": 0.9}]


class _Chain:
    async def retrieve(self, ctx):
        return _ChainResult()


class _OrchestratorSpy:
    def __init__(self):
        self.kwargs: dict = {}

    async def build_context(self, **kwargs):
        self.kwargs = kwargs
        return [{"role": "system", "content": "装配出的上下文"}]


def _ctx(metadata: dict) -> ChatContext:
    return ChatContext(user_input="继续", session_id="sess-1", metadata=metadata,
                       save_memory=False)


async def _runOneStep(metadata: dict):
    agent = _StubAgent()
    spy = _OrchestratorSpy()
    # `ChatPipeline.context_orchestrator` 是无 setter 的转发 property（`:367`），
    # 所以替身必须挂在 agent 那一侧——挂在 pipeline 上会 AttributeError（第一次跑就撞上）。
    agent.context_orchestrator = spy
    pipeline = ChatPipeline(agent)
    # 本脚本只审"作用域口径怎么进编排器"这一格，其余检索步骤由替身承担（不审它们）
    pipeline._retrieve_crystallized_patterns = lambda ctx: asyncio.sleep(0)
    pipeline._retrieve_ekb_experience = lambda ctx: None
    ctx = _ctx(metadata)
    await pipeline._step_retrieve_and_build_context(ctx)
    return spy.kwargs, ctx


async def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    # ── [1][2] 单聊：不抛 + 与 turnScopeContext 同源 ─────────────────
    meta_direct = {"user_id": "u1", "role": "user"}
    kwargs, _ = await _runOneStep(meta_direct)
    expected = turnScopeContext(meta_direct, "sess-1")
    sent = {k: kwargs.get(k) for k in
            ("chat_collab", "chat_room_id", "chat_channel_group", "chat_channel", "chat_group_id")}
    check("[1] 真管线这一步不抛（批 3 的 NameError 已消）",
          bool(kwargs) and "chat_collab" in kwargs, str(list(kwargs)[:3]))
    check("[2] 进编排器的作用域读数 == turnScopeContext 的读数（同源单点）",
          sent["chat_collab"] == expected["collab"]
          and sent["chat_room_id"] == expected["room_id"]
          and sent["chat_channel_group"] == expected["channel_group"]
          and sent["chat_channel"] == expected["channel"]
          and sent["chat_group_id"] == expected["chat_id"],
          f"入参 {sent} vs 单点 {expected}")

    # ── [3] 群聊：编排器收到的必须是群作用域 ────────────────────────
    # 键名按 `turnScopeContext` 的**实际**判据写（`source_channel` + `chat_type` + `chat_id`，
    # 三者由 channel_router 备齐）——第一版这里自造了 "channel" 键，等于审了一条不存在的链。
    meta_group = {"user_id": "ch:feishu:ou_9", "role": "user",
                  "source_channel": "feishu", "chat_type": "group", "chat_id": "oc_group_1"}
    kwargsG, _ = await _runOneStep(meta_group)
    check("[3] 群轮进编排器的是 chgrp 作用域（不是 direct）",
          kwargsG.get("chat_channel_group") is True
          and kwargsG.get("chat_group_id") == "oc_group_1"
          and kwargsG.get("chat_collab") is False,
          str({k: kwargsG.get(k) for k in
               ("chat_collab", "chat_channel_group", "chat_group_id")}))

    # ── [4] 请求通道的属主在这一步之后仍是属主（乙案核心）──────────
    set_request_user_id("owner-77")
    before = get_request_user_id()
    await _runOneStep(meta_group)
    after = get_request_user_id()
    check("[4] 真管线不再改写请求通道：属主保持（渠道会话仍落属主名下）",
          before == after == "owner-77", f"before={before} after={after}")

    print()
    if failures:
        print("LIVE-VERIFY FAILED / 批 9 身份边界与作用域单点：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / 工单 2026-10-11 批 9（§6-121 (b) 乙案 + 批 3 NameError 根修）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
