# -*- coding: utf-8 -*-
"""C4：凭据变更闸门——轮换中诚实拒绝新会话启动，结束后放行。

覆盖 ``neurova/agent/neuacp/credential_gate.py`` 全部公开面：
begin/end 幂等、多 agent 互不干扰、旋转中 assertNoRotation 抛
CredentialRotationInProgress（带「稍后重试」指引），以及 acp_member
会话启动路径的闸门接线（轮换中不拉起任何外部进程）。
"""
import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.neuacp import credential_gate as gateModule
from neurova.agent.neuacp.acp_member import NeuacpMemberAdapter
from neurova.agent.neuacp.credential_gate import (
    CredentialRotationInProgress,
    assertNoRotation,
    beginCredentialRotation,
    endCredentialRotation,
    isRotationActive,
)
from neurova.agent.neuacp.executor import NeuacpExecResult

_AGENT = "agent-gate-1"
_OTHER = "agent-gate-2"


@pytest.fixture(autouse=True)
def _clearRotations():
    """测试隔离：每例后清空活跃轮换集（防失败用例污染后续用例）。"""
    yield
    with gateModule._ROTATION_LOCK:
        gateModule._ACTIVE_ROTATIONS.clear()


# ── 闸门本体语义 ──────────────────────────────────────────────────────────


def test_rotationActiveBlocksAndReportsRetryGuidance():
    beginCredentialRotation(_AGENT)
    assert isRotationActive(_AGENT) is True
    with pytest.raises(CredentialRotationInProgress) as excinfo:
        assertNoRotation(_AGENT)
    # 诚实拒绝：点名 agent 并带「稍后重试」指引
    assert "稍后重试" in str(excinfo.value)
    assert _AGENT in str(excinfo.value)
    assert excinfo.value.agent_id == _AGENT


def test_endRotationReleasesSessionStart():
    beginCredentialRotation(_AGENT)
    endCredentialRotation(_AGENT)
    assert isRotationActive(_AGENT) is False
    # 不抛异常即放行
    assertNoRotation(_AGENT)


def test_beginAndEndAreIdempotent():
    beginCredentialRotation(_AGENT)
    beginCredentialRotation(_AGENT)  # 重复 begin 不报错、不重复计数
    assert isRotationActive(_AGENT) is True
    endCredentialRotation(_AGENT)
    endCredentialRotation(_AGENT)  # 重复 end 不报错
    assert isRotationActive(_AGENT) is False
    endCredentialRotation(_OTHER)  # 未在轮换的 agent end 同样不报错
    assert isRotationActive(_OTHER) is False


def test_agentsDoNotInterfere():
    beginCredentialRotation(_AGENT)
    # 其他 agent 不受牵连
    assert isRotationActive(_OTHER) is False
    assertNoRotation(_OTHER)  # 不抛
    with pytest.raises(CredentialRotationInProgress):
        assertNoRotation(_AGENT)
    endCredentialRotation(_AGENT)
    assertNoRotation(_AGENT)
    assertNoRotation(_OTHER)


# ── acp_member 会话启动路径接线 ───────────────────────────────────────────


class _RecordingExecutor:
    """测试替身执行体：记录 start/prompt 调用，不拉起任何真实进程。"""

    def __init__(self):
        self.startCalls = 0
        self.promptCalls = 0

    async def start(self, ctx):
        self.startCalls += 1

    async def prompt(self, task_text, emitter, on_permission):
        self.promptCalls += 1
        return NeuacpExecResult(text="ok")

    async def cancel(self):
        pass

    async def close(self):
        pass


def _boundAdapter(executor, agentId):
    adapter = NeuacpMemberAdapter(executor, name="外部编码成员")
    run = SimpleNamespace(
        subagent_id="swarm-gate", trace_id="tr-gate",
        agent_name="外部编码成员", agent_id=agentId,
    )
    adapter.bindRun(run, lambda r, t, p=None: None)
    return adapter


def test_memberChatRefusedDuringRotationWithoutStartingExecutor():
    """轮换中 chat 诚实拒绝，且执行体零调用（连进程/会话都不启动）。"""
    executor = _RecordingExecutor()
    adapter = _boundAdapter(executor, _AGENT)
    beginCredentialRotation(_AGENT)

    async def drive():
        return await adapter.chat("任务", stream=True, session_id="m-1", metadata={})

    with pytest.raises(CredentialRotationInProgress) as excinfo:
        asyncio.run(drive())
    assert "稍后重试" in str(excinfo.value)
    assert executor.startCalls == 0 and executor.promptCalls == 0


def test_memberChatAllowedAfterRotationEnds():
    """轮换结束放行：chat 正常走 start → prompt，返回文本。"""
    executor = _RecordingExecutor()
    adapter = _boundAdapter(executor, _AGENT)
    beginCredentialRotation(_AGENT)
    endCredentialRotation(_AGENT)

    async def drive():
        return await adapter.chat("任务", stream=True, session_id="m-1", metadata={})

    assert asyncio.run(drive()) == {"text": "ok"}
    assert executor.startCalls == 1 and executor.promptCalls == 1


def test_memberGateKeyFallsBackToConfigNameWithoutBoundRun():
    """未绑定 run 的适配器按 config.name 作闸门键（键序：run.agent_id 优先）。"""
    executor = _RecordingExecutor()
    adapter = NeuacpMemberAdapter(executor, name="成员甲")
    beginCredentialRotation("成员甲")

    async def drive():
        return await adapter.chat("任务", stream=True, session_id="m-1", metadata={})

    with pytest.raises(CredentialRotationInProgress):
        asyncio.run(drive())
    assert executor.startCalls == 0
    endCredentialRotation("成员甲")
    assert asyncio.run(drive()) == {"text": "ok"}
