# -*- coding: utf-8 -*-
"""P1-2 连接池满池级联停摆红测（全库断点审计 2026-11-12）

缺陷（connection_pool.py get_connection 满池分支）：
1. 满池时在**持有 `_lock` 的状态下** `_pool.get(timeout=30)` 等归还——
   归还方 `return_connection` 的归属校验/借出注销需要同一把锁，于是
   "等归还"把所有归还路径卡死，整池 30 秒级联停摆后才抛超时；
2. 配额判定（锁内 `created_count >= max`）与建连（锁外）分离，
   check-then-act 非原子——并发首爆可超限建连。

修复口径（审计开方）：满池等待移出锁外（锁内只做判定/登记），
配额锁内原子预留（建连失败回滚），满池借出的连接走与快路径同一套
SELECT 1 校验＋PRAGMA 复原。
"""
import threading
import time

import pytest

from neurova.core.connection_pool import SQLiteConnectionPool


def test_full_pool_wait_does_not_block_return(tmp_path):
    """满池等待方不得持锁阻塞归还路径：归还须即时完成，等待方须拿到连接。"""
    pool = SQLiteConnectionPool(str(tmp_path / "p1.db"), max_connections=1, timeout=3.0)
    conn_a = pool.get_connection()  # 借出唯一连接 → 进入满池态

    borrower_result = {}

    def borrower():
        try:
            borrower_result["conn"] = pool.get_connection()
        except Exception as exc:  # 红态：等满 3s 后 RuntimeError
            borrower_result["error"] = exc

    waiter = threading.Thread(target=borrower, daemon=True)
    waiter.start()
    time.sleep(0.3)  # 让等待方先进入满池等待分支

    t0 = time.monotonic()
    returned = pool.return_connection(conn_a)
    return_elapsed = time.monotonic() - t0
    waiter.join(timeout=6.0)

    assert returned is True
    assert return_elapsed < 1.0, (
        f"归还被满池等待方持锁阻塞 {return_elapsed:.2f}s（级联停摆根因未除）"
    )
    assert "conn" in borrower_result, (
        f"等待方应拿到归还的连接而非超时：{borrower_result.get('error')}"
    )


def test_concurrent_burst_respects_max_connections(tmp_path):
    """配额判定须原子：并发首爆时池内连接总数不得越过 max_connections。"""
    pool = SQLiteConnectionPool(str(tmp_path / "p2.db"), max_connections=2, timeout=5.0)
    workers = 4
    barrier = threading.Barrier(workers)
    peak_samples = []
    sample_lock = threading.Lock()

    def grab_and_return():
        barrier.wait()
        conn = pool.get_connection()
        with sample_lock:
            peak_samples.append(pool.total_count)
        time.sleep(0.05)  # 短暂持有，制造竞争窗口
        pool.return_connection(conn)

    threads = [threading.Thread(target=grab_and_return, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert len(peak_samples) == workers, "所有借用者都应拿到连接"
    assert max(peak_samples) <= pool.max_connections, (
        f"并发首爆超限建连：峰值 total_count={max(peak_samples)} > max={pool.max_connections}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
