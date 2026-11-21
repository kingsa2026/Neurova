"""
多模态能力启发式探测

通过文件扩展名、MIME 类型与模型名称的启发式匹配，
判断模型/素材的视觉/音频/视频能力。
"""

from __future__ import annotations

import json
from neurova.core.logger import get_logger
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from neurova.core.data_root import dataPath
from neurova.core.time_utils import nowIso as _now_iso

try:
    import aiohttp
except ImportError:  # 探测矩阵的 HTTP 层；测试经本模块命名空间打桩
    aiohttp = None

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


VISION_EXTS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "bmp",
    "webp",
    "svg",
    "tiff",
    "tif",
    "heic",
    "heif",
}
AUDIO_EXTS = {"mp3", "wav", "ogg", "flac", "m4a", "aac", "wma", "opus", "oga"}
VIDEO_EXTS = {"mp4", "avi", "mov", "mkv", "webm", "flv", "wmv", "m4v", "mpeg", "mpg"}

VISION_MODEL_KEYWORDS = (
    "vision",
    "gpt-4v",
    "gpt-4-v",
    "image",
    "multimodal",
    "llava",
    "qwen-vl",
    "qwen2-vl",
    "gemini",
    "claude-3",
    "claude-3.5",
    "pixtral",
    "internvl",
    "cogvlm",
    "yi-vl",
    "vl-",
    "-vl",
)
AUDIO_MODEL_KEYWORDS = (
    "whisper",
    "audio",
    "asr",
    "tts",
    "speech",
    "voice",
    "bark",
    "musicgen",
    "audiogen",
)
VIDEO_MODEL_KEYWORDS = ("video", "sora", "moviegen")


@dataclass
class ProbeRecord:
    id: str = field(default_factory=lambda: _new_id("probe_"))
    model_id: str = ""
    filename: str = ""
    mime_type: str = ""
    capabilities: List[str] = field(default_factory=list)
    confidence: float = 0.0
    method: str = ""
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProbeRecord":
        if not isinstance(data, dict):
            return cls()
        kwargs: Dict[str, Any] = {}
        for f in cls.__dataclass_fields__.values():
            if f.name in data:
                kwargs[f.name] = data[f.name]
        return cls(**kwargs)


