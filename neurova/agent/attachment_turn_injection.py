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
import os
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


#: 服务商视觉通道普遍接受的位图 MIME（OpenAI / Anthropic / Gemini 同此集合）。
#: 集合外的图要么转码进来，要么诚实拒发——不发必被服务商拒收的原件。
LLM_SUPPORTED_IMAGE_MIMES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp"}
)


def _reencodeToSupportedImage(data: bytes) -> Optional[Tuple[bytes, str]]:
    """把视觉通道不收的位图（AVIF/HEIC/BMP/TIFF…）转码成 PNG/JPEG。

    成功返回 (bytes, mime)；字节解不开（含 SVG 这类非位图矢量格式）返回 None
    ——拒发的决定与文案由调用方落地，这里不静默吞。
    """
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
        hasAlpha = img.mode in ("RGBA", "LA", "PA") or (
            img.mode == "P" and "transparency" in img.info
        )
        out = io.BytesIO()
        if hasAlpha:
            img.save(out, "PNG")
            return out.getvalue(), "image/png"
        img.convert("RGB").save(out, "JPEG", quality=90)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - 解不开就如实上报，不猜格式
        return None


def imagePartForLlm(data: bytes, mime: str, filename: str = "") -> Tuple[Optional[Dict], Optional[str]]:
    """图片附件 → 视觉切片的一道闸：支持格式直装，其余转码兜底或诚实拒发。

    - 支持集合内：走 `visionImagePart`（归一化→base64→data URL 单源）；
    - 集合外但 PIL 可解码（AVIF 等）：先转码成 PNG/JPEG 再装——模型真看得到画面，
      而不是发一张必被服务商拒收的原件（对齐"媒体引用兜底"语义）；
    - SVG（按 mime 或扩展名识别）与解不开的字节：不装切片，返回诚实原因
      （拒发留痕，不静默丢图）。

    返回 `(切片, 拒发原因)`：切片为 None 时原因必非空，二者不会同时为空。
    """
    mime = (mime or "").lower()
    if mime in LLM_SUPPORTED_IMAGE_MIMES:
        return visionImagePart(data, mime), None

    converted = _reencodeToSupportedImage(data)
    if converted is None:
        ext = os.path.splitext(filename or "")[1].lower()
        if mime == "image/svg+xml" or ext == ".svg":
            return None, "SVG 矢量图不在视觉通道支持集内，且无法转码成位图"
        return None, (
            f"图片格式 {mime or '未知'} 不在视觉通道支持集内，且字节无法解码转码"
        )
    return visionImagePart(converted[0], converted[1]), None


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


