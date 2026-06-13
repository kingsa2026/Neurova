"""
多模态能力启发式探测

通过文件扩展名、MIME 类型与模型名称的启发式匹配，
判断模型/素材的视觉/音频/视频能力。
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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


MEDIA_ERROR_KEYWORDS = (
    "image",
    "vision",
    "multimodal",
    "media",
    "picture",
    "photo",
    "audio",
    "speech",
    "voice",
    "video",
    "attachment",
    "unsupported",
    "not supported",
    "cannot process",
    "invalid content type",
    "binary",
    "base64",
    "mime",
    "data uri",
)


def _is_media_keyword_error(message: Any) -> bool:
    if message is None:
        return False
    try:
        text = str(message).lower()
    except Exception:
        return False
    if not text:
        return False
    return any(keyword in text for keyword in MEDIA_ERROR_KEYWORDS)


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
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/multimodal_prober"


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
