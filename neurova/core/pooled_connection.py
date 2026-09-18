"""池化连接句柄：把 `conn.close()` 语义重定向为"归还池"（P1-4 迁移用）

背景（ADR 0014）：把"短连接"迁进池时，最难的不是换 `sqlite3.connect()`，
而是原来的调用方**各自散落 `conn.close()`**（rbac 15 处 + 数十个早退/异常
分支、user_model 19 处、qclaw_binding 13 处）。手工把这些方法集体改成
`with` 上下文，改动面大、缩进重排易错，而漏改一处就是池连接只增不减。

本模块换一条低风险路径：`_get_conn()` 返回一个**委托句柄**，

- 读/写/执行全部透传到真实 `sqlite3.Connection`（`__getattr__` / `__setattr__`）；
- 调用方原有的 `conn.close()` 被重定向为"归还池"，不是真关闭；
- 忘记 `close()` 时由 `__del__` 兜底归还（原裸连接写法也要等 GC 回收
  文件句柄，故这不是新增负担，只是把回收动作变成"归还而非丢弃"）。

于是迁移只要改 `_get_conn()` 一行，散落的 close 点全部变成正确归还 ——
既拿池化收益，也不引入"漏归还即阻塞"的新失败模式。

`row_factory` 等属性赋值走 `__setattr__` 委托（池连接已设 `sqlite3.Row`，
这些赋值是幂等的冗余，但语义必须保持一致）。
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class PooledConnection:
    """懒借出的池化连接句柄（首次使用时才真正借出）。

    懒借出很关键：`_get_conn()` 在有些调用点只是构造连接、随后并未使用
    （早退分支），若立即借出就需要归还；懒借出把"没用到"变成零成本。
    """

    __slots__ = ("_db_path", "_conn", "_released", "_lock")

    def __init__(self, db_path: str):
        object.__setattr__(self, "_db_path", str(db_path))
        object.__setattr__(self, "_conn", None)
        object.__setattr__(self, "_released", False)
        object.__setattr__(self, "_lock", threading.RLock())

    # ── 借出 / 归还 ────────────────────────────────────────────

    def _ensure(self) -> sqlite3.Connection:
        conn = self._conn
        if conn is None:
            from neurova.core.database import get_short_connection

            conn = get_short_connection(self._db_path)
            object.__setattr__(self, "_conn", conn)
        return conn

    def close(self) -> None:
        """归还池（不是真的关闭连接）。幂等。"""
        with self._lock:
            if self._released:
                return
            object.__setattr__(self, "_released", True)
            conn = self._conn
            object.__setattr__(self, "_conn", None)
        if conn is None:
            return
        try:
            from neurova.core.database import release_short_connection

            release_short_connection(conn)
        except Exception:  # noqa: BLE001 - 归还失败降级为真关闭
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def __del__(self):
        """兜底归还：未显式 close 即在此回收（等价于裸写法的 GC 回收）。"""
        try:
            if self._conn is not None and not self._released:
                self.close()
        except Exception:  # noqa: BLE001 - 解释器收尾期不抛
            pass

    # ── 完全委托 ──────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ensure(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("_db_path", "_conn", "_released", "_lock"):
            object.__setattr__(self, name, value)
            return
        setattr(self._ensure(), name, value)

    def __enter__(self):
        # 保留 `with conn:` 的事务语义（sqlite3.Connection.__enter__ 返回自身，
        # 此处必须返回**委托句柄**，否则 with 块内的变量会变成裸连接，
        # 出口的 commit 照做、但块内 close 就不再归还）
        self._ensure().__enter__()
        return self

    def __exit__(self, *exc_info):
        return self._ensure().__exit__(*exc_info)

    def __repr__(self) -> str:
        return f"PooledConnection(db={self._db_path!r}, released={self._released})"
