# -*- coding: utf-8 -*-
"""音频附件接线批（红灯）。

复核实状（本批自己命中，逐处可查）：

- 音频文件从网页上传口进来（`ChatComposerArea.vue:94` 的 accept 里有 `audio/*`），落到
  `chat_pipeline` 的附件注入单点后，与视频一样必然走 `extract_attachment_text` 的 None 分支
  （`attachment_parser.py:9` 明写 image/audio/video 不抽取文本）⇒ 本轮只留一句「未能抽取文本」，
  模型听到的是一段"文件读不出来"，而不是"用户说了一句话"。
- 仓内**已经有一条在役的语音文本化路**，且它的读侧一直在等数据：渠道入站语音由
  `voice_precheck.transcribe_voice_message` 转写后写 `metadata[VOICE_CONTEXT_KEY]`，
  `chat_pipeline.py:1881` 读它、`orchestrator.py:1655` 经 `voiceContextLines()` 渲进 prompt。
  ⇒ 本批不新造第二条注入通道：音频附件的转写文本写进**同一个键**，复用同一个读侧。
- 转写实现的取法也复用现成单点：`voice_precheck` 用的 `api/endpoints/audio._get_asr_manager()`
  （与 `/audio/transcribe` 同口径），不在管线里另接一份 ASR 引擎。
- 超时口径此前只有 `voice_precheck` 一份私有值 `_TRANSCRIBE_TIMEOUT_SECONDS = 20.0`；
  管线再写一个 20 就是第二个事实源，故本批把它提到 `voice_ingress`（该模块自陈是
  「渠道入站语音的口径唯一定义处」）共用。

判据形态：断「转写文本落在既有键上」「抽不到时诚实留原因」「音频不再走文本抽取分支」
「写侧不出现字面量键」「超时口径全仓只有一处定义」。转写这一 seam 的可注入形态比照
既有先例 `_read_attachment_bytes`。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from types import SimpleNamespace

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.voice_context_module import VOICE_CONTEXT_KEY
from tests.ast_scan import parseSource


def _audioAttachment() -> list:
    return [
        {
            "file_id": "aud-1",
            "filename": "会议录音.mp3",
            "file_type": "audio",
            "mime_type": "audio/mpeg",
            "size": 8192,
            "path": "storage/users/u1/会议录音.mp3",
        }
    ]


def _pipelineAndContext():
    pipeline = object.__new__(ChatPipeline)
    ctx = SimpleNamespace(
        user_input="这段录音里我答应了什么",
        metadata={"attachments": _audioAttachment()},
        context=None,
        _pending_vision_parts=None,
    )
    return pipeline, ctx


def test_audioAttachmentTranscriptLandsOnTheExistingVoiceContextKey(monkeypatch):
    """转写文本进既有 VOICE_CONTEXT_KEY（读侧一直在等它），历史里只留中性标记。"""
    pipeline, ctx = _pipelineAndContext()
    transcript = {"text": "我下周三前把报价发给你", "confidence": 0.93,
                  "language": "zh", "engine": "probe-asr", "duration_ms": 3100}
    async def fakeTranscribe(att):
        return transcript, ""

    monkeypatch.setattr(pipeline, "_transcribeAttachmentAudio", fakeTranscribe, raising=False)

    asyncio.run(pipeline._step_inject_attachments(ctx))

    landed = ctx.metadata.get(VOICE_CONTEXT_KEY) or {}
    assert landed.get("text") == "我下周三前把报价发给你", landed
    assert not ctx._pending_vision_parts
    assert "会议录音.mp3" in ctx.user_input
    # 「未能抽取文本」是"模型没听到"被伪装成"文件坏了"的形态，接线后不该再出现在这一路
    assert "未能抽取文本" not in ctx.user_input


def test_audioWithoutTranscriptDegradesHonestlyWithReason(monkeypatch):
    """转写不可得时诚实留痕：原因进本轮文本，且不写语音上下文键。"""
    pipeline, ctx = _pipelineAndContext()
    async def fakeTranscribe(att):
        return {}, "ASR 不可用：没有启用的语音引擎"

    monkeypatch.setattr(pipeline, "_transcribeAttachmentAudio", fakeTranscribe, raising=False)

    asyncio.run(pipeline._step_inject_attachments(ctx))

    assert VOICE_CONTEXT_KEY not in ctx.metadata
    assert "ASR 不可用：没有启用的语音引擎" in ctx.user_input


def test_audioIsNotReadThroughTextExtractor(monkeypatch):
    """音频不得再走文本抽取分支——那是「未能抽取文本」提示的唯一来源。"""
    called: list = []
    pipeline, ctx = _pipelineAndContext()
    async def fakeTranscribe(att):
        return {"text": "一句话", "confidence": 1.0}, ""

    monkeypatch.setattr(pipeline, "_transcribeAttachmentAudio", fakeTranscribe, raising=False)

    import neurova.attachment_parser as attachment_parser

    realExtract = attachment_parser.extract_attachment_text

    def spy(data, filename, file_type):
        called.append(file_type)
        return realExtract(data, filename, file_type)

    monkeypatch.setattr(attachment_parser, "extract_attachment_text", spy)

    asyncio.run(pipeline._step_inject_attachments(ctx))

    assert "audio" not in called


def test_transcriptWriterUsesTheSingleKeyNotALiteral():
    """写侧必须引 `VOICE_CONTEXT_KEY` 常量，不重拼字面量（重拼就是第三份词汇）。"""
    source = pathlib.Path("neurova/agent/chat_pipeline.py").read_text(encoding="utf-8")
    tree = parseSource(source)
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value == "voice_context":
                literals.append(node.value)
    assert not literals, f"chat_pipeline 里出现字面量键 voice_context 共 {len(literals)} 处"


def test_transcribeTimeoutIsDefinedOnceRepoWide():
    """转写超时只允许一处定义（管线与渠道预检共用同一个口径）。"""
    owner = pathlib.Path("neurova/channels/voice_ingress.py")
    assert owner.is_file(), "口径文件必须存在"
    definitions = []
    for path in pathlib.Path("neurova").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("TRANSCRIBE_TIMEOUT_SECONDS") and "=" in stripped:
                definitions.append(str(path))
            if stripped.startswith("_TRANSCRIBE_TIMEOUT_SECONDS") and "=" in stripped:
                definitions.append(str(path))
    assert len(definitions) == 1, f"转写超时被定义了 {len(definitions)} 次: {definitions}"
