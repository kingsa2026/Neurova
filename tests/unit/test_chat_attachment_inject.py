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
