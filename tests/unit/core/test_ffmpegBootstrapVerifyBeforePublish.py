# -*- coding: utf-8 -*-
"""CORE-08：FFmpeg 下载件必须「私下校验通过后才发布并可执行」。

根因：`_download_to()` 先把下载件 `tmp.replace(dest)` 发布到托管可执行路径，
`ensure_ffmpeg()` 再对该路径跑 `-version` 校验；固定 `.part` 名还让并发下载
互相覆盖。下载污染或并发窗口因此会先得到一个可执行路径，再谈校验。

判据（真实 aiohttp 下载 + 真本地 HTTP 源）：
- 校验发生时，托管路径必须尚不存在（校验的是私有临时件，不是已发布件）；
- 校验失败不得留下任何可执行落点；
- 校验通过后才以原子换名发布。
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from neurova.core import ffmpeg


class _PayloadHandler(BaseHTTPRequestHandler):
    payload = b"not-an-ffmpeg-binary"
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *args):
        pass


@pytest.fixture()
def localSource(monkeypatch, tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PayloadHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv("NEUROVA_FFMPEG_URL", f"http://127.0.0.1:{server.server_address[1]}/ffmpeg")
        monkeypatch.setenv("NEUROVA_FFMPEG_SHA256", hashlib.sha256(_PayloadHandler.payload).hexdigest())
        monkeypatch.delenv("NEUROVA_FFMPEG_TAG", raising=False)
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.delenv("NEUROVA_FFMPEG_AUTODOWNLOAD", raising=False)
        monkeypatch.setenv("PATH", "")  # 不命中系统 ffmpeg
        managed = tmp_path / "tools" / "ffmpeg"
        monkeypatch.setattr(ffmpeg, "MANAGED_DIR", managed)
        yield managed
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def testHashMismatchNeverExecutesOrPublishes(localSource, monkeypatch):
    monkeypatch.setenv("NEUROVA_FFMPEG_SHA256", "00" * 32)
    executed = []

    def probe(path):
        executed.append(path)
        return True

    monkeypatch.setattr(ffmpeg, "_verify_binary", probe)

    assert await ffmpeg.ensure_ffmpeg() == ""
    assert executed == [], "哈希不匹配的下载件不得进入执行校验"
    assert not ffmpeg.managed_path().exists()
    assert list(localSource.iterdir()) == []


@pytest.mark.asyncio
async def testUnpinnedCustomBuildFailsClosed(localSource, monkeypatch):
    monkeypatch.setenv("NEUROVA_FFMPEG_TAG", "custom-build")
    monkeypatch.delenv("NEUROVA_FFMPEG_SHA256")
    executed = []

    def probe(path):
        executed.append(path)
        return True

    monkeypatch.setattr(ffmpeg, "_verify_binary", probe)

    assert await ffmpeg.ensure_ffmpeg() == ""
    assert executed == [], "没有可信哈希的自定义构建不得执行"
    assert not ffmpeg.managed_path().exists()
    assert not localSource.exists() or list(localSource.iterdir()) == []


@pytest.mark.asyncio
async def testVerificationRunsOnPrivateTempBeforePublish(localSource, monkeypatch):
    """校验时刻托管路径必须还不存在；失败后目录里不得留下可执行件。"""
    seen: dict = {}

    def probe(path):
        seen["path"] = Path(path)
        seen["published"] = ffmpeg.managed_path().exists()
        return False

    monkeypatch.setattr(ffmpeg, "_verify_binary", probe)

    assert await ffmpeg.ensure_ffmpeg() == ""

    assert seen["published"] is False, "校验前就已发布到可执行路径（CORE-08）"
    assert seen["path"] != ffmpeg.managed_path()
    assert not ffmpeg.managed_path().exists()
    assert list(localSource.iterdir()) == [], "校验失败后残留临时件"


@pytest.mark.asyncio
async def testVerifiedBinaryIsPublishedAtomically(localSource, monkeypatch):
    """校验通过后才发布：返回托管路径且内容与下载源一致。"""
    seen: dict = {}

    def probe(path):
        import os
        expected = os.environ["NEUROVA_FFMPEG_SHA256"]
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, (
            "执行 -version 前必须先通过可信 SHA256"
        )
        seen["path"] = Path(path)
        seen["published"] = ffmpeg.managed_path().exists()
        seen["content"] = Path(path).read_bytes()
        return True

    monkeypatch.setattr(ffmpeg, "_verify_binary", probe)

    result = await ffmpeg.ensure_ffmpeg()

    assert result == str(ffmpeg.managed_path())
    assert seen["published"] is False
    assert seen["content"] == _PayloadHandler.payload
    assert ffmpeg.managed_path().read_bytes() == _PayloadHandler.payload