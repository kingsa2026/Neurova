# -*- coding: utf-8 -*-
"""视频关键帧抽取单点：把「视频附件」变成模型真能看到的 JPEG 帧。

为什么走抽帧而不是"把视频交给模型"：本仓的能力探知面根本没有 `VIDEO` 这一档
（`providers/capability_detector.py` 的 `_probe_prompts` 只有 VISION，probe 的 elif 链也
没有 VIDEO 分支）——按视频能力选模型恒选不到，于是"视频理解"这个请求类型一直是**有枚举、
没数据**。抽帧复用图像那条已在役的 VISION 单通道，不新造第二条多模态出口。

所有失败都返回 `(空列表, 原因)` 而不是抛异常或静默返回空——调用方要把原因如实写进本轮文本，
模型才知道"这次没看到画面"是环境问题而不是用户没给。
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Tuple

#: 单轮最多喂给模型的帧数——帧数直接乘进当轮请求体积与图像轮 token
MAX_FRAMES = 8
#: 时长已知时的最短采样间隔（防短视频被抽出重复帧）
MIN_INTERVAL_SEC = 1.0
#: 时长探测不出来时的兜底间隔：按此采样，长视频也只取前若干帧，宁可少喂不谎报
UNKNOWN_DURATION_INTERVAL_SEC = 15.0

_PROBE_TIMEOUT_SEC = 15.0
_EXTRACT_TIMEOUT_SEC = 90.0
_DURATION_PATTERN = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_STDERR_SNIPPET = 200


def _decodeStderr(raw: bytes) -> str:
    """ffmpeg 的 stderr 按 UTF-8 尽力解，脏字节 replace 而不是抛——它回答的是"为什么失败"。"""
    return (raw or b"").decode("utf-8", errors="replace").strip()


def _resolveFfmpegExecutable() -> str:
    from neurova.core.ffmpeg import resolve_ffmpeg_path

    return resolve_ffmpeg_path()


def probeDurationSeconds(ffmpeg: str, videoPath: str) -> float:
    """读 ffmpeg 对 `-i` 的 stderr 拿时长；读不到返回 0.0（调用侧按未知处理）。

    ffmpeg 只给输入不给输出时必然非 0 退出，Duration 行仍在那段 stderr 里，
    故这里不看 returncode，只按文本判。
    """
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", videoPath],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    match = _DURATION_PATTERN.search(_decodeStderr(proc.stderr))
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    try:
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (TypeError, ValueError):
        return 0.0


def extractKeyframes(videoPath: str, *, maxFrames: int = MAX_FRAMES) -> Tuple[List[bytes], str]:
    """抽至多 ``maxFrames`` 帧 JPEG。

    Returns:
        ``(帧字节列表, 失败原因)``。取到帧时原因为空串；一帧都没取到列表必为空，
        且原因非空——空列表配空原因是「静默失败」，本仓不允许。
    """
    if maxFrames <= 0:
        return [], f"帧数上限必须为正（收到 {maxFrames}）"

    ffmpeg = _resolveFfmpegExecutable()
    if not ffmpeg:
        return [], "未找到可用的 ffmpeg（PATH 与托管目录均无）"

    source = Path(str(videoPath or ""))
    if not source.is_file():
        return [], f"视频文件不在盘上：{source.name or '(空路径)'}"

    duration = probeDurationSeconds(ffmpeg, str(source))
    if duration > 0:
        interval = max(MIN_INTERVAL_SEC, duration / float(maxFrames))
    else:
        interval = UNKNOWN_DURATION_INTERVAL_SEC

    try:
        with tempfile.TemporaryDirectory(prefix="neurova-keyframes-") as workdir:
            pattern = Path(workdir) / "frame_%03d.jpg"
            command = [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-i", str(source),
                "-vf", f"fps=1/{interval:.3f}",
                "-frames:v", str(int(maxFrames)),
                "-q:v", "3",
                str(pattern),
            ]
            proc = subprocess.run(
                command,
                capture_output=True,
                timeout=_EXTRACT_TIMEOUT_SEC,
                check=False,
            )
            frames = [f.read_bytes() for f in sorted(Path(workdir).glob("frame_*.jpg"))]
    except subprocess.TimeoutExpired:
        return [], f"抽帧超时（>{_EXTRACT_TIMEOUT_SEC:.0f}s）"
    except OSError as exc:
        return [], f"抽帧进程启动失败：{exc}"

    if not frames:
        detail = _decodeStderr(proc.stderr)[-_STDERR_SNIPPET:]
        return [], (detail or f"ffmpeg 未产出任何帧（rc={proc.returncode}）")
    return frames, ""
