# -*- coding: utf-8 -*-
"""语言码口径与模型契约（台账 §6-140；用户 2026-10-11 裁「保留 `language/` 并接进现有语言面」）。

本文件先解决两件互相咬着的事：

1. **一条常驻红**：`TestUserLanguagePreference` 早年按想象写了 `language=` 这个键，
   而契约里的字段是 `primary_language`（`models.py:192-202`）——TypeError 起不来，
   整档 1 failed / 9 passed 挂了很久且不在受保护子集里（§6-129 就地登记过）。
2. **一个静默腐蚀读数的兜底**：`Language.from_str("zh-CN")` 今天回 `AUTO`。
   而仓内实际流通的语言码**正是带区域后缀的那一套**（`NeurUI/src/i18n/locales/zh-CN.ts` 等 11 份、
   `api/endpoints/settings.py` 存的 `"zh-CN"`）。未知码与「自动检测」共用一个值 ⇒
   「我没看懂这个码」被 `AUTO` 这个合法成员背书了（与 §6-126 的"故障读成结论"同族）。

修法放在**上游生产非法状态的地方**（教义第 1 条）：口径收成一处 `normalizeTag()`，
不识别就返回 `None` 交调用方点名，不再由枚举自己替调用方决定兜底。
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.ast_scan import parseSource


class TestLanguageTagNormalization:
    def test_regionSuffixedTagsResolveToTheirPrimarySubtag(self):
        """仓内流通的是 BCP-47 带区域码；主子标签归一是唯一口径。"""
        from neurova.language.models import Language

        assert Language.normalizeTag("zh-CN") is Language.CHINESE
        assert Language.normalizeTag("zh_CN") is Language.CHINESE
        assert Language.normalizeTag("en-US") is Language.ENGLISH
        assert Language.normalizeTag("pt-BR") is Language.PORTUGUESE
        assert Language.normalizeTag("DE-de") is Language.GERMAN

    def test_exactCodesStillResolve(self):
        from neurova.language.models import Language

        assert Language.normalizeTag("zh") is Language.CHINESE
        assert Language.normalizeTag("auto") is Language.AUTO
        assert Language.normalizeTag(Language.JAPANESE) is Language.JAPANESE

    def testUnrecognizedCodeIsNotSilentlyAuto(self):
        """未知码必须"没人认"，不许借 `AUTO` 这个合法值装作认得。"""
        from neurova.language.models import Language

        assert Language.normalizeTag("klingon") is None, (
            "normalizeTag 把不识别的码折成了 %r——`AUTO` 是「自动检测」，"
            "不是「我没看懂」" % (Language.normalizeTag("klingon"),))
        assert Language.normalizeTag("") is None

    def test_from_str_raises_for_unrecognized_instead_of_returning_auto(self):
        from neurova.language.models import Language

        assert Language.from_str("zh-CN") is Language.CHINESE

        with pytest.raises(ValueError):
            Language.from_str("klingon")

    def testEmptyAndAutoStayDistinct(self):
        """`auto` 是合法值、空串是"没给"——两者都不得与"不识别"混成一个态。"""
        from neurova.language.models import Language

        assert Language.from_str("auto") is Language.AUTO
        with pytest.raises(ValueError):
            Language.from_str("")


class TestTranslationContract:
    def test_is_dataclass(self):
        from neurova.language.models import Translation
        assert dataclasses.is_dataclass(Translation)

    def testBuiltWithEnumSerializesRoundTrip(self):
        """真装配：`to_dict()` 出得来、`from_dict()` 回得去，不止字段回显。"""
        from neurova.language.models import Language, Translation

        t = Translation(key="hello", language=Language.CHINESE, value="你好", namespace="ui")
        dumped = t.to_dict()

        assert dumped["language"] == "zh", dumped
        assert Translation.from_dict(dumped) == t, "往返不等值——序列化面与构造面口径不同"

    def testRawStringCodeIsNormalizedAtConstruction(self):
        """裸串构造当场归一。

        原缺陷：dataclass 不做任何校验，`Translation(language="zh")` 存的是**字符串**，
        `to_dict()` 里的 `self.language.value` 随即 AttributeError——
        测试却因"字段回显相等"而绿（断形状不断装配）。归一放在构造点，
        非法状态就生产不出来（教义第 1 条），不必在每个消费方补判空。
        """
        from neurova.language.models import Language, Translation

        t = Translation(key="hello", language="zh-CN", value="你好")

        assert t.language is Language.CHINESE, (
            "裸串没归一，`to_dict()` 会在此处 AttributeError：%r" % (t.language,))
        assert t.to_dict()["language"] == "zh"

    def testUnrecognizedCodeCannotBeStoredInATranslation(self):
        from neurova.language.models import Translation

        with pytest.raises(ValueError):
            Translation(key="hello", language="klingon", value="?")


class TestUserLanguagePreferenceContract:
    def test_is_dataclass(self):
        from neurova.language.models import UserLanguagePreference
        assert dataclasses.is_dataclass(UserLanguagePreference)

    def test_can_instantiate(self):
        """按**契约里的键名**构造——原红就是发明了 `language=` 这个不存在的键。"""
        from neurova.language.models import Language, UserLanguagePreference

        pref = UserLanguagePreference(user_id="u1", primary_language=Language.ENGLISH)

        assert pref.user_id == "u1"
        assert pref.primary_language is Language.ENGLISH

    def testLanguageIsNotAContractKey(self):
        """反向格：`language` 不是本类的字段，谁再按想象构造就红在这里。"""
        from neurova.language.models import UserLanguagePreference

        fieldNames = {f.name for f in dataclasses.fields(UserLanguagePreference)}

        assert "primary_language" in fieldNames, sorted(fieldNames)
        assert "language" not in fieldNames, (
            "契约里长出了第二个语言键（与 `primary_language` 并存＝两份口径，教义第 6 条）：%s"
            % sorted(fieldNames))

        with pytest.raises(TypeError):
            UserLanguagePreference(user_id="u1", language="en")

    def testPreferenceCodesAreNormalizedToo(self):
        """偏好对象吃区域码：现役 UI 传的就是 `zh-CN`，不归一就会与枚举比较失配。"""
        from neurova.language.models import Language, UserLanguagePreference

        pref = UserLanguagePreference(
            user_id="u1",
            primary_language="zh-CN",
            secondary_languages=["en-US", "ja"],
            fallback_language="de-DE",
        )

        assert pref.primary_language is Language.CHINESE
        assert pref.secondary_languages == [Language.ENGLISH, Language.JAPANESE]
        assert pref.fallback_language is Language.GERMAN


def _dashSplitSites(root):
    """语言包内**按连字符切标签**的落点：`文件::所属函数`（AST 取节点，不按文本猜）。"""
    import ast as _ast
    import pathlib

    from tests import ast_scan

    sites = []
    # 枚举与解析走 tests/ast_scan 的共享预算；预筛词是判据的**充分条件**
    # （谓词只认 `.split("-")` 这一形态，连 `split` 字样都没有的文件不可能命中）。
    for ref in ast_scan.sourceRefsUnder(pathlib.Path(root), ".py",
                                        ast_scan.textHints("split")):
        try:
            tree = parseSource(ref.code)
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in _ast.walk(tree):
            if not (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                    and node.func.attr == "split"):
                continue
            if not (node.args and isinstance(node.args[0], _ast.Constant)
                    and isinstance(node.args[0].value, str) and "-" in node.args[0].value):
                continue
            holder = None
            for fn in _ast.walk(tree):
                if not isinstance(fn, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                    continue
                if fn.lineno <= node.lineno <= (fn.end_lineno or fn.lineno):
                    if holder is None or fn.lineno > holder.lineno:
                        holder = fn
            sites.append("%s::%s" % (ref.path.name, holder.name if holder else "<module>"))
    return sites


class TestSingleSourceForTagNormalization:
    """「取主子标签」在语言包里只许有一处（教义第 6 条：口径不得有两份定义）。

    原缺陷正是双口径：`detect_browser_language` 自己 `split("-")[0]`，而枚举侧的 `from_str`
    不认区域码——两处都算"在归一"，一处归对、一处归错，读面于是分叉。
    """

    def test_only_normalize_tag_splits_on_the_subtag_separator(self):
        from pathlib import Path as _P

        pkg = _P(__file__).resolve().parents[2] / "neurova" / "language"
        sites = _dashSplitSites(pkg)

        assert sites, "语言包里一处连字符切分都没有——扫描面空了，本格已无从判事"
        offenders = [s for s in sites if not s.endswith("::normalizeTag")]
        assert not offenders, (
            "语言包里长出了第二份区域码归一，它会与 `Language.normalizeTag` 分叉：%s" % offenders)

    def test_guard_detects_a_duplicate_split(self, tmp_path):
        """反空转：合成一处"第二份口径"必须被抓到，否则上一条格可以恒绿。"""
        pkg = tmp_path / "neurova" / "language"
        pkg.mkdir(parents=True)
        (pkg / "other.py").write_text(
            "def helper(tag):\n    return tag.split('-')[0]\n", encoding="utf-8")

        assert _dashSplitSites(pkg) == ["other.py::helper"], (
            "守卫没抓到合成的第二份口径：%s" % _dashSplitSites(pkg))

