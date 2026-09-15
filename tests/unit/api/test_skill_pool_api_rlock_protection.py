"""s8 TDD（历史）→ Wave F 契约演化：并发保护面从 API 内存 dict 下沉到 SkillService

历史 (s8): _private_skills / _public_skills 模块级共享 dict 多线程 read-modify-write
TOCTOU → 加模块级 RLock。

Wave F (2026-09-15): private 链落 SkillService manifest——API 层不再有 private
共享内存态，锁语义由 SkillService._lock（RLock）+ 原子写承载；模块级 _lock
仍保护存量的 _public_skills（公共演示轨）。本文件断言随之演化：
  1. 模块 _lock 仍在且为 RLock（public 轨）；
  2. private CRUD 源码不再引用 _private_skills（内存轨已废除）；
  3. private 链的并发保护验证下沉到 SkillService（register/update/uninstall
     源码 with self._lock 静态断言）。
"""

import inspect
import threading

import pytest


def test_skill_pool_api_has_rlock():
    """s8.1 保持: 模块仍有 _lock（现服务 _public_skills 轨）。"""
    from neurova.api.endpoints import skill_pool_api as mod

    assert hasattr(mod, "_lock"), "skill_pool_api 应有 _lock 保护共享状态"
    assert isinstance(mod._lock, type(threading.RLock()))


def test_lock_is_rlock_not_lock():
    """s8.6 保持: _lock 必须可重入。"""
    from neurova.api.endpoints import skill_pool_api as mod

    lock = mod._lock
    a1 = lock.acquire(blocking=False)
    a2 = lock.acquire(blocking=False)
    if a1:
        lock.release()
    if a2:
        lock.release()
    assert a1 and a2, "_lock 必须是 RLock（可重入）"


@pytest.mark.parametrize(
    "fn_name",
    ["list_private_skills", "create_private_skill", "update_private_skill", "delete_private_skill"],
)
def test_private_chain_no_longer_touches_memory_dict(fn_name):
    """Wave F: private 链不得再引用 _private_skills（双轨合一的静态护栏）。

    用访问式模式检查（`_private_skills[` / `_private_skills.`）——裸子串会被
    函数名 list_private_skills 自身误撞。
    """
    from neurova.api.endpoints import skill_pool_api as mod

    src = inspect.getsource(getattr(mod, fn_name))
    assert "_private_skills[" not in src and "_private_skills." not in src, (
        f"{fn_name} 不应再读写已废除的内存 dict——单源=SkillService manifest"
    )


@pytest.mark.parametrize(
    "method_name",
    ["register_auto_skill", "update_auto_skill", "uninstall_skill", "install_skill"],
)
def test_skill_service_critical_sections_hold_rlock(method_name):
    """Wave F 并发契约下沉: SkillService 读改写临界区必须 with self._lock。"""
    from neurova.skills.skill_service import SkillService

    src = inspect.getsource(getattr(SkillService, method_name))
    assert "with self._lock" in src, (
        f"{method_name} 必须在 self._lock 内做 read-modify-write（API 层已把"
        "并发保护责任交给服务层）"
    )
