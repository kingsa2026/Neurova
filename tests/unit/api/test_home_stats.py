"""
Home / Dashboard 端点真实统计测试（防回归）

背景：home.py 曾是 stub（除 agent_count 外全部硬编码 0，trends 用 random 伪造）。
本测试锁定修复契约：
1. /home/data 的 conversation/token/call/memory 统计必须来自真实数据源
2. /home/trends 必须确定性（两次调用一致）且 token/llm 无历史时返回空数组
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import home
from neurova.core.usage_accounting import get_usage_accounting, reset_usage_accounting
from neurova.session_repository import reset_session_repository


@pytest.fixture(autouse=True)
def _clean_globals():
    """每个用例前后重置记账器/会话仓库单例，避免污染其它测试。"""
    reset_usage_accounting()
    reset_session_repository()
    yield
    reset_usage_accounting()
    reset_session_repository()


class FakeSessionRepo:
    """可控会话仓库桩：list_sessions 返回固定摘要列表。"""

    def __init__(self, sessions):
        self._sessions = sessions

    def list_sessions(self, agent_id: str = "", user_id: str = ""):
        return self._sessions


class FakeMemoryManager:
    def __init__(self, count: int):
        self._count = count

    def get_memory_count(self) -> int:
        return self._count


class TestHomeDataRealStats:
    """/home/data 统计必须来自真实数据源而非硬编码 0。"""

    @pytest.mark.asyncio
    async def test_stats_use_real_sources(self, monkeypatch):
        """conversation/token/call/memory 均应取真实值。"""
        monkeypatch.setattr(
            "neurova.api.endpoints.get_app_state",
            lambda: {"agents": {"default": object(), "alt": object()}},
        )
        reset_usage_accounting()
        acc = get_usage_accounting()
        acc.record(model="gpt-4o", provider="openai", prompt_tokens=100, completion_tokens=50)
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: FakeSessionRepo([{"session_id": "s1"}, {"session_id": "s2"}, {"session_id": "s3"}]),
        )
        monkeypatch.setattr(
            "neurova.api.endpoints.home._sum_agent_persist_counts",
            lambda: 65,
        )

        res = await home.get_home_data(MagicMock())

        stats = res["stats"]
        assert stats["agent_count"] == 2
        assert stats["conversation_count"] == 3, "conversation_count 必须来自会话仓库"
        assert stats["token_consumption"] == 150, "token_consumption 必须来自 usage 记账器"
        assert stats["llm_call_count"] == 1, "llm_call_count 必须来自 usage 记账器"
        assert stats["memory_count"] == 65, "memory_count 必须聚合所有 agent 的记忆库（多 agent 独立库设计）"

    @pytest.mark.asyncio
    async def test_memory_count_falls_back_to_single_manager(self, monkeypatch):
        """聚合不可用（None）时回退默认 agent MemoryManager.get_memory_count。"""
        monkeypatch.setattr("neurova.api.endpoints.get_app_state", lambda: {"agents": {}})
        monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", lambda: None)
        monkeypatch.setattr(
            "neurova.cognitive_layers.memory_layer.manager.get_memory_manager",
            lambda *a, **kw: FakeMemoryManager(42),
        )
        res = await home.get_home_data(MagicMock())
        assert res["stats"]["memory_count"] == 42

    @pytest.mark.asyncio
    async def test_source_failure_falls_back_to_zero(self, monkeypatch):
        """数据源异常时端点不炸，回退 0。"""
        monkeypatch.setattr("neurova.api.endpoints.get_app_state", lambda: {"agents": {}})

        def boom(*a, **kw):
            raise RuntimeError("repo down")

        monkeypatch.setattr("neurova.session_repository.get_session_repository", boom)
        monkeypatch.setattr("neurova.cognitive_layers.memory_layer.manager.get_memory_manager", boom)
        monkeypatch.setattr("neurova.api.endpoints.home._sum_agent_persist_counts", lambda: (_ for _ in ()).throw(RuntimeError("persist scan down")))
        res = await home.get_home_data(MagicMock())
        assert res["stats"]["conversation_count"] == 0
        assert res["stats"]["memory_count"] == 0


class TestMultiAgentAggregation:
    """系统级记忆聚合必须覆盖运行时的全部 agent（新建 agent 的自定义路径也计入）。"""

    @staticmethod
    def _make_agent_with_memory(tmp_path, db_name: str, rows: int):
        import sqlite3

        db = tmp_path / db_name
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
        for i in range(rows):
            conn.execute("INSERT INTO memories (id, content) VALUES (?, ?)", (f"m{i}", "x"))
        conn.commit()
        conn.close()

        class _FakeMemoryManager:
            _persist_db_path = str(db)

        class _FakeMemoryAgent:
            memory_manager = _FakeMemoryManager()

        class _FakeAgent:
            memory_agent = _FakeMemoryAgent()

        return _FakeAgent()

    def test_runtime_agents_are_enumerated(self, monkeypatch, tmp_path):
        """新建 agent（自定义 workspace 路径/persist 库）必须被聚合统计。"""
        a1 = self._make_agent_with_memory(tmp_path, "agent_a.db", 2)
        a2 = self._make_agent_with_memory(tmp_path, "agent_b.db", 3)
        monkeypatch.setattr(
            "neurova.api.endpoints.get_app_state",
            lambda: {"agents": {"a1": a1, "a2": a2}},
        )
        monkeypatch.setattr("neurova.api.endpoints.home._GLOB_AGENT_WORKSPACES", lambda: [])
        assert home._sum_agent_persist_counts() == 5

    def test_glob_fallback_when_no_runtime_agents(self, monkeypatch, tmp_path):
        """无运行时 agent（或少一个未加载库）时 glob 兜底计入。"""
        monkeypatch.setattr("neurova.api.endpoints.get_app_state", lambda: {})
        db = tmp_path / "legacy" / "memory" / "neurova_memories_persist.db"
        db.parent.mkdir(parents=True)
        import sqlite3

        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, content TEXT)")
        conn.execute("INSERT INTO memories (id, content) VALUES (?, ?)", ("m1", "x"))
        conn.commit()
        conn.close()
        monkeypatch.setattr("neurova.api.endpoints.home._GLOB_AGENT_WORKSPACES", lambda: [str(db)])
        assert home._sum_agent_persist_counts() == 1


class TestHomeTrendsRealAggregation:
    """/home/trends 必须确定性且来自真实会话聚合（不允许 random 伪造）。"""

    def _sessions(self):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            {"session_id": "a1", "agent_id": "default", "created_at": f"{today}T10:00:00", "total_messages": 5},
            {"session_id": "a2", "agent_id": "alt", "created_at": f"{today}T11:00:00", "total_messages": 3},
            {"session_id": "a3", "agent_id": "default", "created_at": f"{yesterday}T09:00:00", "total_messages": 1},
        ]

    @pytest.mark.asyncio
    async def test_trends_are_deterministic(self, monkeypatch):
        """两次调用结果必须一致（stub 用 random.randint 时必红）。"""
        sessions = self._sessions()
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: FakeSessionRepo(sessions),
        )
        res1 = await home.get_home_trends(MagicMock(), days=7)
        res2 = await home.get_home_trends(MagicMock(), days=7)
        assert res1 == res2, "trends 必须是确定性数据，不允许 random 伪造"

    @pytest.mark.asyncio
    async def test_trends_aggregate_sessions_by_day(self, monkeypatch):
        """会话趋势按天聚合：今天 2 条 / 昨天 1 条、消息 8 / 1。"""
        sessions = self._sessions()
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: FakeSessionRepo(sessions),
        )
        res = await home.get_home_trends(MagicMock(), days=7)

        labels = res["conversation_trend"]["labels"]
        assert len(labels) == 7
        conv = res["conversation_trend"]["data"]
        assert conv[-1] == 2, "最后一天应为今天创建的会话数"
        assert conv[-2] == 1, "倒数第二天应为昨天创建的会话数"
        assert res["message_trend"]["data"][-1] == 8
        assert res["message_trend"]["data"][-2] == 1
        # agent_trend：今天有 2 个不同 agent 活跃
        assert res["agent_trend"]["data"][-1] == 2

    @pytest.mark.asyncio
    async def test_token_trend_empty_when_no_history(self, monkeypatch):
        """token/llm 无日维度历史时必须返回空数组而非随机数。"""
        monkeypatch.setattr(
            "neurova.session_repository.get_session_repository",
            lambda: FakeSessionRepo(self._sessions()),
        )
        res = await home.get_home_trends(MagicMock(), days=7)
        assert res["token_trend"]["data"] == []
        assert res["llm_trend"]["data"] == []
