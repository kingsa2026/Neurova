"""
ShutdownGuard 契约测试 — 验证测试期望的公共 API 形状。

与 test_shutdown_guard.py 不同,本文件聚焦于"接口契约"的边界条件:
- __init__ 接受 workspace_dir: str
- sentinel 文件名为 .neurova_shutdown_sentinel
- write_sentinel 写入 {pid, started_at}
- mark_clean_shutdown 删除 sentinel 文件
- check_abnormal_shutdown 返回 {abnormal, crash_time}
- flush_all_agent_buffers 接受 agents 字典,返回 {agent_id: {flushed}, total_flushed}

TDD RED 阶段:本文件先于实现编写,运行后应全部失败。
"""
import json
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    """临时工作目录,隔离测试产物。"""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def guard(temp_dir):
    """构造一个隔离工作空间的 ShutdownGuard 实例。"""
    from neurova.recovery.shutdown_guard import ShutdownGuard
    return ShutdownGuard(workspace_dir=str(temp_dir))


SENTINEL_NAME = ".neurova_shutdown_sentinel"


# ── 1. __init__ 契约 ────────────────────────────────────────

class TestInitContract:
    """__init__ 必须接受 workspace_dir: str 参数。"""

    def test_init_accepts_workspace_dir_str(self, temp_dir):
        """构造器接受 workspace_dir 关键字参数(str 类型)。"""
        from neurova.recovery.shutdown_guard import ShutdownGuard
        # 不应抛出 TypeError
        g = ShutdownGuard(workspace_dir=str(temp_dir))
        assert g is not None

    def test_init_accepts_positional_workspace_dir(self, temp_dir):
        """构造器也接受位置参数。"""
        from neurova.recovery.shutdown_guard import ShutdownGuard
        g = ShutdownGuard(str(temp_dir))
        assert g is not None


# ── 2. write_sentinel 契约 ──────────────────────────────────

class TestWriteSentinelContract:
    """write_sentinel 必须创建 .neurova_shutdown_sentinel 文件,含 pid 和 started_at。"""

    def test_write_sentinel_creates_file_with_correct_name(self, guard, temp_dir):
        """sentinel 文件名必须是 .neurova_shutdown_sentinel。"""
        guard.write_sentinel()
        sentinel = temp_dir / SENTINEL_NAME
        assert sentinel.exists(), "sentinel 文件应当被创建"

    def test_write_sentinel_contains_pid_and_started_at(self, guard, temp_dir):
        """sentinel 内容必须含 pid (>0) 和 started_at (ISO 字符串)。"""
        guard.write_sentinel()
        sentinel = temp_dir / SENTINEL_NAME
        data = json.loads(sentinel.read_text(encoding="utf-8"))

        assert "pid" in data, "缺少 pid 字段"
        assert "started_at" in data, "缺少 started_at 字段"
        assert isinstance(data["pid"], int) and data["pid"] > 0
        # started_at 应可被 datetime.fromisoformat 解析
        parsed = datetime.fromisoformat(data["started_at"])
        assert parsed.tzinfo is not None, "started_at 必须带时区"


# ── 3. mark_clean_shutdown 契约 ─────────────────────────────

class TestMarkCleanShutdownContract:
    """mark_clean_shutdown 必须删除 sentinel 文件(而非写入 clean_shutdown 状态)。"""

    def test_mark_clean_shutdown_removes_file(self, guard, temp_dir):
        """mark_clean_shutdown 后 sentinel 文件应不存在。"""
        guard.write_sentinel()
        sentinel = temp_dir / SENTINEL_NAME
        assert sentinel.exists()

        guard.mark_clean_shutdown()
        assert not sentinel.exists(), "clean shutdown 后 sentinel 文件应被删除"

    def test_mark_clean_shutdown_idempotent_when_no_sentinel(self, guard, temp_dir):
        """无 sentinel 时调用 mark_clean_shutdown 不应抛出异常。"""
        # 不写 sentinel 直接调用
        guard.mark_clean_shutdown()  # 不应抛出


# ── 4-6. check_abnormal_shutdown 契约 ───────────────────────

