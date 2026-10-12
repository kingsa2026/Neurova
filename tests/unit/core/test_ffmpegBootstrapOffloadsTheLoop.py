# -*- coding: utf-8 -*-
"""FFmpeg 引导链的 `-version` 校验不得占住事件循环（§6-98，与 §6-93/§6-94 同根）。

一处**错误陈述的自纠**（登记在此免得下轮再信）：`resolve_ffmpeg_path()` 不做子进程探测——
它只有 `Path.is_file()` 与 `shutil.which()`，本机实测 **0.02–0.1ms**；跑 `-version` 的是
`_verify_binary()`（`core/ffmpeg.py:115`，`subprocess.run(timeout=20)`，实测 **42–45ms**），
而它被 `async def ensure_ffmpeg()` 直接调用。§6-93 原文与 §6-94 的"改法"格都把这两件事
混写成"`resolve_ffmpeg_path` 的 `-version` 探测"，本批把代码注释与台账一并改回实况。

判据取协程心跳推进数（同 `6c6b9cbd` 那一格的口径），并先断言校验替身被调用——
`ensure_ffmpeg()` 在"已可得"时早退，不进下载校验支路，那时心跳读数不作数。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_verifyBinary_doesNotBlockTheLoop(monkeypatch, tmp_path):
    from neurova.core import ffmpeg as fm

    calls = {"n": 0}
    monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
    monkeypatch.delenv("NEUROVA_FFMPEG_AUTODOWNLOAD", raising=False)
    monkeypatch.setattr(fm, "MANAGED_DIR", tmp_path / "tools" / "ffmpeg")
    # 三处解析口一律回"本机没有"，把执行体逼进下载 + 校验那一支
    monkeypatch.setattr(fm, "resolve_ffmpeg_path", lambda preferred="": "")
    monkeypatch.setattr(fm, "download_url_candidates", lambda: ["https://stub.local/ffmpeg-x"])

    async def fakeDownload(url, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-binary")
        return True

    def slowVerify(path) -> bool:
        calls["n"] += 1
        time.sleep(0.3)          # 真 `-version` 校验的量级（实测 42–45ms，取严一档）
        return True

    monkeypatch.setattr(fm, "_download_to", fakeDownload)
    monkeypatch.setattr(fm, "_verify_binary", slowVerify)

    ticks = {"n": 0}

    async def ticker():
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    watcher = asyncio.create_task(ticker())
    try:
        before = ticks["n"]
        resolved = await fm.ensure_ffmpeg()
        advanced = ticks["n"] - before
    finally:
        watcher.cancel()

    assert calls["n"] >= 1, (
        "校验一次都没跑（下载支路没进去）——下面那个心跳数是空的，判据在空转")
    assert resolved == str(fm.managed_path()), f"校验通过却没把就位路径回给调用方：{resolved!r}"
    assert Path(resolved).is_file(), f"说就位了却在盘上找不到：{resolved}"
    assert advanced >= 10, (
        f"`-version` 校验期间循环心跳只推进 {advanced} 次：`async def ensure_ffmpeg()` "
        "里同步调 `_verify_binary`，启动阶段整个循环停摆（服务此时已在接受请求）")


@pytest.mark.asyncio
async def test_verifyBinaryFailureLandsHonest(monkeypatch, tmp_path):
    """校验不过 ⇒ 丢弃半截件、诚实回空串（不谎报"已就位"），且不留 `.part`/假二进制。"""
    from neurova.core import ffmpeg as fm

    monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
    monkeypatch.delenv("NEUROVA_FFMPEG_AUTODOWNLOAD", raising=False)
    monkeypatch.setattr(fm, "MANAGED_DIR", tmp_path / "tools" / "ffmpeg")
    monkeypatch.setattr(fm, "resolve_ffmpeg_path", lambda preferred="": "")
    monkeypatch.setattr(fm, "download_url_candidates",
                        lambda: ["https://stub.local/a", "https://stub.local/b"])

    async def fakeDownload(url, dest: Path) -> bool:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"garbage")
        return True

    monkeypatch.setattr(fm, "_download_to", fakeDownload)
    monkeypatch.setattr(fm, "_verify_binary", lambda path: False)

    assert await fm.ensure_ffmpeg() == "", "校验不过却回了路径——调用方会以为 ffmpeg 可用"
    assert not fm.managed_path().exists(), "未通过校验的件没被丢弃"
    assert not list(tmp_path.rglob("*.part")), "半截 `.part` 文件残留"
