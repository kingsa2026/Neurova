# -*- coding: utf-8 -*-
"""FFmpeg 引导器（批次5，用户决策：不打包，首次启动自动下载）。

Neurova 安装包不含 FFmpeg（打包包含项属用户硬约束决策）；一键成片的真合成
依赖 ffmpeg 二进制。本模块提供：

- ``resolve_ffmpeg_path(preferred)``：解析可用 ffmpeg——显式路径 >
  env NEUROVA_FFMPEG_PATH > 托管下载件（data/tools/ffmpeg/）> 系统 PATH；
- ``ensure_ffmpeg()``：三处全不可得才从官方 ffmpeg-static 构建下载单文件
  （免解压），主源 npmmirror（国内可达），回退 GitHub release；
  下载后必须经 ``-version`` 真实校验才移入托管目录——校验失败绝不就位；
- ``start_ffmpeg_bootstrap()``：随服务启动的后台任务（不阻塞启动路径，
  系统已有 ffmpeg 时零下载零网络）；NEUROVA_FFMPEG_AUTODOWNLOAD=0 可关。

任一环节失败只 warning 留痕，不炸服务：compose 节点自动落 slideshow
manifest 诚实降级（见 collaboration/neurflow/drama_nodes.py）。
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
import stat
import subprocess
from pathlib import Path
from typing import List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANAGED_DIR = PROJECT_ROOT / "data" / "tools" / "ffmpeg"

BINARY_NAME = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"

# ffmpeg-static 构建版本（asset 命名 ffmpeg-<platform>-<arch>，单文件可执行）
DEFAULT_TAG = "b6.0"
_MIRROR_TMPL = f"https://registry.npmmirror.com/-/binary/ffmpeg-static/{{tag}}/ffmpeg-{{asset}}"
_GITHUB_TMPL = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{{tag}}/ffmpeg-{{asset}}"


def managed_path() -> Path:
    return MANAGED_DIR / BINARY_NAME


def _asset_name() -> str:
    sysname = platform.system()
    machine = (platform.machine() or "").lower()
    if sysname == "Windows":
        return "win32-arm64" if "arm" in machine else "win32-x64"
    if sysname == "Darwin":
        return "darwin-arm64" if machine == "arm64" else "darwin-x64"
    return "linux-arm64" if machine in ("arm64", "aarch64") else "linux-x64"


def download_url_candidates() -> List[str]:
    """下载源列表（env NEUROVA_FFMPEG_URL 可整体覆盖为单一源）。"""
    override = (os.environ.get("NEUROVA_FFMPEG_URL") or "").strip()
    if override:
        return [override]
    tag = (os.environ.get("NEUROVA_FFMPEG_TAG") or DEFAULT_TAG).strip() or DEFAULT_TAG
    asset = _asset_name()
    return [_MIRROR_TMPL.format(tag=tag, asset=asset), _GITHUB_TMPL.format(tag=tag, asset=asset)]


def _is_exec_file(p: str) -> bool:
    try:
        return bool(p) and Path(p).is_file()
    except OSError:
        return False


def resolve_ffmpeg_path(preferred: str = "") -> str:
    """解析当前可用的 ffmpeg 可执行路径；不可得返回空串。"""
    for cand in (
        preferred,
        (os.environ.get("NEUROVA_FFMPEG_PATH") or "").strip(),
        str(managed_path()),
    ):
        if _is_exec_file(cand):
            return cand
    found = shutil.which("ffmpeg")
    return found or ""


async def _download_to(url: str, dest: Path) -> bool:
    """流式下载单文件到 dest；HTTP 异常/中断返回 False（不留半截文件）。"""
    import aiohttp

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        timeout = aiohttp.ClientTimeout(total=900, sock_read=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    logger.warning("FFmpeg 下载源 HTTP %s: %s", resp.status, url)
                    return False
                with open(tmp, "wb") as f:
                    async for chunk in resp.content.iter_chunked(1 << 20):
                        f.write(chunk)
        tmp.replace(dest)
        return True
    except Exception as e:  # noqa: BLE001 — 单源失败换下一候选
        logger.warning("FFmpeg 下载失败(%s): %s", url, e)
        tmp.unlink(missing_ok=True)
        return False


def _verify_binary(path: Path) -> bool:
    """下载件真实校验：-version 可执行且返回 0，否则视为无效。"""
    try:
        proc = subprocess.run([str(path), "-version"], capture_output=True, timeout=20, check=False)
        return proc.returncode == 0
    except Exception as e:  # noqa: BLE001
        logger.warning("FFmpeg 校验执行失败: %s", e)
        return False


_download_lock: Optional[asyncio.Lock] = None


async def ensure_ffmpeg() -> str:
    """确保 ffmpeg 可得：已可得直接返回；否则自动下载（幂等、单飞锁）。

    Returns:
        可用 ffmpeg 路径；不可得/被禁用时返回空串（调用侧诚实降级）。
    """
    if (os.environ.get("NEUROVA_FFMPEG_AUTODOWNLOAD") or "").strip() == "0":
        return resolve_ffmpeg_path()

    existing = resolve_ffmpeg_path()
    if existing:
        return existing

    global _download_lock
    if _download_lock is None:
        _download_lock = asyncio.Lock()
    async with _download_lock:
        existing = resolve_ffmpeg_path()  # 等锁期间可能已有并发下载完成
        if existing:
            return existing
        MANAGED_DIR.mkdir(parents=True, exist_ok=True)
        for url in download_url_candidates():
            logger.info("FFmpeg 不在本机，开始下载（%s）…", url)
            target = managed_path()
            if not await _download_to(url, target):
                continue
            try:
                target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            except OSError:
                pass
            if _verify_binary(target):
                size_mb = target.stat().st_size / (1 << 20)
                logger.info("FFmpeg 下载完成并通过校验：%s（%.1f MB）", target, size_mb)
                return str(target)
            logger.warning("FFmpeg 下载文件未通过 -version 校验，丢弃：%s", url)
            target.unlink(missing_ok=True)
        logger.warning("FFmpeg 自动下载失败（全部候选源），成片合成将降级为连播清单")
        return ""


_bootstrap_task: Optional[asyncio.Task] = None


def start_ffmpeg_bootstrap() -> Optional[asyncio.Task]:
    """服务启动挂钩：后台确保 ffmpeg（系统已有则零下载；不阻塞启动事件循环）。"""
    global _bootstrap_task
    if _bootstrap_task is not None and not _bootstrap_task.done():
        return _bootstrap_task
    if (os.environ.get("NEUROVA_FFMPEG_AUTODOWNLOAD") or "").strip() == "0":
        return None
    if resolve_ffmpeg_path():
        logger.info("FFmpeg 已可用：%s", resolve_ffmpeg_path())
        return None

    async def _bg() -> None:
        await ensure_ffmpeg()

    _bootstrap_task = asyncio.create_task(_bg(), name="ffmpeg-bootstrap")
    logger.info("FFmpeg 首次启动自动下载已排队（后台，不阻塞服务）")
    return _bootstrap_task


# ── A5：字幕烧录支撑（subtitles filter 转义 / 中文字体探测 / 两步烧录）──

_CJK_FONT_NAMES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc",
                   "simfang.ttf", "NotoSansCJKsc-Regular.otf", "NotoSansCJK-Regular.ttc")


def escape_subtitles_path(p) -> str:
    """subtitles filter 的 filename 转义（实测 ffmpeg b6.0 多形态对照）：
    反斜杠→正斜杠 + 冒号转义为 ``\\:``——filter 层以未转义 ``:`` 分参数，
    盘符 ``E:`` 会被截成 ``E``（报 "parse as image size" 的假 Invalid argument）；
    外层单引号保护空格。含单引号会破坏引号结构，诚实拒绝（ValueError）
    而非拼出错误命令——Studio 生成名可控，出现即异常。"""
    s = str(p).replace("\\", "/")
    if "'" in s:
        raise ValueError(f"字幕路径含单引号，拒绝烧录: {s}")
    return s.replace(":", "\\:")


def _cjk_font_candidates() -> List[Path]:
    """各平台常见中文字体路径（纯文件探测，不依赖 fc-list——pf1 教训：
    无中文字体时烧录只会得到方框假成功，必须先探测再决定烧或不烧）。"""
    if os.name == "nt":
        fonts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Fonts"
        return [fonts / n for n in _CJK_FONT_NAMES]
    if platform.system() == "Darwin":
        return [Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/System/Library/Fonts/Supplemental/Songti.ttc")]
    hits: List[Path] = []
    for root in ("/usr/share/fonts", "/usr/local/share/fonts"):
        if not os.path.isdir(root):
            continue
        for f in Path(root).rglob("*"):
            name = f.name.lower()
            if f.suffix in (".ttc", ".ttf", ".otf") and any(
                    k in name for k in ("cjk", "wenquanyi", "wqy", "sourcehan", "notosans")):
                hits.append(f)
    return hits


def has_cjk_font() -> bool:
    return any(p.is_file() for p in _cjk_font_candidates())


def burn_subtitles(ffmpeg: str, in_path, srt_path, out_path,
                   timeout: int = 600) -> "tuple[bool, str]":
    """第二步烧录：``-i in -vf subtitles=<esc> -c:a copy out``。
    失败不抛（调用方回退无字幕成片 + warning），返回 (ok, err_tail)。"""
    try:
        esc = escape_subtitles_path(srt_path)
    except ValueError as e:
        return False, str(e)
    cmd = [ffmpeg, "-y", "-i", str(in_path),
           "-vf", f"subtitles=filename='{esc}'",
           "-c:a", "copy", str(out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]
    ok = proc.returncode == 0 and Path(out_path).is_file()
    return ok, "" if ok else (proc.stderr or b"")[-200:].decode(errors="ignore")


def probe_has_audio(ffmpeg: str, media_path) -> bool:
    """主片是否自带音轨（混音滤镜选择依据）。ffmpeg 无输出参数时 rc=1 但
    stderr 含流枚举——以 'Audio:' 标记判断，误判代价低（两形态均真执行）。"""
    try:
        proc = subprocess.run([ffmpeg, "-i", str(media_path)],
                              capture_output=True, timeout=60, check=False)
    except Exception:  # noqa: BLE001
        return False
    return b"Audio:" in (proc.stderr or b"")


def mix_bgm(ffmpeg: str, main_path, bgm_path, out_path, has_audio: bool,
            volume: float = 0.35, timeout: int = 600) -> "tuple[bool, str]":
    """A3：BGM 混音（用户提供的循环乐轨，非 AI 生成）。主片有音轨 →
    amix（BGM 压至 volume 后与原声混合）；主片静音（wan 系常见）→ 直接映射
    BGM 音轨。失败不抛，返回 (ok, err_tail) 由调用方降级。"""
    cmd = [ffmpeg, "-y", "-i", str(main_path), "-i", str(bgm_path)]
    if has_audio:
        cmd += ["-filter_complex",
                f"[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first"
                ":dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest"]
    cmd.append(str(out_path))
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]
    ok = proc.returncode == 0 and Path(out_path).is_file()
    return ok, "" if ok else (proc.stderr or b"")[-200:].decode(errors="ignore")
