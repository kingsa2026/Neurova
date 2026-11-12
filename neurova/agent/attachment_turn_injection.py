"""附件进本轮的组装面（从 `chat_pipeline` 抽出，热路径文件的尺寸天花板见
`scripts/ci/perf_gate.py::check_hot_path_file_size`）。

这里只放**组装**：把附件的字节/帧/转写产物变成「本轮 user_input 的段落 + vision 切片」。
四类附件的分派规则、失败原因的字面形态、图像切片的拼法都在本模块一处定义；
`chat_pipeline` 那侧只留薄转发，不重复任何一条口径。

几条不能破的既有契约（搬动时逐条保留，它们各有判据）：

- **视频走图像那一条 vision 通道**，帧与真图片共用同一份拼法（`visionImagePart`）——
  另拼一份，尺寸闸门与编码口径就成了第二事实源，413 防线只在图片轮生效；
- **音频写进 `VOICE_CONTEXT_KEY` 那份既有读侧**，不在管线里另开第二条语音注入路；
- **抽帧与转写的 seam 仍是管线上的方法**（`_extractAttachmentFrames` /
  `_transcribeAttachmentAudio`），实现上它们转发到本模块——判据的装配点因此不变，
  搬动不改变任何一格的 monkeypatch 面。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 按「抽帧进模型」处理的附件类型。
MEDIA_ATTACHMENT_FILE_TYPES = frozenset({"video"})

#: 按「转写进语音上下文」处理的附件类型——转写文本走 `VOICE_CONTEXT_KEY` 那份既有读侧，
#: 不在管线里另开第二条语音注入路。
AUDIO_ATTACHMENT_FILE_TYPES = frozenset({"audio"})


def visionImagePart(data: bytes, mimeType: str) -> Dict[str, Any]:
    """把一张静图装成 OpenAI image_url 切片（真图片与视频抽出的帧共用这一份拼法）。

    归一化 → base64 → data URL 三步只允许一处定义：视频帧若另拼一份，尺寸闸门与
    编码口径就有了第二事实源，大图撑爆请求（413）这类防线会只在图片轮生效。
    """
    import base64

    from neurova.attachment_parser import normalize_image_for_llm

    normalized, mime = normalize_image_for_llm(data, mimeType)
    encoded = base64.b64encode(normalized).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def extractAttachmentFrames(pipeline: Any, attachment: Dict) -> Tuple[List[bytes], str]:
    """把一个视频附件抽成帧字节：路径解析与抽帧各走自己的单点。

    路径只认 `file_id` 经服务端记账解析出来的落点——附件字典里那个客户端传来的 `path`
    是路径穿越面，不采信。抽帧走 `neurova.media.keyframes`（ffmpeg 路径解析复用
    `core.ffmpeg` 单点），本函数不重复实现任何一层的解析口径。
    """
    file_id = str(attachment.get("file_id") or "")
    if not file_id:
        return [], "附件缺少 file_id，无法定位磁盘上的视频"
    try:
        from neurova.api.endpoints import files_api

        resolved = files_api.resolveAttachmentPath(file_id)
    except (OSError, ImportError, RuntimeError) as exc:
        return [], f"附件路径解析失败：{exc}"
    if resolved is None:
        return [], f"视频不在盘上（file_id={file_id}）"
    from neurova.media.keyframes import extractKeyframes

    return extractKeyframes(str(resolved))


async def resolveAttachmentFrames(
    pipeline: Any, attachments: List[Dict]
) -> Dict[str, Tuple[List[bytes], str]]:
    """对每个媒体附件抽帧，阻塞子进程放别的线程（同 aigc_studio 的合片口径）。

    无媒体附件时**零副作用**：不 import ffmpeg、不起进程，普通文本轮一分成本都不多付。
    """
    media = [
        att
        for att in attachments
        if isinstance(att, dict) and att.get("file_type") in MEDIA_ATTACHMENT_FILE_TYPES
    ]
    if not media:
        return {}

    results = await asyncio.gather(
        *(asyncio.to_thread(pipeline._extractAttachmentFrames, att) for att in media),
        return_exceptions=True,
    )
    resolved: Dict[str, Tuple[List[bytes], str]] = {}
    for att, result in zip(media, results):
        fileId = str(att.get("file_id") or "")
        if isinstance(result, tuple):
            resolved[fileId] = result
        else:
            resolved[fileId] = ([], f"抽帧异常：{result}")
    return resolved


async def transcribeAttachmentAudio(
    pipeline: Any, attachment: Dict
) -> Tuple[Dict[str, Any], str]:
    """把音频附件转写成 ASR 原产物 dict（引擎取法与超时口径都在 `voice_ingress`）。

    返回 `(转写产物, 失败原因)`：成功时原因为空串，失败时产物为空 dict——两侧都不许
    空手，静默失败会让这一轮看起来"用户什么都没说"。
    """
    file_id = str(attachment.get("file_id") or "")
    if not file_id:
        return {}, "附件缺少 file_id，无法定位磁盘上的音频"
    data = pipeline._read_attachment_bytes(file_id)
    if not data:
        return {}, "音频字节不在盘上"

    from neurova.channels.voice_ingress import TRANSCRIBE_TIMEOUT_SECONDS

    try:
        from neurova.channels.voice_ingress import getAsrTranscriber

        transcriber = getAsrTranscriber()
        result = await asyncio.wait_for(transcriber(data), timeout=TRANSCRIBE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return {}, f"转写超时（>{TRANSCRIBE_TIMEOUT_SECONDS} 秒）"
    except (OSError, RuntimeError, ValueError) as exc:
        return {}, f"转写失败：{exc}"

    text = str(result.get("text") or "").strip() if isinstance(result, dict) else ""
    if not text:
        return {}, "ASR 返回空文本"
    return result, ""


async def resolveAttachmentTranscripts(
    pipeline: Any, attachments: List[Dict]
) -> Dict[str, Tuple[Dict[str, Any], str]]:
    """逐个音频附件转写。

    无音频附件时**零副作用**：不 import 语音入口、不取 ASR 引擎，普通文本轮一分成本都不多付。
    顺序转写而不是并发：本地 ASR 多为单实例，并发只会排队并放大超时面。
    """
    audio = [
        att
        for att in attachments
        if isinstance(att, dict) and att.get("file_type") in AUDIO_ATTACHMENT_FILE_TYPES
    ]
    transcripts: Dict[str, Tuple[Dict[str, Any], str]] = {}
    for att in audio:
        transcripts[str(att.get("file_id") or "")] = await pipeline._transcribeAttachmentAudio(att)
    return transcripts


def injectAttachmentsIntoInput(
    pipeline: Any,
    userInput: str,
    attachments: List[Dict],
    mediaFrames: Optional[Dict[str, Tuple[List[bytes], str]]] = None,
    audioTranscripts: Optional[Dict[str, Tuple[Dict[str, Any], str]]] = None,
    noticeComposer: Optional[Any] = None,
) -> Tuple[str, List[Dict]]:
    """把附件并入用户文本；图像与视频帧单独收集为 vision content parts。

    `noticeComposer` 是「抽取不到文本」那句文案的单源构造点，由调用方传入
    （它的定义留在 `chat_pipeline`，判据按那个模块名 monkeypatch）。
    """
    from neurova.attachment_parser import extract_attachment_text

    parts: List[str] = []
    if userInput:
        parts.append(userInput)
    vision_parts: List[Dict] = []

    for att in attachments:
        filename = att.get("filename") or "附件"
        file_type = att.get("file_type") or "file"
        mime = att.get("mime_type") or "application/octet-stream"
        file_id = att.get("file_id") or ""

        if file_type in MEDIA_ATTACHMENT_FILE_TYPES:
            # 视频在抽帧之前不进文本抽取分支：`extract_attachment_text` 对 video 恒返回
            # None（attachment_parser 规格明写不抽取），于是本轮只剩一句"未能抽取文本"——
            # 那是"模型没看到视频"被伪装成"文件读不出来"的根因处。
            frames, reason = (mediaFrames or {}).get(str(file_id)) or ([], "本轮未执行抽帧")
            if frames:
                parts.append(
                    f"[用户上传了视频: {filename}（已抽取 {len(frames)} 帧随本轮请求附上）]"
                )
                vision_parts.extend(
                    visionImagePart(frame, "image/jpeg") for frame in frames
                )
            else:
                parts.append(
                    f"[用户上传了视频: {filename}（本轮未能看到画面） 原因: {reason}]"
                )
            continue

        if file_type in AUDIO_ATTACHMENT_FILE_TYPES:
            # 与视频同一条道理：音频走文本抽取恒返回 None，于是"模型没听到"被写成"文件读不出来"。
            transcript, reason = (audioTranscripts or {}).get(str(file_id)) or (
                {}, "本轮未执行转写"
            )
            if transcript:
                parts.append(
                    f"[用户上传了音频: {filename}（已转写为文本，随本轮语音上下文附上）]"
                )
            else:
                parts.append(
                    f"[用户上传了音频: {filename}（本轮未能转写） 原因: {reason}]"
                )
            continue

        try:
            data = pipeline._read_attachment_bytes(file_id)
        except Exception:
            data = None

        if file_type == "image" and data:
            # 大图归一化：超闸门图片降采样重编码，防 413 request_too_large
            vision_parts.append(visionImagePart(data, mime))
            # 持久化通道只留中性标记：指令不能进历史（2026-09-09 串台事故——
            # 图片 base64 只挂当轮请求，历史里的"请结合图片回答"对后续文本轮
            # 是一条无图可依、无法履行的指令，弱模型被带偏去文件系统找图）；
            # 当轮指令由 _apply_vision_attachments 挂到请求级 text part。
            parts.append(f"[用户上传了图片: {filename}（图片已随本轮请求附上）]")
            continue

        text, status = extract_attachment_text(data, filename, file_type)
        if text:
            parts.append(
                f"[用户上传了文件 {filename}，以下为该文件的完整内容（请直接使用，无需调用工具读取）]\n{text}"
            )
        else:
            from neurova.attachment_parser import suggestExtractionPrimitive

            # 抽取失败一律留痕：`unsupported_format` 此前被显式排除在日志外，
            # 于是事故轮在日志里零痕迹，问题只能靠人肉复现（T-03 的缺口信号
            # 也要读得到它，故级别取 warning）。
            logger.warning(
                "[附件注入] %s（%s）未抽取文本: %s（file_id=%s）",
                filename,
                file_type,
                status,
                file_id or "缺失",
            )
            # S1 生产点（T-03）：这里才知道"这个附件真读不出内容"，
            # `status` 也是抽取器给的那一份。缺口驱动入口消费它。
            from neurova.agent.capability_gap import noteAttachmentSignal

            noteAttachmentSignal(filename, file_type, file_id, status)
            parts.append(
                (noticeComposer or _defaultNotice)(
                    filename=filename,
                    file_type=file_type,
                    status=status,
                    file_id=file_id,
                    primitive=suggestExtractionPrimitive(filename, file_type),
                )
            )

    return "\n\n".join(parts), vision_parts


def _defaultNotice(**kwargs: Any) -> str:
    """兜底文案（仅当调用方没传 `noticeComposer` 时用；生产一律由管线传入单源构造）。"""
    from neurova.agent.chat_pipeline import composeUnparseableAttachmentNotice

    return composeUnparseableAttachmentNotice(**kwargs)
