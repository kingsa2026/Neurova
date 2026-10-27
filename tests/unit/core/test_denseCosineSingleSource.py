# -*- coding: utf-8 -*-
"""§6-179 批 33：稠密向量余弦全仓只剩一处实现（教义第 6/7 条收口）。

改前的现量：函数名含 `cosine` 的稠密实现 **13 份**（`cognitive_layers/memory_layer` 8、
`context` 2、`knowledge` 2、`skills` 1）+ `graph_traversal.compute_attention_weight` 里一段
内联，共 14 处算法。分叉不是行数：

- **五份没有长度检查**，`zip` 把长的那条截掉 ⇒ 4 维与 1 维算出 **1.0**（满分）。
  这条不会喊人：换过嵌入引擎、索引里存着旧维度向量、缓存没对齐——都会得到最高分并往上排。
- `skills/skill_semantics.py::_cosine` 直接把点积当余弦（注释赌"引擎输出已 L2 归一化"），
  未归一时 `[3,4]·[3,4]` 返回 **25.0**，而它的下游写的是 `if cos >= threshold`。
- 长度不等的另两种处置：`semantic_emotion`／`similarity_fusion` 抛 `ValueError`。
- 值域两份用 `(cos+1)/2` 映射，注释却写"相似度分数 (0-1)"。

按定义域划界（不是按名字）：当年 `memory_layer/vector_search.py::_cosine_similarity` 吃
`Dict[str, float]` 稀疏向量、按键集并集算，**不属于本族**——被"顺手一起并了"就是把稀疏语义
洗成稠密。（那份实现连同模块已在 §6-376 退净；本档对这条界线仍留两半判据：形状正检
`_isSparseSignature` ＋ `testSparseCosineRetiredWithItsModuleAndMustNotBeReintroducedAsDense`。）
`similarity_fusion.cosine` 的"维度不齐就抛"是
**调用方边界上的前置条件**（那条路的坏数据要喊人），收口后仍归它自己持有，不算第二份实现。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) .venv/Scripts/python.exe -m pytest \
tests/unit/core/test_denseCosineSingleSource.py -q`
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from neurova.core import vector_math

from tests import ast_scan
from tests.ast_scan import parseSource

NEUROVA_ROOT = Path(vector_math.__file__).resolve().parent.parent
SINGLE_FACE = "core/vector_math.py"

#: 现役消费点（改后必须只剩调用，不留实现）。列出来而不是靠名字扫，是因为"新长出一份"
#: 由下面那格按形状自己数——本清单只负责证明**已知的这些**确实改指了单源。
SITE_MODULES = [
    "cognitive_layers/memory_layer/compression.py",
    "cognitive_layers/memory_layer/muscle_memory.py",
    "cognitive_layers/memory_layer/neuHebb_curator.py",
    "cognitive_layers/memory_layer/neuHebb_forge.py",
    "cognitive_layers/memory_layer/semantic_emotion.py",
    "cognitive_layers/memory_layer/semantic_search.py",
    "cognitive_layers/memory_layer/sleep.py",
    "cognitive_layers/memory_layer/graph_traversal.py",
    "context/semantic_drawer.py",
    "context/tool_search.py",
    "knowledge/identity/similarity_fusion.py",
    "knowledge/vector_index.py",
    "skills/skill_semantics.py",
    "cognitive_layers/memory_layer/moe_router.py",
    "evolution/skill_consolidator.py",
    "tool_executor.py",
    "evolution/eval/constraints.py",
    "cognitive_layers/memory_layer/volume_renderer.py",
]


def _isSparseSignature(node: ast.FunctionDef) -> bool:
    """定义域是不是稀疏 `Dict[str, float]`——按注解判，不按名字猜。"""
    rendered = ast.unparse(ast.Module(body=[node], type_ignores=[]))
    return "Dict[str, float]" in rendered


def _computesCosineMath(node: ast.FunctionDef) -> bool:
    """按**整个式子**认余弦：点积 ÷（范数 × 范数）。

    只按名字，或按"体里有 sum 也有 sqrt"，会误伤一圈邻居——本批实测 `vector_norm`、
    `_zero_norm`、`_text_to_embedding`、`confidence_interval`、`_compute_task_value` 等
    七个都只是归一化或求和，不是第二份余弦。假红的守卫最后教会人的是绕开守卫，不是遵守它。
    """
    normNames, dotNames = set(), set()
    for n in ast.walk(node):
        if isinstance(n, ast.Assign) and n.targets and isinstance(n.targets[0], ast.Name):
            src = ast.unparse(n.value)
            name = n.targets[0].id
            if "sqrt(" in src or "** 0.5" in src or "pow(" in src:
                normNames.add(name)
            if "sum(" in src and "*" in src:
                dotNames.add(name)

    def isNorm(expr: str) -> bool:
        return "sqrt(" in expr or "** 0.5" in expr or expr in normNames

    def isDot(expr: str) -> bool:
        return ("sum(" in expr and "*" in expr) or expr in dotNames or expr.startswith(("dot", "cos"))

    for n in ast.walk(node):
        if not (isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div)):
            continue
        right = n.right
        if isinstance(right, ast.BoolOp):
            # 只除一条范数（`dot / (norm(a) or 1.0)`）＝赌另一侧已归一，同样是份余弦实现——
            # `skills/skill_semantics` 改前就是这一形，漏了它等于给它留了重长的口子。
            if isNorm(ast.unparse(right)) and isDot(ast.unparse(n.left)):
                return True
            continue
        if not (isinstance(right, ast.BinOp) and isinstance(right.op, ast.Mult)):
            # 除数是"已经算好的范数"变量（`dot / na`）——这一形是变异对照当场抓出来的洞：
            # 只认式子不认变量名时，站点换个写法就从守卫底下滑走了。
            if isinstance(right, ast.Name) and right.id in normNames and isDot(ast.unparse(n.left)):
                return True
            continue
        leftN, rightN = ast.unparse(right.left), ast.unparse(right.right)
        if isNorm(leftN) and isNorm(rightN) and isDot(ast.unparse(n.left)):
            return True
    return False


def _denseCosineDefinitions() -> list:
    """稠密余弦的定义文件清单（按形状认，不按名字）。

    取数走共享解析预算 `tests/ast_scan`（Issue #148）：私有 `rglob + ast.parse`
    把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟。

    用一次性入口 `transientNodes` 而非保留型：本判据只扫一次，保留语法树没有
    收益，成本却全额留下（`AGENTS.md` 修复教义第 6 条：不新造平行体系）。
    文本预筛按 `_computesCosineMath` 的**充分条件**取词——判据要认的是
    「点积 ÷ 范数」，连 `sqrt`/`sum` 都没出现的文件不可能命中。
    """
    hints = ast_scan.textHints("sqrt", "sum(")
    hits = {
        path.relative_to(NEUROVA_ROOT).as_posix()
        for path, node in ast_scan.transientNodes(NEUROVA_ROOT, hints=hints)
        if isinstance(node, ast.FunctionDef)
        and _computesCosineMath(node)
        and not _isSparseSignature(node)
    }
    return sorted(hits)


# ── 一、单源自己的语义 ──


def testComparableVectorsFollowPlainCosine():
    assert vector_math.cosineSimilarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert vector_math.cosineSimilarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert vector_math.cosineSimilarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    # 未归一的同一对：真余弦是 1.0，不是点积 25.0
    assert vector_math.cosineSimilarity([3.0, 4.0], [3.0, 4.0]) == pytest.approx(1.0)


def testIncomparableDimensionsScoreZeroNotOne():
    """本批的靶心：改前五份实现对 4 维 vs 1 维给的是 1.0（满分），不是 0、也不是报错。"""
    long4 = [1.0, 0.0, 0.0, 0.0]
    short1 = [1.0]

    assert vector_math.cosineSimilarity(long4, short1) == 0.0
    assert vector_math.cosineScore(long4, short1) == 0.0
    assert vector_math.cosineSimilarity([], []) == 0.0
    assert vector_math.cosineSimilarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def testScoreMappingIsDefinedOnceAndKeepsItsThreeReadingsApart():
    """0.5＝确知正交，0.0＝没法比——两个数在映射口径里各指各的事，不许合成一个中性值。"""
    assert vector_math.cosineScore([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.5)
    assert vector_math.cosineScore([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert vector_math.cosineScore([1.0, 0.0, 0.0], [1.0, 0.0]) == 0.0


def testTriStateFaceKeepsTheUncomputableApartForCallersThatMustBranch():
    """`evolution/eval/constraints` 那条进化闸靠 None 回退 Jaccard——把"算不了"折成 0.0
    就等于告诉它"算出来是 0"，回退条件从此永不成立。"""
    assert vector_math.tryCosineSimilarity([1.0, 0.0, 0.0], [1.0]) is None
    assert vector_math.tryCosineSimilarity([0.0, 0.0], [1.0, 2.0]) is None
    assert vector_math.tryCosineSimilarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


# ── 二、只剩一处实现 ──


def testDenseCosineIsImplementedOnlyInTheSingleFace():
    assert _denseCosineDefinitions() == [SINGLE_FACE], (
        f"稠密余弦的算法实现必须只在单源那一个文件，实得 {_denseCosineDefinitions()}"
    )


def testScanFaceIsWideEnough():
    """让判据自己数扫描面：漏扫一半的守卫只会绿得没道理（本卷记过 `grep | head` 那形）。

    枚举走共享预算 `ast_scan.filesUnder`（`SHARED_ENUM_ENTRIES`），不自己 `rglob`。
    """
    scanned = ast_scan.filesUnder(NEUROVA_ROOT)
    assert len(scanned) > 1000, f"扫描面只剩 {len(scanned)} 个文件，口径必然被收窄过"


def testCosineMathProbeHasTeeth():
    """排除型断言在缺功能时会自动成立——先证探测器抓得到真实现，且不被名字、注释或邻居骗。"""
    dense = parseSource(
        "def fake(a, b):\n"
        "    dot = sum(x * y for x, y in zip(a, b))\n"
        "    return dot / (math.sqrt(sum(x * x for x in a)) or 1.0)\n"
    ).body[0]
    denseTwoNorms = parseSource(
        "def fake(a, b):\n"
        "    na = math.sqrt(sum(x * x for x in a))\n"
        "    nb = math.sqrt(sum(y * y for y in b))\n"
        "    return sum(p * q for p, q in zip(a, b)) / (na * nb)\n"
    ).body[0]
    namedButNotMath = parseSource("def cosineSimilarity(a, b):\n    return 0.0\n").body[0]
    normalizer = parseSource(
        "def vector_norm(a):\n    return math.sqrt(sum(x * x for x in a))\n"
    ).body[0]
    accumulator = parseSource(
        "def sim(a, b):\n"
        "    dot = 0.0\n    na = 0.0\n    nb = 0.0\n"
        "    for x, y in zip(a, b):\n        dot += x * y\n        na += x * x\n        nb += y * y\n"
        "    return dot / (math.sqrt(na) * math.sqrt(nb))\n"
    ).body[0]
    sparse = parseSource(
        "from typing import Dict\n"
        "def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:\n"
        "    keys = set(a) | set(b)\n"
        "    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)\n"
        "    return dot / (sum(v * v for v in a.values()) ** 0.5 or 1.0)\n"
    ).body[1]

    assert _computesCosineMath(dense), "一行式假样本必须抓到"
    assert _computesCosineMath(denseTwoNorms), "先算两条范数再相除的形也要抓到"
    assert _computesCosineMath(accumulator), "for 累加写法（vector_index 改前那形）必须抓到"
    singleNormVar = parseSource(
        "import math\n"
        "def f(a, b):\n"
        "    dot = sum(x * y for x, y in zip(a, b))\n"
        "    na = math.sqrt(sum(x * x for x in a)) or 1.0\n"
        "    return dot / na\n"
    ).body[1]
    assert _computesCosineMath(singleNormVar), "除数是范数变量那一形也必须抓到（变异 M4 暴露的洞）"
    assert not _computesCosineMath(namedButNotMath), "只叫 cosine 不算实现，别按名字判"
    assert not _computesCosineMath(normalizer), "归一化不是第二份余弦——按名字或按 sum+sqrt 就会假红"
    assert _isSparseSignature(sparse), "按定义域划界：稀疏那份不该被算进本族"


def testSparseCosineRetiredWithItsModuleAndMustNotBeReintroducedAsDense():
    """稀疏那份随 `vector_search.py` 一起于 §6-376 退净（726 行模块与其测试同批退役）。

    本格原形是「稀疏实现必须还在原文件里」，那条断言在 §6-376 之后失去指涉对象，
    变成常驻 `FileNotFoundError`——**判据自己引用已删路径**，属判据侧债
    （§6-396 分流表里那一格就是它；形态 363 的同族：前提塌了，断言不再指向任何对象）。

    性质本身没变：本族收口不得把稀疏语义洗成稠密。现在由两半守住——
    ① `testJudgeSeparatesSparseFromDense` 仍用 `_isSparseSignature` 对合成稀疏样本**正检**
      （形状判据仍在，不依赖那个文件存在）；
    ② 本格钉住 `vector_search.py` 不得复活，且**单源里不许长出稀疏余弦**：
      将来真要引入稀疏余弦，它必须仍是 `Dict[str, float]` 定义域、按键集并集算，
      而不是改指 `vector_math.cosineSimilarity`——那是把"键集并集"洗成"等长稠密"，
      正是本批当初划界要防的事。
    """
    retired = NEUROVA_ROOT / "cognitive_layers" / "memory_layer" / "vector_search.py"
    assert not retired.exists(), (
        f"{retired.relative_to(NEUROVA_ROOT).as_posix()} 被复活：它在 §6-376 随 "
        "memory_index 退净，恢复它要么给出完整稀疏消费者，要么就是第二条并行向量面"
    )
    singleSource = (NEUROVA_ROOT / SINGLE_FACE).read_text(encoding="utf-8")
    tree = parseSource(singleSource)
    sparseInFace = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _isSparseSignature(n)
    ]
    assert not sparseInFace, (
        f"稠密单源里长出了稀疏实现 {sparseInFace}——两种定义域混在一处，"
        "就是当初『把稀疏顺手并了』那件事的反向形态"
    )


def testEveryKnownSiteNowCallsTheSingleFace():
    """消费点逐个正检：文件里要有对单源的调用，且不再自己算。"""
    for rel in SITE_MODULES:
        source = (NEUROVA_ROOT / rel).read_text(encoding="utf-8")
        tree = parseSource(source)
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("vector_math.")
        ]
        assert calls, f"{rel} 没有任何对 vector_math 单源的调用"
        selfMath = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and _computesCosineMath(n)
        ]
        assert not selfMath, f"{rel} 还留着自己算余弦的函数：{[n.name for n in selfMath]}"


def testCallerSidePreconditionStillSoundsTheAlarm():
    """`similarity_fusion` 那条路把"维度不齐"当坏数据要喊人——收口不许把它折成 0.0 静默。

    这是调用方边界上的前置条件，不是第二份实现：它自己不做点积/范数。
    """
    from neurova.knowledge.identity import similarity_fusion

    assert not any(
        _computesCosineMath(n)
        for n in ast.walk(parseSource(inspect_source(similarity_fusion)))
    ), "similarity_fusion 不该再自己算余弦"
    with pytest.raises(ValueError):
        similarity_fusion.cosine([1.0, 0.0, 0.0], [1.0])


def inspect_source(module) -> str:
    from pathlib import Path as _P

    return _P(module.__file__).read_text(encoding="utf-8")


def testSkillSemanticsScoresAreRealCosinesNotDotProducts():
    """那处把点积当余弦的（注释赌"引擎输出已归一"）现在给真余弦：未归一的同一对 ⇒ 1.0 而非 25.0。"""
    from neurova.skills import skill_semantics

    class _Cache:
        def encode_query(self, query):
            return [3.0, 4.0]

        def vectors_for(self, skills):
            return {"alpha": [3.0, 4.0], "beta": [0.0, 0.0]}

    scores = skill_semantics.semantic_scores_for(_Cache(), "q", {"alpha": {}})
    assert scores["alpha"] == pytest.approx(1.0), f"点积冒充余弦：实得 {scores['alpha']}"
    assert scores["beta"] == 0.0


# ── 三、零向量只有一种口径（`isZeroVector`，§6-419）──


def testZeroVectorFaceCoversEveryShapeOfUncomputable():
    """空、无分量、全零、范数低于阈值都是"这一路没算出来"；有分量的向量一个都不是。

    阈值取 `ZERO_NORM_EPSILON` 本身，不在下游再抄一个 1e-9（见下一格）。
    """
    assert vector_math.isZeroVector(None) is True
    assert vector_math.isZeroVector([]) is True
    assert vector_math.isZeroVector([0.0] * 512) is True
    assert vector_math.isZeroVector([1e-15, 0.0]) is True  # 范数 1e-15 < 1e-12
    assert vector_math.isZeroVector([0.1, 0.2]) is False
    assert vector_math.isZeroVector([1.0, -1.0, 0.0]) is False


#: 零向量这件事有两个落点，二者都只有一处定义（否则就是第三份口径）：
#: ①「这一轮算没算出向量」由引擎自己判（`ONNXEmbeddingEngine.encodeOrNone`）；
#: ②「这条向量是不是全零/空」由 `vector_math.isZeroVector` 判——存量条目里躺着的、
#:    注入引擎交上来的，都要过这一道。
#: 下面这张表是**存量与注入入口**的命中面：两个口都要真的问过 ②（引擎缺档时交上来的
#: 是零向量、存量条目里躺着的也是零向量），只走 ① 的地方则必须问过 `encodeOrNone`。
ZERO_VECTOR_CONSUMERS = [
    "cognitive_layers/memory_layer/manager.py",
    "cognitive_layers/memory_layer/muscle_memory.py",
    "cognitive_layers/memory_layer/semantic_search.py",
    "context/tool_search.py",
    "knowledge/vector_index.py",
    "skills/skill_semantics.py",
]


def testZeroVectorThresholdHasNoSecondCopy():
    """阈值只许有一处。下游各抄一个 1e-9／`all(abs(x) < ...)` 就是第二份口径：
    引擎换档、阈值一改，两处读数立刻分叉，而分叉的那一侧永远是静默的那个。"""
    offenders = []
    for rel in sorted(set(ZERO_VECTOR_CONSUMERS)):
        source = (NEUROVA_ROOT / rel).read_text(encoding="utf-8")
        for node in ast.walk(parseSource(source)):
            if not isinstance(node, ast.Compare):
                continue
            rendered = ast.unparse(node)
            if "1e-9" in rendered or ("abs(" in rendered and "1e-" in rendered):
                offenders.append(f"{rel}: {rendered}")
    assert not offenders, (
        "零向量阈值在外又抄了一份（应当只用 vector_math.isZeroVector / ZERO_NORM_EPSILON）："
        f"{offenders}"
    )


def testEveryStockZeroVectorEntryAsksTheSingleFace():
    """存量与注入入口逐个正检：这些模块要真的问过 `isZeroVector`，而不是各自记着
    "零向量长什么样"。只走引擎判定口的写侧不在此列（它问的是 `encodeOrNone`）。"""
    for rel in sorted(set(ZERO_VECTOR_CONSUMERS)):
        source = (NEUROVA_ROOT / rel).read_text(encoding="utf-8")
        assert "isZeroVector" in source or "ZERO_NORM_EPSILON" in source, (
            f"{rel} 没有向单源问过零向量——它要么漏判（把算不出来的存量当有效向量），"
            "要么自己记了一套阈值"
        )


def testZeroVectorProbeHasTeeth():
    """反空转：探测器对合成坏样本必须点名，对合规写法不许误报。"""
    def _offenders(snippet: str) -> list:
        found = []
        for node in ast.walk(parseSource(snippet)):
            if isinstance(node, ast.Compare):
                rendered = ast.unparse(node)
                if "1e-9" in rendered or ("abs(" in rendered and "1e-" in rendered):
                    found.append(rendered)
        return found

    assert _offenders("def f(v):\n    return all(abs(x) < 1e-9 for x in v)\n")
    assert _offenders("def f(v):\n    return max(abs(x) for x in v) < 1e-9\n")
    assert not _offenders("def f(v):\n    return vector_math.isZeroVector(v)\n")
    assert not _offenders("def f(v):\n    return vector_math.vectorNorm(v) <= vector_math.ZERO_NORM_EPSILON\n")
