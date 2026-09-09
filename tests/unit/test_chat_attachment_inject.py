"""
测试：附件注入步骤（R-3 pipeline 附件进上下文）

契约：
  1. 文本/文档附件（txt/md/docx/xlsx/pptx/pdf/csv）抽取内容后追加到用户输入，
     模型可感知附件内容
  2. 图像附件 → 生成 vision content list（OpenAI 多模态格式），
     供多模态 LLM 直接接收（若模型无 vision 能力则降级为提示文本）
  3. 音频/视频/过大的附件 → 不抛异常，降级为文件名提示
  4. 无附件时用户输入不变
"""

import io
import pytest
from neurova.agent.chat_pipeline import ChatPipeline


def _docx_bytes():
    import docx

    d = docx.Document()
    d.add_paragraph("文档里的一行内容")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_pipeline():
    """构造一个最小 ChatPipeline（mock agent 属性）"""
    p = object.__new__(ChatPipeline)
    return p


def test_inject_attachments_text_appends_to_user_input(monkeypatch):
    p = make_pipeline()

    def fake_read(fid):
        return b"hello world"

    monkeypatch.setattr(p, "_read_attachment_bytes", fake_read)

    attachments = [
        {"file_id": "f1", "filename": "note.txt", "file_type": "text", "mime_type": "text/plain", "size": 11, "path": "/tmp/note.txt"}
    ]
    user_input, vision_parts = p._inject_attachments_into_input(
        "帮我看看", attachments
    )
    assert "note.txt" in user_input
    assert "hello world" in user_input
    assert vision_parts == []


def test_inject_attachments_docx_extracted(monkeypatch):
    p = make_pipeline()
    monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: _docx_bytes())

    attachments = [
        {"file_id": "f2", "filename": "报告.docx", "file_type": "document", "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "size": 100, "path": "/tmp/report.docx"}
    ]
    user_input, vision_parts = p._inject_attachments_into_input("总结", attachments)
    assert "文档里的一行内容" in user_input
    assert vision_parts == []


def test_inject_attachments_image_produces_vision_parts(monkeypatch):
    p = make_pipeline()
    # 最小 PNG 头（1x1 透明像素）
    import base64

    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: png)

    attachments = [
        {"file_id": "f3", "filename": "pic.png", "file_type": "image", "mime_type": "image/png", "size": len(png), "path": "/tmp/pic.png"}
    ]
    user_input, vision_parts = p._inject_attachments_into_input("这是什么", attachments)
    assert len(vision_parts) == 1
    assert vision_parts[0]["type"] == "image_url"
    assert vision_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_inject_attachments_mixed(monkeypatch):
    p = make_pipeline()
    monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: b"text content")

    attachments = [
        {"file_id": "f4", "filename": "a.md", "file_type": "text", "mime_type": "text/markdown", "size": 12, "path": "/tmp/a.md"},
        {"file_id": "f5", "filename": "video.mp4", "file_type": "video", "mime_type": "video/mp4", "size": 999, "path": "/tmp/v.mp4"},
    ]
    user_input, vision_parts = p._inject_attachments_into_input("说明", attachments)
    assert "a.md" in user_input  # 视频降级为提示
    assert "video.mp4" in user_input
    assert vision_parts == []


def test_inject_attachments_none_keeps_input(monkeypatch):
    p = make_pipeline()
    monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: None)

    attachments = [
        {"file_id": "f6", "filename": "gone.txt", "file_type": "text", "mime_type": "text/plain", "size": 0, "path": "/tmp/gone.txt"}
    ]
    user_input, vision_parts = p._inject_attachments_into_input("原文", attachments)
    assert "原文" in user_input
    assert vision_parts == []


