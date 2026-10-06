# -*- coding: utf-8 -*-
"""eval 目录的 LLM 出站闸与离线 agent。

来历：本目录 `test_noise_floor.py` / `test_history_ledger.py` /
`test_heldout_isolation.py` 三个文件长期"挂死"，把整目录跑测连带打死（30s 全局
timeout 用 thread 方法直接 kill 进程）。插桩取到的 await 链是

    service.evolve → _noise_band_for → calibrate_noise_band → runner._evaluate
        → service.SimulatedAgent.run → MultiModelLLMClient.chat
        → _sleep_for_retry → asyncio.sleep

根因不在 runner，在这三个文件传了 `agent=None`：`service.py:209/327` 的
`agent or SimulatedAgent(...)` 于是回落到**真**多模型客户端。本机当时有可用
provider，调用被判成 `rate_limited` 后进入"≤10 次 × 间隔 10s"的等待重试——
不是死循环，是**真花配额发 LLM 请求 + 远超 30s 用例预算**。同目录另 18 个文件
都注入假 agent，所以从不触发。

本 conftest 钉两件事：
1. 出站闸——`MultiModelLLMClient.chat` / `chat_stream` 一旦被调用即抛
   `_RealLlmCallAttempted`。必须是 `BaseException` 子类：`SimulatedAgent.run`
   外层是 `except Exception`（service.py:63），普通 AssertionError 会被吞成空回复，
   闸就成了哑闸。
2. `offlineAgent` 夹具——把技能文本原样回显，与同目录 `_Agent` 同语义，
   供三个文件替换 `agent=None`。
"""

import pytest

from neurova.llm.multi_model_client import MultiModelLLMClient


class _RealLlmCallAttempted(BaseException):
    """eval 目录的用例发起了真实 LLM 调用。BaseException 才不被 except Exception 吞。"""


@pytest.fixture(autouse=True)
def _blockOutboundLlmCalls(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _RealLlmCallAttempted(
            "eval 目录的用例不得发起真实 LLM 调用（会真花配额，且 429 等待重试远超用例预算）。"
            "请注入 offlineAgent：SkillEvolutionRunner/…evolve(..., agent=offlineAgent)。"
        )

    async def _blockedAsync(*args, **kwargs):
        raise _RealLlmCallAttempted(
            "eval 目录的用例不得发起真实 LLM 调用（流式路径同样拦）。请注入 offlineAgent。"
        )

    monkeypatch.setattr(MultiModelLLMClient, "chat", _blocked, raising=False)
    monkeypatch.setattr(MultiModelLLMClient, "chat_stream", _blockedAsync, raising=False)


class _EchoAgent:
    """离线执行器：把技能文本原样当输出，使脚本判分器可确定性打分。"""

    async def run(self, *, skill_text, task_input):
        return skill_text


@pytest.fixture
def offlineAgent():
    return _EchoAgent()
