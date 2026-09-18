# -*- coding: utf-8 -*-
"""模型产物完整性清单（Issue #56 残留边界收口）。

背景：pip-audit / npm audit 覆盖的是"包管理器的依赖树"。模型权重不在其中——
它们经 `snapshot_download` / hf-mirror 直链 / ModelScope 拉到本地后直接喂给
onnxruntime 反序列化。此前**零校验**：镜像站投毒、传输截断、磁盘静默损坏
都不会被发现，只会在推理时表现为"结果莫名其妙"。

本模块把"权重应当是什么"固化成清单（sha256），并给出校验入口：

1. `MANIFEST`：按模型名 → {文件名: sha256}，与发布方（ModelScope / HF LFS）
   公布的哈希逐一对齐（见每条注释的取证来源）。
2. `verify_model(model_name, model_dir)`：逐文件核对。不匹配即点名，供下载后
   校验与运维自检复用。
3. `find_altered_files(...)`：只返回不匹配项（校验后清理重下用）。

设计取舍：
- **只收 `required_files`**（下载器保证存在的文件）。可选文件（如 bge 的
  model.onnx、README、meta json）不进清单——不同镜像站的发布集合不完全一致，
  收进来会把"源差异"误报成"完整性事故"。
- **不给 `is_model_available` 加哈希校验**：那是每次调用都跑的热路径，对
  200MB+ 文件逐个 sha256 会让可用性判断变成秒级阻塞。校验只发生在下载之后
  （一次性）与显式自检时。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

# 分块读，避免把 440MB 权重整体读进内存
_CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    """流式 sha256（大权重文件友好）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def is_lfs_pointer(path: Path) -> bool:
    """判断是否为未 smudge 的 Git LFS 指针（CI 未 `lfs: true` 时会看到）。

    指针文件内容是 `version https://git-lfs.github.com/spec/v1\\noid sha256:...`，
    校验时必须跳过——否则会把"LFS 没拉"误报成"权重损坏"。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec")


# ── 清单：sha256 与发布方公布值逐一对齐（2026-09-18 取证）──────────────────
# 取证方式：
#   * ModelScope 开放 API `repo/files` 返回每个 blob 的 `Sha256` 字段；
#   * HF 侧 LFS 文件用 `tree/main` 的 `lfs.oid`（LFS 的 oid 就是文件 sha256）；
#   * 二者对同一文件一致，且与本仓在库文件实算一致（无 LFS 指针时）。
# 因此清单同时锚定"上游发布值"与"本仓在库值"两侧，任一侧漂移都会被守卫抓到。
MANIFEST: Dict[str, Dict[str, str]] = {
    "moss-tts-nano": {
        # HF: OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX / MS: OpenMOSS/MOSS-TTS-Nano-100M-ONNX
        "moss_tts_prefill.onnx": "d56126dcd0574c2f15d98fc6b35eda68d0386b5bd9c5e38e28548d6f2ea8f3db",
        "moss_tts_decode_step.onnx": "698cbc2fc1c2feca16e5895614ed52bbb32ded10f236c076f477b2e69abf32d8",
        "moss_tts_local_cached_step.onnx": "aa9035fefc1c138a951a8bcfc0374fb03a25f1ece67f7f7f53bce349b84a1dd5",
        "moss_tts_local_decoder.onnx": "51aa754301b38550a5f9adda0ad93bd3dc95819afb511e6dcabf4a90b345a454",
        "moss_tts_local_fixed_sampled_frame.onnx": "40cdb00efc171c450cf91468e01429caa41b0252222cd308e978f58fe354afa8",
        "moss_tts_global_shared.data": "bce8312c3df6a44545302cae229b61054fe0672e0b252ba59cba47adeed831dc",
        "moss_tts_local_shared.data": "bae7782032c0fb12490ab42afe009f87ae6c75a0f0596fc7b5c08e4d5ee93916",
        "tokenizer.model": "c353ee1479b536bf414c1b247f5542b6607fb8ae91320e5af1781fee200fddff",
    },
    "moss-audio-tokenizer": {
        # MS: OpenMOSS/MOSS-Audio-Tokenizer-Nano-ONNX
        "moss_audio_tokenizer_encode.onnx": "eadea4a645abdcf98714c7aead122ee2ce7da6e080f9f80b977cd1ca8e19473a",
        "moss_audio_tokenizer_encode.data": "aa751265b2bab2887eac224484546b194875aa7494b607115439b3dc6b228a2c",
        "moss_audio_tokenizer_decode_step.onnx": "9527c86a29e1837edec1f74db57d5eeaadb3a715af3382703566460afed25855",
        "moss_audio_tokenizer_decode_shared.data": "e69d52e0f4e84ca27850557ee54face46632d3a5a16c89bd246c7c408466dcad",
    },
    "bge-small-zh-v1.5": {
        # HF: BAAI/bge-small-zh-v1.5 / MS: AI-ModelScope/bge-small-zh-v1.5
        "model.safetensors": "354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026",
        "tokenizer.json": "48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26",
    },
}


def manifest_for(model_name: str) -> Dict[str, str]:
    """取某模型的哈希清单（无清单返回空 dict，调用方据此跳过校验）。"""
    return dict(MANIFEST.get(model_name) or {})


def find_altered_files(model_name: str, model_dir: Path) -> List[Tuple[str, str, str]]:
    """返回 [(文件名, 期望 sha256, 实得 sha256)]；全部匹配则为空列表。

    上下文：
    - 文件缺失 → 实得值记 "(missing)"，由 `is_model_available` 负责存在性，
      此处只报"对不上"。
    - LFS 指针 → 跳过（未拉取的大文件不是损坏）。
    """
    manifest = manifest_for(model_name)
    altered: List[Tuple[str, str, str]] = []
    for fname, expected in manifest.items():
        p = Path(model_dir) / fname
        if is_lfs_pointer(p):
            continue
        if not p.is_file():
            altered.append((fname, expected, "(missing)"))
            continue
        actual = sha256_file(p)
        if actual != expected:
            altered.append((fname, expected, actual))
    return altered


def verify_model(model_name: str, model_dir: Path) -> None:
    """校验模型产物完整性；不匹配抛 RuntimeError（信息含具体文件与双方哈希）。"""
    altered = find_altered_files(model_name, model_dir)
    if not altered:
        return
    lines = [f"  {n}: 期望 {e} / 实得 {a}" for n, e, a in altered]
    raise RuntimeError(
        f"模型 `{model_name}` 产物完整性校验失败（{len(altered)} 个文件）：\n"
        + "\n".join(lines)
        + "\n可能原因：镜像站投毒 / 传输截断 / 磁盘损坏。"
        "已按「宁缺勿错」处理——请删除该模型目录后重新下载。"
    )


def manifest_covers_required_files(model_name: str, required_files: List[str]) -> List[str]:
    """返回 required_files 中**未被清单覆盖**的项（守卫用；空列表即完备）。"""
    manifest = manifest_for(model_name)
    return [f for f in required_files if f not in manifest]
