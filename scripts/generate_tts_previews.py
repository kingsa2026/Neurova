# -*- coding: utf-8 -*-
"""生成 Agent 表单音色试听文件（2026-09-08）。

固定试听文本"你好，我是Neurova，您的专属人工智能助手！"按各音色合成，
输出到 NeurUI/public/tts-preview/（前端 Vite/打包静态服务直接可访问）。

- moss 内置音色（10 个）：本地推理，16kHz 单声道 WAV——听感与本地引擎实际输出一致
- edge-tts 在线音色（4 个）：需网络；失败跳过（重跑本脚本补齐）

可重复执行：已存在且非空的文件跳过（--force 全量重生成）。

用法: python scripts/generate_tts_previews.py [--force]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PREVIEW_TEXT = "你好，我是Neurova，您的专属人工智能助手！"
OUT_DIR = Path(__file__).resolve().parents[1] / "NeurUI" / "public" / "tts-preview"

# moss 内置音色（与 models/tts/moss-nano/browser_poc_manifest.json 的 builtin_voices 对应）
MOSS_VOICES = [
    "Junhao",   # 中文男声
    "Zhiming",  # 中文男声
    "Weiguo",   # 中文男声
    "Xiaoyu",   # 中文女声
    "Yuewen",   # 中文女声
    "Lingyu",   # 中文女声
    "Trump",    # 英文男声
    "Ava",      # 英文女声
    "Bella",    # 英文女声
    "Adam",     # 英文男声
]
# edge-tts 在线音色（与 AgentFormPage 下拉一致）
EDGE_VOICES = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunyangNeural",
]


async def gen_moss(force: bool) -> int:
    from neurova.tts.moss_nano import MOSSNanTTS

    engine = MOSSNanTTS(model_dir="models/tts/moss-nano", tokenizer_dir="models/tts/moss-tokenizer", auto_download=False)
    if not await engine.initialize():
        print("[moss] 引擎初始化失败（模型缺失或内存不足），跳过本地音色试听")
        return 0
    made = 0
    try:
        for voice in MOSS_VOICES:
            out = OUT_DIR / f"{voice}.wav"
            if out.exists() and out.stat().st_size > 10000 and not force:
                print(f"[moss] {voice}: 已存在，跳过")
                continue
            audio = await engine.synthesize(PREVIEW_TEXT, voice=voice)
            if not audio:
                print(f"[moss] {voice}: 合成失败")
                continue
            out.write_bytes(audio)
            made += 1
            print(f"[moss] {voice}: {len(audio) // 1024}KB -> {out.name}")
    finally:
        await engine.shutdown()
    return made


async def gen_edge(force: bool) -> int:
    from neurova.tts.edge_tts import EdgeTTS

    engine = EdgeTTS()
    if not await engine.initialize():
        print("[edge] edge-tts 不可用，跳过在线音色试听")
        return 0
    made = 0
    for voice in EDGE_VOICES:
        out = OUT_DIR / f"{voice}.mp3"
        if out.exists() and out.stat().st_size > 10000 and not force:
            print(f"[edge] {voice}: 已存在，跳过")
            continue
        audio = await engine.synthesize(PREVIEW_TEXT, voice=voice)
        if not audio:
            print(f"[edge] {voice}: 合成失败（网络？）")
            continue
        out.write_bytes(audio)
        made += 1
        print(f"[edge] {voice}: {len(audio) // 1024}KB -> {out.name}")
    return made


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="全量重生成")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    import asyncio

    total = asyncio.run(gen_moss(args.force)) + asyncio.run(gen_edge(args.force))
    print(f"\n完成：新生成 {total} 个试听文件 -> {OUT_DIR}")


if __name__ == "__main__":
    main()
