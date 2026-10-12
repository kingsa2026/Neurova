"""
Neurova Language 管理器

功能:
1. 多语言翻译管理
2. 用户语言偏好管理（**落盘**，见下）
3. 实时语言切换
4. 翻译缓存
5. 用户数据隔离（每个用户独立的语言设置）

用户语言偏好的落盘口径（台账 §6-145 裁定乙）：原先偏好只存在实例字典里，
进程重启即全失，而 `get_statistics()` 一直在数它——那是一个每次启动都归零的读数。
现在写盘走 `core/atomic_io.atomic_write_text` 单点，落点刻意放在
**译文目录的旁边而不是里面**：`_load_external_translations()` 把 `data_dir/*.json`
的每个文件当一个命名空间读，偏好文件放里面会长出一条假的 namespace（多出来的读数不报错，
只会一直在那儿）。写盘失败 ⇒ 内存回滚并回 `False`，不许"内存改了、告诉用户已保存"。
"""

import json
from neurova.core.logger import get_logger
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.language.models import (
    Language,
    LanguageStats,
    Translation,
    TranslationRequest,
    TranslationResponse,
    UserLanguagePreference,
)
from neurova.core.atomic_io import atomic_write_text, quarantine_corrupt_file
from neurova.core.data_root import callerPath
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)

#: 偏好文件名（放在译文目录的**同级**，见模块 docstring 那条 glob 约束）
PREFERENCES_FILE_NAME = "language_preferences.json"
#: 落盘格式版本。读到不认识的版本一律不采信并隔离——半自动映射会把"当初没人签字的决定"
#: 变成"看起来有人签字过"（与插件授权存储 `STORE_VERSION` 同一口径）。
PREFERENCES_STORE_VERSION = 1
#: 存储里那条**开箱默认**的顶层键名（§6-167 取长补短取进来的那一格）。它落在顶层而不是
#: `preferences` 表里——占一条用户行的话，「多少人设过偏好」会被管理员那一次点击灌大，
#: 而 `configured` 也会把一个替所有人做的决定报成本人做过的决定。
#: **新增可选键不抬版本**：抬了就是让今天已落盘的每条按人偏好被上面那段版本隔离逻辑
#: 改名隔离——那不是兼容，是凭空丢掉真数据。
DEFAULT_STORE_KEY = "default"
#: 那条开箱默认在内存里的**保留属主名**（`UserLanguagePreference.user_id` 要求非空，
#: 而这一格不属于任何具体的人）。它**永远不进 `preferences` 表**——真有个用户叫这名字
#: 也拿不到那条读数，判据 `testTheDefaultIsNotStoredAsAUserRow` 钉的就是这件事。
#: HTTP 面要构造那条哨兵偏好时取用本常量，不在自己文件里再抄一遍串（教义第 6 条）。
OUT_OF_BOX_OWNER = "__defaults__"


