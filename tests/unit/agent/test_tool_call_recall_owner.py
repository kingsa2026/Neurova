# -*- coding: utf-8 -*-
"""直取寻址必须按**会话真实属主**读台账（Issue #90 · T-10a 放大视角第二命中点）。

写侧 `mem_core.save_to_session` 把会话写在 `<sessions>/<config.agent_id>/` 下；
读侧 `ToolExecutor._recall_by_call_id` 却用**空 agent_id** 查台账，而空值会被
`SessionManager._get_session_dir` 归入 `default/` 目录（见其 docstring 的 #1 改造）。
于是"我自己写下的硬地址，我自己读不回来"——T-10a 刚落盘的 `tool_call_id`,
T-10b 的重建与 `recall_history(session_id, tool_call_id)` 直取都拿不到原文。

实测（真 SessionManager，写侧传真 agent_id、读侧传空）：

```
sessions 根目录下：['neurova_real']
agent_id='neurova_real' -> msgs=2 tool_calls=1
agent_id=''             -> msgs=0 tool_calls=0   ← 生产读法
```

判据取**读侧的实得读数**（发给仓库的 agent_id 必须等于会话属主），不取实现细节。
"""

from types import SimpleNamespace

import pytest

from neurova.session_manager import SessionManager
from neurova.tool_executor import ToolExecutor

OWNER = "neurova_owner"
SESSION = "sess_owner"


def _makeExecutor(repo):
    agent = SimpleNamespace(
        current_session_id=SESSION,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id=OWNER),
        session_repo=repo,
        workspace_path=".",
    )
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._agent = agent
    return executor


class TestDirectRecallReadsOwningAgent:
    @pytest.mark.asyncio
    async def test_recall_uses_owning_agent_not_default_dir(self):
        """台账读侧的 agent_id 必须是会话属主 —— 空值等于去 `default/` 找一个不在那儿的地址。"""
        seen = {}

        class _Repo:
            def get_history(self, agent_id="", session_id="", max_messages=0):
                seen["agent_id"] = agent_id
                seen["session_id"] = session_id
                return [
                    {
                        "role": "assistant",
                        "metadata": {
                            "tool_calls": [
                                {
                                    "type": "tool_result",
                                    "tool_call_id": "call_owner_1",
                                    "tool_name": "probe_read",
                                    "result": "台账原文",
                                }
                            ]
                        },
                    }
                ]

        out = await _makeExecutor(_Repo())._recall_by_call_id(
            "call_owner_1", {"session_id": SESSION}
        )

        assert seen.get("agent_id") == OWNER, (
            "直取读台账用的是空 agent_id（被会话管理器当成 `default` 目录）——"
            f"写侧落在会话属主目录下，读侧因此恒读不回来（实测 agent_id={seen.get('agent_id')!r}）"
        )
        assert out.get("result") == "台账原文" or out.get("content") == "台账原文"

    @pytest.mark.asyncio
    async def test_round_trip_through_real_session_manager(self, tmp_path):
        """真 `SessionManager` 上把这条链走一遍：写侧落属主目录 → 读侧必须取回。"""
        session_manager = SessionManager()
        session_manager._sessions_dir = tmp_path
        session_manager.add_message(
            agent_id=OWNER,
            session_id=SESSION,
            user_content="问题",
            assistant_content="回答",
            metadata=None,
            assistant_metadata={
                "tool_calls": [
                    {
                        "type": "tool_result",
                        "tool_call_id": "call_owner_1",
                        "tool_name": "probe_read",
                        "result": "台账原文",
                    }
                ]
            },
            user_id="",
        )

        executor = _makeExecutor(session_manager)
        out = await executor._recall_by_call_id("call_owner_1", {"session_id": SESSION})

        assert out.get("result") == "台账原文" or out.get("content") == "台账原文", (
            f"写侧落在 `{OWNER}/` 下、读侧却读不回来：{out}"
        )
