# -*- coding: utf-8 -*-
r"""匿名化出口 + `isCredentialKey` 注解面（static-gate 这两处未定义名的判据）。

CI 的 static-gate 只报"有个未定义名"，报不出"哪个出口值是错的"，这两处各有各的落点：

- `MemorySecurity.anonymize_content`：两个分支都在 `with` 块内 `return`，块外还留着一句
  `return result`，而 `result` 在本函数从未绑定。非空输入走不到它，**空输入**才走到
  ——"反正走不到"不能当修法，这一格把空输入钉住。
- `sensitive_info.isCredentialKey(name: Any)`：注解里的 `Any` 没从 `typing` 带进来。
  因为 `from __future__ import annotations` 把注解串化了，模块能 import 成功、运行期不炸，
  只有静态门禁红一次；`typing.get_type_hints()` 是这条注解第一次被真正求值的地方。

判据全部走**在役入口**（构造 `MemorySecurity()`、调 `isCredentialKey()`），不 reference
任何新符号：实现怎么改都行，读数必须一样。
掩码档「与单源引擎逐字相等」的裁决只在
`test_sensitiveInfoRulesAreSingleSourced.py::testSanitizeEngineHasOneImplementation` 一处，
本文件不抄第二份。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.security import MemorySecurity
from neurova.security.sensitive_info import isCredentialKey

#: 一条键值式凭据与一条纯散文（散文两档都不该被动手）。
_SECRET_TEXT = "rotate token=abcdef123456 now"
_BENIGN_TEXT = "把报告转成 PDF 并放到 docs/ 目录"


class TestAnonymizeReturnsTheEngineReading:
    def testSecretIsGoneInBothBranches(self):
        """两档都不得把原值原样交回去。"""
        memory = MemorySecurity()
        for text in (_SECRET_TEXT, "配置密钥 password=Alpha7 Bravo9 后重启"):
            for preserve in (True, False):
                out = memory.anonymize_content(text, preserve_format=preserve)
                assert "abcdef123456" not in out and "Alpha7 Bravo9" not in out, (preserve, out)

    def testKeepFormatBranchKeepsTheLength(self):
        """保长度档：长度看得见、值看不见（与掩码档是两种形状，不并成一条）。"""
        out = MemorySecurity().anonymize_content(_SECRET_TEXT, preserve_format=True)
        assert len(out) == len(_SECRET_TEXT), out
        assert out != _SECRET_TEXT

    def testBenignTextPassesThroughVerbatim(self):
        """正对照：无凭据的散文两档都逐字不动（把正常文本打花不是更安全）。"""
        memory = MemorySecurity()
        for preserve in (True, False):
            assert memory.anonymize_content(_BENIGN_TEXT, preserve_format=preserve) == _BENIGN_TEXT


class TestAnonymizeEmptyInputIsAnEmptyString:
    """空输入这一支正是那句话（块外 `return result`）的落点——它必须是 `""`，不是 `None`。"""

    @pytest.mark.parametrize("preserve", [True, False])
    def testEmptyInputYieldsEmptyString(self, preserve):
        out = MemorySecurity().anonymize_content("", preserve_format=preserve)
        assert out == "" and isinstance(out, str), repr(out)


class TestCredentialKeyAnnouncesItsType:
    """`isCredentialKey(name: Any)` 的注解得能真的解析出 `Any`（静态面才是通的那一面）。"""

    def testAnnotationResolvesToARealType(self):
        import typing
        hints = typing.get_type_hints(isCredentialKey)
        assert hints["name"] is typing.Any, hints["name"]
        assert hints["rules"] is not None

    def testReadingsSurviveTheAnnotationFix(self):
        """正反两向对照：注解修完读数不得变（`Any` 换成别的更宽类型就是另一件事了）。"""
        for key in ("api_key", "apikey", "token", "authorization", "cookie", "secret", "password", "口令"):
            assert isCredentialKey(key) is True, key
        for key in ("", "  ", "token_count", "notes", None, 42):
            assert isCredentialKey(key) is False, repr(key)
