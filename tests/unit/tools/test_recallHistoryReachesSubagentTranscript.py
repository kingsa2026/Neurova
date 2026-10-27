# -*- coding: utf-8 -*-
"""下钻可达：主 Agent 凭信封指针经 `recall_history` 取回子 Agent 的会话原文。

裁定是「旁路只给信封 + 指针，详情从信封下钻到记录原始会话的 json」。指针要真是
一条可执行的指引，取回口必须能读到**子 Agent 目录下**的那份会话。现状读不到，
两处缺口叠在一起：

1. `_recall_by_call_id` 把会话属主硬取**当前** Agent（`self._agent_identity()`，
   `tool_executor.py:3246`），而 member 会话由写侧落在 `sessions/<子agent_id>/` 下
   ——拿着正确的 session_id 去主 Agent 的目录找一个不在那儿的地址，恒落空；
   `recall_history` 的参数表里也没有 `agent_id`，模型无从指定。
2. 直取模式只认台账里 `type == "tool_result"` 且带 `tool_call_id` 的条目，而子
   Agent 的最终报告是 assistant 消息正文，不在那本台账里。

下面第 1 格是缺陷本身（改前红）；第 2、3 格是反向控制，钉住「不带 agent_id 时
既有行为逐字不变」——含 Issue #90 那批落下的属主派生判据，不能被这次扩展顺手破掉。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from neurova.session_manager import SessionManager
from neurova.tool_executor import ToolExecutor

PARENT_AGENT = "neurova_parent"
CHILD_AGENT = "neurova_researcher"
MEMBER_SESSION = "swarm_a1b2c3d4e5f6"
REPORT_BODY = "子 Agent 的完整报告：三套方案逐项比对，β 在写入放大上占优。"


def _executorWith(agentId: str, repo) -> ToolExecutor:
    """按同域既有先例最小装配（避开真 Agent 冷装配，读侧仍走真 SessionManager）。"""
    agent = SimpleNamespace(
        current_session_id="s-parent",
        config=SimpleNamespace(name="probe", user_id="u1", agent_id=agentId),
        session_repo=repo,
        context_orchestrator=None,
        workspace_path=".",
    )
    executor = ToolExecutor.__new__(ToolExecutor)
    executor._agent = agent
    return executor


class TestDrillDownIntoSubagentTranscript:
    @pytest.mark.asyncio
    async def testAgentScopedRecallReadsChildSessionFile(self, tmp_path):
        """真写侧落盘 → 真读侧按 (agent_id, session_id) 取回原文。"""
        sm = SessionManager()
        sm._sessions_dir = tmp_path
        sm.add_message(
            agent_id=CHILD_AGENT,
            session_id=MEMBER_SESSION,
            user_content="调研三套方案",
            assistant_content=REPORT_BODY,
            metadata=None,
            user_id="",
        )
        landed = sorted(p.name for p in (tmp_path / CHILD_AGENT).glob("*.json"))
        assert landed, f"写侧没落盘，下钻无源：{list(tmp_path.iterdir())}"

        executor = _executorWith(PARENT_AGENT, sm)
        result = await executor._execute_recall_history({
            "agent_id": CHILD_AGENT,
            "session_id": MEMBER_SESSION,
        })
        dumped = json.dumps(result, ensure_ascii=False, default=str)
        assert "error" not in result, f"按属主取回失败：{result}"
        assert REPORT_BODY in dumped, (
            "取回内容里没有 member 会话正文——指针指到了读不到的地方（属主目录错）"
        )

    @pytest.mark.asyncio
    async def testRecallWithoutAgentIdStillUsesCurrentOwner(self):
        """反向控制（今天该绿）：不带 agent_id 时属主派生不变，Issue #90 的判据不许被这次扩展松动。"""
        seen = {}

        class _Repo:
            def get_history(self, agent_id="", session_id="", max_messages=0):
                seen["agent_id"] = agent_id
                return [{
                    "role": "assistant",
                    "metadata": {"tool_calls": [{
                        "type": "tool_result", "tool_call_id": "call_x",
                        "tool_name": "probe", "result": "台账原文",
                    }]},
                }]

        executor = _executorWith(PARENT_AGENT, _Repo())
        out = await executor._recall_by_call_id("call_x", {"session_id": MEMBER_SESSION})

        assert seen.get("agent_id") == PARENT_AGENT, (
            f"缺省属主派生被动了：实得 {seen.get('agent_id')!r}"
        )
        assert out.get("result") == "台账原文" or out.get("content") == "台账原文"

    @pytest.mark.asyncio
    async def testSessionIdWithoutAgentIdDoesNotEnterTranscriptBranch(self):
        """反向控制（今天该绿）：只给 session_id 不触发整取，仍走原有模糊召回语义。"""
        executor = _executorWith(PARENT_AGENT, None)
        result = await executor._execute_recall_history({"session_id": MEMBER_SESSION})
        assert "上下文池不可用" in str(result.get("error", "")), (
            f"只给 session_id 就被拉进整取分支，等于改了既有工具的缺省语义：{result}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
