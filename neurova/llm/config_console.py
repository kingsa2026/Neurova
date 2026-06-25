"""LLM 配置控制台

提供 LLM 提供商配置、模型选择、参数调优和 Token 使用统计功能。

功能:
1. LLM 提供商配置界面 API
2. 模型选择与管理
3. 参数调优（temperature, top_p, etc.）
4. Token 使用统计
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


_DEFAULT_CONFIG_PATH = "./data/llm_config.json"
_DEFAULT_PARAMS: Dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 1.0,
    "max_tokens": 4096,
}
_PROVIDER_REQUIRED_FIELDS = ("name", "provider_type")
_DEFAULT_PROVIDER_PARAMS: Dict[str, Any] = {
    "temperature": 0.7,
    "top_p": 1.0,
    "max_tokens": 4096,
}


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class LLMConfigConsole:
    """LLM 提供商配置 / 参数 / Token 统计 控制台。"""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._path = Path(config_path) if config_path else self._get_default_config_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._providers: Dict[str, Dict[str, Any]] = {}
        self._default_params: Dict[str, Any] = dict(_DEFAULT_PARAMS)
        self._default_provider_id: Optional[str] = None
        self._selected_model: Optional[str] = None
        self._provider_params: Dict[str, Dict[str, Any]] = {}
        self._models: Dict[str, Dict[str, Any]] = {}
        self._token_usage: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self._load()

    def _get_default_config_path(self) -> Path:
        return Path(_DEFAULT_CONFIG_PATH)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load LLM config %s: %s", self._path, exc)
            return
        if not isinstance(data, dict):
            return
        providers = data.get("providers")
        if isinstance(providers, dict):
            for pid, pdata in providers.items():
                if isinstance(pdata, dict):
                    pdata.setdefault("id", pid)
                    self._providers[pid] = pdata
        elif isinstance(providers, list):
            for pdata in providers:
                if isinstance(pdata, dict) and pdata.get("id"):
                    self._providers[pdata["id"]] = pdata
        default_params = data.get("default_params")
        if isinstance(default_params, dict):
            merged = dict(_DEFAULT_PARAMS)
            for key in _DEFAULT_PARAMS:
                if key in default_params:
                    merged[key] = default_params[key]
            self._default_params = merged
        self._default_provider_id = data.get("default_provider_id")
        self._selected_model = data.get("selected_model")
        provider_params = data.get("provider_params")
        if isinstance(provider_params, dict):
            for pid, params in provider_params.items():
                if isinstance(params, dict):
                    self._provider_params[pid] = dict(params)
        models = data.get("models")
        if isinstance(models, dict):
            self._models = {mid: dict(m) for mid, m in models.items() if isinstance(m, dict)}
        token_usage = data.get("token_usage")
        if isinstance(token_usage, list):
            for entry in token_usage:
                if isinstance(entry, dict):
                    self._token_usage.append(dict(entry))

    def _save(self) -> None:
        payload = {
            "providers": self._providers,
            "default_params": self._default_params,
            "default_provider_id": self._default_provider_id,
            "selected_model": self._selected_model,
            "provider_params": self._provider_params,
            "models": self._models,
            "token_usage": self._token_usage,
        }
        try:
            self._path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save LLM config %s: %s", self._path, exc)

    def _provider_to_dict(self, provider: Dict[str, Any]) -> Dict[str, Any]:
        return dict(provider)

    def list_providers(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._provider_to_dict(p) for p in self._providers.values()]

    def get_provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self._providers.get(provider_id)
            return self._provider_to_dict(p) if p else None

    def add_provider(self, data: Dict[str, Any]) -> str:
        if not isinstance(data, dict):
            raise ValueError("Provider data must be a dict")
        for field in _PROVIDER_REQUIRED_FIELDS:
            if field not in data or data[field] in (None, ""):
                raise ValueError(f"Provider missing required field: {field}")
        with self._lock:
            pid = _new_id("pv_")
            record = {
                "id": pid,
                "name": str(data["name"]),
                "provider_type": str(data["provider_type"]),
                "enabled": bool(data.get("enabled", True)),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            for key, value in data.items():
                if key in ("id", "created_at", "updated_at"):
                    continue
                record[key] = value
            self._providers[pid] = record
            if self._default_provider_id is None:
                self._default_provider_id = pid
            self._save()
            return pid

    def update_provider(self, provider_id: str, fields: Dict[str, Any]) -> bool:
        if not isinstance(fields, dict):
            return False
        with self._lock:
            provider = self._providers.get(provider_id)
            if not provider:
                return False
            for key, value in fields.items():
                if key == "id":
                    continue
                provider[key] = value
            provider["updated_at"] = _now_iso()
            self._save()
            return True

    def remove_provider(self, provider_id: str) -> bool:
        with self._lock:
            existed = self._providers.pop(provider_id, None) is not None
            if not existed:
                return False
            self._provider_params.pop(provider_id, None)
            if self._default_provider_id == provider_id:
                self._default_provider_id = next(iter(self._providers), None)
            self._save()
            return True

    def test_provider_connection(self, provider_id: str) -> Dict[str, Any]:
        with self._lock:
            provider = self._providers.get(provider_id)
            if not provider:
                return {"ok": False, "error": "unknown provider", "provider_id": provider_id}
            return {
                "ok": bool(provider.get("enabled", True)),
                "provider_id": provider_id,
                "name": provider.get("name"),
                "provider_type": provider.get("provider_type"),
                "tested_at": _now_iso(),
            }

    def set_default_provider(self, provider_id: str) -> bool:
        with self._lock:
            if provider_id not in self._providers:
                return False
            self._default_provider_id = provider_id
            self._save()
            return True

    def get_default_provider(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._default_provider_id:
                return None
            provider = self._providers.get(self._default_provider_id)
            return self._provider_to_dict(provider) if provider else None

    def list_models(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(m) for m in self._models.values()]

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            model = self._models.get(model_id)
            return dict(model) if model else None

    def select_model(self, model_id: Optional[str]) -> bool:
        with self._lock:
            if model_id is not None and model_id not in self._models:
                return False
            self._selected_model = model_id
            self._save()
            return True

    def get_default_params(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._default_params)

    def update_default_params(self, fields: Dict[str, Any]) -> bool:
        if not isinstance(fields, dict):
            return False
        with self._lock:
            for key, value in fields.items():
                if key in _DEFAULT_PARAMS:
                    self._default_params[key] = value
            self._save()
            return True

    def get_provider_params(self, provider_id: str) -> Dict[str, Any]:
        with self._lock:
            params = self._provider_params.get(provider_id)
            if params is None:
                return dict(_DEFAULT_PROVIDER_PARAMS)
            merged = dict(_DEFAULT_PROVIDER_PARAMS)
            merged.update(params)
            return merged

    def update_provider_params(self, provider_id: str, fields: Dict[str, Any]) -> bool:
        if not isinstance(fields, dict):
            return False
        with self._lock:
            if provider_id not in self._providers:
                return False
            current = self._provider_params.setdefault(provider_id, dict(_DEFAULT_PROVIDER_PARAMS))
            for key, value in fields.items():
                if key in _DEFAULT_PROVIDER_PARAMS:
                    current[key] = value
            self._save()
            return True

    def reset_provider_params(self, provider_id: str) -> bool:
        with self._lock:
            if provider_id not in self._providers:
                return False
            if self._provider_params.pop(provider_id, None) is not None:
                self._save()
            return True

    def record_token_usage(
        self,
        provider_id: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        entry = {
            "provider_id": provider_id,
            "model": model,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "cost": float(cost),
            "recorded_at": _now_iso(),
        }
        with self._lock:
            self._token_usage.append(entry)
            self._save()

    def get_token_usage(
        self,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            results: List[Dict[str, Any]] = []
            for entry in self._token_usage:
                if provider_id is not None and entry.get("provider_id") != provider_id:
                    continue
                if model is not None and entry.get("model") != model:
                    continue
                results.append(dict(entry))
            return results

    def get_token_stats(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            entries = [e for e in self._token_usage if provider_id is None or e.get("provider_id") == provider_id]
            total_prompt = sum(int(e.get("prompt_tokens", 0)) for e in entries)
            total_completion = sum(int(e.get("completion_tokens", 0)) for e in entries)
            total_cost = float(sum(float(e.get("cost", 0.0)) for e in entries))
            total_requests = len(entries)
            by_provider: Dict[str, Dict[str, Any]] = {}
            for e in entries:
                pid = e.get("provider_id", "unknown")
                bucket = by_provider.setdefault(
                    pid,
                    {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "cost": 0.0,
                        "requests": 0,
                    },
                )
                bucket["prompt_tokens"] += int(e.get("prompt_tokens", 0))
                bucket["completion_tokens"] += int(e.get("completion_tokens", 0))
                bucket["cost"] = float(bucket["cost"]) + float(e.get("cost", 0.0))
                bucket["requests"] += 1
            return {
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_cost": total_cost,
                "total_requests": total_requests,
                "by_provider": by_provider,
            }

    def get_token_usage_summary(self, provider_id: Optional[str] = None) -> Dict[str, Any]:
        return self.get_token_stats(provider_id=provider_id)

    def reset_token_usage(self, provider_id: Optional[str] = None) -> int:
        with self._lock:
            if provider_id is None:
                removed = len(self._token_usage)
                self._token_usage.clear()
            else:
                kept: List[Dict[str, Any]] = []
                removed = 0
                for entry in self._token_usage:
                    if entry.get("provider_id") == provider_id:
                        removed += 1
                    else:
                        kept.append(entry)
                self._token_usage = kept
            if removed:
                self._save()
            return removed

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            token_stats = self.get_token_stats()
            return {
                "providers": len(self._providers),
                "models": len(self._models),
                "default_provider_id": self._default_provider_id,
                "selected_model": self._selected_model,
                "token": token_stats,
            }


_singleton: Optional["LLMConfigConsole"] = None
_singleton_lock = threading.Lock()


def get_llm_config_console(config_path: Optional[str] = None) -> LLMConfigConsole:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            path = config_path or _DEFAULT_CONFIG_PATH
            _singleton = LLMConfigConsole(config_path=path)
        return _singleton


def reset_llm_config_console() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
