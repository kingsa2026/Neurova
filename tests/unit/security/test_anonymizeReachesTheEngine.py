# -*- coding: utf-8 -*-
r"""匿名化出口 + `isCredentialKey` 注解面（static-gate 这两处未定义名的判据）。

CI 的 static-gate 只报"有个未定义名"，报不出"哪个出口值是错的"，这两处各有各的落点：

- `MemorySecurity.anonymize_content`：两个分支都在 `with` 块内 `return`，块外还留着一句
  `return result`，而 `result` 在本函数从未绑定。非空输入走不到它，**空输入**才走到
  ——"反正走不到"不能当修法，这一格把空输入钉住。
- `sensitive_info.isCredentialKey(name: …)`：注解里的名字必须在模块命名空间里真存在。
  因为 `from __future__ import annotations` 把注解串化了，模块能 import 成功、运行期不炸，
  只有静态门禁红一次；`typing.get_type_hints()` 是这条注解第一次被真正求值的地方。
  拼法有两种合法处置（`typing.Any` ＋补 import，或直接用 `object`），本档不站边——
  它按 AST 读声明的名字，再要求那个名字解得出来（§6-498 把这条从旧拼法松开）。

判据全部走**在役入口**（构造 `MemorySecurity()`、调 `isCredentialKey()`），不 reference
任何新符号：实现怎么改都行，读数必须一样。
掩码档「与单源引擎逐字相等」的裁决只在
`test_sensitiveInfoRulesAreSingleSourced.py::testSanitizeEngineHasOneImplementation` 一处，
本文件不抄第二份。
"""

from __future__ import annotations

import ast
import inspect
import sys
import typing

import pytest

from neurova.cognitive_layers.memory_layer.security import MemorySecurity
from neurova.security.sensitive_info import isCredentialKey
from tests.ast_scan import parseSource

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
    """`isCredentialKey` 的 `name` 注解得能真的解析——钉的是「能解析」，不是某一种拼法。

    来历：这格建档时钉的是 `hints["name"] is typing.Any`，因为当时产品写的就是 `Any`
    而 `Any` 没被 import（`from __future__ import annotations` 把注解串化，运行期不炸，
    只有静态门禁红）。`e2098e29` 收同一根因时选了另一种处置——把注解改成 `object`
    （不 import `Any`）。两种处置都合法且等价（该参数确实收任意对象、非 str 即 False），
    所以判据不能跟着某一种拼法走：现在按 AST 读**声明的那个名字**，再要求它
    ① 在运行期命名空间（模块 → 内置）里真存在（未 import 的 `Any` 走不到这一步）
    ② 求值结果与 `get_type_hints` 一致。
    """

    def testAnnotationResolvesToARealType(self):
        declared = _annotationNameOf(isCredentialKey, "name")
        module = sys.modules[isCredentialKey.__module__]
        resolved = _resolveInRuntimeNamespace(module, declared)
        assert resolved is not None, (
            f"注解声明的名字 {declared!r} 既不在 {module.__name__} 的命名空间、也不是内置名——"
            "串化注解让运行期不炸，只有这里能看见它")

        hints = typing.get_type_hints(isCredentialKey)
        assert hints["name"] is resolved, f"求值出 {hints['name']!r}，声明的是 {declared!r}"
        assert hints["rules"] is not None

    def testUndefinedAnnotationNameDoesBlowUpAtEvalTime(self):
        """反向控制：未定义名的注解在求值那一刻真的会炸——否则上一格是恒绿的空话。"""

        def _probe(value: _NameNobodyImports) -> None:  # noqa: F821
            return None

        with pytest.raises(NameError):
            typing.get_type_hints(_probe)


def _annotationNameOf(fn, argName: str) -> str:
    """按 AST 取某参数**声明**的注解名（解析出口走 `tests.ast_scan`，不另起 `ast.parse`）。"""

    tree = parseSource(inspect.getsource(fn))
    target = tree.body[0]
    for a in list(target.args.posonlyargs) + list(target.args.args):
        if a.arg == argName:
            assert a.annotation is not None, f"`{argName}` 没带注解——本档前提不成立"
            assert isinstance(a.annotation, ast.Name), (
                f"`{argName}` 的注解是 `{ast.unparse(a.annotation)}`（非裸名）——"
                "本格只覆盖裸名形，换成组合形请同步扩这格的取法，别把它改成恒真")
            return a.annotation.id
    raise AssertionError(f"`{fn.__name__}` 没有名为 `{argName}` 的参数")


def _resolveInRuntimeNamespace(module, name: str):
    """按 Python 自己解析注解名的顺序找：模块命名空间 → 内置。

    `object` 这一形只会从内置那一步解出来；只看 `vars(module)` 会把合法注解判成未定义名。
    """

    import builtins

    for ns in (vars(module), vars(builtins)):
        if name in ns:
            return ns[name]
    return None

    def testReadingsSurviveTheAnnotationFix(self):
        """正反两向对照：注解修完读数不得变（`Any` 换成别的更宽类型就是另一件事了）。"""
        for key in ("api_key", "apikey", "token", "authorization", "cookie", "secret", "password", "口令"):
            assert isCredentialKey(key) is True, key
        for key in ("", "  ", "token_count", "notes", None, 42):
            assert isCredentialKey(key) is False, repr(key)
