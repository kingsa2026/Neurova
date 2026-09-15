# -*- coding: utf-8 -*-
"""AIGC 能力检测与预置回归（先红后绿）。

根因：_IMAGE_GEN_PAT / _VIDEO_GEN_PAT 未覆盖 doubao-seedance-*（无 t2v 后缀时）、
agnes-image-* / agnes-video-*、gpt-image-*、qwen-image-*（带版本后缀时），
导致这些已配置模型在 AIGC 下拉（按 capability 过滤）中不出现，
agnes-video-* 更被误标为"视频理解"。
"""
import pytest

from neurova.llm.capability_detector import infer_capabilities, detect_model_capabilities


@pytest.mark.parametrize("mid", [
    "doubao-seedream-4-0-250828",
    "doubao-seedream-5-0-pro-260628",
    "gpt-image-1",
    "agnes-image-2.1-flash",
    "agnes-image-2.0-flashv",
    "qwen-image-2.0-20260111",
])
def test_image_gen_models_tagged(mid):
    caps = infer_capabilities(mid)
    assert "image_generation" in caps, (mid, caps)
    assert "text" not in caps, f"纯生成模型不应带 text: {mid} {caps}"


@pytest.mark.parametrize("mid", [
    "doubao-seedance-1-0-pro-250528",      # 无 t2v/i2v 后缀
    "doubao-seedance-2-0-fast-260128",
    "doubao-seedance-2-5-260628",
    "agnes-video-2.5",
    "agnes-video-2.5-flash",
    "veo-3.1-generate-preview",
    "wan2.7-t2v",
])
def test_video_gen_models_tagged(mid):
    caps = infer_capabilities(mid)
    assert "video_generation" in caps, (mid, caps)
    # 关键：不能把生成模型误标为「视频理解」（video 能力）
    assert "video" not in caps, f"生成模型不应落视频理解: {mid} {caps}"
    assert "text" not in caps, f"纯生成模型不应带 text: {mid} {caps}"


def test_agnes_video_not_mislabeled_understanding():
    caps = infer_capabilities("agnes-video-2.5")
    assert "video_generation" in caps and "video" not in caps


def test_detect_model_capabilities_consistent():
    # 对外入口 detect_model_capabilities 与 infer 同结论
    assert "image_generation" in detect_model_capabilities("agnes-image-2.1-flash")
    assert "video_generation" in detect_model_capabilities("doubao-seedance-2-5-260628")


def test_text_models_unaffected():
    for mid in ("deepseek-v3", "gpt-4o", "qwen3-vl-8b"):
        caps = infer_capabilities(mid)
        assert "image_generation" not in caps and "video_generation" not in caps
    assert "text" in infer_capabilities("gpt-4o")