class MultimodalProber:
    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "probes.json"
        self._records: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._records.update(data)
            except Exception as exc:
                logger.warning("Failed to load %s: %s", self._path, exc)
        else:
            self._save()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def detect_capabilities(
        self,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> ProbeRecord:
        caps: List[str] = []
        method_parts: List[str] = []
        confidence = 0.0

        ext = ""
        if filename:
            ext = os.path.splitext(filename)[1].lower().lstrip(".")
            if ext in VISION_EXTS:
                if "vision" not in caps:
                    caps.append("vision")
                method_parts.append("extension")
                confidence = max(confidence, 0.9)
            elif ext in AUDIO_EXTS:
                if "audio" not in caps:
                    caps.append("audio")
                method_parts.append("extension")
                confidence = max(confidence, 0.9)
            elif ext in VIDEO_EXTS:
                if "video" not in caps:
                    caps.append("video")
                method_parts.append("extension")
                confidence = max(confidence, 0.9)

        if mime_type:
            m = mime_type.lower().strip()
            if m.startswith("image/"):
                if "vision" not in caps:
                    caps.append("vision")
                method_parts.append("mime")
                confidence = max(confidence, 0.95)
            elif m.startswith("audio/"):
                if "audio" not in caps:
                    caps.append("audio")
                method_parts.append("mime")
                confidence = max(confidence, 0.95)
            elif m.startswith("video/"):
                if "video" not in caps:
                    caps.append("video")
                method_parts.append("mime")
                confidence = max(confidence, 0.95)

        mid = (model_id or "").lower().strip()
        if mid:
            vision_hit = any(kw in mid for kw in VISION_MODEL_KEYWORDS)
            audio_hit = any(kw in mid for kw in AUDIO_MODEL_KEYWORDS)
            video_hit = any(kw in mid for kw in VIDEO_MODEL_KEYWORDS)

            if vision_hit and "vision" not in caps:
                caps.append("vision")
                method_parts.append("model_name")
                confidence = max(confidence, 0.7)
            elif audio_hit and "audio" not in caps:
                caps.append("audio")
                method_parts.append("model_name")
                confidence = max(confidence, 0.7)
            elif video_hit and "video" not in caps:
                caps.append("video")
                method_parts.append("model_name")
                confidence = max(confidence, 0.7)

        if not caps:
            caps = ["text"]
            method_parts.append("fallback")
            confidence = max(confidence, 0.1)

        method = "+".join(method_parts) if method_parts else "unknown"

        rec = ProbeRecord(
            model_id=model_id or "",
            filename=filename or "",
            mime_type=mime_type or "",
            capabilities=caps,
            confidence=confidence,
            method=method,
        )

        with self._lock:
            self._records[rec.id] = rec.to_dict()
            self._save()
        return rec

    def is_vision(
        self,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        rec = self.detect_capabilities(filename=filename, mime_type=mime_type, model_id=model_id)
        return "vision" in rec.capabilities

    def is_audio(
        self,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        rec = self.detect_capabilities(filename=filename, mime_type=mime_type, model_id=model_id)
        return "audio" in rec.capabilities

    def is_video(
        self,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> bool:
        rec = self.detect_capabilities(filename=filename, mime_type=mime_type, model_id=model_id)
        return "video" in rec.capabilities

    def get_record(self, record_id: str) -> Optional[ProbeRecord]:
        with self._lock:
            data = self._records.get(record_id)
        if not data:
            return None
        return ProbeRecord.from_dict(data)

    def list_records(self, model_id: Optional[str] = None) -> List[ProbeRecord]:
        with self._lock:
            snapshot = [ProbeRecord.from_dict(d) for d in self._records.values()]
        if model_id:
            snapshot = [r for r in snapshot if r.model_id == model_id]
        return snapshot

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._save()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = len(self._records)
            by_capability: Dict[str, int] = {}
            by_method: Dict[str, int] = {}
            for d in self._records.values():
                for c in d.get("capabilities", []) or []:
                    by_capability[c] = by_capability.get(c, 0) + 1
                m = d.get("method", "unknown")
                by_method[m] = by_method.get(m, 0) + 1
        return {
            "total": total,
            "by_capability": by_capability,
            "by_method": by_method,
        }


_singleton: Optional[MultimodalProber] = None
_singleton_lock = threading.RLock()
_DEFAULT_DIR = dataPath("multimodal_prober")


def get_multimodal_prober() -> MultimodalProber:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = MultimodalProber(_DEFAULT_DIR)
    return _singleton


def reset_multimodal_prober() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


_MEDIA_KEYWORDS = (
    "image",
    "images",
    "vision",
    "multimodal",
    "photo",
    "picture",
    "audio",
    "speech",
    "voice",
    "sound",
    "music",
    "video",
    "movie",
    "clip",
    "media",
    "attachment",
    "input_image",
    "input_audio",
    "input_video",
    "image_url",
    "image_input",
    "content",
    "blob",
    "base64",
)


def _is_media_keyword_error(message: Any) -> bool:
    if not message:
        return False
    text = str(message).lower()
    if not text:
        return False
    if "no image" in text or "no audio" in text or "no video" in text:
        return True
    if "does not support" in text and any(
        k in text for k in ("image", "audio", "video", "vision", "media", "multimodal")
    ):
        return True
    if "unsupported" in text and any(k in text for k in ("image", "audio", "video", "vision", "media", "multimodal")):
        return True
    return any(kw in text for kw in _MEDIA_KEYWORDS)


def evaluate_image_probe_answer(answer: Any) -> Dict[str, Any]:
    if answer is None:
        return {"supports_vision": False, "confidence": 0.0, "reason": "empty"}
    text = str(answer).strip().lower()
    if not text:
        return {"supports_vision": False, "confidence": 0.0, "reason": "empty"}
    negative_markers = (
        "cannot",
        "can't",
        "unable",
        "no image",
        "not support",
        "do not see",
        "no visual",
        "no picture",
        "as a text model",
    )
    positive_markers = (
        "i see",
        "i can see",
        "the image",
        "this image",
        "shows",
        "depicts",
        "in the picture",
        "in the image",
        "describes",
    )
    if any(m in text for m in negative_markers):
        return {"supports_vision": False, "confidence": 0.85, "reason": "negative_marker"}
    if any(m in text for m in positive_markers):
        return {"supports_vision": True, "confidence": 0.85, "reason": "positive_marker"}
    return {"supports_vision": False, "confidence": 0.2, "reason": "no_marker"}


# ---------------------------------------------------------------------------
# 视觉探测矩阵（M7，2026-11-22）：按 provider 协议族构建真图探测请求。
#
# 此前只有 openai 一家发真图（openai_provider._image_probe_request），其余
# provider 的 probe_model_multimodal 是名称启发式（恒 supported=True）——
# 声明与实测的一致性无从对齐。矩阵把「红图 + 主色调提问」的请求形态按协议
# 族收口到本模块一处：openai 兼容族（openrouter/ollama/lm_studio/opencode…）、
# anthropic 原生 /v1/messages、gemini 原生 generateContent(inline_data)。
# 红图与提问复用 openai_provider 的既有单源（懒加载取用，不另造第二份）；
# HTTP 层经本模块命名空间的 aiohttp 打桩即可进 CI，真 Key 手动档走同一入口。
# ---------------------------------------------------------------------------

#: 纯红答案的判定词（与 openai_provider 的红图口径一致：答出红色系才算真看见）
_RED_ANSWER_KEYWORDS = ("red", "scarlet", "crimson", "红", "赤")

_GEMINI_PROVIDER_KINDS = frozenset({"gemini", "google", "google-vertex", "google-cn"})


@dataclass(frozen=True)
class ImageProbeRequest:
    """一个 provider 协议族的图像探测请求（protocol 决定答案提取口径）。"""

    protocol: str
    url: str
    headers: Dict[str, str]
    payload: Dict[str, Any]


def _probeAssets() -> "tuple[str, str]":
    """红图 base64 与提问文案（懒加载复用 openai_provider 的既有单源）。"""
    from neurova.llm.providers.openai_provider import OpenAIProvider, _redProbeSquareBase64

    return _redProbeSquareBase64(), OpenAIProvider._IMAGE_PROBE_PROMPT


def buildImageProbeRequest(
    providerType: str,
    modelId: str,
    baseUrl: str,
    apiKey: str,
) -> ImageProbeRequest:
    """provider 类型 → 该协议族的真图探测请求（纯函数，单一事实源）。

    未显式认识的类型一律按 OpenAI 兼容族处理（openrouter/ollama/lm_studio/
    opencode/deepseek 等都是 /chat/completions 形态）。
    """
    kind = (providerType or "").strip().lower()
    imageB64, prompt = _probeAssets()

    if kind == "anthropic":
        from neurova.llm.providers.anthropic_client import anthropic_endpoint_url

        return ImageProbeRequest(
            protocol="anthropic",
            url=anthropic_endpoint_url(baseUrl),
            headers={
                "x-api-key": apiKey or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            payload={
                "model": modelId,
                "max_tokens": 200,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": imageB64,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            },
        )

    if kind in _GEMINI_PROVIDER_KINDS:
        from neurova.llm.providers.gemini_client import geminiImagePartFromUrl

        base = (baseUrl or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        if "/v1beta" not in base:
            base = f"{base}/v1beta"
        short = (modelId or "").split("/")[-1]
        return ImageProbeRequest(
            protocol="gemini",
            url=f"{base}/models/{short}:generateContent",
            headers={"x-goog-api-key": apiKey or "", "Content-Type": "application/json"},
            payload={
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            geminiImagePartFromUrl(f"data:image/png;base64,{imageB64}"),
                            {"text": prompt},
                        ],
                    }
                ],
                "generationConfig": {"maxOutputTokens": 200},
            },
        )

    base = (baseUrl or "https://api.openai.com/v1").rstrip("/")
    return ImageProbeRequest(
        protocol="openai",
        url=f"{base}/chat/completions",
        headers={
            "Authorization": f"Bearer {apiKey or ''}",
            "Content-Type": "application/json",
        },
        payload={
            "model": modelId,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{imageB64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "max_tokens": 200,
            "stream": False,
        },
    )


def extractProbeAnswer(protocol: str, data: Dict[str, Any]) -> str:
    """按协议族从探测响应里提取模型文本答案。"""
    if protocol == "anthropic":
        blocks = data.get("content") or []
        texts = [
            str(b.get("text") or "")
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(t for t in texts if t)
    if protocol == "gemini":
        candidates = data.get("candidates") or [{}]
        parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
        return "\n".join(
            str(p.get("text") or "") for p in parts if isinstance(p, dict) and p.get("text")
        )
    choices = data.get("choices") or [{}]
    message = choices[0].get("message") or {}
    return str(message.get("content") or message.get("reasoning_content") or "")


async def _sendImageProbe(request: ImageProbeRequest, timeoutSeconds: float) -> str:
    """发探测请求并提取答案；HTTP >= 400 抛异常（由 probeProviderVision 归一）。"""
    if aiohttp is None:
        raise RuntimeError("aiohttp 未安装，无法进行图像探测")
    timeout = aiohttp.ClientTimeout(total=timeoutSeconds) if hasattr(aiohttp, "ClientTimeout") else None
    async with aiohttp.ClientSession() as session:
        kwargs: Dict[str, Any] = {"headers": request.headers, "json": request.payload}
        if timeout is not None:
            kwargs["timeout"] = timeout
        async with session.post(request.url, **kwargs) as response:
            if response.status >= 400:
                detail = ""
                try:
                    body = await response.json()
                    detail = str(body.get("error", {}).get("message", body))
                except Exception:  # noqa: BLE001 — body 解析失败保留状态码信息
                    detail = await response.text() if hasattr(response, "text") else ""
                exc = RuntimeError(f"HTTP {response.status}: {detail or 'probe rejected'}")
                exc.status_code = response.status
                raise exc
            data = await response.json()
            return extractProbeAnswer(request.protocol, data)


async def probeProviderVision(
    providerType: str,
    modelId: str,
    baseUrl: str,
    apiKey: str,
    timeoutSeconds: float = 20.0,
):
    """对任意 provider 协议族发真图探测，返回归一的 ProbeResult。

    - 答出红色系/正向看见 → supported=True + vision；
    - 请求被媒体关键词拒绝 → supported=False（probe_source=probed）；
    - 其他错误（限频/网络/网关）→ probe_source=inconclusive，不下结论；
    - 永不抛异常：探测失败必须归一返回，不炸调用链。
    """
    from neurova.llm.providers.openai_provider import OpenAIProvider
    from neurova.llm.providers.types import ProbeResult

    request = buildImageProbeRequest(providerType, modelId, baseUrl, apiKey)
    start_time = time.time()

    try:
        answer = await _sendImageProbe(request, timeoutSeconds)
    except Exception as e:  # noqa: BLE001 — 探测失败归一返回
        message = str(e).lower()
        if OpenAIProvider._is_media_keyword_error(message):
            return ProbeResult(
                model_id=modelId,
                supported=False,
                capabilities=[],
                latency_ms=(time.time() - start_time) * 1000,
                metadata={
                    "protocol": request.protocol,
                    "probe_source": "probed",
                    "probe_detail": "media_rejected",
                },
            )
        return ProbeResult(
            model_id=modelId,
            supported=False,
            capabilities=[],
            latency_ms=(time.time() - start_time) * 1000,
            metadata={
                "protocol": request.protocol,
                "probe_source": "inconclusive",
                "probe_detail": str(e)[:300],
            },
        )

    evaluation = evaluate_image_probe_answer(answer)
    answer_text = str(answer or "").strip()
    saw_red = any(k in answer_text.lower() for k in _RED_ANSWER_KEYWORDS)
    if evaluation.get("supports_vision") or saw_red:
        supported, source, capabilities = True, "probed", ["vision"]
    elif evaluation.get("confidence", 0) >= 0.5:
        supported, source, capabilities = False, "probed", []
    else:
        supported, source, capabilities = False, "inconclusive", []

    return ProbeResult(
        model_id=modelId,
        supported=supported,
        capabilities=capabilities,
        latency_ms=(time.time() - start_time) * 1000,
        metadata={
            "protocol": request.protocol,
            "probe_source": source,
            "probe_answer": answer_text[:200],
        },
    )
