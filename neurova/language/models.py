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
    def normalizeTag(cls, tag: Any) -> Optional["Language"]:
        """语言码 → 枚举的**唯一口径**；不识别返回 `None`，不替调用方决定兜底。

        仓内实际流通的是带区域后缀的 BCP-47 码（前端 11 份 locale 文件名、
        `api/endpoints/settings.py` 存的 `"zh-CN"`），所以主子标签归一是必须的一步——
        这步原本只在 `LanguageManager.detect_browser_language` 里私有一份
        （`lang.split("-")[0]`），枚举自己反而不认，于是 `zh-CN` 一路落到兜底值。
        """
        if isinstance(tag, cls):
            return tag
        if tag is None:
            return None

        text = str(tag).strip().lower().replace("_", "-")
        if not text:
            return None

        # 全码优先（`zh-cn` 不是成员，走第二刀）；再取主子标签（`zh-cn` → `zh`）
        for candidate in (text, text.split("-", 1)[0]):
            try:
                return cls(candidate)
            except ValueError:
                continue
        return None

    @classmethod
    def from_str(cls, value: str) -> "Language":
        """总入口：不识别**当场报错**，不再把未知码折成 `AUTO`。

        原兜底 `except ValueError: return cls.AUTO` 让「我没看懂这个码」与「自动检测」
        共用一个合法成员值——写进去的外部译文库因此整批落进 `auto` 桶，
        按 `Language.CHINESE` 永远读不出来（台账 §6-140，教义第 2 条禁「把失败改写成默认值」）。
        调用方要兜底就显式用自己的默认语言。
        """
        normalized = cls.normalizeTag(value)
        if normalized is None:
            raise ValueError("无法识别的语言码: %r" % (value,))
        return normalized

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

    def __post_init__(self) -> None:
        """构造点就把语言码归一成枚举成员——非法状态生产不出来（教义第 1 条）。

        原形态：dataclass 不校验，`Translation(language="zh")` 存进去的是**裸串**，
        于是 `to_dict()` 里那句 `self.language.value` 当场 AttributeError；
        而配套测试只断「字段回显相等」，所以它一直是绿的（断形状不断装配，§6-129 同族）。
        """
        if isinstance(self.language, Language):
            return
        self.language = Language.from_str(str(self.language))

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

    def __post_init__(self) -> None:
        """三个语言字段一律归一成枚举成员。

        现役 UI 与 `app_settings.json` 存的是 `zh-CN` 这一族带区域码的标签；
        不归一就会与 `Language.ZH` 系比较失配（`get_translation` 那侧比的是 `.value`），
        于是"选了语言却读不到对应文案"——与 §6-140 那条 `from_str` 静默折成 `AUTO`
        是同一根因的两个出口。
        """
        self.primary_language = Language.from_str(
            self.primary_language.value if isinstance(self.primary_language, Language)
            else str(self.primary_language))
        self.fallback_language = Language.from_str(
            self.fallback_language.value if isinstance(self.fallback_language, Language)
            else str(self.fallback_language))
        self.secondary_languages = [
            Language.from_str(lang.value if isinstance(lang, Language) else str(lang))
            for lang in (self.secondary_languages or [])
        ]
        # `AUTO` 表达的是"自动检测"，而这件事本类已有 `auto_detect: bool` 专职承载。
        # 让 `primary_language = AUTO` 过关，等于把 §6-140 刚拆掉的"不识别与自动检测共用
        # 一个合法值"在新字段上重建一遍：下游按 `.value` 比语言时，`auto` 谁都不会命中，
        # 表现是"用户选了语言却读不到对应文案"。非法状态在构造点就拒。
        for field_name in ("primary_language", "fallback_language"):
            if getattr(self, field_name) is Language.AUTO:
                raise ValueError(
                    "`UserLanguagePreference.%s` 不接受 `auto`：它表达的是「自动检测」，"
                    "那个意思由 `auto_detect` 承载；首选/回退语言必须是一个真实语言" % field_name)

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
