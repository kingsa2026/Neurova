"""C-21 回归测试：MobilePairingManager 线程安全、有界撤销表、安全随机码。

缺陷：
- _sessions/_by_pairing_id/_revoked_tokens 无锁并发访问；
- _revoked_tokens 为无界 set；
- 配对码用全局 random.choices（非 CSPRNG）。
"""

import threading
import time

from neurova.channels.mobile_pairing import MobilePairingManager


def test_lock_created_and_revoked_tokens_is_dict():
    mgr = MobilePairingManager()
    assert isinstance(mgr._lock, type(threading.RLock()))
    assert isinstance(mgr._revoked_tokens, dict)


def test_pairing_code_not_using_global_random(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("配对码不得使用全局 random.choices")

    monkeypatch.setattr("random.choices", boom)
    mgr = MobilePairingManager()
    session = mgr.generate_pairing_code("u1")
    assert len(session.code) == 6 and session.code.isdigit()


def test_revoked_token_expired_entries_pruned_on_add():
    mgr = MobilePairingManager(ttl_seconds=300)
    s1 = mgr.generate_pairing_code("u1")
    r1 = mgr.confirm_pairing(s1.code)
    assert mgr.revoke_pairing(s1.pairing_id, "u1") is True
    assert mgr.verify_ws_token(r1.ws_token) is None

    # 把第一条撤销记录改为已过期，再撤销第二个会话 → 过期项被顺带清理
    stale_token = r1.ws_token
    mgr._revoked_tokens[stale_token] = time.time() - 1
    s2 = mgr.generate_pairing_code("u2")
    r2 = mgr.confirm_pairing(s2.code)
    mgr.revoke_pairing(s2.pairing_id, "u2")

    assert stale_token not in mgr._revoked_tokens
    assert r2.ws_token in mgr._revoked_tokens


def test_revoked_token_value_is_retention_expiry():
    mgr = MobilePairingManager(ttl_seconds=300)
    s = mgr.generate_pairing_code("u1")
    r = mgr.confirm_pairing(s.code)
    before = time.time()
    mgr.revoke_pairing(s.pairing_id, "u1")
    expiry = mgr._revoked_tokens[r.ws_token]
    assert expiry > before  # 存的是"撤销过期时间"而非任意哨兵值


def test_concurrent_generate_produces_unique_codes():
    mgr = MobilePairingManager()
    codes = []
    lock = threading.Lock()

    def worker():
        local = [mgr.generate_pairing_code("u").code for _ in range(50)]
        with lock:
            codes.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(codes) == 400
    assert len(set(codes)) == 400


def test_concurrent_confirm_revoke_verify_smoke():
    mgr = MobilePairingManager(ttl_seconds=300)
    sessions = [mgr.generate_pairing_code(f"u{i}") for i in range(20)]
    errors = []

    def hammer():
        try:
            for s in sessions:
                mgr.confirm_pairing(s.code)
                mgr.list_user_pairings("u1")
                mgr.get_pairing_by_code(s.code)
                mgr.verify_ws_token("1:2:3:4")
                mgr.get_statistics()
                mgr.revoke_pairing(s.pairing_id, "u0")
        except Exception as e:  # noqa: BLE001 - 竞态冒烟：任何异常都算失败
            errors.append(e)

    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
