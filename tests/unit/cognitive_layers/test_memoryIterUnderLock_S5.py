"""P2 §3.3-1 红灯：MemoryManager 锁外迭代 _memories（M-06 修复的漏网点）。

点名三处：get_emotion_timeline(:3281)、compress_low_value_memories 候选构建(:4795)、
get_memories_by_emotion(:4579)；按 M-06 注释口径全扫，漏网另有 _scoped_memories/
_agent_memories(:1505/:1514)、_ensure_content_index(:1580)、import 去重基集(:2535)、
retire 扫描(:2590)。并发 remember/forget 下 `.values()` 迭代撞 RuntimeError。
修复判据：全量读一律在 self._lock 内快照（`list(...)` 材料化也须持锁）。
钉法：_GuardedDict 在 values()/items() 调用瞬间检查 RLock 是否被当前线程持有，
锁外调用记违规——业务侧无论后续成败，违规列表非空即红。
"""

import threading

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import Memory


class _GuardedDict(dict):
    """在 values()/items() 调用瞬间校验 manager._lock 被当前线程持有。"""

    def __init__(self, guardLock, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._guardLock = guardLock
        self.violations = []

    def _check(self, caller):
        if not self._guardLock._is_owned():
            self.violations.append(caller)

    def values(self):
        self._check("values")
        return super().values()

    def items(self):
        self._check("items")
        return super().items()


class _GetGuardedDict(_GuardedDict):
    """额外覆盖 get()：用于钉 get_memories_by_emotion 的基集快照纪律。"""

    def get(self, key, default=None):
        self._check("get")
        return super().get(key, default)


def _makeManager(tmp_path, guarded_cls=_GuardedDict) -> tuple:
    manager = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="s5-agent",
        neuser_id="s5-neuser",
        user_id="s5-user",
    )
    for i in range(3):
        manager._memories[f"mem_{i}"] = Memory(
            id=f"mem_{i}", content=f"内容{i}", agent_id="s5-agent",
            neuser_id="s5-neuser", user_id="s5-user",
        )
    guarded = guarded_cls(manager._lock, dict(manager._memories))
    manager._memories = guarded
    return manager, guarded


def test_get_emotion_timeline_snapshots_under_lock(tmp_path):
    manager, guarded = _makeManager(tmp_path)
    try:
        manager.get_emotion_timeline()
    except Exception:  # noqa: BLE001 - 情绪模块缺席等业务异常不属本断言域
        pass
    assert guarded.violations == [], (
        f"get_emotion_timeline 锁外迭代 _memories（M-06 漏网）：{guarded.violations}"
    )


def test_scoped_and_agent_views_snapshot_under_lock(tmp_path):
    manager, guarded = _makeManager(tmp_path)
    try:
        manager._scoped_memories()
        manager._agent_memories()
    except Exception:  # noqa: BLE001
        pass
    assert guarded.violations == [], (
        f"_scoped_memories/_agent_memories 锁外迭代 _memories：{guarded.violations}"
    )


def test_get_memories_by_emotion_snapshots_under_lock(tmp_path):
    manager, guarded = _makeManager(tmp_path, _GetGuardedDict)
    try:
        manager.get_memories_by_emotion("happy")
    except Exception:  # noqa: BLE001
        pass
    assert guarded.violations == [], (
        f"get_memories_by_emotion 锁外读 _memories 基集：{guarded.violations}"
    )


def test_compress_candidates_snapshot_under_lock(tmp_path):
    manager, guarded = _makeManager(tmp_path)
    try:
        manager.compress_low_value_memories(dry_run=True)
    except Exception:  # noqa: BLE001
        pass
    assert guarded.violations == [], (
        f"compress_low_value_memories 候选构建锁外迭代 _memories：{guarded.violations}"
    )


def test_ensure_content_index_snapshots_under_lock(tmp_path):
    manager, guarded = _makeManager(tmp_path)
    manager._content_index_ready = False
    try:
        manager._ensure_content_index()
    except Exception:  # noqa: BLE001
        pass
    assert guarded.violations == [], (
        f"_ensure_content_index 锁外迭代 _memories：{guarded.violations}"
    )


def test_guard_works_as_expected():
    """钉子自检：锁外调用必须被记违规（防 _is_owned 判据失效的假绿）。"""
    lock = threading.RLock()
    guarded = _GuardedDict(lock)
    guarded["x"] = 1

    list(guarded.values())
    assert guarded.violations, "守卫未在锁外调用时记违规——判据失效"

    guarded.violations.clear()
    with lock:
        list(guarded.values())
    assert guarded.violations == [], "持锁调用被误记违规——判据过严"
