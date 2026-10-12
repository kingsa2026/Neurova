# -*- coding: utf-8 -*-
"""video-compose 节点的 concat 挪出事件循环——live-verify（§6-98）。

跑的真生产对象：真 `neurflow/drama_nodes.exec_video_compose`（节点执行体本体）、
真 `_concatLocalClips`（本批新收口的那个同步段）、**真 FFmpeg 二进制**（仓库托管件，
经 `NEUROVA_FFMPEG_PATH` 显式指向；不下载、不开外网）、真 mp4 素材（同一二进制现生成的
testsrc 片段）、真事件循环（`asyncio.run` 直跑，本缺陷的现场就在循环上，不涉及 HTTP）。
数据根走 `_liveVerifyIsolation.isolatedDataRoot()`。

两格对测，同一个量：**期间心跳推进次数与最大间隔**。

- 实验组：`await exec_video_compose(...)`——concat 在别的线程里，循环照常调度心跳；
- 对照组：在协程里**直接同步调** 同一个生产函数 `_concatLocalClips(...)`（＝改前形态），
  心跳应几乎不推进。对照组自己必须真卡住，否则这个测法分辨不出东西、判据不算过。

`ensure_ffmpeg()` 那一发（`_verify_binary`，实测 42–45ms）**不在本脚本取证范围**：
它的下载支路要出网，探针不开外网也不花钱；该格由行为判据
`tests/unit/core/test_ffmpegBootstrapOffloadsTheLoop.py`（心跳推进数 + 阻塞替身被调用）
与上面这发的同型实测定性覆盖，边界写在这里，不假装证过。

一条命令复现（机器无关串）：
PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/dramaComposeOffload_live.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()
CLIP_DIR = DATA_ROOT / "composeclips"
CLIP_DIR.mkdir(parents=True, exist_ok=True)
REPO_DATA_DIR = PROJECT_ROOT / "data"
#: 素材规模按**本机实测标定**定的，不是拍的：`-c copy` 拼接耗时随帧数线性走，
#: 现量 90,000 帧（60 段 × 60s @25fps）= 0.81s。这里取 2 段 30s 各重复 60 次
#: ＝ 180,000 帧 ≈ 1.6s 的阻塞窗口——够长到能分辨循环有没有被占死，又不必真编码 90 分钟。
#: 重复引用同一文件只为拉长数据量，节点走的分支与真实素材完全一致。
SRC_SECONDS = 30
REPEATS = 120

FFMPEG = ""


def _useRealFfmpeg() -> str:
    """env 写在函数体内，不放模块顶层（`test_manualScriptsEnvMutationRatchet` 守这一形态）。"""
    os.environ["NEUROVA_FFMPEG_AUTODOWNLOAD"] = "0"
    for cand in (REPO_DATA_DIR / "tools" / "ffmpeg" / "ffmpeg.exe",
                 REPO_DATA_DIR / "tools" / "ffmpeg" / "ffmpeg"):
        if cand.is_file():
            os.environ["NEUROVA_FFMPEG_PATH"] = str(cand)
            return str(cand)
    import shutil

    found = shutil.which("ffmpeg") or ""
    if found:
        os.environ["NEUROVA_FFMPEG_PATH"] = found
    return found


def fingerprintDataDir():
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}:{st.st_size}:{st.st_mtime_ns}")
    digest = hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest() if items else "empty"
    return digest, len(items)


def makeClip(outPath: Path, n: int) -> None:
    import subprocess

    cmd = [FFMPEG, "-y", "-f", "lavfi", "-i",
           f"testsrc=size=640x360:rate=25:duration={SRC_SECONDS}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(outPath)]
    proc = subprocess.run(cmd, capture_output=True, timeout=300, check=False)
    if proc.returncode != 0 or not outPath.is_file():
        raise RuntimeError(f"素材生成失败({outPath.name}): "
                           + (proc.stderr or b"")[-200:].decode(errors="ignore"))


async def measure(runner) -> dict:
    """runner 期间数心跳推进次数与最长间隔；返回 {advanced, maxGapS, durS}。"""
    ticks = {"n": 0, "last": time.perf_counter(), "maxGap": 0.0}

    async def ticker():
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            ticks["n"] += 1
            ticks["maxGap"] = max(ticks["maxGap"], now - ticks["last"])
            ticks["last"] = now

    watcher = asyncio.create_task(ticker())
    before = ticks["n"]
    t0 = time.perf_counter()
    try:
        await runner()
    finally:
        dur = time.perf_counter() - t0
    # 关键一格：**循环被完全占死时，心跳一帧都没推进，上面那个 maxGap 会记成 0**——
    # 阻塞期恰恰藏在"最后一拍到 runner 返回"这段没被任何拍子覆盖的空窗里。
    # 不补这一维，"占死"会读成"零延迟"，判据就会朝反方向绿（首跑实测正是 0ms）。
    stall = time.perf_counter() - ticks["last"]
    watcher.cancel()
    try:
        await watcher
    except asyncio.CancelledError:
        pass
    return {"advanced": ticks["n"] - before,
            "maxGapS": max(ticks["maxGap"], stall), "stallS": stall, "durS": dur}


async def mainAsync() -> int:
    failures: list[str] = []
    from neurova.collaboration.neurflow import drama_nodes as dn
    from neurova.llm.generators.runtime import GENERATION_OUTPUT_DIR

    clips: list[str] = []
    for n in (1, 2):
        cp = CLIP_DIR / f"src_{n}.mp4"
        makeClip(cp, n)
        clips.extend([str(cp)] * REPEATS)
    frames = len(clips) * SRC_SECONDS * 25
    print(f"素材：2 段 × {SRC_SECONDS}s，各重复 {REPEATS} 次 = {len(clips)} 条目"
          f"（约 {frames} 帧），ffmpeg={FFMPEG}，数据根={DATA_ROOT}")

    # ── 实验组：真节点（concat 在别的线程里）───────────────────────────────
    box: dict = {}

    async def runNode():
        box["out"] = await dn.exec_video_compose({"clips": clips}, {})

    exp = await measure(runNode)
    out = box["out"]["output"]
    print(f"实验组 exec_video_compose：用时 {exp['durS']:.2f}s，期间心跳推进 "
          f"{exp['advanced']} 次，最长空窗 {exp['maxGapS'] * 1000:.0f}ms，"
          f"mode={out.get('mode')!r} composed={out.get('composed')}")
    if out.get("composed") is not True:
        failures.append(f"节点没真出片，后面的心跳读数不作数：{out.get('mode')!r}"
                        f" / {out}")
    if not Path(str(out.get("video") or "")).is_file():
        failures.append(f"库里说成片在 {out.get('video')!r}，磁盘上没有")
    if exp["durS"] < 1.0:
        failures.append(f"concat 只用了 {exp['durS']:.2f}s，太短不足以分辨循环是否被占死"
                        "（素材规模按标定值取，见文件头）")
    if exp["advanced"] < 50:
        failures.append(f"实验组 1s+ 的拼接期间心跳只推进 {exp['advanced']} 次"
                        "——offload 没起作用")

    # ── 对照组：同一个生产同步段，直接压在循环里跑（＝改前形态）─────────────
    ctrlOut = Path(GENERATION_OUTPUT_DIR) / "ctrl_compose.mp4"

    async def runBlocking():
        # 改前形态原样复刻：协程里同步调阻塞子进程，不 offload
        dn._concatLocalClips(FFMPEG, clips, ctrlOut)

    ctrl = await measure(runBlocking)
    print(f"对照组 _concatLocalClips（循环内同步）：用时 {ctrl['durS']:.2f}s，期间心跳推进 "
          f"{ctrl['advanced']} 次，最长空窗 {ctrl['maxGapS'] * 1000:.0f}ms"
          f"（其中末段空窗 {ctrl['stallS'] * 1000:.0f}ms）")
    if ctrl["advanced"] > 3:
        failures.append(f"对照组心跳推进了 {ctrl['advanced']} 次——这个测法分辨不出阻塞，"
                        "判据不能算过")
    if ctrl["maxGapS"] < 0.5:
        failures.append(f"对照组最长间隔只有 {ctrl['maxGapS'] * 1000:.0f}ms，没真卡住")
    if ctrl["maxGapS"] <= exp["maxGapS"] * 3:
        failures.append(f"实验组最长间隔 {exp['maxGapS'] * 1000:.0f}ms 没显著优于对照组 "
                        f"{ctrl['maxGapS'] * 1000:.0f}ms")
    ctrlOut.unlink(missing_ok=True)   # 对照组那份是纯测量副产物，几十 MB，用完即删

    # ── 降级面：片段非本地件时诚实回连播清单，且这条支路本就不碰子进程 ──────
    manBox: dict = {}

    async def runManifest():
        manBox["out"] = await dn.exec_video_compose({"clips": ["http://x/a.mp4"]}, {})

    man = await measure(runManifest)
    manOut = manBox["out"]["output"]
    print(f"降级面：mode={manOut.get('mode')!r} composed={manOut.get('composed')} "
          f"items={len(manOut.get('items') or [])}，期间心跳推进 {man['advanced']} 次")
    if manOut.get("mode") != "slideshow_manifest" or manOut.get("composed") is not False:
        failures.append(f"非本地片段没落到诚实连播清单：{manOut.get('mode')!r}")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    return 0


if __name__ == "__main__":
    FFMPEG = _useRealFfmpeg()
    if not FFMPEG:
        print("FAIL: 本机无可执行 FFmpeg——本批取证只能在真二进制下做，不出数即不算自证")
        sys.exit(1)
    before, nBefore = fingerprintDataDir()
    rc = asyncio.run(mainAsync())
    after, nAfter = fingerprintDataDir()
    print(f"仓内 data/ 指纹：before={before[:12]}({nBefore}) after={after[:12]}({nAfter})")
    if after != before:
        print("FAIL: 仓内 data/ 被写动了")
        rc = 1
    if rc == 0:
        print("DRAMA COMPOSE OFFLOAD LIVE VERIFY PASSED")
    sys.exit(rc)
