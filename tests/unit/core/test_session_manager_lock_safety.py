"""S3 + S4 线程安全 RED 测试 — SessionManager 锁缺陷

S3 (Critical #4): _get_file_lock TOCTOU 竞态
  _get_file_lock 用 check-then-act 模式:
    if key not in self._file_locks:      # Thread A: True (interleaved)
        self._file_locks[key] = Lock()  # Thread B: True → 创建 Lock2 覆盖 Lock1
    return self._file_locks[key]        # 两线程拿到不同 Lock → 文件竞态
  修复: 引入 _file_locks_lock (RLock) + 双重检查锁定 (DCL)

S4 (Critical #5): add_message 跨锁边界 read-modify-write
  add_message 流程:
    session_data = self._read_session_file(file_path)  # READ (无锁!)
    session_data["messages"].extend(new_messages)       # MODIFY (无锁!)
    self._write_session_file(file_path, session_data)   # WRITE (有锁,但只锁 write)
  竞态: Thread A read → Thread B read → A write → B write (B 丢失 A 的更新)
  修复: RMW 整体入 file_lock,新增 _write_session_file_unlocked 避免重入死锁

参考: project_memory "CPython 3.15 GIL 行为变化让简单竞态测试不可靠",
      用静态契约 + 不变量断言替代竞态触发断言.
"""
from __future__ import annotations

import inspect
import threading
from pathlib import Path
from threading import RLock
from unittest.mock import MagicMock, patch

import pytest

from neurova.session_manager import SessionManager


# ── Fixtures ────────────────────────────────────────────


@pytest.fixture
def fresh_manager(tmp_path: Path) -> SessionManager:
    """创建非单例 SessionManager, sessions_dir 指向 tmp_path.

    手动初始化所有 __init__ 会设置的属性 (绕过单例),包括 S3 的 _file_locks_lock.
    """
    mgr = SessionManager.__new__(SessionManager)
    mgr._sessions_dir = tmp_path
    mgr._sessions_dir.mkdir(exist_ok=True)
    mgr._file_locks = {}
    # S3: 与 __init__ 保持一致,初始化 _file_locks_lock
    mgr._file_locks_lock = RLock()
    return mgr


# ════════════════════════════════════════════════════════════
# S3: _get_file_lock TOCTOU 修复
# ════════════════════════════════════════════════════════════


class TestS3FileLocksTOCTOU:
    """S3: _file_locks dict 应由独立 RLock 保护,防止 TOCTOU 竞态."""

    def test_file_locks_lock_attribute_exists(self):
        """RED: SessionManager 单例应有 _file_locks_lock 属性 (由 __init__ 创建)."""
        # 用真实单例 (而非 fresh_manager) 验证 __init__ 契约
        mgr = SessionManager()
        assert hasattr(mgr, "_file_locks_lock"), (
            "S3: SessionManager.__init__ 应创建 _file_locks_lock 属性. "
            "BUG: _get_file_lock 用 check-then-act 模式,无独立锁保护 → TOCTOU."
        )

    def test_file_locks_lock_is_rlock(self):
        """RED: _file_locks_lock 应是 RLock (允许 _get_file_lock 内部重入)."""
        mgr = SessionManager()
        if not hasattr(mgr, "_file_locks_lock"):
            pytest.skip("S3 fix not yet applied (_file_locks_lock missing)")
        rlock = threading.RLock()
        assert isinstance(mgr._file_locks_lock, type(rlock)), (
            f"S3: _file_locks_lock 应是 RLock, got {type(mgr._file_locks_lock)}. "
            "RLock 允许 _get_file_lock 在持锁时重入 (如 __init__ 内调用)."
        )

    def test_get_file_lock_uses_protection_lock(self):
        """RED: _get_file_lock 源码应使用 _file_locks_lock 或 setdefault."""
        source = inspect.getsource(SessionManager._get_file_lock)
        # 修复后应包含 DCL 模式或 setdefault
        has_protection = (
            "_file_locks_lock" in source
            or "setdefault" in source
        )
        assert has_protection, (
            "S3: _get_file_lock 应使用 _file_locks_lock (DCL) 或 dict.setdefault 保护. "
            "BUG: 当前用 `if key not in dict: dict[key] = Lock()` check-then-act → TOCTOU."
        )

    def test_get_file_lock_idempotent_single_thread(self, fresh_manager):
        """契约: 同一 file_path 多次调用应返回同一 Lock 实例 (单线程基线)."""
        # 跳过 fresh_manager (没有 _file_locks_lock), 用真实单例
        mgr = SessionManager()
        lock1 = mgr._get_file_lock("/test/s3/path")
        lock2 = mgr._get_file_lock("/test/s3/path")
        assert lock1 is lock2, (
            "同一 path 应返回同一 Lock 实例. "
            f"Got {lock1!r} vs {lock2!r}"
        )