class TestVisionMount:
    """图像切片必须挂到 context 最后一条 user 消息（R-3）"""

    def test_mounts_on_last_user_message(self):
        from types import SimpleNamespace

        p = make_pipeline()
        ctx = SimpleNamespace(context=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "看了吗"},
            {"role": "assistant", "content": "嗯"},
            {"role": "user", "content": "看图"},
        ])
        vision = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]
        p._apply_vision_attachments(ctx, vision)

        # 最后一条 user 消息（index 3）变为 content list
        assert ctx.context[3]["content"] == [
            {"type": "text", "text": "看图"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]
        # 之前的 user 消息（index 1）保持不变
        assert ctx.context[1]["content"] == "看了吗"

    def test_no_user_message_returns_without_crash(self):
        from types import SimpleNamespace

        p = make_pipeline()
        ctx = SimpleNamespace(context=[{"role": "system", "content": "sys"}])
        vision = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]
        p._apply_vision_attachments(ctx, vision)  # 不抛异常
        assert ctx.context[0]["content"] == "sys"


class TestImageNormalization:
    """大图注入前必须归一化（2026-09-09 413 事故）

    服务商请求体普遍 5MB 上限：4.4MB 照片 base64 膨胀 4/3 ≈ 5.9MB，
    整体请求 6.38MB 被 413 request_too_large 拒绝。契约：
    1. 超阈值图片 → 降采样重编码，payload 显著变小、长边 ≤ 2048；
    2. 小图原样透传（字节不变，零质量损失零 CPU 开销）；
    3. 解码失败（坏图）→ 原样返回不抛异常。
    """

    def _big_jpeg(self):
        import os
        from PIL import Image

        img = Image.frombytes("RGB", (4000, 3000), os.urandom(4000 * 3000 * 3))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        data = buf.getvalue()
        assert len(data) > 2 * 1024 * 1024  # 前置：构造物必须超阈值
        return data

    def test_large_image_normalized_under_payload_limit(self, monkeypatch):
        from neurova.attachment_parser import LLM_IMAGE_MAX_DIMENSION

        p = make_pipeline()
        big = self._big_jpeg()
        monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: big)

        attachments = [
            {"file_id": "fbig", "filename": "photo.jpg", "file_type": "image",
             "mime_type": "image/jpeg", "size": len(big), "path": "/tmp/photo.jpg"}
        ]
        user_input, vision_parts = p._inject_attachments_into_input("分析", attachments)

        assert len(vision_parts) == 1
        url = vision_parts[0]["image_url"]["url"]
        # base64 载荷 < 3MB：叠加上下文后整体请求远离服务商 5MB 上限
        b64_payload = url.split(",", 1)[1]
        assert len(b64_payload) < 3 * 1024 * 1024
        # 无 alpha → 重编码为 JPEG
        assert url.startswith("data:image/jpeg;base64,")
        # 长边降采样到上限内
        import base64 as b64mod
        from PIL import Image

        out = Image.open(io.BytesIO(b64mod.b64decode(b64_payload)))
        assert max(out.size) <= LLM_IMAGE_MAX_DIMENSION

    def test_small_image_passthrough_unchanged(self, monkeypatch):
        import base64 as b64mod

        p = make_pipeline()
        png = b64mod.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: png)

        attachments = [
            {"file_id": "fsmall", "filename": "pic.png", "file_type": "image",
             "mime_type": "image/png", "size": len(png), "path": "/tmp/pic.png"}
        ]
        _, vision_parts = p._inject_attachments_into_input("看", attachments)

        assert vision_parts[0]["image_url"]["url"] == f"data:image/png;base64,{b64mod.b64encode(png).decode()}"

    def test_corrupt_large_image_falls_back_to_raw(self, monkeypatch):
        import os

        p = make_pipeline()
        junk = b"\x89PNG\r\n\x1a\n" + os.urandom(3 * 1024 * 1024)
        monkeypatch.setattr(p, "_read_attachment_bytes", lambda fid: junk)

        attachments = [
            {"file_id": "fbad", "filename": "broken.png", "file_type": "image",
             "mime_type": "image/png", "size": len(junk), "path": "/tmp/broken.png"}
        ]
        _, vision_parts = p._inject_attachments_into_input("看", attachments)

        # 解码失败不抛异常，原样透传（当前行为兜底）
        assert vision_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
