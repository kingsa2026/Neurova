"""s8 TDD: _private_skills / _public_skills 加 RLock 保护

背景:
- AGENTS.md 规定 "Thread safety: use threading.RLock for shared state"
- _private_skills / _public_skills 是模块级共享 dict, create/update/delete
  进行 read-modify-write, 多线程部署 (uvicorn --threads N) 会有 TOCTOU race
- 当前 async def 无 await 点, 单事件循环线程内原子, 但违反防御性规范

契约:
1. skill_pool_api 模块应有 _lock 属性, 类型为 threading.RLock
2. create/update/delete 临界区应在 with _lock: 内 (静态契约)
3. list 端点也应用 _lock 保护读
"""

import inspect
import threading

import pytest


def test_skill_pool_api_has_rlock():
    """s8.1: skill_pool_api 模块应有 _lock 属性, 类型为 RLock"""
    from neurova.api.endpoints import skill_pool_api as mod

    assert hasattr(mod, "_lock"), "skill_pool_api 应有 _lock 保护共享状态"
    # RLock 可重入; Lock 不可重入. RLock 实例 acquire() 后再 acquire() 不死锁
    assert isinstance(mod._lock, type(threading.RLock())), (
        f"_lock 应为 RLock 类型 (可重入), 实际: {type(mod._lock)}"
    )


def test_create_private_skill_uses_lock():
    """s8.2 静态契约: create_private_skill 应在 with _lock: 内写 _private_skills"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.create_private_skill)
    assert "with _lock" in src or "with mod._lock" in src, (
        "create_private_skill 应在 with _lock: 内写入 _private_skills"
    )


def test_update_private_skill_uses_lock():
    """s8.3 静态契约: update_private_skill 应在 with _lock: 内 read-modify-write"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.update_private_skill)
    assert "with _lock" in src or "with mod._lock" in src, (
        "update_private_skill 应在 with _lock: 内 read-modify-write"
    )


def test_delete_private_skill_uses_lock():
    """s8.4 静态契约: delete_private_skill 应在 with _lock: 内删除"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.delete_private_skill)
    assert "with _lock" in src or "with mod._lock" in src, (
        "delete_private_skill 应在 with _lock: 内删除 _private_skills[sid]"
    )


def test_list_private_skills_uses_lock():
    """s8.5 静态契约: list_private_skills 应在 with _lock: 内读 _private_skills"""
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(mod.list_private_skills)
    assert "with _lock" in src or "with mod._lock" in src, (
        "list_private_skills 应在 with _lock: 内读 _private_skills (防止迭代时被并发修改)"
    )


def test_lock_is_rlock_not_lock():
    """s8.6 类型断言: _lock 必须是 RLock, 不能是 Lock

    Lock 不可重入, 若某方法持锁后调用同对象另一个持锁方法会死锁.
    RLock 可重入, 安全.
    """
    from neurova.api.endpoints import skill_pool_api as mod

    if not hasattr(mod, "_lock"):
        pytest.skip("_lock 不存在, s8.1 已暴露")

    lock = mod._lock
    # RLock.acquire() 后再次 acquire() 不死锁
    acquired1 = lock.acquire(blocking=False)
    acquired2 = lock.acquire(blocking=False)
    if acquired1:
        lock.release()
    if acquired2:
        lock.release()
    assert acquired1 and acquired2, (
        "_lock 必须是 RLock (可重入). Lock 第二次 acquire 会阻塞/失败. "
        f"acquired1={acquired1}, acquired2={acquired2}"
    )