# ════════════════════════════════════════════════════════════
# S4: add_message 跨锁 read-modify-write 修复
# ════════════════════════════════════════════════════════════


class TestS4AddMessageAtomicRMW:
    """S4: add_message 应将 read-modify-write 整体置于 file_lock 内."""

    def test_write_session_file_unlocked_exists(self):
        """RED: SessionManager 应有 _write_session_file_unlocked 方法."""
        # S4 修复前: 只有 _write_session_file (会获取锁)
        # S4 修复后: 新增 _write_session_file_unlocked (不获取锁,调用方已持锁)
        assert hasattr(SessionManager, "_write_session_file_unlocked"), (
            "S4: SessionManager 应有 _write_session_file_unlocked 方法. "
            "BUG: add_message 调 _write_session_file 会重新获取 file_lock, "
            "而 Lock 不可重入 → 死锁. 需要 unlocked 版本供持锁调用方使用."
        )

    def test_add_message_calls_unlocked_write(self):
        """RED: add_message 源码应调 _write_session_file_unlocked (非 _write_session_file)."""
        source = inspect.getsource(SessionManager.add_message)
        assert "_write_session_file_unlocked" in source, (
            "S4: add_message 应调用 _write_session_file_unlocked (持锁写入). "
            "BUG: 当前调用 _write_session_file,read 在锁外,write 在锁内 → RMW 跨锁边界."
        )

    def test_add_message_acquires_file_lock_before_read(self):
        """RED: add_message 源码应在 _read_session_file 之前获取 file_lock."""
        source = inspect.getsource(SessionManager.add_message)
        # 查找 file_lock 获取位置 vs _read_session_file 调用位置
        lock_pos = source.find("with file_lock")
        read_pos = source.find("_read_session_file")
        assert lock_pos != -1, (
            "S4: add_message 应在方法内获取 file_lock (`with file_lock:`). "
            "BUG: 当前 read 无锁保护."
        )
        assert lock_pos < read_pos, (
            "S4: file_lock 获取应在 _read_session_file 之前. "
            f"lock_pos={lock_pos}, read_pos={read_pos}. "
            "BUG: read 在锁外 → read-modify-write 跨锁边界 → lost update."
        )

    def test_add_message_releases_lock_after_write(self):
        """RED: add_message 应在 _write_session_file_unlocked 之后释放 file_lock."""
        source = inspect.getsource(SessionManager.add_message)
        # with file_lock 块应包含 read + modify + write 全部
        lock_start = source.find("with file_lock")
        assert lock_start != -1, "S4: 应有 `with file_lock:` 块"
        # with 块的缩进
        with_line_end = source.find("\n", lock_start)
        indent = len(source[lock_start:]) - len(source[lock_start:].lstrip())
        # 找到 with 块结束 (缩进回到 with 之前)
        after_with = source[with_line_end + 1 :]
        for line in after_with.split("\n"):
            if line.strip() and not line.startswith(" " * (indent + 1)):
                # with 块结束
                block_end = with_line_end + 1 + after_with.find(line)
                break
        else:
            block_end = len(source)
        block = source[lock_start:block_end]
        assert "_write_session_file_unlocked" in block, (
            "S4: _write_session_file_unlocked 应在 `with file_lock:` 块内. "
            "BUG: write 在锁外."
        )
        assert "_read_session_file" in block, (
            "S4: _read_session_file 应在 `with file_lock:` 块内. "
            "BUG: read 在锁外."
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