def resolveAttachmentBudgetTokens(pipeline: Any) -> Optional[int]:
    """本轮附件注入可用的文本预算（P1-5，保守口径）。

    附件注入早于 `build_context`，会话既有占用在该点不可得；故只对本轮
    **新增附件**设上限：上限 = 模型预算 × `CONTEXT_COMPACT_TRIGGER_RATIO`
    （压缩触发线以下的空间，预算经 `ContextPool.get_token_budget_for_model`
    单源计算）。附件载荷自身不越过触发线 ⇒ 附件永不成为压缩的触发者。
    拿不到模型名/预算 → None（调用方走透传计划，不造数）。
    """
    try:
        model = str(pipeline._current_model_name() or "")
    except Exception:
        return None
    if not model:
        return None
    try:
        from neurova.context_pool import CONTEXT_COMPACT_TRIGGER_RATIO, ContextPool

        budget = int(ContextPool.get_token_budget_for_model(model))
        if budget <= 0:
            return None
        return max(0, int(budget * CONTEXT_COMPACT_TRIGGER_RATIO))
    except Exception:
        return None


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

    P1-5 预算闸：文本段先经 `attachment_budget.planAttachmentInjection` 判据
    ——预算内全文并入，超预算转"预览 + 句柄说明"；拿不到模型预算时透传
    （行为与既往一致）。vision 切片不走这份文本预算（它们有自己的尺寸闸门）。
    """
    from neurova.attachment_parser import extract_attachment_text
    from neurova.context.attachment_budget import (
        DECISION_PREVIEW,
        planAttachmentInjection,
    )

    # 第一遍：逐附件产出"全文并入"形态（口径与既往一致），预算判据在其上裁剪。
    # 元素 = (附件元数据, 全文段落, 可截断正文, vision 切片)。
    rendered: List[Tuple[Dict, str, str, List[Dict]]] = []
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
                fullText = (
                    f"[用户上传了视频: {filename}（已抽取 {len(frames)} 帧随本轮请求附上）]"
                )
                segVision = [visionImagePart(frame, "image/jpeg") for frame in frames]
            else:
                fullText = f"[用户上传了视频: {filename}（本轮未能看到画面） 原因: {reason}]"
                segVision = []
            rendered.append((att, fullText, "", segVision))
            continue

        if file_type in AUDIO_ATTACHMENT_FILE_TYPES:
            # 与视频同一条道理：音频走文本抽取恒返回 None，于是"模型没听到"被写成"文件读不出来"。
            transcript, reason = (audioTranscripts or {}).get(str(file_id)) or (
                {}, "本轮未执行转写"
            )
            if transcript:
                fullText = (
                    f"[用户上传了音频: {filename}（已转写为文本，随本轮语音上下文附上）]"
                )
            else:
                fullText = f"[用户上传了音频: {filename}（本轮未能转写） 原因: {reason}]"
            rendered.append((att, fullText, "", []))
            continue

        try:
            data = pipeline._read_attachment_bytes(file_id)
        except Exception:
            data = None

        if (file_type == "image" or mime.lower().startswith("image/")) and data:
            # 图片格式闸：支持格式直装；AVIF 等非常规位图转码兜底；SVG/解不开的
            # 拒发留痕——不把必被服务商拒收的原件发出去，也不静默丢图。
            part, refusalReason = imagePartForLlm(data, mime, filename)
            if part is not None:
                # 超闸门大图在 visionImagePart 内降采样重编码，防 413 request_too_large
                # 持久化通道只留中性标记：指令不能进历史（2026-09-09 串台事故——
                # 图片 base64 只挂当轮请求，历史里的"请结合图片回答"对后续文本轮
                # 是一条无图可依、无法履行的指令，弱模型被带偏去文件系统找图）；
                # 当轮指令由 _apply_vision_attachments 挂到请求级 text part。
                rendered.append(
                    (att, f"[用户上传了图片: {filename}（图片已随本轮请求附上）]", "", [part])
                )
            else:
                logger.warning(
                    "[附件注入] 图片 %s（%s）拒发: %s（file_id=%s）",
                    filename,
                    mime,
                    refusalReason,
                    file_id or "缺失",
                )
                rendered.append(
                    (
                        att,
                        f"[用户上传了图片: {filename}（本轮未能看到画面） 原因: {refusalReason}]",
                        "",
                        [],
                    )
                )
            continue

        text, status = extract_attachment_text(data, filename, file_type)
        if text:
            rendered.append(
                (
                    att,
                    f"[用户上传了文件 {filename}，以下为该文件的完整内容（请直接使用，无需调用工具读取）]\n{text}",
                    text,
                    [],
                )
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
            notice = (noticeComposer or _defaultNotice)(
                filename=filename,
                file_type=file_type,
                status=status,
                file_id=file_id,
                primitive=suggestExtractionPrimitive(filename, file_type),
            )
            rendered.append((att, notice, "", []))

    # 第二遍：预算判据（单源）裁剪——预算内全文并入，超预算转"预览 + 句柄说明"。
    budget = resolveAttachmentBudgetTokens(pipeline)
    plan = planAttachmentInjection(
        attachments=[
            {
                "file_id": str(att.get("file_id") or ""),
                "filename": str(att.get("filename") or "附件"),
                "file_type": str(att.get("file_type") or "file"),
                "full_text": fullText,
                "body": body,
            }
            for att, fullText, body, _vision in rendered
        ],
        remaining_budget_tokens=budget,
    )
    if not plan.isValid():
        logger.warning(
            "[附件预算] 计划超预算（不应发生）：total=%s budget=%s",
            plan.total_used_tokens,
            budget,
        )

    parts: List[str] = []
    if userInput:
        parts.append(userInput)
    vision_parts: List[Dict] = []
    for (_att, _fullText, _body, segVision), decision in zip(rendered, plan.decisions):
        if decision.decision == DECISION_PREVIEW:
            logger.info(
                "[附件预算] %s 超预算转预览：保留 %d/%d 字符（预算 %s token）",
                decision.file_id or decision.filename,
                decision.preview_chars,
                decision.preview_chars + decision.truncated_chars,
                budget,
            )
        if decision.injected_text:
            parts.append(decision.injected_text)
        vision_parts.extend(segVision)

    return "\n\n".join(parts), vision_parts


def _defaultNotice(**kwargs: Any) -> str:
    """兜底文案（仅当调用方没传 `noticeComposer` 时用；生产一律由管线传入单源构造）。"""
    from neurova.agent.chat_pipeline import composeUnparseableAttachmentNotice

    return composeUnparseableAttachmentNotice(**kwargs)
