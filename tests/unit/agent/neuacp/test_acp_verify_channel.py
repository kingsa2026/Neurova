# -*- coding: utf-8 -*-
"""P1-2 红绿灯：外部成员验收/评审判定通道（NeuacpVerifyChannel）。

红线（计划 §1.4，拍板 D-B=独立 ACP 判定会话）：swarm.py:1984 的构造形态
（不传 verify_channel）下，``adapter.llm_client`` 必须自带可用判定通道
（``async chat``）——现状 ``acp_member.py`` 把形参原样赋给 ``self.llm_client``，
缺省恒为 ``None``，于是 swarm.py:2430 ``getattr(agent, "llm_client", None)``
取不到通道，外部成员交付物恒走 judge_unavailable 诚实降级
（acceptance_gate.py:118-135），验收/评审门对外部成员形同虚设。

绿灯判据：
- 判定通道满足 goal_verifier/review 的注入协议（``chat(messages) ->
  {"content": str}``，经 callSubSessionChannel 单源调用）；
- 判定「未达标」→ runAcceptanceLoop 带 missing 回炉一次 → 再不达标
  failed(cause=acceptance_failed)（swarm 侧据此置 run failed）；
- 判定「达标」→ failedReason=None（swarm 侧据此置 completed）且
  acceptance.achieved is True；
- 判定会话收到 session/request_permission → 恒 fail-closed deny，且已收集
  判定文本不受影响；帧照走 F2（permission 请求/应答帧落 frame_log）；
- 通道不吞异常：执行体故障原样上抛（goal_verifier 判 parse_ok=False 走
  诚实降级，不由通道兜底）。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from neurova.agent.acceptance_gate import runAcceptanceLoop
from neurova.agent.neuacp.acp_client import NeuacpError
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.executor import NeuacpExecResult
from neurova.agent.neuacp.frame_log import readFrames
from neurova.agent.neuacp.scripted_executor import NeuacpScriptedExecutor

VERDICT_FAIL = json.dumps(
    {
        "achieved": False,
        "confidence": 0.2,
        "missing": ["缺少密码输入框", "提交后无校验反馈"],
        "explanation": "证据未覆盖全部成功条目",
    },
    ensure_ascii=False,
)

VERDICT_PASS = json.dumps(
    {
        "achieved": True,
        "confidence": 0.9,
        "missing": [],
        "explanation": "全部成功条目均有证据支持",
    },
    ensure_ascii=False,
)

VERIFY_MESSAGES = [
    {"role": "system", "content": "你是目标验收判定员。只输出 JSON。"},
    {"role": "user", "content": "<goal>写一个登录页</goal>\n<evidence>首轮产出</evidence>"},
]


def makeAdapter(script):
    """以 swarm.py:1984 的构造形态建 adapter（不传 verify_channel）。"""
    executor = NeuacpScriptedExecutor(script=script, cwd=".")
    return NeuacpMemberAdapter(executor, name="外部编码代理", cwd=".")


def makeRun():
    """最小 SubAgentRun 鸭子面：带验收条件（gateActiveFor 据此开门）。"""
    return SimpleNamespace(
        subagent_id="sw_verify",
        trace_id="tr-verify",
        agent_name="外部编码代理",
        task="写一个登录页",
        task_unit={
            "goal": "写一个登录页",
            "acceptanceCriteria": ["包含邮箱与密码输入框", "提交后给出校验反馈"],
            "reviewMode": "none",
        },
        acceptance=None,
    )


# ── 红灯：缺省构造必须自带判定通道 ────────────────────────────────────────


def test_adapterSelfBuildsVerifyChannelWhenNotInjected():
    """swarm 构造形态（不传 verify_channel）→ llm_client 非 None 且 chat 可达。

    现状：self.llm_client = verify_channel 恒 None → 外部成员恒 judge_unavailable。
    """
    adapter = makeAdapter([])
    assert adapter.llm_client is not None, "外部成员缺省必须自带判定通道（P1-2 / D-B）"
    chat = getattr(adapter.llm_client, "chat", None)
    assert callable(chat), "判定通道必须暴露 async chat（goal_verifier 消费协议）"


def test_defaultChannelIsNeuacpVerifyChannel():
    """缺省自建的就是 NeuacpVerifyChannel（同模块小类，持同一执行体）。"""
    from neurova.agent.neuacp.acp_member import NeuacpVerifyChannel

    adapter = makeAdapter([])
    assert isinstance(adapter.llm_client, NeuacpVerifyChannel)
    assert adapter.llm_client._executor is adapter._executor


def test_explicitVerifyChannelStillWins():
    """显式注入优先（本仓 provider 通道/测试替身）——默认自建不覆盖注入。"""
    adapter = makeAdapter([])

    class InjectedChannel:
        async def chat(self, messages, **kwargs):
            return {"content": "injected"}

    injected = InjectedChannel()
    adapter2 = NeuacpMemberAdapter(
        NeuacpScriptedExecutor(script=[]), name="外部编码代理", cwd=".",
        verify_channel=injected,
    )
    assert adapter2.llm_client is injected


# ── 绿灯：判定通道喂饱验收门 ─────────────────────────────────────────────


def test_verifyChannelFeedsAcceptanceLoopFailPath():
    """判定「未达标」→ 带 missing 回炉一次 → 再判仍不达标 → failed(acceptance_failed)。"""
    adapter = makeAdapter([{"emit": ["content", VERDICT_FAIL]}])
    run = makeRun()
    reworkPrompts = []

    async def chatFn(text):
        reworkPrompts.append(text)
        return "修订后的完整产出"

    async def drive():
        return await runAcceptanceLoop(
            run,
            chatFn=chatFn,
            verifyChannel=adapter.llm_client.chat,
            firstReport="首轮产出",
        )

    gate = asyncio.run(drive())
    assert gate.failedReason is not None
    assert "acceptance_failed" in gate.failedReason
    assert gate.cause == "acceptance_failed"
    assert gate.info["achieved"] is False
    assert gate.info["reworked"] is True
    assert gate.info["rounds"] == 1
    # 回炉恰好一次，missing 逐条进修正指令（可执行、可核对）
    assert len(reworkPrompts) == 1
    assert "验收打回" in reworkPrompts[0]
    assert "缺少密码输入框" in reworkPrompts[0]
    assert "提交后无校验反馈" in reworkPrompts[0]


def test_verifyChannelFeedsAcceptanceLoopPassPath():
    """判定「达标」→ failedReason=None（swarm 侧置 completed）且 achieved is True。"""
    adapter = makeAdapter([{"emit": ["content", VERDICT_PASS]}])
    run = makeRun()

    async def chatFn(text):
        raise AssertionError("达标不应回炉")

    async def drive():
        return await runAcceptanceLoop(
            run,
            chatFn=chatFn,
            verifyChannel=adapter.llm_client.chat,
            firstReport="首轮产出",
        )

    gate = asyncio.run(drive())
    assert gate.failedReason is None
    assert gate.cause == ""
    assert gate.info["achieved"] is True
    assert gate.info["reworked"] is False
    assert gate.info["rounds"] == 0


# ── 判定会话权限面：恒 deny + 文本收集不受影响 + F2 留痕 ─────────────────


def test_verifySessionPermissionAlwaysDeniedAndTextIntact():
    """判定会话收到 session/request_permission → 恒 deny；已收集判定文本完整返回。

    scripted 桩与 wire 同纪律：deny 后中止剩余步骤、以 cancelled 收尾——
    因此把判定文本放在权限步骤之前，验证 deny 不吞掉已收集文本；
    permission 请求/应答帧照走 F2（frame_log 落盘，应答 approved=False）。
    """
    executor = NeuacpScriptedExecutor(
        script=[
            {"emit": ["content", VERDICT_PASS]},
            {"request_permission": {"action": "acp:fs:write", "reason": "判定期间想写文件"}},
            {"emit": ["content", "deny 后不应再收集的文本"]},
        ],
        cwd=".",
    )
    executor.setFrameKey("sw_verify_perm")
    adapter = NeuacpMemberAdapter(executor, name="外部编码代理", cwd=".")

    async def drive():
        return await adapter.llm_client.chat(VERIFY_MESSAGES)

    response = asyncio.run(drive())
    assert response["content"] == VERDICT_PASS

    frames = [record["frame"] for record in readFrames("sw_verify_perm")]
    requests = [f for f in frames if f.get("type") == "permission_request"]
    responses = [f for f in frames if f.get("type") == "permission_response"]
    assert requests, "判定会话的权限请求帧应落 F2 账本"
    assert responses and responses[0]["approved"] is False, "裁决必须 fail-closed deny"


def test_denyVerifyPermissionAlwaysDenies():
    """通道的权限裁决函数：任何动作恒 deny（四键裁决 dict，与审批泵同形）。"""
    from neurova.agent.neuacp.acp_member import denyVerifyPermission

    for action in ("acp:fs:read", "acp:fs:write", "acp:shell:execute", "acp:unknown:other"):
        decision = denyVerifyPermission(action, "r", "c")
        assert decision["approved"] is False
        assert decision["denied"] is True
        assert decision["pending"] is False
        assert decision["reason"]


# ── 通道协议：消息渲染 + 委托执行体 + 不吞异常 ───────────────────────────


def test_verifyChannelRendersMessagesAndDelegatesToExecutor():
    """chat(messages) 渲染成单段提示词委托执行体（plugin 单向管道即此形态）；
    emitter 恒 None（判定正文不进内容流）、on_permission 恒 deny。"""

    class RecordingExecutor:
        def __init__(self):
            self.prompts = []

        async def prompt(self, task_text, emitter, on_permission):
            self.prompts.append((task_text, emitter, on_permission))
            return NeuacpExecResult(text=VERDICT_PASS)

        async def start(self, ctx):
            return None

        async def cancel(self):
            return None

        async def close(self):
            return None

    executor = RecordingExecutor()
    adapter = NeuacpMemberAdapter(executor, name="外部编码代理", cwd=".")

    async def drive():
        return await adapter.llm_client.chat(VERIFY_MESSAGES)

    response = asyncio.run(drive())
    assert response == {"content": VERDICT_PASS}
    taskText, emitter, onPermission = executor.prompts[0]
    assert "你是目标验收判定员" in taskText, "system 判据进判定提示词"
    assert "<goal>写一个登录页</goal>" in taskText and "首轮产出" in taskText
    assert emitter is None
    assert onPermission("acp:fs:write", "", "")["approved"] is False


def test_verifyChannelPropagatesExecutorFailure():
    """执行体故障原样上抛（不吞、不兜底）——goal_verifier 据此判 parse_ok=False
    走 judge_unavailable 诚实降级；通道若吞错反而是掩盖。"""
    adapter = makeAdapter([{"crash": "segfault"}])

    async def drive():
        await adapter.llm_client.chat(VERIFY_MESSAGES)

    with pytest.raises(NeuacpError):
        asyncio.run(drive())
