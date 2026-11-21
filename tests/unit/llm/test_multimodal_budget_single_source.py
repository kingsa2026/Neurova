# -*- coding: utf-8 -*-
"""多模态预算口径单源化（多模态追平批二卡 M5）。

现状（红灯）：多模态输入侧的尺寸/预算上限散落三处——
- `neurova/attachment_parser.py`：`LLM_IMAGE_MAX_PAYLOAD_BYTES` / `LLM_IMAGE_MAX_DIMENSION`
  （`normalize_image_for_llm` 的 413 防线闸门）；
- `neurova/agent/image_retention.py`：`apply_image_retention(keep_last=4)` 的保留窗口；
- `neurova/api/endpoints/files_api.py`：`_MAX_UPLOAD_BYTES` 上传限幅。
`llm/model_limits.py` 只管输出 token，不承载多模态输入口径。

判据（红→绿）：三个消费点必须与 `model_limits` 多模态输入预算段**同源同值**；
数值与收拢前逐项一致（现值平移，不改变任何现有限幅行为）。
"""

from __future__ import annotations

import importlib
import io
import os

import pytest

import neurova.agent.image_retention as image_retention
import neurova.api.endpoints.files_api as files_api
import neurova.attachment_parser as attachment_parser
from neurova.llm import model_limits


class TestMultimodalBudgetSingleSource:
    """三个消费点与 model_limits 多模态输入预算段同源同值。"""

    def test_budget_constants_exist_with_current_values(self):
        # 现值平移：与收拢前各散落点字面量逐项一致
        assert model_limits.MULTIMODAL_IMAGE_MAX_PAYLOAD_BYTES == 3 * 1024 * 1024
        assert model_limits.MULTIMODAL_IMAGE_MAX_DIMENSION == 2048
        assert model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN == 4
        assert model_limits.MULTIMODAL_ATTACHMENT_MAX_UPLOAD_BYTES == 100 * 1024 * 1024

    def test_image_normalization_reads_single_source(self):
        # `is` 判同源：attachment_parser 的名字只是绑定到单源的兼容别名，不是第二份定义
        assert (
            attachment_parser.LLM_IMAGE_MAX_PAYLOAD_BYTES
            is model_limits.MULTIMODAL_IMAGE_MAX_PAYLOAD_BYTES
        )
        assert (
            attachment_parser.LLM_IMAGE_MAX_DIMENSION
            is model_limits.MULTIMODAL_IMAGE_MAX_DIMENSION
        )

    def test_image_retention_default_reads_single_source(self):
        default_keep_last = image_retention.apply_image_retention.__defaults__[0]
        assert default_keep_last == model_limits.MULTIMODAL_IMAGE_RETAIN_PER_TURN

    def test_upload_limit_reads_single_source(self):
        assert (
            files_api._MAX_UPLOAD_BYTES
            is model_limits.MULTIMODAL_ATTACHMENT_MAX_UPLOAD_BYTES
        )

    def test_upload_limit_env_override_semantics_preserved(self, monkeypatch):
        # 环境变量 NEUROVA_MAX_UPLOAD_MB 的覆盖语义随表达式原样上收，不因搬家失效
        saved = dict(model_limits.__dict__)
        try:
            monkeypatch.setenv("NEUROVA_MAX_UPLOAD_MB", "7")
            importlib.reload(model_limits)
            assert model_limits.MULTIMODAL_ATTACHMENT_MAX_UPLOAD_BYTES == 7 * 1024 * 1024
        finally:
            model_limits.__dict__.clear()
            model_limits.__dict__.update(saved)
            monkeypatch.delenv("NEUROVA_MAX_UPLOAD_MB", raising=False)


# ---------------------------------------------------------------------------
# 行为不变护栏：以下断言在收拢前后都必须成立（守的现有限幅行为，不是新口径）。
# ---------------------------------------------------------------------------


def _noisePng(mode: str, width: int, height: int) -> bytes:
    """编码最坏情况的真图（逐像素随机字节），保证真的超闸门。"""
    from PIL import Image

    channels = 4 if mode == "RGBA" else 3
    img = Image.frombytes(mode, (width, height), os.urandom(width * height * channels))
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _imageMsg() -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }


class TestMultimodalBudgetBehaviorUnchanged:
    def test_oversize_image_still_shrunk_into_gate(self):
        raw = _noisePng("RGB", 1600, 1600)
        assert len(raw) > model_limits.MULTIMODAL_IMAGE_MAX_PAYLOAD_BYTES
        out, mime = attachment_parser.normalize_image_for_llm(raw, "image/png")
        assert len(out) <= model_limits.MULTIMODAL_IMAGE_MAX_PAYLOAD_BYTES, (
            f"归一化后仍超闸门：{len(out)} B"
        )
        assert mime == "image/jpeg"

    def test_oversize_upload_rejected_honestly(self):
        oversized = b"\0" * (model_limits.MULTIMODAL_ATTACHMENT_MAX_UPLOAD_BYTES + 1)
        with pytest.raises(files_api.FileRejection) as excinfo:
            files_api.persistBytes(
                user_id="u1", agent_id="a1", session_id="s1",
                filename="big.bin", data=oversized,
            )
        assert excinfo.value.status == 413
        assert "File too large" in excinfo.value.detail

    def test_default_retention_window_keeps_four_rounds(self):
        messages = [_imageMsg() for _ in range(6)]
        cleaned, stats = image_retention.apply_image_retention(messages)
        assert stats["images_kept"] == 4
        assert stats["images_removed"] == 2
        # 最旧的两轮图片被置占位，最近四轮原样保留
        assert cleaned[0]["content"][1]["type"] == "text"
        assert cleaned[5]["content"][1]["type"] == "image_url"
