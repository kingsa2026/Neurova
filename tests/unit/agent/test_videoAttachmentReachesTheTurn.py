# -*- coding: utf-8 -*-
"""视频附件要真进当轮请求（接线批 · 红灯）。

复核实状（本批自己逐处命中，与旧台账描述不同处以本文为准）：

- 真入口只有一个：`ChatPipeline._step_inject_attachments`（`chat_pipeline.py:1520`）读
  `ctx.metadata["attachments"]`，写者是 `console.py:182 attach_files`（属主校验后产出服务端
  元数据）。渠道那条 `Agent.process_multimodal` 的 image/video/document 三支**对真用户从不达**
  ——其唯一入口 `MessageRouter._route_chat`（`router.py:322`）只在 `media_type == "voice"` 时调它，
  而 `process_message` 的生产调用点只有评测面（既有在册判据
  `tests/unit/channels/test_channelVoiceContextReachesTheTurn.py` 的 docstring 已自陈同一事实）。
  本批不碰那条死支，只修唯一在投入口。
- 缺口形态：`_inject_attachments_into_input` 只认两态——image → vision parts、可抽文本 → 文本注入；
  `file_type == "video"` 必然走到 `extract_attachment_text` 返回 None 的分支
  （`attachment_parser.py:9` 规格明写「image / audio / video → 不抽取文本」），于是本轮只留下一句
  「未能解析」提示，模型手里**没有一个视频字节**。
- 能力档实测：`ModelCapability.VIDEO` 在探知面根本没有条目（`providers/capability_detector.py:79`
  的 `_probe_prompts` 只有 VISION，probe 的 elif 链亦无 VIDEO 分支）⇒ 按 VIDEO 选模型恒空。
  故接线形态是**抽帧复用既有 VISION 单通道**（`resolve_vision_capable_model` +
  `_apply_vision_attachments`），不新造第二条多模态出口。

判据写法：断「视频轮真的产出了 image_url 切片」与「抽不到帧时诚实留痕」，都在真入口上断，
不 patch 生产装配点本身；抽帧这一 seam 的可注入形态比照既有先例 `_read_attachment_bytes`。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.agent.chat_pipeline import ChatPipeline


def _jpegBytes(marker: int) -> bytes:
    """真 JPEG 字节（走 Pillow 现造，不用替身冒充媒体数据）。"""
    from PIL import Image

    from io import BytesIO

    color = ((marker * 40) % 256, (marker * 90) % 256, (marker * 150) % 256)
    buf = BytesIO()
    Image.new("RGB", (24, 24), color).save(buf, format="JPEG")
    return buf.getvalue()


def _videoAttachment() -> list:
    return [
        {
            "file_id": "vid-1",
            "filename": "发布会.mp4",
            "file_type": "video",
            "mime_type": "video/mp4",
            "size": 4096,
            "path": "storage/users/u1/发布会.mp4",
        }
    ]


def _pipelineAndContext():
    pipeline = object.__new__(ChatPipeline)
    ctx = SimpleNamespace(
        user_input="这场发布会讲了什么",
        metadata={"attachments": _videoAttachment()},
        context=None,
        _pending_vision_parts=None,
    )
    return pipeline, ctx


def test_videoAttachmentFramesBecomeVisionPartsOnTheTurn(monkeypatch):
    """抽到帧的视频附件必须产出 image_url 切片，与图片同一条 vision 通道。"""
    pipeline, ctx = _pipelineAndContext()
    frames = [_jpegBytes(1), _jpegBytes(2), _jpegBytes(3)]
    monkeypatch.setattr(
        pipeline, "_extractAttachmentFrames", lambda att: (frames, ""), raising=False,
    )

    asyncio.run(pipeline._step_inject_attachments(ctx))

    assert len(ctx._pending_vision_parts) == 3, "视频帧没有进当轮 vision 切片"
    for part in ctx._pending_vision_parts:
        assert part["type"] == "image_url"
        assert part["image_url"]["url"].startswith("data:image/")
    # 历史里只留中性标记 + 帧数，不留下"看不了"的谎
    assert "发布会.mp4" in ctx.user_input
    assert "3" in ctx.user_input
    assert "未能" not in ctx.user_input


def test_videoWithoutFramesDegradesHonestlyAndKeepsReason(monkeypatch):
    """抽不到帧（如无 ffmpeg）时诚实留痕：原因进文本，且不产空切片。"""
    pipeline, ctx = _pipelineAndContext()
    monkeypatch.setattr(
        pipeline,
        "_extractAttachmentFrames",
        lambda att: ([], "未找到可用的 ffmpeg"),
        raising=False,
    )

    asyncio.run(pipeline._step_inject_attachments(ctx))

    assert not ctx._pending_vision_parts
    assert "发布会.mp4" in ctx.user_input
    assert "未找到可用的 ffmpeg" in ctx.user_input


def test_videoFramesAreNotReadThroughTextExtractor(monkeypatch):
    """视频不得再走文本抽取分支——那是「未能解析」提示的唯一来源。"""
    called: list = []
    pipeline, ctx = _pipelineAndContext()
    monkeypatch.setattr(
        pipeline, "_extractAttachmentFrames", lambda att: ([_jpegBytes(7)], ""), raising=False,
    )

    import neurova.attachment_parser as attachment_parser

    realExtract = attachment_parser.extract_attachment_text

    def spy(data, filename, file_type):
        called.append(file_type)
        return realExtract(data, filename, file_type)

    monkeypatch.setattr(attachment_parser, "extract_attachment_text", spy)

    asyncio.run(pipeline._step_inject_attachments(ctx))

    assert "video" not in called


def test_extractAttachmentFramesResolvesPathAtSinglePoint():
    """抽帧 seam 存在且按 file_id 取服务端路径（不采信客户端拼出来的路径）。"""
    pipeline = object.__new__(ChatPipeline)
    frames, reason = pipeline._extractAttachmentFrames({"file_id": "missing-id", "filename": "x.mp4"})
    assert frames == []
    assert reason, "取不到附件路径时必须给出原因，不许静默空列表"


@pytest.mark.parametrize("file_type", ["video"])
def test_audioAndVideoShareTheMediaBranchNotTheTextBranch(file_type):
    """分派表里视频归媒体支；音频本批不动（另批），此处只钉住视频这一格。"""
    from neurova.agent.chat_pipeline import MEDIA_ATTACHMENT_FILE_TYPES

    assert file_type in MEDIA_ATTACHMENT_FILE_TYPES

@pytest.mark.timeout(120)   # 父墙 120 > 子墙 60：先后关系钉住，别让全局 30s 先到点把整场打死
def test_extractKeyframesOnRealVideoOrHonestReason(tmp_path):
    """抽帧判据咬真视频真 ffmpeg；本宿主没有 ffmpeg 时改咬"诚实原因"。

    不写 skip——跳过等于宣布这条链没被验过，而这条链的产物正是"模型看见了什么"。
    """
    import subprocess

    from neurova.core.ffmpeg import resolve_ffmpeg_path
    from neurova.media.keyframes import extractKeyframes

    exe = resolve_ffmpeg_path()
    if not exe:
        frames, reason = extractKeyframes(str(tmp_path / "absent.mp4"))
        assert frames == [] and "ffmpeg" in reason
        return

    clip = tmp_path / "clip.mp4"
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=duration=6:size=160x120:rate=10",
         "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip)],
        capture_output=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            "ffmpeg 在位却造不出测试片段: "
            + (proc.stderr or b"")[-160:].decode(errors="replace")
        )

    frames, reason = extractKeyframes(str(clip), maxFrames=3)
    assert reason == "", f"抽帧失败: {reason}"
    assert 1 <= len(frames) <= 3
    magic = bytes((0xFF, 0xD8, 0xFF))  # JPEG SOI，不用转义字面量免得写进源码就变样
    assert all(f[:3] == magic for f in frames), "抽出的不是 JPEG 帧"

