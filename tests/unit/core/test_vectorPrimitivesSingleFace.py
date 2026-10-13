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

NEUROVA_ROOT = Path(vector_math.__file__).resolve().parent.parent
SINGLE_FACE = "core/vector_math.py"
OLD_HOST = "cognitive_layers/memory_layer/unified_vector_store.py"
PRIMITIVES = ("vector_norm", "vector_dot", "vector_normalize", "vectorNorm", "vectorDot", "vectorNormalize")


def _parse(rel: str) -> ast.Module:
    return ast.parse((NEUROVA_ROOT / rel).read_text(encoding="utf-8"))


def _primitiveDefinitions() -> list:
    """全仓 `neurova/` 里这几个原语的**定义**落点（按归属收口，不看调用也不看文本包含）。"""
    hits = []
    for path in sorted(NEUROVA_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 收集卫生守卫兜
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in PRIMITIVES:
                hits.append("%s::%s" % (path.relative_to(NEUROVA_ROOT).as_posix(), node.name))
    return sorted(hits)


def _importsFromOldHost() -> list:
    """还有谁从旧落点导这几个名字——留着就是两份出口并存，改一处另一处静默不跟。"""
    hits = []
    for path in sorted(NEUROVA_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("unified_vector_store"):
                bad = [a.name for a in node.names if a.name in PRIMITIVES]
                if bad:
                    hits.append("%s:%s" % (path.relative_to(NEUROVA_ROOT).as_posix(), ",".join(sorted(bad))))
    return sorted(hits)


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
    dup = ast.parse("def vector_norm(a):\n    return 0.0\n").body[0]
    unrelated = ast.parse("def render(a):\n    return 0.0\n").body[0]
    assert dup.name in PRIMITIVES and unrelated.name not in PRIMITIVES
    imports = ast.parse(
        "from neurova.cognitive_layers.memory_layer.unified_vector_store import vector_norm, UnifiedVectorStore\n"
    ).body[0]
    assert sorted(a.name for a in imports.names if a.name in PRIMITIVES) == ["vector_norm"]


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
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        if rel == SINGLE_FACE:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 收集卫生守卫兜
            continue
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
