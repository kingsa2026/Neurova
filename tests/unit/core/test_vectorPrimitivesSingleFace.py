# -*- coding: utf-8 -*-
"""§6-182 批 34：向量原语（范数／点积／归一化）也只有单源那一个出口（教义第 6 条）。

批 33 把余弦收成一份后，同一族里还剩三个公共原语住在 `unified_vector_store` 里
（`vector_norm` / `vector_dot` / `vector_normalize`）——按仓主的裁定"把它们也接进单源当公共出口"。
本批是**纯搬家**：语义逐值不变（含两处容易顺手改错的细节——零范数时 `vector_normalize` 返回的是
**传入的那个对象本身**而不是副本；`vector_dot` 对长度不等按 `zip` 截断，那是点积的定义而非缺陷，
维度守卫归余弦那一处）。所以判据同时钉两件事：搬完读数一字不变、旧落点不再导出这三个名字。

`_rawCosine` 不复用 `vectorNorm`：它在一次遍历里同时算点积与两条范数（检索热路），
拆成三次遍历是白付一倍开销——这不是"第二份实现"，是同一份口径下的另一种循环形状。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) .venv/Scripts/python.exe -m pytest \
tests/unit/core/test_vectorPrimitivesSingleFace.py -q`
"""

from __future__ import annotations

import ast
from pathlib import Path

from neurova.core import vector_math

from tests import ast_scan
from tests.ast_scan import parseSource

NEUROVA_ROOT = Path(vector_math.__file__).resolve().parent.parent
SINGLE_FACE = "core/vector_math.py"
OLD_HOST = "cognitive_layers/memory_layer/unified_vector_store.py"
#: 旧落点的**绝对模块名**——相对形要按它比，不能按末段名猜
OLD_HOST_MODULE = "neurova." + OLD_HOST[: -3].replace("/", ".")
PRIMITIVES = ("vector_norm", "vector_dot", "vector_normalize", "vectorNorm", "vectorDot", "vectorNormalize")


def _parse(rel: str) -> ast.Module:
    return parseSource((NEUROVA_ROOT / rel).read_text(encoding="utf-8"))


def _primitiveDefinitions() -> list:
    """全仓 `neurova/` 里这几个原语的**定义**落点（按归属收口，不看调用也不看文本包含）。

    取数走共享解析预算 `tests/ast_scan`（Issue #148）：私有 `rglob + ast.parse`
    把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟。
    文本预筛按**定义形状**取词——`def <名字>` 都没出现的文件不可能定义它。
    """
    hits = []
    for ref in ast_scan.sourceRefsUnder(
            NEUROVA_ROOT, hints=tuple("def %s" % name for name in PRIMITIVES)):
        for node in ast.walk(ast_scan._cachedParse(ref.stamp, ref.code)):
            if isinstance(node, ast.FunctionDef) and node.name in PRIMITIVES:
                hits.append("%s::%s" % (ref.path.relative_to(NEUROVA_ROOT).as_posix(),
                                        node.name))
    return sorted(hits)


def _importsFromOldHost() -> list:
    """还有谁从旧落点导这几个名字——留着就是两份出口并存，改一处另一处静默不跟。

    取数走共享入口 `namesTakenFrom`：它把每一条 `from … import …`（含 `from .x`、`from ..x`
    这些相对形）先经 `resolveImportModule` 解析成绝对名再比对，判据自己不再猜"末段名相配"。
    预筛仍取旧落点名——那是充分条件：连这串字样都没出现的文件不可能从它导东西。

    **已知未收边界**（记在 §6-318，不在本格内偷偷放宽）：
    `import …unified_vector_store as p` 之后 `p.vector_norm` 这种**属性取法**不在本格面内。
    要覆盖它得换 `takenPerModule`，而那是整树全量解析、不带文本预筛——常驻格付不起这个成本，
    付得起的写法是把属性形做成一次性取证而不是常驻判据。
    """
    scan = ast_scan.nodeScan(NEUROVA_ROOT, ".py", ast_scan.textHints("unified_vector_store"))
    return sorted({f"{ast_scan.relativeToRepo(path)}:{name}"
                   for name, path, _lineno
                   in ast_scan.namesTakenFrom(scan, OLD_HOST_MODULE)
                   if name in PRIMITIVES})


def testPrimitivesAreDefinedOnlyInTheSingleFace():
    assert _primitiveDefinitions() == [
        "%s::vectorDot" % SINGLE_FACE,
        "%s::vectorNorm" % SINGLE_FACE,
        "%s::vectorNormalize" % SINGLE_FACE,
    ], f"三个原语的定义必须只在单源，实得 {_primitiveDefinitions()}"


def testNobodyImportsThePrimitivesFromTheOldHost():
    assert _importsFromOldHost() == [], f"旧落点还在被当公共出口用：{_importsFromOldHost()}"


