"""红灯③：usage-overview 的三个会话类 KPI 必须说真话。

现状（2026-10-02 截图 gui-test-screenshots/usage-stats.png 实证）：
库完全为空（累计 0、峰值 0、「暂无数据」），但 KPI 卡显示
「最长聊天时长 11.1 小时 / 当前连续 11 天 / 最长连续 11 天」。

根因两条，都在 `stats.py::get_usage_overview` 对会话摘要的取数口径上：

1. `longest_session_seconds = updated_at - created_at`。会话文件的 `created_at`
   是**该会话首次产生消息**的时刻，`updated_at` 是**最后一次活动**的时刻——
   两者之差是会话「跨醒时长」（用户挂着页面过夜/整日不关就是这个数），
   不是「聊天时长」。11.1 小时 = 09:00 建会 → 20:06 最后一条消息。
2. 活跃日期集取 `created_at[:10]`（会话创建日），并集进 `active_dates`。
   于是「11 天前建过一个会话」被算成「连续活跃 11 天」，与 token 是否为 0 无关。

修正口径（会话「时长」的唯一事实源只能是消息时间戳）：
- 会话时长 = 该会话**最后一条消息**与**第一条消息**时间戳之差；
- 活跃日 = 该会话**有消息的那些天**（消息时间戳的日期），不是建会日。
"""

from datetime import date, timedelta

from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import stats as stats_endpoint
from neurova.core.usage_history import reset_usage_history


@pytest.fixture(autouse=True)
def _clean_history():
    reset_usage_history()
    yield
    reset_usage_history()


def _stub_sessions(sessions):
    """按 SessionRepository 真实契约打桩：list_sessions + get_history。

    会话消息（`messages`）不在 list_sessions 摘要里——真实实现由
    `get_history(agent_id, session_id)` 提供，端点必须走这条路径取消息。
    """
    by_key = {(s.get("agent_id") or "", s.get("session_id") or ""): s for s in sessions}

    class _Repo:
        def list_sessions(self, user_id="", agent_id=""):
            return [s for s in sessions if not user_id or s.get("user_id") == user_id]

        def get_history(self, agent_id, session_id, max_messages=0):
            s = by_key.get((agent_id or "", session_id or ""))
            return list((s or {}).get("messages") or [])

    return lambda: _Repo()


class TestLongestSessionIsChatSpanNotLifetimeSpan:
    @pytest.mark.asyncio
    async def test_session_straddling_a_full_day_is_not_reported_as_chat_hours(self, monkeypatch):
        """挂机过夜场景：建会 09:00、最后一条消息 09:20 → 时长只能算 20 分钟。

        旧口径会给出 11.1 小时（09:00 → 20:06），即截图里那个数。
        """
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        sessions = [
            {
                "user_id": "u1",
                "agent_id": "a1",
                "session_id": "s1",
                "created_at": f"{yesterday}T09:00:00",   # 建会时刻
                "updated_at": f"{yesterday}T20:06:00",   # 最后一次活动（挂机到晚上）
                # 真实消息：只在 09:00 和 09:20 之间聊过
                "messages": [
                    {"role": "user", "timestamp": f"{yesterday}T09:00:00"},
                    {"role": "assistant", "timestamp": f"{yesterday}T09:20:00"},
                ],
            }
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository", _stub_sessions(sessions)
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["summary"]["longest_session_seconds"] == 20 * 60, (
            "会话时长必须由消息时间戳算出（最后一条 - 第一条），"
            "不得用 updated_at - created_at 的跨醒时长冒充"
        )

    @pytest.mark.asyncio
    async def test_session_without_messages_contributes_zero(self, monkeypatch):
        """无消息的会话文件不产生时长——不得因为字段齐全就造出一个非零值。"""
        d = date.today().isoformat()
        sessions = [
            {
                "user_id": "u1",
                "agent_id": "a1",
                "session_id": "s1",
                "created_at": f"{d}T09:00:00",
                "updated_at": f"{d}T20:06:00",
                "messages": [],
            }
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository", _stub_sessions(sessions)
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["summary"]["longest_session_seconds"] == 0

    @pytest.mark.asyncio
    async def test_single_message_session_is_zero_span(self, monkeypatch):
        d = date.today().isoformat()
        sessions = [
            {
                "user_id": "u1",
                "agent_id": "a1",
                "session_id": "s1",
                "created_at": f"{d}T09:00:00",
                "updated_at": f"{d}T20:06:00",
                "messages": [{"role": "user", "timestamp": f"{d}T09:00:00"}],
            }
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository", _stub_sessions(sessions)
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        assert res["summary"]["longest_session_seconds"] == 0


class TestActiveDaysComeFromMessageTimestamps:
    @pytest.mark.asyncio
    async def test_creation_day_alone_is_not_an_active_day(self, monkeypatch):
        """空库 + 11 天前建的会话：活跃天数必须是 0，不是 11。

        这正是截图里「累计 token 0 / 当前连续 11 天」的自相矛盾。
        """
        old = (date.today() - timedelta(days=11)).isoformat()
        sessions = [
            {
                "user_id": "u1",
                "agent_id": "a1",
                "session_id": "s1",
                "created_at": f"{old}T10:00:00",
                "updated_at": f"{old}T10:00:00",
                "messages": [],
            }
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository", _stub_sessions(sessions)
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        s = res["summary"]
        assert s["total_tokens"] == 0
        assert s["active_days"] == 0, "无消息的建会日不是活跃日"
        assert s["current_streak_days"] == 0
        assert s["longest_streak_days"] == 0, (
            "11 天前建一个空会话不得算成「连续活跃 11 天」"
        )

    @pytest.mark.asyncio
    async def test_streak_follows_message_days_not_creation_days(self, monkeypatch):
        """跨 3 天各有消息 → 连续 3 天；建会日早于消息日则以消息日为准。"""
        today = date.today()
        d0 = today.isoformat()
        d1 = (today - timedelta(days=1)).isoformat()
        d2 = (today - timedelta(days=2)).isoformat()
        created = (today - timedelta(days=30)).isoformat()
        sessions = [
            {
                "user_id": "u1",
                "agent_id": "a1",
                "session_id": "s1",
                "created_at": f"{created}T08:00:00",
                "updated_at": f"{d0}T18:00:00",
                "messages": [
                    {"role": "user", "timestamp": f"{d2}T09:00:00"},
                    {"role": "assistant", "timestamp": f"{d1}T09:00:00"},
                    {"role": "user", "timestamp": f"{d0}T09:00:00"},
                ],
            }
        ]
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository", _stub_sessions(sessions)
        )
        res = await stats_endpoint.get_usage_overview(
            MagicMock(), days=7, trend_days=7, current_user={"user_id": "u1"}
        )
        s = res["summary"]
        assert s["current_streak_days"] == 3
        assert s["longest_streak_days"] == 3
        assert s["active_days"] == 3, "建会日（30 天前）不得混进活跃日"
