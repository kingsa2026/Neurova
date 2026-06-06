"""
Neurova Language 管理器

功能:
1. 多语言翻译管理
2. 用户语言偏好管理
3. 实时语言切换
4. 翻译缓存
5. 用户数据隔离（每个用户独立的语言设置）
"""

import json
import logging
from pathlib import Path
import time
import threading
from typing import Any, Dict, List, Optional, Union

from neurova.language.models import (
    Language, Translation, TranslationKey, UserLanguagePreference,
    LanguageStats, TranslationRequest, TranslationResponse
)

logger = logging.getLogger(__name__)


class LanguageManager:
    """
    语言管理器
    
    负责管理多语言翻译、用户语言偏好和翻译缓存。
    """
    
    def __init__(self, data_dir: Optional[str] = None, 
                 default_language: Language = Language.CHINESE):
        """
        初始化语言管理器
        
        Args:
            data_dir: 数据目录路径
            default_language: 默认语言
        """
        self.data_dir = Path(data_dir) if data_dir else Path("data/language")
        self.default_language = default_language
        
        # 线程锁
        self._lock = threading.RLock()
        
        # 翻译存储: {namespace: {key: {language: Translation}}}
        self._translations: Dict[str, Dict[str, Dict[str, Translation]]] = {}
        
        # 用户语言偏好: {user_id: UserLanguagePreference}
        self._user_preferences: Dict[str, UserLanguagePreference] = {}
        
        # 翻译缓存
        self._cache: Dict[str, Dict[str, str]] = {}  # {cache_key: {language: value}}
        self._cache_ttl = 3600  # 缓存TTL（秒）
        self._cache_timestamps: Dict[str, float] = {}
        
        # 统计信息
        self._stats: Dict[str, LanguageStats] = {}
        
        # 加载翻译
        self._load_all_translations()
        
        logger.info(f"LanguageManager initialized: default_language={default_language.value}")
    
    def _load_all_translations(self) -> None:
        """加载所有翻译"""
        try:
            # 加载内置翻译
            self._load_builtin_translations()
            
            # 加载外部翻译文件
            self._load_external_translations()
            
            logger.info(f"Loaded translations: {len(self._translations)} namespaces")
        except Exception as e:
            logger.error(f"Failed to load translations: {e}")
    
    def _load_builtin_translations(self) -> None:
        """加载内置翻译"""
        # 内置翻译数据
        builtin_translations = {
            "default": {
                "greeting": {
                    "zh": "你好",
                    "en": "Hello",
                    "ja": "こんにちは",
                    "ko": "안녕하세요"
                },
                "farewell": {
                    "zh": "再见",
                    "en": "Goodbye",
                    "ja": "さようなら",
                    "ko": "안녕히 가세요"
                },
                "thanks": {
                    "zh": "谢谢",
                    "en": "Thank you",
                    "ja": "ありがとう",
                    "ko": "감사합니다"
                },
                "error": {
                    "zh": "错误",
                    "en": "Error",
                    "ja": "エラー",
                    "ko": "오류"
                },
                "loading": {
                    "zh": "加载中...",
                    "en": "Loading...",
                    "ja": "読み込み中...",
                    "ko": "로딩 중..."
                },
                "success": {
                    "zh": "成功",
                    "en": "Success",
                    "ja": "成功",
                    "ko": "성공"
                },
                "cancel": {
                    "zh": "取消",
                    "en": "Cancel",
                    "ja": "キャンセル",
                    "ko": "취소"
                },
                "confirm": {
                    "zh": "确认",
                    "en": "Confirm",
                    "ja": "確認",
                    "ko": "확인"
                }
            },
            "ui": {
                "settings": {
                    "zh": "设置",
                    "en": "Settings",
                    "ja": "設定",
                    "ko": "설정"
                },
                "profile": {
                    "zh": "个人资料",
                    "en": "Profile",
                    "ja": "プロフィール",
                    "ko": "프로필"
                },
                "logout": {
                    "zh": "退出登录",
                    "en": "Logout",
                    "ja": "ログアウト",
                    "ko": "로그아웃"
                },
                "login": {
                    "zh": "登录",
                    "en": "Login",
                    "ja": "ログイン",
                    "ko": "로그인"
                }
            },
            "messages": {
                "welcome": {
                    "zh": "欢迎使用 Neurova",
                    "en": "Welcome to Neurova",
                    "ja": "Neurovaへようこそ",
                    "ko": "Neurova에 오신 것을 환영합니다"
                },
                "goodbye": {
                    "zh": "感谢使用，再见！",
                    "en": "Thank you for using Neurova, goodbye!",
                    "ja": "ご利用ありがとうございまNetherlands、さようなら！",
                    "ko": "이용해 주셔서 감사합니다, 안녕히 가세요!"
                }
            }
        }
        
        # 转换为 Translation 对象
        for namespace, keys in builtin_translations.items():
            if namespace not in self._translations:
                self._translations[namespace] = {}
            
            for key, translations in keys.items():
                if key not in self._translations[namespace]:
                    self._translations[namespace][key] = {}
                
                for lang_code, value in translations.items():
                    language = Language.from_str(lang_code)
                    translation = Translation(
                        key=key,
                        language=language,
                        value=value,
                        namespace=namespace,
                        is_approved=True,
                        translator="builtin"
                    )
                    self._translations[namespace][key][language.value] = translation
    
    def _load_external_translations(self) -> None:
        """加载外部翻译文件"""
        try:
            # 检查数据目录
            if not self.data_dir.exists():
                self.data_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created language data directory: {self.data_dir}")
            
            # 加载 JSON 翻译文件
            for json_file in self.data_dir.glob("*.json"):
                try:
                    self._load_translations_from_resource(json_file)
                except Exception as e:
                    logger.warning(f"Failed to load translation file {json_file}: {e}")
            
            # 加载 YAML 翻译文件（如果安装了 pyyaml）
            try:
                import yaml
                for yaml_file in self.data_dir.glob("*.yaml"):
                    try:
                        self._load_translations_from_resource(yaml_file, is_yaml=True)
                    except Exception as e:
                        logger.warning(f"Failed to load translation file {yaml_file}: {e}")
            except ImportError:
                logger.debug("PyYAML not installed, skipping YAML translation files")
                
        except Exception as e:
            logger.error(f"Failed to load external translations: {e}")
    
    def _load_translations_from_resource(self, file_path: Path, 
                                        is_yaml: bool = False) -> None:
        """从资源文件加载翻译"""
        try:
            if is_yaml:
                import yaml
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            
            # 解析翻译数据
            namespace = file_path.stem  # 文件名作为命名空间
            
            if namespace not in self._translations:
                self._translations[namespace] = {}
            
            # 应用外部翻译
            self._apply_external_translations(namespace, data)
            
            logger.info(f"Loaded translations from {file_path}")
            
        except Exception as e:
            logger.error(f"Failed to load translations from {file_path}: {e}")
            raise
    
    def _apply_external_translations(self, namespace: str, 
                                    data: Dict[str, Any]) -> None:
        """应用外部翻译数据"""
        if not isinstance(data, dict):
            return
        
        for key, translations in data.items():
            if not isinstance(translations, dict):
                continue
            
            if key not in self._translations[namespace]:
                self._translations[namespace][key] = {}
            
            for lang_code, value in translations.items():
                if isinstance(value, str):
                    language = Language.from_str(lang_code)
                    translation = Translation(
                        key=key,
                        language=language,
                        value=value,
                        namespace=namespace,
                        is_approved=False,  # 外部翻译默认未审批
                        translator="external"
                    )
                    self._translations[namespace][key][language.value] = translation
    
    def save_external_translations(self, namespace: str, 
                                  translations: Dict[str, Dict[str, str]]) -> bool:
        """
        保存外部翻译
        
        Args:
            namespace: 命名空间
            translations: 翻译数据 {key: {language: value}}
            
        Returns:
            是否保存成功
        """
        try:
            with self._lock:
                # 更新内存中的翻译
                if namespace not in self._translations:
                    self._translations[namespace] = {}
                
                for key, lang_translations in translations.items():
                    if key not in self._translations[namespace]:
                        self._translations[namespace][key] = {}
                    
                    for lang_code, value in lang_translations.items():
                        language = Language.from_str(lang_code)
                        translation = Translation(
                            key=key,
                            language=language,
                            value=value,
                            namespace=namespace,
                            is_approved=False,
                            translator="user"
                        )
                        self._translations[namespace][key][language.value] = translation
                
                # 保存到文件
                file_path = self.data_dir / f"{namespace}.json"
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(translations, f, ensure_ascii=False, indent=2)
                
                logger.info(f"Saved translations to {file_path}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to save translations: {e}")
            return False
    
    def get_translation(self, key: str, language: Optional[Language] = None,
                       namespace: str = "default",
                       fallback: bool = True) -> Optional[str]:
        """
        获取翻译
        
        Args:
            key: 翻译键
            language: 目标语言
            namespace: 命名空间
            fallback: 是否使用回退语言
            
        Returns:
            翻译文本
        """
        if language is None:
            language = self.default_language
        
        # 检查缓存
        cache_key = f"{namespace}:{key}:{language.value}"
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # 查找翻译
        with self._lock:
            namespace_translations = self._translations.get(namespace, {})
            key_translations = namespace_translations.get(key, {})
            
            # 直接匹配
            translation = key_translations.get(language.value)
            if translation and translation.is_approved:
                self._set_cache(cache_key, translation.value)
                return translation.value
            
            # 尝试回退语言
            if fallback:
                # 尝试默认语言
                if language != self.default_language:
                    translation = key_translations.get(self.default_language.value)
                    if translation and translation.is_approved:
                        self._set_cache(cache_key, translation.value)
                        return translation.value
                
                # 尝试英语
                if language != Language.ENGLISH and self.default_language != Language.ENGLISH:
                    translation = key_translations.get(Language.ENGLISH.value)
                    if translation and translation.is_approved:
                        self._set_cache(cache_key, translation.value)
                        return translation.value
            
            # 返回键名作为最后回退
            return key
    
    def translate(self, text: str, target_language: Optional[Language] = None,
                 source_language: Optional[Language] = None,
                 context: Optional[str] = None) -> TranslationResponse:
        """
        翻译文本
        
        Args:
            text: 要翻译的文本
            target_language: 目标语言
            source_language: 源语言
            context: 上下文
            
        Returns:
            翻译响应
        """
        if target_language is None:
            target_language = self.default_language
        
        # 尝试从翻译表中查找
        # 这里简化处理，实际应用中可能需要更复杂的翻译逻辑
        request = TranslationRequest(
            key=text,
            source_language=source_language or Language.AUTO,
            target_language=target_language,
            context=context
        )
        
        # 查找翻译
        translated = self.get_translation(text, target_language)
        if translated and translated != text:
            return TranslationResponse(
                request=request,
                translated_text=translated,
                confidence=1.0,
                source="memory"
            )
        
        # 如果没有找到翻译，返回原文
        return TranslationResponse(
            request=request,
            translated_text=text,
            confidence=0.0,
            source="fallback"
        )
    
    def set_user_preference(self, user_id: str, 
                           preference: UserLanguagePreference) -> bool:
        """
        设置用户语言偏好
        
        Args:
            user_id: 用户ID
            preference: 用户语言偏好
            
        Returns:
            是否设置成功
        """
        try:
            with self._lock:
                self._user_preferences[user_id] = preference
                logger.info(f"Set user preference: {user_id} -> {preference.primary_language.value}")
                return True
        except Exception as e:
            logger.error(f"Failed to set user preference: {e}")
            return False
    
    def get_user_preference(self, user_id: str) -> Optional[UserLanguagePreference]:
        """
        获取用户语言偏好
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户语言偏好
        """
        return self._user_preferences.get(user_id)
    
    def get_available_languages(self) -> List[Language]:
        """获取可用语言列表"""
        languages = set()
        
        with self._lock:
            for namespace_translations in self._translations.values():
                for key_translations in namespace_translations.values():
                    languages.update(key_translations.keys())
        
        # 转换为 Language 枚举
        result = []
        for lang_code in languages:
            try:
                result.append(Language.from_str(lang_code))
            except ValueError:
                continue
        
        return sorted(result, key=lambda x: x.value)
    
    def detect_browser_language(self, accept_language: str) -> Language:
        """
        检测浏览器语言
        
        Args:
            accept_language: Accept-Language 头
            
        Returns:
            检测到的语言
        """
        if not accept_language:
            return self.default_language
        
        # 解析 Accept-Language 头
        languages = []
        for part in accept_language.split(','):
            part = part.strip()
            if ';q=' in part:
                lang, q = part.split(';q=')
                try:
                    quality = float(q)
                except ValueError:
                    quality = 0.0
            else:
                lang = part
                quality = 1.0
            
            # 提取语言代码
            lang_code = lang.split('-')[0].lower()
            languages.append((lang_code, quality))
        
        # 按质量排序
        languages.sort(key=lambda x: x[1], reverse=True)
        
        # 查找第一个支持的语言
        available_languages = self.get_available_languages()
        for lang_code, _ in languages:
            language = Language.from_str(lang_code)
            if language in available_languages:
                return language
        
        return self.default_language
    
    def clear_cache(self) -> None:
        """清除缓存"""
        with self._lock:
            self._cache.clear()
            self._cache_timestamps.clear()
            logger.info("Translation cache cleared")
    
    def reload_translations(self) -> None:
        """重新加载翻译"""
        with self._lock:
            self._translations.clear()
            self.clear_cache()
            self._load_all_translations()
            logger.info("Translations reloaded")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total_translations = 0
            approved_translations = 0
            
            for namespace_translations in self._translations.values():
                for key_translations in namespace_translations.values():
                    for translation in key_translations.values():
                        total_translations += 1
                        if translation.is_approved:
                            approved_translations += 1
            
            return {
                "total_translations": total_translations,
                "approved_translations": approved_translations,
                "pending_translations": total_translations - approved_translations,
                "namespaces": len(self._translations),
                "user_preferences": len(self._user_preferences),
                "cache_size": len(self._cache),
                "available_languages": len(self.get_available_languages())
            }
    
    def _get_from_cache(self, key: str) -> Optional[str]:
        """从缓存获取"""
        if key in self._cache:
            # 检查TTL
            timestamp = self._cache_timestamps.get(key, 0)
            if time.time() - timestamp < self._cache_ttl:
                # 返回第一个可用的语言
                for lang, value in self._cache[key].items():
                    return value
            else:
                # 缓存过期
                del self._cache[key]
                del self._cache_timestamps[key]
        
        return None
    
    def _set_cache(self, key: str, value: str, 
                  language: Optional[Language] = None) -> None:
        """设置缓存"""
        if key not in self._cache:
            self._cache[key] = {}
        
        lang_key = language.value if language else "default"
        self._cache[key][lang_key] = value
        self._cache_timestamps[key] = time.time()


# 全局实例
_language_manager: Optional[LanguageManager] = None


def get_language_manager() -> LanguageManager:
    """获取全局 language 管理器实例"""
    global _language_manager
    if _language_manager is None:
        _language_manager = LanguageManager()
    return _language_manager


def init_language(data_dir: Optional[str] = None, 
                 default_language: Language = Language.CHINESE) -> LanguageManager:
    """
    初始化全局 language 管理器
    
    Args:
        data_dir: 数据目录路径
        default_language: 默认语言
        
    Returns:
        LanguageManager 实例
    """
    global _language_manager
    _language_manager = LanguageManager(data_dir=data_dir, default_language=default_language)
    return _language_manager