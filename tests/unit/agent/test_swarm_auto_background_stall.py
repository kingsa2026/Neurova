# -*- coding: utf-8 -*-
"""P2（蜂群对照 #4/#5）：前台自动转后台 + 卡死渐进提醒。

- 自动转后台：前台派生在 env 窗口内未跑完即转后台（返回 background 信封），
  窗口内跑完照常前台返回；env 未设/为 0 保持既有"前台等到底"语义；
- 卡死看门狗：member 连续无产出达首报阈值即广播 subagent_stalled + 邮箱提醒，
  阈值指数退避；**只提醒不裁决**（run 状态机不受影响）；chunk 到达即触碰进度位。
"""

import asyncio
import time
from unittest.mock import patch

import pytest

from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)


class ScriptedAgent:
    """按脚本吐 chunk/收尾的假子 Agent：emit 后 delay 秒返回"""

    def __init__(self, name="子Agent", chunks=(), delay=0.0, reply="完成"):
        self.config = type("Cfg", (), {"name": name})()
        self._chunks = chunks
        self._delay = delay
        self._reply = reply
        import types
        from unittest.mock import AsyncMock

        self.chat = AsyncMock(side_effect=self._chat)

    async def _chat(self, task, **kwargs):
        emitter = (kwargs.get("metadata") or {}).get("event_emitter")
        for chunk in self._chunks:
            if emitter is not None:
                emitter("content", chunk)
        await asyncio.sleep(self._delay)
        return {"text": self._reply}


@pytest.fixture
def swarm():
    reset_swarm_manager()
    return get_swarm_manager()


class TestAutoBackground:
    @pytest.mark.asyncio
    async def test_slow_foreground_converts_to_background(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_BACKGROUND_AFTER_S", "0.2")
        agent = ScriptedAgent(chunks=("部分",), delay=0.8, reply="迟到的报告")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            t0 = time.monotonic()
            result = await swarm.spawn(task="长任务", agent_id="researcher")
            elapsed = time.monotonic() - t0

        # 立即返回后台信封，父轮不被阻塞到任务结束
        assert result["background"] is True
        assert result["auto_background"] is True
        assert result["subagent_id"].startswith("swarm_")
        assert elapsed < 0.6
        # 任务继续跑并落终态（可查、可回灌）
        await asyncio.sleep(1.2)
        final = swarm.status(result["subagent_id"])
        assert final["status"] == "completed"
        assert final["report"] == "迟到的报告"

    @pytest.mark.asyncio
    async def test_fast_foreground_completes_inline(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_AUTO_BACKGROUND_AFTER_S", "5")
        agent = ScriptedAgent(reply="秒回")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="快任务", agent_id="researcher")

        assert result["status"] == "completed"
        assert result["report"] == "秒回"
        assert "background" not in result

    @pytest.mark.asyncio
    async def test_disabled_by_default_keeps_blocking_semantics(self, swarm, monkeypatch):
        monkeypatch.delenv("NEUROVA_SWARM_AUTO_BACKGROUND_AFTER_S", raising=False)
        agent = ScriptedAgent(delay=0.3, reply="等到了")
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="任务", agent_id="researcher")

        assert result["status"] == "completed"
        assert "background" not in result


class TestStallWatchdog:
    def _seedRunning(self, swarm):
        run = SubAgentRun(
            agent_id="researcher",
            agent_name="研究员",
            task="长任务",
            origin="chat",
            session_id="parent-s1",
            member_session_id="member-s1",
        )
        run.status = SUBAGENT_RUNNING
        swarm._runs[run.subagent_id] = run
        return run

    @pytest.mark.asyncio
    async def test_stall_fires_reminder_then_exits_on_terminal(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_STALL_FIRST_S", "0.1")
        run = self._seedRunning(swarm)
        run.last_progress_at = time.monotonic() - 5  # 已停更 5s

        broadcasts = []

        async def fakeBroadcast(r, name, payload):
            broadcasts.append((name, payload))

        monkeypatch.setattr(swarm, "_broadcast", fakeBroadcast)
        mails = []
        monkeypatch.setattr(swarm, "_notifyStallMail", lambda r, p: mails.append(p))

        wd = asyncio.create_task(swarm._stallWatchdog(run))
        await asyncio.sleep(1.3)  # poll=1.0s → 首报触发
        run.status = SUBAGENT_COMPLETED  # 终态 → 看门狗应退出
        await asyncio.sleep(0.2)
        wd.cancel()

        assert broadcasts, "停更超阈值必须广播 subagent_stalled"
        name, payload = broadcasts[0]
        assert name == "subagent_stalled"
        assert payload["subagent_id"] == run.subagent_id
        assert payload["stalled_seconds"] >= 5
        assert payload["reminder_count"] == 1
        assert run.stall_reminder_count == 1
        assert mails and mails[0]["subagent_id"] == run.subagent_id

    @pytest.mark.asyncio
    async def test_watchdog_disabled_when_env_zero(self, swarm, monkeypatch):
        monkeypatch.setenv("NEUROVA_SWARM_STALL_FIRST_S", "0")
        run = self._seedRunning(swarm)
        run.last_progress_at = time.monotonic() - 100

        broadcasts = []

        async def fakeBroadcast(r, name, payload):
            broadcasts.append((name, payload))

        monkeypatch.setattr(swarm, "_broadcast", fakeBroadcast)
        wd = asyncio.create_task(swarm._stallWatchdog(run))
        await asyncio.sleep(0.3)
        wd.cancel()

        assert broadcasts == []

    @pytest.mark.asyncio
    async def test_chunk_touches_progress(self, swarm):
        run = self._seedRunning(swarm)
        old = run.last_progress_at
        emitter = swarm._make_emitter(run)
        await asyncio.sleep(0.01)
        emitter("content", "有产出")
        assert run.last_progress_at >= old

    def test_threshold_defaults_and_env_override(self, swarm, monkeypatch):
        monkeypatch.delenv("NEUROVA_SWARM_STALL_FIRST_S", raising=False)
        assert swarm._stallFirstSeconds() == 900.0
        monkeypatch.setenv("NEUROVA_SWARM_STALL_FIRST_S", "30")
        assert swarm._stallFirstSeconds() == 30.0
        monkeypatch.setenv("NEUROVA_SWARM_STALL_CAP_S", "60")
        assert swarm._stallCapSeconds() == 60.0
