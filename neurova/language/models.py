"""
language 数据模型
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Language(str, Enum):
    """语言枚举"""

    CHINESE = "zh"
    ENGLISH = "en"
    JAPANESE = "ja"
    KOREAN = "ko"
    FRENCH = "fr"
    GERMAN = "de"
    SPANISH = "es"
    RUSSIAN = "ru"
    ARABIC = "ar"
    PORTUGUESE = "pt"
    ITALIAN = "it"
    DUTCH = "nl"
    TURKISH = "tr"
    THAI = "th"
    VIETNAMESE = "vi"
    INDONESIAN = "id"
    MALAY = "ms"
    HINDI = "hi"
    BENGALI = "bn"
    POLISH = "pl"
    UKRAINIAN = "uk"
    CZECH = "cs"
    SWEDISH = "sv"
    DANISH = "da"
    FINNISH = "fi"
    NORWEGIAN = "no"
    HUNGARIAN = "hu"
    ROMANIAN = "ro"
    GREEK = "el"
    HEBREW = "he"
    PERSIAN = "fa"
    AUTO = "auto"  # 自动检测

    @classmethod
    def from_str(cls, value: str) -> "Language":
        """从字符串创建"""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.AUTO

    def get_name(self) -> str:
        """获取语言名称"""
        names = {
            "zh": "中文",
            "en": "English",
            "ja": "日本語",
            "ko": "한국어",
            "fr": "Français",
            "de": "Deutsch",
            "es": "Español",
            "ru": "Русский",
            "ar": "العربية",
            "pt": "Português",
            "it": "Italiano",
            "nl": "Nederlands",
            "tr": "Türkçe",
            "th": "ไทย",
            "vi": "Tiếng Việt",
            "id": "Bahasa Indonesia",
            "ms": "Bahasa Melayu",
            "hi": "हिन्दी",
            "bn": "বাংলা",
            "pl": "Polski",
            "uk": "Українська",
            "cs": "Čeština",
            "sv": "Svenska",
            "da": "Dansk",
            "fi": "Suomi",
            "no": "Norsk",
            "hu": "Magyar",
            "ro": "Română",
            "el": "Ελληνικά",
            "he": "עברית",
            "fa": "فارسی",
            "auto": "自动检测",
        }
        return names.get(self.value, self.value)


@dataclass
class TranslationKey:
    """翻译键"""

    key: str
    namespace: str = "default"
    description: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "key": self.key,
            "namespace": self.namespace,
            "description": self.description,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationKey":
        """从字典创建"""
        return cls(
            key=data["key"],
            namespace=data.get("namespace", "default"),
            description=data.get("description", ""),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    def get_full_key(self) -> str:
        """获取完整键名"""
        if self.namespace == "default":
            return self.key
        return f"{self.namespace}.{self.key}"


@dataclass
class Translation:
    """翻译"""

    key: str
    language: Language
    value: str
    namespace: str = "default"
    is_approved: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    translator: str = ""  # 翻译者
    confidence: float = 1.0  # 置信度 (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "key": self.key,
            "language": self.language.value,
            "value": self.value,
            "namespace": self.namespace,
            "is_approved": self.is_approved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "translator": self.translator,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Translation":
        """从字典创建"""
        return cls(
            key=data["key"],
            language=Language.from_str(data["language"]),
            value=data["value"],
            namespace=data.get("namespace", "default"),
            is_approved=data.get("is_approved", True),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            translator=data.get("translator", ""),
            confidence=data.get("confidence", 1.0),
            metadata=data.get("metadata", {}),
        )

    def get_full_key(self) -> str:
        """获取完整键名"""
        if self.namespace == "default":
            return self.key
        return f"{self.namespace}.{self.key}"


@dataclass
class UserLanguagePreference:
    """用户语言偏好"""

    user_id: str
    primary_language: Language = Language.CHINESE
    secondary_languages: List[Language] = field(default_factory=list)
    auto_detect: bool = True
    fallback_language: Language = Language.ENGLISH
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "user_id": self.user_id,
            "primary_language": self.primary_language.value,
            "secondary_languages": [lang.value for lang in self.secondary_languages],
            "auto_detect": self.auto_detect,
            "fallback_language": self.fallback_language.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserLanguagePreference":
        """从字典创建"""
        return cls(
            user_id=data["user_id"],
            primary_language=Language.from_str(data.get("primary_language", "zh")),
            secondary_languages=[Language.from_str(lang) for lang in data.get("secondary_languages", [])],
            auto_detect=data.get("auto_detect", True),
            fallback_language=Language.from_str(data.get("fallback_language", "en")),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {}),
        )

    def get_preferred_languages(self) -> List[Language]:
        """获取首选语言列表"""
        languages = [self.primary_language]
        languages.extend(self.secondary_languages)
        if self.fallback_language not in languages:
            languages.append(self.fallback_language)
        return languages

    def should_auto_detect(self) -> bool:
        """是否应该自动检测语言"""
        return self.auto_detect


@dataclass
class LanguageStats:
    """语言统计"""

    language: Language
    translation_count: int = 0
    approved_count: int = 0
    pending_count: int = 0
    coverage_percentage: float = 0.0
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "language": self.language.value,
            "translation_count": self.translation_count,
            "approved_count": self.approved_count,
            "pending_count": self.pending_count,
            "coverage_percentage": self.coverage_percentage,
            "last_updated": self.last_updated,
        }


@dataclass
class TranslationRequest:
    """翻译请求"""

    key: str
    source_language: Language
    target_language: Language
    context: Optional[str] = None
    namespace: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "key": self.key,
            "source_language": self.source_language.value,
            "target_language": self.target_language.value,
            "context": self.context,
            "namespace": self.namespace,
            "metadata": self.metadata,
        }


@dataclass
class TranslationResponse:
    """翻译响应"""

    request: TranslationRequest
    translated_text: str
    confidence: float = 1.0
    source: str = "memory"  # memory, cache, api, fallback
    alternatives: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request": self.request.to_dict(),
            "translated_text": self.translated_text,
            "confidence": self.confidence,
            "source": self.source,
            "alternatives": self.alternatives,
            "metadata": self.metadata,
        }
