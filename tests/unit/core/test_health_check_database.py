# -*- coding: utf-8 -*-
"""database 健康检查真连库防回归（原为硬编码 (True, "SQLite OK") 假检查）。

app.py 的 _register_default_health_checks 之前注册的 database 检查是无条件
返回成功的 lambda——线上 DB 损坏时 /health 仍报绿。本测试锁定工厂
_make_database_health_check 的真连库语义。
"""
from pathlib import Path

from neurova.api.app import _make_database_health_check


def test_database_check_executes_real_query(tmp_path: Path):
    check = _make_database_health_check(str(tmp_path / "health.db"))
    ok, detail = check()
    assert ok is True
    # 详情须体现真实探测语义，而非静态 "SQLite OK"
    assert "select" in detail.lower()


def test_database_check_reports_failure(tmp_path: Path, monkeypatch):
    # 不可达目录 → sqlite 打不开文件 → (False, 含原因)
    check = _make_database_health_check(str(tmp_path / "missing_dir" / "x.db"))
    ok, detail = check()
    assert ok is False
    assert "database check failed" in detail

    # 再验证异常路径兜底（sqlite3.connect 是函数内 import，patch 标准库模块）
    import sqlite3 as sqlite3_mod

    check2 = _make_database_health_check(str(tmp_path / "ok.db"))

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(sqlite3_mod, "connect", boom)
    ok2, detail2 = check2()
    assert ok2 is False
    assert "db down" in detail2
