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

## 闸的覆盖面（2026-10-25 补）：拦"那一刻的类"，不是"导入时那个类"

改前闸盯的是 `MultiModelLLMClient` 这个**类对象上的方法**。`SimulatedAgent` 与
`SyntheticDatasetBuilder` 都不持有客户端实例，它们**每次调用现取**
`get_multi_model_client()` 再 `.chat(...)`；只要 `get_multi_model_client()` 给回来的
是另一个类/另一份实例（单例被前序用例重置过、或换了装配），类上那个补丁就一行都不生效。
实测形态：本目录单跑 3s 全绿，CI 全量批跑里 `TestEvolveFlow` 三格撞 `pytest-timeout (>30s)`——
那三格传了 `dataset`，可闸漏了，落到了**真实 provider 等待**上。

所以补的第二层是**实例侧**：把当前单例实例上的同名方法也钉住。两层都按"调用那一刻"取，
不按"导入那一刻"缓存；`get_multi_model_client()` 若在本用例内被重置，实例换了，
闸仍按新实例上的补丁生效（`_isolate_*` 夹具每用例复位单例，故这层不会漏到下一个用例）。
"""

import pytest

from neurova.evolution.eval import service as service
from neurova.evolution.eval import synthetic as synthetic
from neurova.llm import multi_model_client as mmc
from neurova.llm.multi_model_client import MultiModelLLMClient


def _patchInstance(client, blocked, blockedAsync) -> None:
    """把 `client` 自身的 `chat` / `chat_stream` 换成拦子（含夹具进来前已缓存的旧实例）。"""
    if client is None:
        return
    client.chat = blocked
    client.chat_stream = blockedAsync


class _RealLlmCallAttempted(BaseException):
    """eval 目录的用例发起了真实 LLM 调用。BaseException 才不被 except Exception 吞。"""


@pytest.fixture(autouse=True)
def _blockOutboundLlmCalls(monkeypatch):
    """本用例内禁止真实 LLM 出站（装配见下）。"""
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
    # 实例侧再钉一层（**活解析**）：`SimulatedAgent`／`SyntheticDatasetBuilder` 每次都现取
    # `get_multi_model_client()` 再 `.chat(...)`。只钉类不够——单例一旦被换成另一个类的实例
    # （前序用例重置过、或换了装配），类上那个补丁一行都不生效，闸就成了哑闸。
    # 所以把「取单例」这个入口本身包一层：谁取，谁拿到的实例就被钉上拦子。
    # 夹具进来之前已经缓存的实例也一并补钉（本夹具 autouse，第一例就装上了）。
    _patchInstance(mmc._multi_model_client, _blocked, _blockedAsync)
    for _scopeClient in list(mmc._multi_model_clients.values()):
        _patchInstance(_scopeClient, _blocked, _blockedAsync)
    _originalGetter = mmc.get_multi_model_client

    def _guardedGetter(scope=None):
        client = _originalGetter(scope)
        _patchInstance(client, _blocked, _blockedAsync)
        return client

    monkeypatch.setattr(mmc, "get_multi_model_client", _guardedGetter)
    # 已经 `from … import get_multi_model_client` 的那个名字也指向拦子（`synthetic` 是
    # 调用期导入，`service` 不持有它，故两处都改；raising=False 免得绑定形态不同就报错）。
    for module in (service, synthetic):
        if hasattr(module, "get_multi_model_client"):
            monkeypatch.setattr(module, "get_multi_model_client", _guardedGetter, raising=False)
    yield


class _EchoAgent:
    """离线执行器：把技能文本原样当输出，使脚本判分器可确定性打分。"""

    async def run(self, *, skill_text, task_input):
        return skill_text


@pytest.fixture
def offlineAgent():
    return _EchoAgent()
