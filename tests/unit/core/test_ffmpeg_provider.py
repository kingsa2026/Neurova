# -*- coding: utf-8 -*-
"""批次5：FFmpeg 不打包，首次启动自动下载（core/ffmpeg 引导器）。

锁定契约（用户决策 2026-09-14）：
- 解析顺序：显式 preferred（节点 config.ffmpeg_path / env NEUROVA_FFMPEG_PATH）
  → 托管下载文件 data/tools/ffmpeg/ffmpeg(.exe) → 系统 PATH；
- 启动 bootstrap：三处全不可得才后台下载（npmmirror 镜像主源、GitHub
  ffmpeg-static release 回退；单文件直写免解压），系统已有 ffmpeg 时零下载；
- 下载后必须经 `-version` 真实校验才就位；任一源失败不炸服务（warning 留痕），
  compose 节点自动落 slideshow manifest 诚实降级；
- NEUROVA_FFMPEG_AUTODOWNLOAD=0 可关自动下载。
"""
from __future__ import annotations

import stat

import pytest

from neurova.core import ffmpeg as ff

pytestmark = pytest.mark.timeout(60)


class TestResolve:
    def test_preferred_first(self, tmp_path, monkeypatch):
        fake = tmp_path / "ffmpeg-custom"
        fake.write_text("x")
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        assert ff.resolve_ffmpeg_path(str(fake)) == str(fake)

    def test_env_path_second(self, tmp_path, monkeypatch):
        fake = tmp_path / "ffmpeg-env"
        fake.write_text("x")
        monkeypatch.setenv("NEUROVA_FFMPEG_PATH", str(fake))
        assert ff.resolve_ffmpeg_path("") == str(fake)

    def test_managed_third(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path)
        m = ff.managed_path()
        m.write_text("x")
        assert ff.resolve_ffmpeg_path("") == str(m)

    def test_path_fallback_and_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path / "nope")
        monkeypatch.setattr(ff.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        assert ff.resolve_ffmpeg_path("") == "/usr/bin/ffmpeg"
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        assert ff.resolve_ffmpeg_path("") == ""

    def test_nonexistent_preferred_falls_through(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path / "none")
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        assert ff.resolve_ffmpeg_path("/ghost/ffmpeg") == ""


class TestPlatformAssets:
    def test_suffix_mapping(self, monkeypatch):
        monkeypatch.setattr(ff.platform, "system", lambda: "Windows")
        monkeypatch.setattr(ff.platform, "machine", lambda: "AMD64")
        urls = ff.download_url_candidates()
        assert urls and "ffmpeg-win32-x64" in urls[0]
        assert any("registry.npmmirror.com" in u for u in urls)
        assert any("github.com" in u for u in urls)

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_FFMPEG_URL", "https://example.test/ffmpeg")
        assert ff.download_url_candidates() == ["https://example.test/ffmpeg"]


class TestEnsureDownload:
    @pytest.mark.asyncio
    async def test_skip_when_available(self, monkeypatch, tmp_path):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        # MANAGED_DIR 隔离（同 test_download_verifies_and_places 惯例）：否则
        # data/tools/ffmpeg 一旦有真实缓存（全量跑时可能触发真下载），本地
        # 缓存会短路 which 分支，本测试永远红
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path / "ffmpeg")
        monkeypatch.setattr(ff.shutil, "which", lambda _: "/usr/bin/ffmpeg")
        called = {"n": 0}

        async def spy(url, dest):
            called["n"] += 1

        monkeypatch.setattr(ff, "_download_to", spy)
        out = await ff.ensure_ffmpeg()
        assert out == "/usr/bin/ffmpeg"
        assert called["n"] == 0

    @pytest.mark.asyncio
    async def test_download_verifies_and_places(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path)

        async def fake_download(url, dest):
            dest.write_bytes(b"#!/bin/sh\necho fake")
            return True

        class P:
            returncode = 0

        runs = []

        def fake_run(cmd, **kw):
            runs.append(list(cmd))
            return P()

        monkeypatch.setattr(ff, "_download_to", fake_download)
        import subprocess as sp

        monkeypatch.setattr(sp, "run", fake_run)

        out = await ff.ensure_ffmpeg()
        assert out and ff.managed_path().is_file()
        assert out == str(ff.managed_path())
        assert runs and runs[0][0] == str(tmp_path) + __import__("os").sep + ff.BINARY_NAME
        # POSIX 可执行位
        if __import__("sys").platform != "win32":
            assert ff.managed_path().stat().st_mode & stat.S_IXUSR

    @pytest.mark.asyncio
    async def test_all_sources_fail_no_exception(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path / "deep")

        async def boom(url, dest):
            return False

        monkeypatch.setattr(ff, "_download_to", boom)
        out = await ff.ensure_ffmpeg()
        assert out == ""
        assert not ff.managed_path().exists()

    @pytest.mark.asyncio
    async def test_failed_verification_not_placed(self, tmp_path, monkeypatch):
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path)

        async def fake_download(url, dest):
            dest.write_bytes(b"garbage")
            return True

        class P:
            returncode = 1

        monkeypatch.setattr(ff, "_download_to", fake_download)
        import subprocess as sp

        monkeypatch.setattr(sp, "run", lambda *a, **k: P())
        out = await ff.ensure_ffmpeg()
        assert out == ""
        assert not ff.managed_path().exists()  # 校验失败绝不就位

    @pytest.mark.asyncio
    async def test_autodownload_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_FFMPEG_AUTODOWNLOAD", "0")
        monkeypatch.delenv("NEUROVA_FFMPEG_PATH", raising=False)
        monkeypatch.setattr(ff, "MANAGED_DIR", tmp_path / "none")
        monkeypatch.setattr(ff.shutil, "which", lambda _: None)
        out = await ff.ensure_ffmpeg()
        assert out == ""
