"""
模型路由配置模块

提供用户和管理员级别的模型路由表配置功能，支持优先级：
用户设定 > 管理员设定 > 系统自动路由

功能：
1. 模型路由表存储（支持用户/管理员/系统级别）
2. 路由优先级管理
3. 基于 JSON 的线程安全持久化
"""

import datetime
import enum
import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class RouteLevel(str, enum.Enum):
    """路由级别枚举"""

    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"

    @classmethod
    def from_value(cls, value: Any) -> "RouteLevel":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.SYSTEM
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.SYSTEM


class RequestType(str, enum.Enum):
    """请求类型枚举（路由配置专用）"""

    GENERAL = "general"
    CHAT = "chat"
    TOOL_CALL = "tool_call"
    CODE_GENERATION = "code_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_UNDERSTANDING = "audio_understanding"
    VIDEO_UNDERSTANDING = "video_understanding"
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_IMAGE = "image_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    TEXT_TO_SPEECH = "text_to_speech"
    SPEECH_TO_TEXT = "speech_to_text"
    EMBEDDING = "embedding"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"

    @classmethod
    def from_value(cls, value: Any) -> "RequestType":
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.GENERAL
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.GENERAL


_LEVEL_RANK: Dict[RouteLevel, int] = {
    RouteLevel.USER: 3,
    RouteLevel.ADMIN: 2,
    RouteLevel.SYSTEM: 1,
}


@dataclass
class ModelRouteConfig:
    """模型路由配置实体"""

    level: RouteLevel = RouteLevel.SYSTEM
    request_type: RequestType = RequestType.GENERAL
    model_id: str = ""
    provider_id: str = ""
    user_id: Optional[str] = None
    priority: int = 0
    enabled: bool = True
    route_id: str = field(default_factory=lambda: _new_id("route_"))
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if not isinstance(self.level, RouteLevel):
            self.level = RouteLevel.from_value(self.level)
        if not isinstance(self.request_type, RequestType):
            self.request_type = RequestType.from_value(self.request_type)
        if not self.route_id:
            self.route_id = _new_id("route_")
        if self.priority is None:
            self.priority = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id,
            "user_id": self.user_id,
            "level": self.level.value,
            "request_type": self.request_type.value,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "priority": int(self.priority),
            "enabled": bool(self.enabled),
            "description": self.description,
            "extra": dict(self.extra or {}),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelRouteConfig":
        if not isinstance(data, dict):
            raise TypeError("ModelRouteConfig.from_dict expects a dict")
        return cls(
            route_id=data.get("route_id") or _new_id("route_"),
            user_id=data.get("user_id"),
            level=RouteLevel.from_value(data.get("level", RouteLevel.SYSTEM)),
            request_type=RequestType.from_value(data.get("request_type", RequestType.GENERAL)),
            model_id=data.get("model_id", "") or "",
            provider_id=data.get("provider_id", "") or "",
            priority=int(data.get("priority", 0) or 0),
            enabled=bool(data.get("enabled", True)),
            description=data.get("description", "") or "",
            extra=dict(data.get("extra") or {}),
            created_at=data.get("created_at") or _now_iso(),
            updated_at=data.get("updated_at") or _now_iso(),
        )

    def matches_request(
        self,
        request_type: Any,
        user_id: Optional[str] = None,
    ) -> bool:
        if not self.enabled:
            return False
        if self.level == RouteLevel.USER:
            if not self.user_id or self.user_id != user_id:
                return False
        req = RequestType.from_value(request_type)
        if self.request_type == RequestType.GENERAL:
            return True
        return self.request_type == req

    def clone(self) -> "ModelRouteConfig":
        return ModelRouteConfig.from_dict(self.to_dict())


