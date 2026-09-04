"""Member 即 SessionKey + spawn 三明治治理测试（OpenOcta 启发 P2 #9/#10）

#9 Member 即 SessionKey：
  OpenOcta 蜂群成员只是一条 `agent:<id>:swarm:<ws>:<member>` 命名空间下的
  普通会话——完全复用单 agent 的 Runtime 池、transcript、usage 管线，多
  agent 编排不引入第二套运行时。
  Neurova 等价实现：SwarmManager 派生时把子 Agent 的会话键定为
  `swarm_<subagent_id>`（member 命名空间，Windows 文件名安全——冒号在
  NTFS 非法，OpenOcta 的冒号分节形式在此等价转写），代替原
  session_id=None（不落盘、无历史、member 每轮任务从零开始）。member 的
  任务对话经既有 save_to_session → SessionManager.add_message 持久化到
  sessions/<agent_id>/session_swarm_<id>_*.json，复用全部会话存储——
  不建第二套管线。member 内递归 spawn 时其 current_session_id 即为
  member 键（chat 管线请求级回写），治理阀门天然覆盖递归。

#10 spawn 三明治治理：
  OpenOcta：常量硬限制 → 数据层结构化拒绝（SpawnRejectReason）→ 返回值
  带配额闭环。LLM 自主繁殖子 agent 时"提示词约束必然被忽略"由数据层
  硬拒绝兜底。本文件测前两层+闭环；第三层（提示词纪律内嵌工具描述）
  见 builtin_tools.py spawn_subagent schema 静态文案。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import SwarmManager, get_swarm_manager, reset_swarm_manager


def make_mock_agent(name="子Agent", reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = name
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestMemberSessionKey:
    """P2-9：member 是一条命名空间会话，不是匿名一次性调用。"""

    @pytest.mark.asyncio
    async def test_chat_session_id_uses_member_key(self, swarm):
        """agent.chat 的 session_id = member 会话键（进会话存储）。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="子任务A")

        sid = agent.chat.call_args.kwargs.get("session_id")
        assert sid and sid.startswith("swarm_"), f"chat session_id 应为 member 键，got {sid}"

    @pytest.mark.asyncio
    async def test_member_key_filesystem_safe(self, swarm):
        """member 键必须 Windows 文件名安全（SessionManager 直接拼文件名）。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="任务")
        sid = agent.chat.call_args.kwargs.get("session_id")
        forbidden = set('<>:"/\\|?*')
        assert not (set(sid) & forbidden), f"member 键含 NTFS 非法字符: {sid}"

    @pytest.mark.asyncio
    async def test_member_key_unique_per_run(self, swarm):
        """每次派生独立 member 键（member 粒度隔离）。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            await swarm.spawn(task="任务1")
            await swarm.spawn(task="任务2")

        keys = {c.kwargs.get("session_id") for c in agent.chat.call_args_list}
        assert len(keys) == 2, "两次派生应是两个独立 member 会话"

    @pytest.mark.asyncio
    async def test_run_records_member_session_key(self, swarm):
        """run 记录 member 键（可查询/审计）。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务X")

        st = swarm.status(result["subagent_id"])
        assert st["member_session_id"].startswith("swarm_")


class TestSpawnSandwich:
    """P2-10：常量硬限 + 数据层结构化拒绝 + 返回值配额闭环。"""

    @pytest.mark.asyncio
    async def test_active_children_cap_hard_reject(self, swarm):
        """超过 MAX_ACTIVE_CHILDREN 硬限：数据层拒绝，不派生。"""
        agent = make_mock_agent()

        async def slow_chat(*a, **k):
            await asyncio.sleep(30)  # 保持 running 状态
            return {"text": "x"}

        agent.chat = AsyncMock(side_effect=slow_chat)
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            tasks = [
                swarm.spawn(task=f"t{i}", background=True)
                for i in range(SwarmManager.MAX_ACTIVE_CHILDREN)
            ]
            results = await asyncio.gather(*tasks)
            assert all(r.get("background") for r in results)

            overflow = await swarm.spawn(task="超限任务")
        assert overflow.get("rejected") is True, "超限派生必须被数据层结构化拒绝"
        rej = overflow["rejection"]
        assert rej["code"] == "MAX_ACTIVE_CHILDREN"
        assert rej["message"]
        assert overflow.get("active_children") == SwarmManager.MAX_ACTIVE_CHILDREN
        assert overflow.get("limit") == SwarmManager.MAX_ACTIVE_CHILDREN

    @pytest.mark.asyncio
    async def test_task_size_cap_reject(self, swarm):
        """task 超长（防 LLM 把整段历史塞进 task）：结构化拒绝。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="x" * (SwarmManager.MAX_TASK_CHARS + 1))
        assert result.get("rejected") is True
        assert result["rejection"]["code"] == "TASK_TOO_LARGE"

    @pytest.mark.asyncio
    async def test_rejection_is_decision_not_failure(self, swarm):
        """拒绝结果不得被误记为工具故障（is_policy_denial 口径）。"""
        from neurova.security.governance import is_policy_denial

        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="x" * (SwarmManager.MAX_TASK_CHARS + 1))
        assert is_policy_denial(result) is True

    @pytest.mark.asyncio
    async def test_success_result_carries_quota(self, swarm):
        """成功派生（前台）返回值带 active_children/limit 闭环。"""
        agent = make_mock_agent()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="正常任务")
        assert result["status"] == "completed"
        assert result["active_children"] == 0  # 已结束不再计入
        assert result["limit"] == SwarmManager.MAX_ACTIVE_CHILDREN
