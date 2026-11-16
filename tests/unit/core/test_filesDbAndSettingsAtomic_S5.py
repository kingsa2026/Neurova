"""P2 §3.2-12 红灯：files.json 读改写无锁（并发丢更新）+ app_settings 裸 write_text。

- file_utils.save_file_metadata/delete_file_metadata：load → 改 → save 三步无锁，
  并发写丢更新；save_files_db 用 open("w") 直写（非 tmp+replace，读方可撞半截文件）。
- app_settings.save_app_settings:154 裸 write_text——对照 session_manager 的
  tmp+replace+fsync 范本。
修复判据：RMW 全程持模块锁；落盘走「先序列化后 tmp+os.replace」。
"""

import os
import threading
from pathlib import Path

import pytest

from neurova.core import app_settings, file_utils


def _twoThreads(fn_a, fn_b):
    errors = []

    def _run(fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - 线程异常收集到主线程断言
            errors.append(e)

    ta = threading.Thread(target=_run, args=(fn_a,))
    tb = threading.Thread(target=_run, args=(fn_b,))
    ta.start()
    tb.start()
    ta.join(timeout=10)
    tb.join(timeout=10)
    return errors


def test_concurrent_file_metadata_writes_do_not_lose_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(file_utils, "filesDbPath", lambda: tmp_path / "files.json")

    barrier = threading.Barrier(2)
    real_load = file_utils.load_files_db

    def barrierLoad():
        db = real_load()
        try:
            # 两线程都完成 load 后才放行——红：双方都看到空库，后写覆盖前写
            # 绿：模块锁串行化，第二个 load 进不来，屏障超时放行（串行后读已含前者）
            barrier.wait(timeout=1.0)
        except threading.BrokenBarrierError:
            pass
        return db

    monkeypatch.setattr(file_utils, "load_files_db", barrierLoad)

    errors = _twoThreads(
        lambda: file_utils.save_file_metadata("fa", {"name": "a"}),
        lambda: file_utils.save_file_metadata("fb", {"name": "b"}),
    )
    assert errors == []

    final = real_load()
    assert "fa" in final and "fb" in final, (
        f"并发 save_file_metadata 丢更新：files.json 只有 {sorted(final)}"
    )


def test_save_files_db_writes_via_atomic_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(file_utils, "filesDbPath", lambda: tmp_path / "files.json")

    real_replace = os.replace
    replace_calls = []

    def spyReplace(src, dst):
        replace_calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(file_utils.os, "replace", spyReplace)

    assert file_utils.save_files_db({"f1": {"name": "x"}}) is True
    assert replace_calls, "save_files_db 未走 tmp+os.replace 原子写（open('w') 直写会截断）"
    dst = replace_calls[0][1]
    assert dst.endswith("files.json"), f"原子替换目标不是 files.json 本体: {dst}"
    assert not list(tmp_path.glob("*.tmp")), "tmp 残留未清理"


def test_concurrent_app_settings_section_saves_do_not_lose_updates(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    app_settings.save_app_settings("base", {"seed": 1}, path=p)  # 建立基线文件

    barrier = threading.Barrier(2)
    real_read = Path.read_text

    def barrierRead(self, *args, **kwargs):
        result = real_read(self, *args, **kwargs)
        if self == p:
            try:
                barrier.wait(timeout=1.0)
            except threading.BrokenBarrierError:
                pass
        return result

    monkeypatch.setattr(Path, "read_text", barrierRead)

    errors = _twoThreads(
        lambda: app_settings.save_app_settings("a", {"x": 1}, path=p),
        lambda: app_settings.save_app_settings("b", {"y": 2}, path=p),
    )
    assert errors == []

    final = app_settings.load_app_settings(p)
    assert "a" in final and "b" in final, (
        f"并发 save_app_settings 丢 section：最终只有 {sorted(final)}"
    )
    assert final.get("base", {}).get("seed") == 1


def test_save_app_settings_writes_via_atomic_replace(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"

    real_replace = os.replace
    replace_calls = []

    def spyReplace(src, dst):
        replace_calls.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(app_settings.os, "replace", spyReplace)

    app_settings.save_app_settings("s", {"x": 1}, path=p)
    assert replace_calls, "save_app_settings 未走 tmp+os.replace 原子写（裸 write_text）"
    assert replace_calls[0][1].endswith("settings.json")
    assert not list(tmp_path.glob("*.tmp")), "tmp 残留未清理"
