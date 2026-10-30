# -*- coding: utf-8 -*-
"""坏库首触的句柄泄漏（2026-10-31 收欠账批次的 PermissionError 根因）。

缺陷：`_create_connection` 的基线 PRAGMA 在坏库上抛错时，连接已建、
`_owned` 登记未执行——句柄脱离池追踪，`close_all_pools` 关不掉，
Windows 下该文件进程存活期内永远删不掉（files_store 清理撞 WinError 32）。
次生：`get_connection` 的空闲校验只捕 ProgrammingError，池内连接坏掉
（DatabaseError）时同样带着句柄走人。
"""
import os

import pytest


def test_corrupt_db_handle_released_after_pool_close(tmp_path):
    """坏库首触：借出必须诚实失败，且池关后文件可删（句柄不泄漏）。"""
    from neurova.core.database import close_all_pools, short_transaction

    db = tmp_path / "corrupt.db"
    db.write_bytes(b"not a sqlite db")
    with pytest.raises(Exception):
        with short_transaction(str(db)):
            pass  # 坏库不可用：首触失败必须如实上抛，不许吞成空结果
    close_all_pools()
    os.remove(str(db))  # 修前：WinError 32——泄漏的句柄锁死文件

