# -*- coding: utf-8 -*-
"""SC-5（SELFCOMPACT 对照批）：`context_compress` 回执附**结构化召回指引**。

## 根因（对照文档 §8.3，元认知支架的第二半）

模型自决折叠（`context_compress`）的回执只带计数（folded/tokens），不带
"压掉的去哪了、怎么找回"。折叠产物（SUMMARY 层节点）本来就有可解析的
`covers_ref`（T-11d 确定性下钻的地址，`fold_index.renderCoversRef` 单点派生），
但回执不带——模型刚折完就只能凭空猜寻址，正是对照批点名的缺陷。

## 本票契约

1. 折叠成功的回执带 `recall_guide`：`covers_ref` + 被折区间寻址字段
   （turn_range / hash 样本，以现场折叠产物实际携带的为准）+ 三条找回路径
   （recall_history 直取 / pool_search 语义 / recall_context_span 下钻）；
2. 指引**可执行验证**：回执里的 `covers_ref` 必须能被 `recall_context_span`
   实际取回被折区间原文（往返闭环），不许给不可解析的提示文案；
3. 长度纪律：hash 样本数具名常量封顶（有界），不把大段内容塞回执；
4. 手动 /compact 与 context_compress 共用同一折叠机构：指引只在工具回执层加，
   compact 本身行为与严格变小守卫口径不变。
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.tool_executor import ToolExecutor


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _agent():
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
    agent.user_id = "u-sc5"
    agent.agent_id = "a-sc5"
    return agent


def _orchestrator(agent) -> ContextOrchestrator:
    # 显式会话身份（测试替身没有每轮单源；与 T-11d/T-11a 测试同纪律），
    # 保证折叠槽键 = 池归属 = covers_ref 里的会话，三处同源。
    orch = ContextOrchestrator(
        agent, use_pool=True, auto_tag=False, session_id="sess-sc5"
    )
    orch._window_token_budget = 1200
    return orch


def _longMsg(i: int) -> dict:
    return {"role": "user", "content": f"第{i}轮的长讨论：项目背景细节{i}。" + "测" * 600}


def _install_summarizer(orch: ContextOrchestrator) -> None:
    async def fake_summarize(dropped_msgs, previous_summary=""):
        return f"摘要：早期 {len(dropped_msgs)} 条的要点。"

    orch._window_summarizer = fake_summarize


async def _compress(agent, orch, history):
    """生产同构前置：先按 build_context 的同一写入咽喉归档原文，再走工具折叠。"""
    _install_summarizer(orch)
    orch._archive_conversation_to_pool(history)
    agent.context_orchestrator = orch
    agent.conversation_history = list(history)
    executor = ToolExecutor(agent)
    receipt = await executor.execute_tool("context_compress", {"reason": "阶段完成"})
    return executor, receipt


class TestCompressRecallGuide:
    @pytest.mark.asyncio
    async def test_compress_receipt_carries_drillable_recall_guide(self):
        """回执含 covers_ref，且 recall_context_span 据此取回被折区间原文（往返闭环）。"""
        agent = _agent()
        orch = _orchestrator(agent)
        history = [_longMsg(i) for i in range(30)]
        executor, receipt = await _compress(agent, orch, history)

        assert receipt.get("compacted") is True, f"应真折叠：{receipt}"
        # 严格变小守卫口径不因本卡放松：折叠后 token 必须严格变小。
        assert receipt.get("tokens_after", 0) < receipt.get("tokens_before", 0), receipt

        guide = receipt.get("recall_guide")
        assert guide, f"回执缺结构化召回指引（SC-5）：{list(receipt)}"
        ref = str(guide.get("covers_ref") or "")
        assert ref.startswith("covers_ref=fold:"), f"covers_ref 不可解析：{ref!r}"
        assert guide.get("covered_count", 0) > 0, guide
        assert guide.get("turn_range"), guide

        # 三条找回路径点名到真实注册的工具名。
        paths = " ".join(str(p) for p in guide.get("paths") or [])
        for tool in ("recall_history", "pool_search", "recall_context_span"):
            assert tool in paths, f"找回路径缺 {tool}：{paths}"

        # 往返闭环：指引里的引用必须能被 recall_context_span 实际取回被折原文。
        span = await executor.execute_tool("recall_context_span", {"covers_ref": ref})
        assert span.get("success") is True, f"按回执指引下钻失败：{span}"
        originals = span.get("originals") or []
        assert originals, f"下钻取回为空：{span}"
        got = {str(o.get("content") or "") for o in originals}
        all_contents = {str(m.get("content") or "") for m in history}
        assert got <= all_contents, "下钻取回了不属于本会话的内容"
        early = {str(history[0].get("content")), str(history[1].get("content"))}
        assert got & early, "下钻未取回被折的早期原文（指引不可执行）"

    @pytest.mark.asyncio
    async def test_recall_guide_hash_samples_are_bounded(self):
        """长度纪律：hash 样本数具名常量封顶，不随折叠规模膨胀。"""
        from neurova.context.orchestrator import FOLDED_REF_HASH_SAMPLES

        agent = _agent()
        orch = _orchestrator(agent)
        history = [_longMsg(i) for i in range(40)]
        executor, receipt = await _compress(agent, orch, history)

        guide = receipt.get("recall_guide") or {}
        assert guide, f"回执缺召回指引：{list(receipt)}"
        assert len(guide.get("hash_samples") or []) <= FOLDED_REF_HASH_SAMPLES
        assert guide.get("covered_count", 0) >= len(guide.get("hash_samples") or [])

    @pytest.mark.asyncio
    async def test_no_recall_guide_when_nothing_folded(self):
        """没折 anything 就不造指引——编一个引用出来就是伪造寻址能力。"""
        agent = _agent()
        orch = _orchestrator(agent)
        _install_summarizer(orch)
        agent.context_orchestrator = orch
        agent.conversation_history = [
            {"role": "user", "content": "短消息一"},
            {"role": "assistant", "content": "短回复一"},
        ]
        executor = ToolExecutor(agent)
        receipt = await executor.execute_tool("context_compress", {"reason": "试试"})

        assert receipt.get("compacted") is False, receipt
        assert "recall_guide" not in receipt, receipt