def testEnumerationProbesHaveTeeth():
    """排除型守卫要先证自己抓得到——否则"只剩一处"绿得没道理。"""
    dup = parseSource("def vector_norm(a):\n    return 0.0\n").body[0]
    unrelated = parseSource("def render(a):\n    return 0.0\n").body[0]
    assert dup.name in PRIMITIVES and unrelated.name not in PRIMITIVES
    imports = parseSource(
        "from neurova.cognitive_layers.memory_layer.unified_vector_store import vector_norm, UnifiedVectorStore\n"
    ).body[0]
    assert sorted(a.name for a in imports.names if a.name in PRIMITIVES) == ["vector_norm"]

    # 本格对 `from .x import` 这一形是否有输入：相对名必须解得回旧落点的绝对模块名，
    # 否则 `_importsFromOldHost` 的等值比对就是瞎的（解名这件事由共享单点负责）
    rel = parseSource("from .unified_vector_store import vector_norm\n").body[0]
    assert ast_scan.resolveImportModule(
        "neurova/cognitive_layers/memory_layer/some_module.py", rel) == OLD_HOST_MODULE, \
        "相对形解不回旧落点——本格看不见 `from .unified_vector_store import vector_norm`"


def testMovedSemanticsAreValueIdentical():
    """搬家不改读数：零范数时 normalize 返回**传入对象本身**（不是副本），dot 按 zip 截断。"""
    assert vector_math.vectorNorm([3, 4]) == 5.0
    assert vector_math.vectorNorm([0, 0]) == 0.0
    assert vector_math.vectorDot([1, 2, 3], [4, 5, 6]) == 32
    assert vector_math.vectorDot([0, 0], [1, 1]) == 0.0

    normalized = vector_math.vectorNormalize([3, 4])
    assert abs(normalized[0] - 0.6) < 1e-6 and abs(normalized[1] - 0.8) < 1e-6
    zero = [0.0, 0.0]
    assert vector_math.vectorNormalize(zero) is zero, "零范数那支改前返回原对象，改成副本就是另一种契约"


def testHotPathsNowCallTheSingleFace():
    """消费点正检：旧落点与 moe_router 都改经单源取这三个名字，且自己不再定义任何一个。"""
    for rel in (OLD_HOST, "cognitive_layers/memory_layer/moe_router.py"):
        tree = _parse(rel)
        throughFace = sorted(
            ast.unparse(n.func) for n in ast.walk(tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("vector_math.vector")
        )
        assert throughFace, f"{rel} 里没有任何对单源原语的调用"
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert not (defined & set(PRIMITIVES)), f"{rel} 还自己定义着 {sorted(defined & set(PRIMITIVES))}"


def _isNormShape(src: str) -> bool:
    """式子里既"平方和"又"开根"才算模长自算。两步写法（先 `norm = sum(x*x…)` 再 `sqrt(norm)`）
    不在本探测的覆盖里——这是已知限度，写在格子里而不是装作没有。"""
    if "sum(" not in src:
        return False
    hasSquares = any(x in src for x in ("x * x", "a * a", "y * y", "i * i", "v * v", "p * p"))
    return hasSquares and ("sqrt(" in src or "** 0.5" in src)


def _normShapeHits(root: Path) -> list:
    """按**形状**数"自己算模长"的落点，单源自己那处除外。

    批 33 那枚 M4 教出来的口径：只认函数名的话，站点把原语内联重写一遍就滑过去了
    （本批 M3 正是这一形）。所以这里按式子认，不按 `def vector_norm` 认。"""
    hits = []
    # 取数走共享预算的一次性入口（本判据只扫一次，不留常驻语法树）。
    # 文本预筛：判据要认「平方和 + 开根」，连 `sqrt` 与 `** 0.5` 都没出现的文件
    # 不可能命中——这是 `_isNormShape` 的**充分条件**。
    for ref in ast_scan.sourceRefsUnder(
            root, hints=ast_scan.textHints("sqrt(", "** 0.5")):
        rel = ref.path.relative_to(root).as_posix()
        if rel == SINGLE_FACE:
            continue
        tree = ast_scan._cachedParse(ref.stamp, ref.code)
        for node in ast.walk(tree):
            src = None
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "sqrt":
                src = ast.unparse(node)
            elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
                src = ast.unparse(node)
            if src and _isNormShape(src):
                hits.append("%s:%d" % (rel, getattr(node, "lineno", 0)))
    return sorted(hits)


def testNoSiteRecomputesANormInline():
    """模长只有一个算法落点：`core/vector_math.vectorNorm`（`_rawCosine` 在单源内自算，另计）。"""
    assert _normShapeHits(NEUROVA_ROOT) == [], f"还有站点自己算模长：{_normShapeHits(NEUROVA_ROOT)}"


def testNormShapeProbeHasTeeth():
    """枚举格先证自己抓得到内联重写——否则"只剩一处"绿得没道理。"""
    assert _isNormShape("math.sqrt(sum(x * x for x in v))")
    assert _isNormShape("sum(x * x for x in v) ** 0.5")
    assert not _isNormShape("sum(v) / len(v)"), "均值不是模长，别把它算成命中"
    assert not _isNormShape("math.sqrt(len(v))"), "没平方和就不是模长"
    assert not _isNormShape("sum(x * y for x, y in zip(a, b))"), "点积不是模长"