class LanguageManager:
    """
    语言管理器

    负责管理多语言翻译、用户语言偏好和翻译缓存。
    """

    #: 「这个人现在该看哪种语言」这条解析链的**来源词汇，全仓只在这一定义**（教义第 6 条）。
    #: 三个值各有实义：`user`＝本人显式选过；`out_of_box`＝管理员替还没选的人定的起点；
    #: `builtin`＝谁都没定，落到枚举级的 last resort。HTTP 面与前端的分支都取这一份，
    #: 第二处字面量长出来时先漂移的一定是没人对着读的那份（判据按文件面钉住）。
    EFFECTIVE_SOURCES = ("user", "out_of_box", "builtin")

    def __init__(self, data_dir: Optional[str] = None, default_language: Language = Language.CHINESE,
                 preferences_path: Optional[str] = None):
        """
        初始化语言管理器

        Args:
            data_dir: 数据目录路径
            default_language: 默认语言
            preferences_path: 用户偏好落盘路径；不给则落 `data_dir` **同级**的
                `language_preferences.json`（同级而不是里面，理由见模块 docstring）
        """
        self.data_dir = callerPath(data_dir, "language")
        self.default_language = default_language
        self.preferences_path = (Path(preferences_path) if preferences_path
                                 else self.data_dir.parent / PREFERENCES_FILE_NAME)

        # 线程锁
        self._lock = threading.RLock()

        # 翻译存储: {namespace: {key: {language: Translation}}}
        self._translations: Dict[str, Dict[str, Dict[str, Translation]]] = {}

        # 用户语言偏好: {user_id: UserLanguagePreference}
        self._user_preferences: Dict[str, UserLanguagePreference] = {}

        #: 管理员定的「开箱默认」（§6-167 取长补短取进来的那一格）：它**不是**一条用户偏好，
        #: 所以不占 `_user_preferences` 的任何键，也不进"多少人设过偏好"的计数。
        self._outOfBoxDefault: Optional[UserLanguagePreference] = None

        # 翻译缓存
        self._cache: Dict[str, Dict[str, str]] = {}  # {cache_key: {language: value}}
        self._cache_ttl = 3600  # 缓存TTL（秒）
        self._cache_timestamps: Dict[str, float] = {}

        # 统计信息
        self._stats: Dict[str, LanguageStats] = {}

        # 加载翻译
        self._load_all_translations()

        # 读回用户偏好（缺文件＝没人设过，不是错误）
        self._load_user_preferences()

        logger.info("LanguageManager initialized: default_language=%s", default_language.value)

    def _load_all_translations(self) -> None:
        """加载所有翻译"""
        try:
            # 加载内置翻译
            self._load_builtin_translations()

            # 加载外部翻译文件
            self._load_external_translations()

            logger.info("Loaded translations: %s namespaces", len(self._translations))
        except Exception as e:
            logger.error("Failed to load translations: %s", e)

    def _load_builtin_translations(self) -> None:
        """加载内置翻译"""
        # 内置翻译数据
        builtin_translations = {
            "default": {
                "greeting": {"zh": "你好", "en": "Hello", "ja": "こんにちは", "ko": "안녕하세요"},
                "farewell": {"zh": "再见", "en": "Goodbye", "ja": "さようなら", "ko": "안녕히 가세요"},
                "thanks": {"zh": "谢谢", "en": "Thank you", "ja": "ありがとう", "ko": "감사합니다"},
                "error": {"zh": "错误", "en": "Error", "ja": "エラー", "ko": "오류"},
                "loading": {"zh": "加载中...", "en": "Loading...", "ja": "読み込み中...", "ko": "로딩 중..."},
                "success": {"zh": "成功", "en": "Success", "ja": "成功", "ko": "성공"},
                "cancel": {"zh": "取消", "en": "Cancel", "ja": "キャンセル", "ko": "취소"},
                "confirm": {"zh": "确认", "en": "Confirm", "ja": "確認", "ko": "확인"},
            },
            "ui": {
                "settings": {"zh": "设置", "en": "Settings", "ja": "設定", "ko": "설정"},
                "profile": {"zh": "个人资料", "en": "Profile", "ja": "プロフィール", "ko": "프로필"},
                "logout": {"zh": "退出登录", "en": "Logout", "ja": "ログアウト", "ko": "로그아웃"},
                "login": {"zh": "登录", "en": "Login", "ja": "ログイン", "ko": "로그인"},
            },
            "messages": {
                "welcome": {
                    "zh": "欢迎使用 Neurova",
                    "en": "Welcome to Neurova",
                    "ja": "Neurovaへようこそ",
                    "ko": "Neurova에 오신 것을 환영합니다",
                },
                "goodbye": {
                    "zh": "感谢使用，再见！",
                    "en": "Thank you for using Neurova, goodbye!",
                    "ja": "ご利用いただき、ありがとうございました。さようなら！",
                    "ko": "이용해 주셔서 감사합니다, 안녕히 가세요!",
                },
            },
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
                        translator="builtin",
                    )
                    self._translations[namespace][key][language.value] = translation

    def _load_external_translations(self) -> None:
        """加载外部翻译文件"""
        try:
            # 检查数据目录
            if not self.data_dir.exists():
                self.data_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Created language data directory: %s", self.data_dir)

            # 加载 JSON 翻译文件
            for json_file in self.data_dir.glob("*.json"):
                try:
                    self._load_translations_from_resource(json_file)
                except Exception as e:
                    logger.warning("Failed to load translation file %s: %s", json_file, e)

            # 加载 YAML 翻译文件（如果安装了 pyyaml）
            try:
                pass

                for yaml_file in self.data_dir.glob("*.yaml"):
                    try:
                        self._load_translations_from_resource(yaml_file, is_yaml=True)
                    except Exception as e:
                        logger.warning("Failed to load translation file %s: %s", yaml_file, e)
            except ImportError:
                logger.debug("PyYAML not installed, skipping YAML translation files")

        except Exception as e:
            logger.error("Failed to load external translations: %s", e)

    def _load_translations_from_resource(self, file_path: Path, is_yaml: bool = False) -> None:
        """从资源文件加载翻译"""
        try:
            if is_yaml:
                import yaml

                with open(file_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
            else:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

            # 解析翻译数据
            namespace = file_path.stem  # 文件名作为命名空间

            if namespace not in self._translations:
                self._translations[namespace] = {}

            # 应用外部翻译
            self._apply_external_translations(namespace, data)

            logger.info("Loaded translations from %s", file_path)

        except Exception as e:
            logger.error("Failed to load translations from %s: %s", file_path, e)
            raise

    def _apply_external_translations(self, namespace: str, data: Dict[str, Any]) -> None:
        """应用外部翻译数据。

        单个不识别的语言码**只跳它自己**，并点名到日志——原先它是被折成 `AUTO` 存下
        （污染库），而 `from_str` 改成会报错之后，若不在此逐条处置，一个坏码就会让
        整份文件在装载面被丢掉（`_load_translations_from_resource` 抛、外层只 warning），
        内存里还可能已经写进了半截——那是比污染更难查的第三种形态。
        """
        if not isinstance(data, dict):
            return

        for key, translations in data.items():
            if not isinstance(translations, dict):
                continue

            if key not in self._translations[namespace]:
                self._translations[namespace][key] = {}

            for lang_code, value in translations.items():
                if not isinstance(value, str):
                    continue
                language = Language.normalizeTag(lang_code)
                if language is None:
                    logger.warning(
                        "跳过不识别的语言码：namespace=%s key=%s code=%r",
                        namespace, key, lang_code)
                    continue
                translation = Translation(
                    key=key,
                    language=language,
                    value=value,
                    namespace=namespace,
                    is_approved=False,  # 外部翻译默认未审批
                    translator="external",
                )
                self._translations[namespace][key][language.value] = translation

    def rejectedLanguageTags(self, translations: Dict[str, Any]) -> List[tuple]:
        """整批预验语言码，返回拒收项 `(key, 坏码)`——**这份校验的唯一出处**。

        抽成公开方法是为了让 HTTP 写面能在动手之前拿到点名的拒因。
        端点若自己再写一遍这段循环，同一件事就有了两份口径（教义第 6 条），
        漂移时先坏的是"拒因文本"这种没人对着读的东西。判据
        `tests/unit/api/test_languageFaceReadSurface.py::…RefusalNamesTheBadCodeThroughTheSameSinglePoint`
        用桩替本方法来自证那条 400 确实经这里。
        """
        rejected: List[tuple] = []
        for key, lang_translations in (translations or {}).items():
            if not isinstance(lang_translations, dict):
                rejected.append((key, "<值不是映射>"))
                continue
            for lang_code, value in lang_translations.items():
                if Language.normalizeTag(lang_code) is None or not isinstance(value, str):
                    rejected.append((key, lang_code))
        return rejected

    def save_external_translations(self, namespace: str, translations: Dict[str, Dict[str, str]]) -> bool:
        """保存外部翻译——**先整批验码，再一起动内存与盘**。

        两处原缺陷（台账 §6-140）：

        - 语言码走的是 `from_str` 的旧兜底：`zh-CN` 这类带区域后缀的码（仓内实际流通的那一套）
          被折成 `AUTO` 存进 `auto` 桶，按 `Language.CHINESE` 永远读不回来；
        - 循环是"边写内存边转码"，转码一旦失败就被外层 `except Exception` 兜成 False，
          于是**内存已经半写、文件还没写**，两边从此两套数——比存错桶更难查。
        """
        normalized: List[tuple] = []
        rejected = self.rejectedLanguageTags(translations)

        if rejected:
            logger.warning("译文库整批拒收：namespace=%s，不识别的语言码 %r", namespace, rejected)
            return False

        for key, lang_translations in (translations or {}).items():
            for lang_code, value in lang_translations.items():
                normalized.append((key, Language.normalizeTag(lang_code), value))

        # 校验与写入之间的一致性哨兵：正常情况下上面已经拒过，走到这里还拿到 `None`
        # 只可能是"校验被绕过"（桩替、将来新增的第三条写路）。宁可点名拒写，
        # 也不要在这里把 None 传进 `language.value` —— 那会被下面的 except 兜成 False，
        # 而那时内存里可能已经写进半截（§6-140 记的就是这个形态）。
        stray = [(k, c) for k, lang, c in normalized if lang is None]
        if stray:
            logger.error("译文库写入被中止：校验放过了一条不识别的语言码 %r（不该发生）", stray)
            return False

        try:
            with self._lock:
                # 更新内存中的翻译
                if namespace not in self._translations:
                    self._translations[namespace] = {}

                for key, language, value in normalized:
                    if key not in self._translations[namespace]:
                        self._translations[namespace][key] = {}

                    translation = Translation(
                        key=key,
                        language=language,
                        value=value,
                        namespace=namespace,
                        is_approved=False,
                        translator="user",
                    )
                    self._translations[namespace][key][language.value] = translation

                # 保存到文件
                self.data_dir.mkdir(parents=True, exist_ok=True)
                file_path = self.data_dir / f"{namespace}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(translations, f, ensure_ascii=False, indent=2)

                logger.info("Saved translations to %s", file_path)
                return True

        except Exception as e:
            logger.error("Failed to save translations: %s", e)
            return False

    def overlayEntries(self, namespace: str, language: Language) -> List[Translation]:
        """覆盖层读面：按命名空间与语言取出**全部**条目，含未审的，按 key 排序。

        为什么单开一个读法而不是放宽 `get_translation()`：后者是内置那条读路，门是
        `is_approved`（`:328`）；裁定「不引入审批」的意思是"不假装有人审过"，
        不是"把未审的当已审送进所有读路径"。所以这里原样取出、把 `is_approved`
        与 `translator` 一起交给调用方，让读的人自己看得见状态。
        """
        with self._lock:
            bucket = (self._translations.get(namespace) or {})
            entries = [t for keys in bucket.values()
                       for t in keys.values() if t.language is language]
        return sorted(entries, key=lambda t: t.key)

    def get_translation(
        self, key: str, language: Optional[Language] = None, namespace: str = "default", fallback: bool = True
    ) -> Optional[str]:
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

    def translate(
        self,
        text: str,
        target_language: Optional[Language] = None,
        source_language: Optional[Language] = None,
        context: Optional[str] = None,
    ) -> TranslationResponse:
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
            key=text, source_language=source_language or Language.AUTO, target_language=target_language, context=context
        )

        # 查找翻译
        translated = self.get_translation(text, target_language)
        if translated and translated != text:
            return TranslationResponse(request=request, translated_text=translated, confidence=1.0, source="memory")

        # 如果没有找到翻译，返回原文
        return TranslationResponse(request=request, translated_text=text, confidence=0.0, source="fallback")

    def _load_user_preferences(self) -> None:
        """从盘上读回用户偏好：一个坏条目只跳它自己，整份文件坏了就改名隔离。

        三种形态分开处置，混在一起就会造出"读数看起来正常、其实是被清空"：
        - 文件不存在 ⇒ 正常空态（没人设过偏好，不是故障，也不建文件）；
        - JSON 解析失败 / 版本不认识 ⇒ `quarantine_corrupt_file` 留现场，内存按空态起，
          原路径腾空——否则紧接着的任何一次成功保存会用内存空态覆盖掉真数据（整库丢失）；
        - 单个用户条目不合法（不识别的语言码、`user_id` 与键不一致）⇒ 只跳那一条并点名，
          与译文装载面「一个坏码不许毁掉整份文件」是同一条口径（§6-145）。
        """
        path = Path(self.preferences_path)
        if not path.exists():
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            quarantined = quarantine_corrupt_file(path)
            logger.error("用户偏好文件无法解析，已隔离现场 %s：%s（本轮按空态起，不覆盖原文件）",
                         quarantined, e)
            return

        if not isinstance(data, dict) or data.get("version") != PREFERENCES_STORE_VERSION:
            quarantined = quarantine_corrupt_file(path)
            logger.error("用户偏好文件格式版本不认识（现值 %r，期望 %r），已隔离现场 %s——"
                         "不做自动映射：那种映射会把没人签过字的旧数据读成签过",
                         data.get("version") if isinstance(data, dict) else "<非映射>",
                         PREFERENCES_STORE_VERSION, quarantined)
            return

        loaded = 0
        self._outOfBoxDefault = self._readDefaultEntry(data.get(DEFAULT_STORE_KEY))
        for key, entry in (data.get("preferences") or {}).items():
            if not isinstance(entry, dict):
                logger.warning("跳过格式不合法的用户偏好条目：user=%r", key)
                continue
            try:
                preference = UserLanguagePreference.from_dict(entry)
            except Exception as e:
                logger.warning("跳过不合法的用户偏好条目 user=%r：%s", key, e)
                continue
            if preference.user_id != key:
                logger.warning("跳过键与条目属主不一致的用户偏好：键=%r 条目=%r",
                               key, preference.user_id)
                continue
            self._user_preferences[preference.user_id] = preference
            loaded += 1

        logger.info("读回用户语言偏好：%s 条（跳过 %s 条）",
                    loaded, len(data.get("preferences") or {}) - loaded)

    def _persist_user_preferences(self) -> None:
        """把当前全部偏好原子写盘；失败向上抛，由调用方（按人写入 / 开箱默认写入）回滚。

        `default` 键**只在设过的时候出现**：一条 GET 之后不该凭空长出这格，
        而"没人定过起点"与"定过但值是 zh"必须是两个能区分的读数。
        """
        payload: Dict[str, Any] = {
            "version": PREFERENCES_STORE_VERSION,
            "preferences": {uid: pref.to_dict() for uid, pref in self._user_preferences.items()},
        }
        if self._outOfBoxDefault is not None:
            payload[DEFAULT_STORE_KEY] = self._outOfBoxDefault.to_dict()
        atomic_write_text(self.preferences_path, json.dumps(payload, ensure_ascii=False, indent=2))

    def _readDefaultEntry(self, raw: Any) -> Optional[UserLanguagePreference]:
        """把存储顶层那条 `default` 读成一条开箱默认；坏就只跳它自己并点名。

        一条坏默认值不许把整份按人偏好带下水——与 `_load_user_preferences` 里
        「一个坏码不许毁掉整份文件」是同一条口径（§6-145）。
        """
        if raw is None:
            return None
        if not isinstance(raw, dict):
            logger.warning("跳过格式不合法的开箱默认条目（不是对象）：%r", type(raw).__name__)
            return None
        try:
            preference = UserLanguagePreference.from_dict(raw)
        except Exception as e:
            logger.warning("跳过不合法的开箱默认条目：%s", e)
            return None
        # 存的就是"给所有没选过的人"的那一条，属主名不进 `preferences` 表，所以这里
        # 只要求它是那条保留名；别的名字说明这份文件被手改过，按不合法跳掉而不是猜。
        if preference.user_id != OUT_OF_BOX_OWNER:
            logger.warning("开箱默认条目的属主不是保留名（现值 %r），按不合法跳过",
                           preference.user_id)
            return None
        return preference

    def getOutOfBoxDefault(self) -> Optional[UserLanguagePreference]:
        """管理员替「还没表达过偏好的人」定的起点；没设过就是 `None`（不冒充成一条决定）。"""
        with self._lock:
            return self._outOfBoxDefault

    def setOutOfBoxDefault(self, preference: UserLanguagePreference) -> bool:
        """写开箱默认：内存与盘同成或同败（与按人偏好那条纪律一寸不差）。

        这一格影响的是**所有还没选过的人**，所以"内存里已经有了、盘上没写成"
        绝不能被当成保存成功——重启后它就不在了，而管理员已经以为改动生效。
        """
        if preference.user_id != OUT_OF_BOX_OWNER:
            logger.warning("拒绝写入属主不是保留名的开箱默认条目（user_id=%r）",
                           preference.user_id)
            return False

        with self._lock:
            previous = self._outOfBoxDefault
            self._outOfBoxDefault = preference
            try:
                self._persist_user_preferences()
            except Exception as e:
                self._outOfBoxDefault = previous
                logger.error("Failed to persist out-of-box language default: %s", e)
                return False

            logger.info("开箱语言默认已保存：%s（影响所有未表达过偏好的用户）",
                        preference.primary_language.value)
            return True

    def resolvePreference(self, user_id: str) -> Tuple[UserLanguagePreference, str]:
        """这个人现在该看哪种语言，**以及这个读数是哪个来源给的**。

        解析链三格：本人偏好 → 开箱默认 → 枚举级 last resort。不点名来源就退成"返回一个
        偏好"，那「管理员设的开箱默认到底生效了没」在生产里不可观测——而这条链在 §6-167
        之前正是靠不可观测活着的（四份默认值谁都没读过它）。
        """
        with self._lock:
            preference = self._user_preferences.get(user_id)
            if preference is not None:
                return preference, self.EFFECTIVE_SOURCES[0]
            if self._outOfBoxDefault is not None:
                return self._outOfBoxDefault, self.EFFECTIVE_SOURCES[1]
            return (UserLanguagePreference(user_id=user_id or OUT_OF_BOX_OWNER,
                                           primary_language=self.default_language,
                                           fallback_language=self.default_language),
                    self.EFFECTIVE_SOURCES[2])

    def set_user_preference(self, user_id: str, preference: UserLanguagePreference) -> bool:
        """
        设置用户语言偏好（写内存 + 落盘，两边同成或同败）

        Args:
            user_id: 用户ID
            preference: 用户语言偏好

        Returns:
            是否设置成功——**盘上没写成就不算成功**（调用方据此如实回错，
            不能拿"内存里已经有了"对用户承诺已保存）
        """
        if not user_id:
            logger.warning("拒绝写入无属主的语言偏好（user_id 为空）")
            return False

        with self._lock:
            previous = self._user_preferences.get(user_id)
            self._user_preferences[user_id] = preference
            try:
                self._persist_user_preferences()
            except Exception as e:
                if previous is None:
                    self._user_preferences.pop(user_id, None)
                else:
                    self._user_preferences[user_id] = previous
                logger.error("Failed to persist user preference for %s: %s", user_id, e)
                return False

            logger.info("Set user preference: %s -> %s", user_id, preference.primary_language.value)
            return True

    def get_user_preference(self, user_id: str) -> Optional[UserLanguagePreference]:
        """获取用户语言偏好（**只读**，不在这里建文件也不落默认值）"""
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
        """检测浏览器语言（Accept-Language 头）。

        口径不再自己有一份：原先这里私藏一刀 `lang.split("-")[0]`，而枚举侧的 `from_str`
        反而不认区域码——同一件事两处各写一遍，其中一遍还是错的（教义第 6 条）。
        现在统一走 `Language.normalizeTag()`，不识别的候选**跳过**，
        全部不识别时回调用方给的默认语言（不再是枚举的 `AUTO`）。
        """
        if not accept_language:
            return self.default_language

        # 解析 Accept-Language 头
        candidates: List[tuple] = []
        for part in accept_language.split(","):
            part = part.strip()
            if ";q=" in part:
                lang, q = part.split(";q=")
                try:
                    quality = float(q)
                except ValueError:
                    quality = 0.0
            else:
                lang = part
                quality = 1.0
            candidates.append((lang.strip(), quality))

        # 按质量排序
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 查找第一个支持的语言
        available_languages = self.get_available_languages()
        for tag, _quality in candidates:
            language = Language.normalizeTag(tag)
            if language is not None and language in available_languages:
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
                "available_languages": len(self.get_available_languages()),
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

    def _set_cache(self, key: str, value: str, language: Optional[Language] = None) -> None:
        """设置缓存"""
        if key not in self._cache:
            self._cache[key] = {}

        lang_key = language.value if language else "default"
        self._cache[key][lang_key] = value
        self._cache_timestamps[key] = time.time()


# 全局实例
_language_manager: Optional[LanguageManager] = None


@lazySingleton("_language_manager")
def get_language_manager() -> LanguageManager:
    """获取全局 language 管理器实例"""
    return LanguageManager()


def init_language(data_dir: Optional[str] = None, default_language: Language = Language.CHINESE) -> LanguageManager:
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
