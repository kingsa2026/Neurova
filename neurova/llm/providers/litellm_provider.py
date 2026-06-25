"""
LiteLLM Provider

使用 litellm 库统一适配 100+ LLM 模型
支持: OpenAI, Anthropic, Google, AWS Bedrock, Azure, OpenRouter, Ollama 等

安装: pip install litellm
文档: https://docs.litellm.ai/
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.llm.providers.base import BaseProvider
from neurova.llm.providers.types import (
    ModelInfo,
    ProbeResult,
    ProviderCapability,
    ProviderType,
)

try:
    import litellm

    _LITELLM_AVAILABLE = True
except ImportError:
    litellm = None
    _LITELLM_AVAILABLE = False


logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


_CAPABILITY_ALIASES = {
    "text": ProviderCapability.TEXT,
    "vision": ProviderCapability.VISION,
    "image": ProviderCapability.VISION,
    "audio": ProviderCapability.AUDIO,
    "video": ProviderCapability.VIDEO,
    "image_generation": ProviderCapability.IMAGE_GENERATION,
    "video_generation": ProviderCapability.VIDEO_GENERATION,
    "tts": ProviderCapability.TTS,
    "stt": ProviderCapability.STT,
    "multimodal": ProviderCapability.MULTIMODAL,
    "tool_use": ProviderCapability.TOOL_USE,
    "function_calling": ProviderCapability.TOOL_USE,
    "tools": ProviderCapability.TOOL_USE,
}


def _parse_capability(name: str) -> ProviderCapability:
    if not name:
        return ProviderCapability.TEXT
    key = str(name).strip().lower()
    if key in _CAPABILITY_ALIASES:
        return _CAPABILITY_ALIASES[key]
    try:
        return ProviderCapability(key)
    except ValueError:
        return ProviderCapability.TEXT


def _infer_capabilities_from_model_info(
    model_info: Dict[str, Any],
) -> List[ProviderCapability]:
    caps: List[ProviderCapability] = [ProviderCapability.TEXT]
    if not isinstance(model_info, dict):
        return caps
    name = str(model_info.get("model_name") or model_info.get("name") or "").lower()
    info_caps = model_info.get("capabilities") or model_info.get("supported_capabilities")
    if isinstance(info_caps, list):
        for entry in info_caps:
            try:
                parsed = _parse_capability(str(entry))
                if parsed not in caps:
                    caps.append(parsed)
            except Exception:
                pass
    if "vision" in name or "image" in name or "multimodal" in name:
        if ProviderCapability.VISION not in caps:
            caps.append(ProviderCapability.VISION)
        if ProviderCapability.MULTIMODAL not in caps:
            caps.append(ProviderCapability.MULTIMODAL)
    if model_info.get("supports_function_calling") is True or model_info.get("function_calling") is True:
        if ProviderCapability.TOOL_USE not in caps:
            caps.append(ProviderCapability.TOOL_USE)
    if model_info.get("supports_audio") is True:
        if ProviderCapability.AUDIO not in caps:
            caps.append(ProviderCapability.AUDIO)
    return caps


_DEFAULT_MODELS: List[str] = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5-turbo",
    "claude-3-5-sonnet",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-pro",
    "ollama/llama2",
    "ollama/llama3",
    "ollama/mistral",
    "ollama/codellama",
    "ollama/phi",
    "openrouter/anthropic/claude-3-opus",
    "openrouter/openai/gpt-4o",
    "bedrock/anthropic.claude-3-sonnet",
    "azure/gpt-4",
    "command-r-plus",
    "mixtral-8x7b",
    "llama2-70b",
    "deepseek-chat",
    "qwen-plus",
]


_DEFAULT_HISTORY_DIR = "./data/litellm_history"


_singleton: Optional["LiteLLMProvider"] = None
_singleton_lock = threading.Lock()


class LiteLLMProvider(BaseProvider):
    """LiteLLMProvider"""

    _DEFAULT_PROVIDER_TYPE = ProviderType.OPENAI

    def __init__(
        self,
        provider_id: str = "litellm",
        api_key: str = "",
        base_url: str = "",
        history_dir: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            provider_type=self._DEFAULT_PROVIDER_TYPE,
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
        self._history_dir = history_dir or _DEFAULT_HISTORY_DIR
        self._history_path = Path(self._history_dir) / "history.json"
        self._history: List[Dict[str, Any]] = []
        self._history_lock = threading.RLock()
        self._litellm_available = _LITELLM_AVAILABLE
        self._load_history()

    def _load_history(self) -> None:
        with self._history_lock:
            self._history = []
            if not self._history_path.exists():
                return
            try:
                data = json.loads(self._history_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._history = [e for e in data if isinstance(e, dict)]
            except Exception as exc:
                logger.warning("Failed to load history %s: %s", self._history_path, exc)

    def _save_history(self) -> None:
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._history_path.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save history %s: %s", self._history_path, exc)

    def record_request_history(
        self,
        model_id: str,
        success: bool,
        latency_ms: float = 0.0,
        error: str = "",
    ) -> None:
        entry: Dict[str, Any] = {
            "id": _new_id("rh_"),
            "model_id": str(model_id),
            "success": bool(success),
            "latency_ms": float(latency_ms),
            "error": str(error) if error else "",
            "timestamp": _now_iso(),
        }
        with self._history_lock:
            self._history.append(entry)
            self._save_history()

    def get_request_history(
        self,
        model_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        with self._history_lock:
            items = list(self._history)
        if model_id is not None:
            items = [e for e in items if e.get("model_id") == model_id]
        if limit is not None and limit >= 0:
            items = items[-limit:]
        return items

    def clear_request_history(self) -> None:
        with self._history_lock:
            self._history = []
            self._save_history()

    def get_supported_models(self) -> List[str]:
        models = list(_DEFAULT_MODELS)
        if self._config.get("extra_models"):
            extras = self._config["extra_models"]
            if isinstance(extras, list):
                for m in extras:
                    if isinstance(m, str) and m not in models:
                        models.append(m)
        return models

    def is_model_supported(self, model_id: str) -> bool:
        if not model_id:
            return False
        needle = str(model_id).lower().strip()
        if not needle:
            return False
        for m in self.get_supported_models():
            if m.lower() == needle:
                return True
        for m in self.get_supported_models():
            base = m.split("/")[-1].lower()
            if base and base in needle:
                return True
        return False

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        if not model_id:
            return None
        if not self.is_model_supported(model_id):
            return None
        provider_type = self._determine_provider_type(model_id)
        caps = _infer_capabilities_from_model_info({"model_name": model_id})
        return {
            "id": model_id,
            "name": model_id,
            "provider": self.provider_id,
            "provider_type": provider_type.value,
            "capabilities": [c.value for c in caps],
            "metadata": {"source": "litellm_provider"},
        }

    def _determine_provider_type(self, model_id: str) -> ProviderType:
        if not model_id:
            return ProviderType.CUSTOM
        mid = str(model_id).lower().strip()
        if not mid:
            return ProviderType.CUSTOM
        if mid.startswith("ollama/") or mid.startswith("ollama:") or "/ollama" in mid:
            return ProviderType.OLLAMA
        if "ollama" in mid.split("/")[0:1]:
            return ProviderType.OLLAMA
        if mid.startswith("openrouter/") or "/openrouter" in mid:
            return ProviderType.OPENROUTER
        if mid.startswith("claude") or "claude" in mid or "anthropic" in mid:
            return ProviderType.ANTHROPIC
        if "gpt" in mid or mid.startswith("openai/") or "openai" in mid.split("/")[0]:
            return ProviderType.OPENAI
        if "gemini" in mid or "palm" in mid or mid.startswith("google/"):
            return ProviderType.GEMINI
        if mid.startswith("bedrock/") or "bedrock" in mid:
            return ProviderType.CUSTOM
        if mid.startswith("azure/"):
            return ProviderType.OPENAI
        return ProviderType.CUSTOM

    async def get_available_models(self) -> List[ModelInfo]:
        out: List[ModelInfo] = []
        for mid in self.get_supported_models():
            try:
                caps = _infer_capabilities_from_model_info({"model_name": mid})
                ptype = self._determine_provider_type(mid)
                out.append(
                    ModelInfo(
                        id=mid,
                        name=mid,
                        provider=self.provider_id,
                        provider_type=ptype,
                        capabilities=caps,
                    )
                )
            except Exception:
                continue
        return out

    async def create_chat_model(self, model_id: str, **kwargs: Any) -> Any:
        if not self._litellm_available:
            raise RuntimeError(
                "litellm is not installed. Install with `pip install litellm` to use create_chat_model()."
            )
        cfg = {
            "model": model_id,
            "api_key": self.api_key or None,
            "base_url": self.base_url or None,
        }
        if kwargs:
            cfg.update(kwargs)
        cfg = {k: v for k, v in cfg.items() if v is not None}
        try:
            return litellm.completion(**cfg)
        except Exception as exc:
            logger.error("create_chat_model failed for %s: %s", model_id, exc)
            raise

    async def probe_model_multimodal(self, model_id: str) -> ProbeResult:
        if not self.is_model_supported(model_id):
            return ProbeResult(
                model_id=model_id,
                supported=False,
                capabilities=[],
                error="model not supported",
            )
        caps = _infer_capabilities_from_model_info({"model_name": model_id})
        return ProbeResult(
            model_id=model_id,
            supported=True,
            capabilities=caps,
        )

    def supports_capability(self, capability: ProviderCapability) -> bool:
        return capability in _infer_capabilities_from_model_info({})


def get_litellm_provider() -> LiteLLMProvider:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = LiteLLMProvider()
    return _singleton


def reset_litellm_provider() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None


def list_supported_models() -> List[str]:
    provider = get_litellm_provider()
    return provider.get_supported_models()
