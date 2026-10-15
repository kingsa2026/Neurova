# -*- coding: utf-8 -*-
"""包门面上的通用名泄漏 + 模块顶层被同名后定义盖掉的 import（§6-212，批 47）。

**这条与「零消费者的业务类再导出」不是一回事。** 档案
`audit-reports/facade-reexport-triage-2026-10-15.md` 把 364 个零消费者绑定分完四态后，
本批只处理其中「无任何自陈背书」的两形：

- 272 个绑在 `__all__` 里＝**明写的公开面**，"无人经门面取"不等于该删（删＝改产品语义）；
- 74 个是本文件自己在用的 typing/stdlib 帮助名——那 5 个包的**实现就写在 `__init__.py` 里**
  （`execution_layers` 706 行 / 16 个定义、`computer_use` 701 行、`benchmark` 562 行、
  `image_pipeline` 382 行、`api/endpoints` 368 行），删不掉，缺的是「声明公开面」那一步；
- 18 个业务类再导出逐档读过后**全部带自陈**（`neurova/memory/__init__.py` 自称"兼容性层，
  为兼容现有测试代码中的导入语句"；`meta_cognition_layer/__init__.py` 的注释明写这次导出是
  批 42/43 拆掉空转 try 段后的**根因修复**）⇒ 要删得逐包裁，不由 AST 规则代拍。

**规则甲（通用名泄漏，只看包门面）**：`neurova/**/__init__.py` 顶层绑了一个
stdlib/typing/dataclasses 帮助名或全仓唯一的取日志器 `get_logger`，而本文件从不读它、
也没写进 `__all__` ⇒ 这条 import 唯一的作用是把通用名变成**包的属性**
（`from neurova.auth import hashlib` 今天真能跑通）。现算落点 1 处：`neurova/auth/__init__.py:10`。

**规则乙（被盖掉的 import，看全部生产文件）**：模块顶层 `from X import a`（或 `import a`）
之后**同一文件里又在顶层**定义同名函数/类/赋值 ⇒ 那条 import 在绑定的一刻就作废，
永远读不到。现算 3 处：`neurova/security/__init__.py:15`（`get_logger` 被 `:22` 的同名 def 盖掉，
而 `__all__` 里那格指的是本地那只——本地这只全仓零引用，§6-201 已按"预存死码、本批不顺手"
登记过）、`neurova/api/endpoints/growth.py:59`（`get_agent as _get_agent` / `get_request_id as
_get_request_id` 被 `:71`/`:76` 的局部包装盖掉；真转发用的是 `:36` 那条 `_impl` 别名，所以
这两条别名 import 从来没生效过）。

两形现算共 4 处，所以两条都按**零容忍**钉，不留存量表（留表＝把"以后再加一条也无妨"写进判据）。
口径成对钉住：用了的不报（否则整仓一起红）、字符串注解里用了的算用（否则造
假红）、只在 docstring 里提过的不算用（否则文本冒充证据）。
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 绑在包级就属"意外泄漏"候选的通用名：标准库与 typing/dataclasses 的帮助名，
#: 外加全仓唯一的取日志器（`neurova.core.logger.get_logger`——它不是 stdlib，但同属
#: "谁都不会打算让包门面替它代言"的那一类，见本档开头）。
GENERIC_NAMES = frozenset({
    "Any", "Callable", "Dict", "List", "Optional", "Set", "Tuple", "Union", "Iterable",
    "Awaitable", "Coroutine", "Sequence", "Mapping", "TypeVar", "Generic", "Literal",
    "TypedDict", "Protocol", "Annotated", "Final", "ClassVar", "cast", "overload",
    "dataclass", "field", "asdict", "astuple", "Enum", "IntEnum", "StrEnum", "auto",
    "unique", "ABC", "ABCMeta", "abstractmethod", "hashlib", "json", "os", "sys", "re",
    "time", "uuid", "asyncio", "threading", "datetime", "timedelta", "Path",
    "OrderedDict", "defaultdict", "Counter", "TextIO", "IO", "BinaryIO",
    "getLogger", "get_logger", "partial", "lru_cache", "cached_property",
})

#: 规则甲只看这些顶层来源的 `from X import 名字`；业务模块的再导出不在这里判
#: （那是上面那 18 个带自陈落点的事，需逐包裁）。`neurova.core.logger` 单独列进来，
#: 因为 `get_logger` 正是从那里取的。
GENERIC_SOURCES = frozenset({
    "typing", "dataclasses", "enum", "abc", "collections", "hashlib", "json", "os",
    "sys", "re", "time", "uuid", "asyncio", "threading", "datetime", "pathlib",
    "functools", "io", "copy", "math", "random", "string", "inspect", "traceback",
    "importlib", "itertools", "contextlib", "logging", "neurova",
})


def _identifiersInExprText(text: str) -> set:
    """字符串注解（PEP 563 风格）里的名字也算"在用"。不认就会造假红。"""
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def _namesUsedInFile(tree: ast.AST) -> set:
    """文件内被读到的名字：跳过 import 语句本身，认属性、基类、装饰器与字符串注解。"""
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        if isinstance(node, ast.ClassDef):
            for base in list(node.bases) + list(node.keywords or []):
                used |= {w for w in GENERIC_NAMES if w in ast.unparse(base).replace(".", " ").split()}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in node.decorator_list:
                used |= {w for w in GENERIC_NAMES if w in ast.unparse(deco).replace(".", " ").split()}
        for attr in ("annotation", "returns"):
            ann = getattr(node, attr, None)
            if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
                used |= _identifiersInExprText(ann.value)
    return used


def _publicDeclaration(tree: ast.AST) -> set:
    """本文件 `__all__` 字面量里写到的名字（＝作者明说"这是公开面"）。"""
    declared = set()
    for node in tree.body:
        targets = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                   if isinstance(node, ast.Assign)
                   else ([node.target.id]
                         if isinstance(getattr(node, "target", None), ast.Name) else []))
        if "__all__" in targets:
            declared |= {e.value for e in getattr(node.value, "elts", [])
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return declared


def genericNameOffenders(tree: ast.AST) -> list:
    """规则甲：包级绑了本文件不读、也未进 `__all__` 的通用名 ⇒ `(lineno, 名, 来源)`。"""
    used, declared = _namesUsedInFile(tree), _publicDeclaration(tree)
    out = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = (alias.asname or alias.name).split(".")[0]
                if bound in GENERIC_NAMES and bound not in used and bound not in declared:
                    out.append((node.lineno, bound, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module not in (None, "__future__"):
            if (node.module or "").split(".")[0] not in GENERIC_SOURCES:
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                if (bound in GENERIC_NAMES and bound not in used
                        and bound not in declared):
                    out.append((node.lineno, bound, f"{node.module}.{alias.name}"))
    return out


def shadowedImportOffenders(tree: ast.AST) -> list:
    """规则乙：顶层 import 的名字又被同层后置定义盖掉 ⇒ 那条 import 从未生效。

    只看 `tree.body` 直列的节点：包在 `try:` 里的可选依赖兜底是**另一种形状**（正当），
    不在本条口径内。
    """
    imported = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.setdefault((alias.asname or alias.name).split(".")[0], node.lineno)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.setdefault(alias.asname or alias.name, node.lineno)
    rebound = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.setdefault(node.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    rebound.setdefault(t.id, node.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)) and isinstance(
                getattr(node, "target", None), ast.Name):
            rebound.setdefault(node.target.id, node.lineno)
    return sorted((ln, nm, rebound[nm]) for nm, ln in imported.items()
                  if nm in rebound and rebound[nm] > ln)


@functools.lru_cache(maxsize=1)
def _scan():
    """一次解析、两条规则共用（`ast_scan.transientTree`＝一次性入口，不留常驻树）。"""
    tracked = [p for p in ast_scan.trackedPaths()
               if p.startswith("neurova/") and p.endswith(".py") and (PROJECT_ROOT / p).exists()]
    generic, shadowed, inits = [], [], 0
    for rel in tracked:
        tree = ast_scan.transientTree(PROJECT_ROOT / rel)
        if rel.endswith("__init__.py"):
            inits += 1
            generic += [(rel, ln, nm, src) for ln, nm, src in genericNameOffenders(tree)]
        shadowed += [(rel, ln, nm, rl) for ln, nm, rl in shadowedImportOffenders(tree)]
    return {"files": tracked, "inits": inits, "generic": generic, "shadowed": shadowed}


def test_noPackageInitBindsAnUnusedGenericName():
    """包门面里不许有"本文件不读、也未声明成公开面"的通用名。"""
    got = _scan()["generic"]
    assert not got, (
        f"这些包级 __init__.py 绑了本文件不读、也没进 __all__ 的通用名，等于把它们变成包的属性："
        f"{[f'{r}:{l} {n}←{s}' for r, l, n, s in got]}")


def test_noTopLevelImportIsShadowedByALaterDefinition():
    """生产文件里不许有"绑上即被同名后定义盖掉"的顶层 import——它从来没生效过。"""
    got = _scan()["shadowed"]
    assert not got, (
        f"这些顶层 import 被同文件后面的同名定义盖掉（import 从未生效）："
        f"{[f'{r}:{l} {n}← 被 :{rl} 的同名定义覆盖' for r, l, n, rl in got]}")


def test_declaredPublicSurfaceHoldsNoGenericName():
    """堵住"把 hashlib 写进 __all__ 来消音"这条后门：通用名不是包的公开面。"""
    offenders = []
    for rel in _scan()["files"]:
        if not rel.endswith("__init__.py"):
            continue
        tree = ast_scan.transientTree(PROJECT_ROOT / rel)
        offenders += [f"{rel} {n}" for n in sorted(_publicDeclaration(tree) & GENERIC_NAMES)]
    assert not offenders, (
        f"这些包把通用名声明进了 __all__（消音不是修法）：{offenders}")


def test_theScanActuallyCoversTheTrackedProductionTree():
    """地板格：两条规则的扫描面都是"全部被跟踪的 `neurova/*.py`"，不许悄悄收窄。

    与批 22 同形——"现值 4 ⇒ 零容忍"的规则，若扫描集合本身能缩，红会在下一次改名/
    挪目录时静默消失。
    """
    read = _scan()
    tracked = [p for p in ast_scan.trackedPaths()
               if p.startswith("neurova/") and p.endswith(".py")]
    assert sorted(read["files"]) == sorted(tracked), (
        f"扫描集合与跟踪面不符（取数 {len(read['files'])}／应有 {len(tracked)}）")
    assert len(read["files"]) >= 900, f"生产侧文件数现读 {len(read['files'])}，地板 900 被打破"
    assert read["inits"] >= 60, f"包门面数量现读 {read['inits']}，地板 60 被打破"
    for known in ("neurova/auth/__init__.py", "neurova/security/__init__.py",
                  "neurova/skills/__init__.py", "neurova/api/endpoints/growth.py"):
        assert known in read["files"], f"{known} 不在扫描集合里——取数口径被收窄了"


def test_aNameTheFileActuallyUsesIsNotReported():
    """反空转配对格：文件真在用的通用名不得被报（否则整仓一起红，规则活不过第二次改码）。"""
    sample = ast.parse("from typing import Dict, Any\n\n"
                       "def f(x: Dict[str, Any]) -> int:\n    return 1\n")
    assert genericNameOffenders(sample) == [], (
        f"文件自己在用却被报：{genericNameOffenders(sample)}")


def test_aStringAnnotationStillCountsAsUse():
    """字符串注解（PEP 563 风格）也是"在用"——不认就会造假红，按真实写法钉住。"""
    sample = ast.parse("from typing import Optional\n\n"
                       "def f(x: \"Optional[str]\") -> None:\n    return None\n")
    assert genericNameOffenders(sample) == [], (
        f"字符串注解里的名字未被认作使用：{genericNameOffenders(sample)}")


def test_aDocstringMentionIsNotAUse():
    """反向的另一半：只在 docstring 里提过 hashlib 仍然算"没读"——文本不是证据。"""
    sample = ast.parse('"""这里说到 hashlib 只是文档。"""\nimport hashlib\n')
    got = genericNameOffenders(sample)
    assert [n for _l, n, _s in got] == ["hashlib"], (
        f"docstring 被当成了使用（判据退化成文本匹配）：{got}")


def test_anImportInsideTryIsNotCalledShadowed():
    """规则乙的另一半口径：可选依赖的 try/except 兜底是正当形状，不得被报。"""
    sample = ast.parse("try:\n    import torch\nexcept ImportError:\n    torch = None\n")
    assert shadowedImportOffenders(sample) == [], (
        f"try 里的可选依赖兜底被误报：{shadowedImportOffenders(sample)}")


def test_aLaterTopLevelDefinitionDoesShadowTheImport():
    """规则乙必须真咬：同名后定义在顶层出现时报，且报的是 import 那一行。"""
    sample = ast.parse("from neurova.core.logger import get_logger\n\n"
                       "def get_logger(name):\n    return None\n")
    got = shadowedImportOffenders(sample)
    assert [n for _l, n, _r in got] == ["get_logger"], (
        f"顶层同名后定义未被识为盖掉：{got}")


def test_anEarlierDefinitionIsNotCalledShadowed():
    """规则乙的**先后**语义：定义在前、import 在后时是 import 覆盖旧定义（正当写法），不报。

    少了这一格，把 `rebound[nm] > ln` 写成 `nm in rebound` 也照样全绿——顺序就成了没人钉的装饰。
    """
    sample = ast.parse("def get_logger(name):\n    return None\n\n"
                       "from neurova.core.logger import get_logger\n")
    assert shadowedImportOffenders(sample) == [], (
        f"import 在后（覆盖旧定义）被误报成死 import：{shadowedImportOffenders(sample)}")
