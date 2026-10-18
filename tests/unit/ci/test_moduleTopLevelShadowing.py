# -*- coding: utf-8 -*-
"""模块级重名定义＝被后一份静默遮蔽的死码（同功能双源的一种最隐蔽形态）。

来历：本仓在一次接缝重构里把 `isRealAgentTrajectoryExecutor` 写了两遍（旧那份读
`realAgentTrajectory` 旗标，新那份改结构推导）。**测试全绿**——因为后定义的覆盖了先定义的，
读到的行为恰好是想要的那个，而旧那份连同它的常量一起躺在文件里当"已经改过了"的证据。
同一次扫描还抓到 `llm/providers/multimodal_prober.py` 的 `_is_media_keyword_error`
（两版判定口径不同，先写的那版从不生效）。

判据一条：**同一模块内不得有两个同名顶层 def/class**。遮蔽只在"两份碰巧同义"时无害，
而没人知道它们是否同义——这正是双源该收口的理由（教义第 6/7 条）。

**面这件事被改过一次，改前它是这条判据最窄的一条腿**：建档那轮实跑面只喂 `neurova/`，
而 docstring 讲的是"同一模块内"这个通用形状。后来在 `tests/` 下量到 4 处既存遮蔽
（两处两份同体、两处体不同——其中一处是被遮住的那个 `Test*` 类名下 3 条用例**连收集都不发生**，
另一处是模块级常量的唯一消费点正落在被遮住的那份里 ⇒ 改那个常量既不报错也不生效）。
同一把谓词喂 `tests/` 当场报出这 4 处、喂 `neurova/` 报 0 处 ⇒ **洞在面（根参数），不在谓词**。
现面＝整仓三族（`neurova`／`tests`／`scripts`），并由
`test_surfaceCoversAllThreeSourceFamilies` 反向钉住：谁把根退回单族，那条格当场红。

取数走 `tests/ast_scan.py::shadowedTopLevelNames`（同一形状只这一份取数口）：它自带词法闸
（真命中必然让某个 def/class 头名在词法层重复出现，反斜杠续行那一形整档兜底），
实测解析面 3545 档 → 834 档；且**一次性**解析不留常驻语法树——原先这里用保留型
`parsedModules`，对只扫一次的判据是白付内存账。
扫描面收缩到 0 个文件也当场红——"路径写错→零文件→全绿"是最常见的假门禁。
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

#: 整仓面单次读数实测 2.9s（本机：取清单 + 词法闸 + 闸内解析）。墙钟给 30 倍余量——
#: 宁可这条格自己慢，也不让它"机器慢就不算红"（判据成本也是回归面）。
pytestmark = pytest.mark.timeout(90)


def _describe(dup: ast_scan.TopLevelNameDup) -> str:
    kind = "两份同体（连说明行一起相同）" if dup.sameIgnoringDocstring else "两份有分叉"
    return f"  {dup.rel} :: {dup.name} @ {dup.linenos} —— {kind}"


def test_noShadowedTopLevelDefinitionsAnywhereInRepo():
    """整仓（三族）模块级同名 `def`／`async def`／`class` 必须为 0 处，且这条格自己得真扫到整仓。"""
    surface: dict = {}
    dups = ast_scan.shadowedTopLevelNames(ast_scan.REPO_ROOT, stats=surface)
    # 面自证：建档那轮把根喂成 `neurova/`，读数同样是"空集"——而空集既可能意味着"干净"，
    # 也可能意味着"没扫到"。两者只有靠**这次扫描自己的面读数**才分得开，故它必须由同一次扫描给出。
    assert surface.get("filesSeen", 0) > 3000, (
        f"这条格扫的不是整仓（现读 {surface}）——根被退回单族时遮蔽就没人看了")
    assert not dups, (
        "出现模块级重名定义——后一份会把前一份静默遮住（前一份若是 `Test*` 类，"
        "它名下每条用例连收集都不发生）：\n"
        + "\n".join(_describe(d) for d in dups)
        + "\n修法：按教义第 7 条先比后合——比两份的断言与实现，取长补短选定一份，删掉另一份。"
          "两份只差说明文字时也照删，别留「看着一样所以都留着」。"
    )


def test_surfaceCoversAllThreeSourceFamilies():
    """反空转（钉的是**面**）：三族各自必须在扫描面里且量级在。

    为什么单独有这一格：建档那轮只喂生产根，`tests/` 下的遮蔽存活了整整三批而无人报——
    "谓词正确、面窄于声明"这种坏法不会让任何格子变红，只有把面的下限钉成断言才拦得住。
    """
    counts = {
        rel: sum(1 for p in ast_scan.filesUnder(ast_scan.REPO_ROOT / rel) if p.suffix == ".py")
        for rel in ("neurova", "tests", "scripts")
    }
    assert all(v > 50 for v in counts.values()), f"扫描面被收窄到不可用的程度：{counts}"
    assert sum(counts.values()) > 1000, f"三族 `.py` 总量异常低：{counts}"


def test_guardActuallyCatchesAShadowedDefinition(tmp_path):
    """反空转（钉的是**谓词**）：造一个重名模块必须被抓到——取数口坏掉时它安静地什么都不报。"""
    (tmp_path / "dup.py").write_text(textwrap.dedent('''
        def helper(x):
            return x

        def helper(x):
            return x * 2
    '''), encoding="utf-8")

    dups = ast_scan.shadowedTopLevelNames(tmp_path)
    assert len(dups) == 1, f"重名模块没被抓到（取数口空转？）：{dups}"
    assert dups[0].name == "helper" and dups[0].linenos == [2, 5], dups
    assert dups[0].rel.endswith("dup.py"), dups


@pytest.mark.parametrize("label, source, expectHit", [
    # 正检六形：真遮蔽只认「模块级同名」，不认写法
    ("普通 def", "import os\n\n\ndef fetch():\n    return os\n\n\ndef fetch():\n    return None\n", True),
    ("async def", "async def pull():\n    yield 1\n\n\nasync def pull():\n    yield 2\n", True),
    ("关键字后多空格", "def   spaced():\n    pass\n\n\ndef  spaced():\n    pass\n", True),
    ("带装饰器", "import functools\n\n\n@functools.cache\ndef memo():\n    return 1\n\n\n"
                 "@functools.cache\ndef memo():\n    return 2\n", True),
    ("同名 class", "class Widget:\n    pass\n\n\nclass Widget:\n    pass\n", True),
    ("头名被反斜杠续行拆走",
     "def \\\n    shadowed():\n    return 1\n\n\ndef \\\n    shadowed():\n    return 2\n", True),
    # 反检三形：合法写法不许报——报了下一轮就有人来放宽判据
    ("不同类里的同名方法是合法的",
     "class A:\n    def run(self):\n        pass\n\n\nclass B:\n    def run(self):\n        pass\n", False),
    ("条件定义不在面内",
     "import sys\n\n\nif sys.platform == 'win32':\n    def go():\n        pass\n"
     "else:\n    def go():\n        pass\n", False),
    ("函数体内的嵌套同名不在面内",
     "def outer():\n    def inner():\n        return 3\n    return inner()\n\n\n"
     "def other():\n    def inner():\n        return 4\n    return inner()\n", False),
])
def test_gateAndPredicateAcceptEveryRealFormAndRejectLegalOnes(tmp_path, label, source, expectHit):
    """词法闸与语法判据在合成样本上双向自证：正检六形都要报，反检三形不许误报。

    这格钉的是**预筛的充分性**：预筛一旦把某种真命中滤掉，主格就会在有人引入遮蔽时照样绿——
    那种绿比没有判据更糟。反检那三形钉的是另一侧：判据宽到能咬合法写法，红线就会被人来放宽。
    """
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    dups = ast_scan.shadowedTopLevelNames(tmp_path)
    if expectHit:
        assert len(dups) == 1, f"取法「{label}」没被认出来（预筛把它滤掉了？）：{dups}"
        assert dups[0].rel.endswith("sample.py") and len(dups[0].linenos) == 2, dups
    else:
        assert not dups, f"{label} 被误判成遮蔽——判据宽到能咬合法写法：{dups}"


def test_shapeFlagTellsProseDriftApartFromRealDivergence(tmp_path):
    """报错文本里的「同体／有分叉」按语法图判，四形各归各位。

    为什么要有这一格：分流处置要靠它——只差说明文字的两份是"同一件事写了两遍"，
    真分叉的两份得先比出哪半不可替代。把这两形混成一个读数，下一轮就会有人
    拿「反正一样」当理由把分叉也划掉。
    """
    cases = [
        ("f", "def f():\n    return 1\n\n\ndef f():\n    return 1\n", True),
        ("g", 'def g():\n    """甲版说明"""\n    return 1\n\n\n'
              'def g():\n    """乙版说明"""\n    return 1\n', True),
        ("h", "def h():\n    return 1\n\n\ndef h():\n    return 2\n", False),
        ("k", "import functools\n\n\n@functools.cache\ndef k():\n    return 1\n\n\n"
              "def k():\n    return 1\n", False),
    ]
    for i, (name, source, _expect) in enumerate(cases):
        (tmp_path / f"s{i}.py").write_text(source, encoding="utf-8")
    dups = sorted(ast_scan.shadowedTopLevelNames(tmp_path), key=lambda d: d.rel)
    assert [d.name for d in dups] == [c[0] for c in cases], [d.rel for d in dups]
    assert [d.sameIgnoringDocstring for d in dups] == [c[2] for c in cases], \
        [(d.rel, d.name, d.sameIgnoringDocstring) for d in dups]
    # 跨文件同名不是遮蔽：四档各自一条，不得并成一条（并了就会有人以为"只剩一处"）
    assert len({d.rel for d in dups}) == 4, [d.rel for d in dups]


def test_classLevelMethodNamesAreNotFlagged(tmp_path):
    """不误伤（建档那轮原格保留）：类内同名方法是正常形态，判据只管模块体。"""
    (tmp_path / "ok.py").write_text(textwrap.dedent('''
        class A:
            def run(self):
                return 1

        class B:
            def run(self):
                return 2

        def outer():
            def inner():
                return 3
            return inner()
    '''), encoding="utf-8")

    assert ast_scan.shadowedTopLevelNames(tmp_path) == []