class ModelRouteConfigStorage:
    """模型路由配置存储（线程安全 JSON 持久化）"""

    def __init__(self, storage_dir: str) -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._routes_path = self._dir / "routes.json"
        self._routes: Dict[str, ModelRouteConfig] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._routes_path.exists():
            return
        try:
            raw = json.loads(self._routes_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load routes from %s: %s", self._routes_path, exc)
            return
        if not isinstance(raw, dict):
            return
        for rid, payload in raw.items():
            try:
                cfg = ModelRouteConfig.from_dict(payload)
                cfg.route_id = rid
                self._routes[rid] = cfg
            except Exception as exc:
                logger.warning("Skip invalid route %s: %s", rid, exc)

    def _save(self) -> None:
        data = {rid: cfg.to_dict() for rid, cfg in self._routes.items()}
        self._routes_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def create_route(self, cfg: ModelRouteConfig) -> str:
        if cfg is None:
            raise ValueError("cfg must not be None")
        with self._lock:
            if not cfg.route_id:
                cfg.route_id = _new_id("route_")
            while cfg.route_id in self._routes:
                cfg.route_id = _new_id("route_")
            cfg.created_at = cfg.created_at or _now_iso()
            cfg.updated_at = _now_iso()
            self._routes[cfg.route_id] = cfg
            self._save()
            return cfg.route_id

    def get_route(self, route_id: str) -> Optional[ModelRouteConfig]:
        with self._lock:
            cfg = self._routes.get(route_id)
            return cfg.clone() if cfg else None

    def update_route(self, route_id: str, **fields: Any) -> bool:
        with self._lock:
            cfg = self._routes.get(route_id)
            if cfg is None:
                return False
            data = cfg.to_dict()
            for key, value in fields.items():
                if key == "route_id":
                    continue
                if key == "level":
                    data["level"] = RouteLevel.from_value(value).value
                elif key == "request_type":
                    data["request_type"] = RequestType.from_value(value).value
                elif key == "extra":
                    data["extra"] = dict(value or {})
                else:
                    data[key] = value
            data["route_id"] = route_id
            data["updated_at"] = _now_iso()
            self._routes[route_id] = ModelRouteConfig.from_dict(data)
            self._save()
            return True

    def delete_route(self, route_id: str) -> bool:
        with self._lock:
            existed = self._routes.pop(route_id, None) is not None
            if existed:
                self._save()
            return existed

    def list_routes(
        self,
        level: Optional[RouteLevel] = None,
        user_id: Optional[str] = None,
        request_type: Optional[RequestType] = None,
        enabled_only: bool = False,
    ) -> List[ModelRouteConfig]:
        with self._lock:
            results: List[ModelRouteConfig] = []
            for cfg in self._routes.values():
                if level is not None:
                    target_level = RouteLevel.from_value(level)
                    if cfg.level != target_level:
                        continue
                if user_id is not None and cfg.user_id != user_id:
                    continue
                if request_type is not None:
                    target_rt = RequestType.from_value(request_type)
                    if cfg.request_type != target_rt:
                        continue
                if enabled_only and not cfg.enabled:
                    continue
                results.append(cfg.clone())
            return results

    def select_best_route(
        self,
        request_type: Any,
        user_id: Optional[str] = None,
    ) -> Optional[ModelRouteConfig]:
        with self._lock:
            candidates: List[ModelRouteConfig] = []
            for cfg in self._routes.values():
                if cfg.matches_request(request_type, user_id=user_id):
                    candidates.append(cfg)
            if not candidates:
                return None
            candidates.sort(
                key=lambda c: (
                    _LEVEL_RANK.get(c.level, 0),
                    int(c.priority or 0),
                    c.updated_at,
                ),
                reverse=True,
            )
            return candidates[0].clone()

    def get_user_routes(self, user_id: str) -> List[ModelRouteConfig]:
        return self.list_routes(level=RouteLevel.USER, user_id=user_id)

    def get_admin_routes(self) -> List[ModelRouteConfig]:
        return self.list_routes(level=RouteLevel.ADMIN)

    def get_system_routes(self) -> List[ModelRouteConfig]:
        return self.list_routes(level=RouteLevel.SYSTEM)

    def delete_user_routes(self, user_id: str) -> int:
        with self._lock:
            targets = [
                rid for rid, cfg in self._routes.items() if cfg.level == RouteLevel.USER and cfg.user_id == user_id
            ]
            for rid in targets:
                self._routes.pop(rid, None)
            if targets:
                self._save()
            return len(targets)

    def clear_all(self) -> int:
        with self._lock:
            count = len(self._routes)
            self._routes.clear()
            self._save()
            return count

    def count(self) -> int:
        with self._lock:
            return len(self._routes)


_singleton: Optional[ModelRouteConfigStorage] = None
_singleton_lock = threading.Lock()
_DEFAULT_DIR = "./data/model_route_config"


def get_model_route_config_storage() -> ModelRouteConfigStorage:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            Path(_DEFAULT_DIR).mkdir(parents=True, exist_ok=True)
            _singleton = ModelRouteConfigStorage(_DEFAULT_DIR)
    return _singleton


def reset_model_route_config_storage() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
