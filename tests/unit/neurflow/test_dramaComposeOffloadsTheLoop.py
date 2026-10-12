# -*- coding: utf-8 -*-
"""`exec_video_compose` 的 concat 子进程不得占住事件循环（§6-93 同根余格，§6-98）。

`video-compose` 节点是 `async def`，其内 `subprocess.run(concat, timeout=300)` 裸调——
`Studio 导出` 那一发已在 `6c6b9cbd` 挪出循环，这一发是同一根因的另一条管线命中点。
判据取**协程心跳推进数**这个行为量，不测字符串存在、也不测"快不快"：改前那 0.3s 里
一次 await 点都没有，心跳推进 0 次；offload 到 `asyncio.to_thread` 后照常推进。

反向对照一格（`ffmpegStage` 未真被调用时心跳读数不作数）：节点在 `local_files` 为空或
ffmpeg 解析不到时会走 `slideshow_manifest` 降级支路，那条支路根本不碰子进程——
不先断"替身被调用过"，心跳为 0 也能被读成"判据没过"或"过了"，两种都误导。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_event_loop_keeps_running_during_the_concat(monkeypatch, tmp_path):
    import subprocess as _sp
    from neurova.collaboration.neurflow import drama_nodes as dn

    monkeypatch.setattr(dn, "_GEN_OUTPUT_DIR", tmp_path / "gens")
    calls = {"n": 0}

    class FakeProc:
        returncode = 0
        stderr = b""

    def slowConcat(cmd, **kw):
        calls["n"] += 1
        time.sleep(0.3)                    # 真 concat 的量级（一段几十秒的片子）
        Path(cmd[-1]).write_bytes(b"mp4")  # 模拟 ffmpeg 产出
        return FakeProc()

    monkeypatch.setattr(_sp, "run", slowConcat)
    # 让 resolve_ffmpeg_path 解析到一个真实存在的文件（它只做 stat + which，不跑子进程）
    fakeBin = tmp_path / "ffmpeg"
    fakeBin.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setenv("NEUROVA_FFMPEG_PATH", str(fakeBin))
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for c in clips:
        c.write_bytes(b"x")

    ticks = {"n": 0}

    async def ticker():
        while True:
            ticks["n"] += 1
            await asyncio.sleep(0.01)

    watcher = asyncio.create_task(ticker())
    try:
        before = ticks["n"]
        out = await dn.exec_video_compose({"clips": [str(c) for c in clips]}, {})
        advanced = ticks["n"] - before
    finally:
        watcher.cancel()

    assert out["output"].get("composed") is True, (
        f"节点没走到 concat 支路，下面的心跳读数不作数：{out['output'].get('mode')}")
    assert calls["n"] >= 1, "concat 子进程一次都没被调用——判据在空转"
    assert advanced >= 10, (
        f"concat 期间循环心跳只推进 {advanced} 次：阻塞调用仍占着事件循环，"
        "同进程内 chat 流式、别的长任务轮询与 recovery 定时任务全在排队")


@pytest.mark.asyncio
async def test_concat_still_produces_the_file_after_offload(monkeypatch, tmp_path):
    """offload 不许把产出弄丢：真出片那一支的 `video`/`video_url` 读数照旧。"""
    import subprocess as _sp
    from neurova.collaboration.neurflow import drama_nodes as dn

    monkeypatch.setattr(dn, "_GEN_OUTPUT_DIR", tmp_path / "gens")

    class FakeProc:
        returncode = 0
        stderr = b""

    def fakeConcat(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"mp4")
        return FakeProc()

    monkeypatch.setattr(_sp, "run", fakeConcat)
    fakeBin = tmp_path / "ffmpeg"
    fakeBin.write_bytes(b"#!/bin/sh\n")
    monkeypatch.setenv("NEUROVA_FFMPEG_PATH", str(fakeBin))
    clips = [tmp_path / "a.mp4", tmp_path / "b.mp4"]
    for c in clips:
        c.write_bytes(b"x")

    out = (await dn.exec_video_compose({"clips": [str(c) for c in clips]}, {}))["output"]
    assert out["mode"] == "ffmpeg_concat"
    assert Path(out["video"]).is_file(), "库里说成片在，磁盘上没有"
    assert out["video_url"].startswith("/api/v1/generation/files/")