class TestCheckAbnormalShutdownContract:
    """check_abnormal_shutdown 返回 dict {abnormal: bool, crash_time: Optional[datetime]}。"""

    def test_no_sentinel_returns_not_abnormal(self, guard, temp_dir):
        """无 sentinel 文件时返回 {abnormal: False, crash_time: None}。"""
        result = guard.check_abnormal_shutdown()
        assert isinstance(result, dict)
        assert result["abnormal"] is False
        assert result["crash_time"] is None

    def test_existing_sentinel_returns_abnormal_with_crash_time(self, guard, temp_dir):
        """存在 sentinel(模拟崩溃)时返回 {abnormal: True, crash_time: <datetime>}。"""
        crash_time = datetime.now(timezone.utc) - timedelta(hours=1)
        sentinel = temp_dir / SENTINEL_NAME
        sentinel.write_text(json.dumps({
            "pid": 99999,
            "started_at": crash_time.isoformat(),
            "status": "running",
        }), encoding="utf-8")

        result = guard.check_abnormal_shutdown()
        assert result["abnormal"] is True
        assert result["crash_time"] is not None
        assert isinstance(result["crash_time"], datetime)
        # crash_time 应从 started_at 解析,误差 < 5 秒
        assert abs((result["crash_time"] - crash_time).total_seconds()) < 5

    def test_result_is_dict_not_bool(self, guard, temp_dir):
        """返回值必须是 dict,不能是 bool(回归测试)。"""
        result = guard.check_abnormal_shutdown()
        assert isinstance(result, dict), "check_abnormal_shutdown 必须返回 dict,不能是 bool"
        assert "abnormal" in result
        assert "crash_time" in result


# ── 7-9. flush_all_agent_buffers 契约 ───────────────────────

class TestFlushAllAgentBuffersContract:
    """flush_all_agent_buffers(agents) 返回 {agent_id: {flushed: int}, total_flushed: int}。"""

    def test_flush_calls_memory_manager_flush_buffer(self, guard):
        """对每个 agent 调用其 memory_manager.flush_buffer()。"""
        agent1 = MagicMock()
        agent1.config.agent_id = "agent_1"
        agent2 = MagicMock()
        agent2.config.agent_id = "agent_2"

        with patch.object(agent1, 'memory_manager', create=True) as mm1, \
             patch.object(agent2, 'memory_manager', create=True) as mm2:
            mm1.flush_buffer = MagicMock(return_value=3)
            mm2.flush_buffer = MagicMock(return_value=5)

            agents = {"agent_1": agent1, "agent_2": agent2}
            result = guard.flush_all_agent_buffers(agents)

            mm1.flush_buffer.assert_called_once()
            mm2.flush_buffer.assert_called_once()
            assert result["agent_1"]["flushed"] == 3
            assert result["agent_2"]["flushed"] == 5
            assert result["total_flushed"] == 8

    def test_flush_handles_missing_memory_manager(self, guard):
        """memory_manager=None 的 agent 被跳过,flushed=0。"""
        agent = MagicMock()
        agent.config.agent_id = "no_mem"
        agent.memory_manager = None

        agents = {"no_mem": agent}
        result = guard.flush_all_agent_buffers(agents)

        assert result["no_mem"]["flushed"] == 0
        assert result["total_flushed"] == 0

    def test_flush_handles_exception_without_blocking_others(self, guard):
        """单个 agent 抛异常不应阻塞其他 agent。"""
        agent1 = MagicMock()
        agent1.config.agent_id = "good_agent"
        agent2 = MagicMock()
        agent2.config.agent_id = "bad_agent"

        with patch.object(agent1, 'memory_manager', create=True) as mm1, \
             patch.object(agent2, 'memory_manager', create=True) as mm2:
            mm1.flush_buffer = MagicMock(return_value=10)
            mm2.flush_buffer = MagicMock(side_effect=RuntimeError("DB locked"))

            agents = {"good_agent": agent1, "bad_agent": agent2}
            result = guard.flush_all_agent_buffers(agents)

            assert result["good_agent"]["flushed"] == 10
            assert "error" in result["bad_agent"], "失败的 agent 应记录 error 字段"
            assert result["total_flushed"] == 10, "total_flushed 只统计成功的"

    def test_flush_returns_total_flushed_key(self, guard):
        """返回值必须含 total_flushed 键。"""
        result = guard.flush_all_agent_buffers({})
        assert "total_flushed" in result
        assert result["total_flushed"] == 0
