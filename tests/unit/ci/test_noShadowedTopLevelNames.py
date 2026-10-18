# -*- coding: utf-8 -*-
"""模块级重名定义（`def`/`class` 同名两次）＝遮蔽，本档把它做成会红的格子。

根因（不是「下次编代码注意点」）：一个模块里 `def f(): ...` 写两遍，第二份**静默遮住**
第一份——模块命名空间里只剩后一份，前一份连「有没有跑」都不报。两种后果各自实测过：

* `tests/unit/computer_use/test_action_result.py` 里 `class TestNonIntrusiveVocabulary`
  写了两遍（85/119 行），`--collect-only` 现读只有**一个** Class 节点／该档共 20 tests——
  前一份名下 3 条用例从未被收集。读代码的人以为 6 格在跑，实为 3 格。
* `tests/unit/core/test_plugins_modules.py` 里 `_writePluginInto` 写了两遍（38/63 行）且
  **两份体不同**：跑的是后一份，而模块级常量 `_PLUGIN_SOURCE_LINES` 的唯一消费点正好落在
  被遮住的那份里 ⇒ 改那个常量既不报错也不生效——同功能的第二份表示（修复教义第 6 条）。

所以判据**不看体是否相同**：同体也是遮蔽（「编辑哪一份才生效」这件事本身就答不出来），
体只写进报错文本供分流处置。取数走 `tests/ast_scan.py` 的共享入口
`shadowedTopLevelNames`（词法闸是充分条件：实测把解析面从 3545 档降到 834 档，
本仓单次读数 2.9s ↔ 全量解析 5.2s），本档不自己 `ast.parse`。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

#: 单次读数实测 2.9s（本机：取清单 + 词法闸 + 闸内解析）。墙钟按 30 倍余量给——
#: 宁可这条格自己慢，也不让它「机器慢就不算红」（判据成本也是回归面）。
pytestmark = pytest.mark.timeout(90)


def _describe(dup: ast_scan.TopLevelNameDup) -> str:
    kind = "两份同体（连说明行一起相同）" if dup.sameIgnoringDocstring else "两份有分叉"
    return f"  {dup.rel} :: {dup.name} @ {dup.linenos} —— {kind}"


def test_noShadowedTopLevelNameAnywhereInRepo():
    """全仓模块级同名 `def`／`async def`／`class` 必须为 0 处。"""
    dups = ast_scan.shadowedTopLevelNames(ast_scan.REPO_ROOT)
    assert not dups, (
        "出现模块级重名定义——后一份会把前一份静默遮住（前一份若是 `Test*` 类，"
        "它名下每条用例连收集都不发生）：\n"
        + "\n".join(_describe(d) for d in dups)
        + "\n修法：按教义第 7 条先比后合——比两份的断言与实现，取长补短选定一份，删掉另一份。"
          "两份只差说明文字时也照删，别留「看着一样所以都留着」。"
    )


def test_surfaceActuallyCoversAllThreeSourceFamilies():
    """反空转：扫描面缩水时「零命中」是假的——先证三族源码都在面内且量级在。"""
    counts = {
        rel: sum(1 for p in ast_scan.filesUnder(ast_scan.REPO_ROOT / rel) if p.suffix == ".py")
        for rel in ("neurova", "tests", "scripts")
    }
    assert all(v > 50 for v in counts.values()), f"扫描面被收窄到不可用的程度：{counts}"
    assert sum(counts.values()) > 1000, f"三族 `.py` 总量异常低：{counts}"


@pytest.mark.parametrize("label, source, expectHit", [
    # 正检五形：真遮蔽只认「模块级同名」，不认写法
    ("普通 def", "import os\n\n\ndef fetch():\n    return os\n\n\ndef fetch():\n    return None\n", True),
    ("async def", "async def pull():\n    yield 1\n\n\nasync def pull():\n    yield 2\n", True),
    ("关键字后多空格", "def   spaced():\n    pass\n\n\ndef  spaced():\n    pass\n", True),
    ("带装饰器", "import functools\n\n\n@functools.cache\ndef memo():\n    return 1\n\n\n"
                 "@functools.cache\ndef memo():\n    return 2\n", True),
    ("同名 class", "class Widget:\n    pass\n\n\nclass Widget:\n    pass\n", True),
    # 反斜杠续行把 `def` 与头名拆到两行——词法闸读不到任何名字，全靠 `\\\n` 兜底整档放行
    ("头名被续行拆走", "def \\\n    shadowed():\n    return 1\n\n\ndef \\\n    shadowed():\n    return 2\n", True),
    # 反检两形：合法写法不许报——报了下一轮就有人来放宽判据
    ("不同类里的同名方法是合法的",
     "class A:\n    def run(self):\n        pass\n\n\nclass B:\n    def run(self):\n        pass\n", False),
    ("条件定义不在面内",
     "import sys\n\n\nif sys.platform == 'win32':\n    def go():\n        pass\n"
     "else:\n    def go():\n        pass\n", False),
])
def test_gateAndPredicateAcceptEveryRealFormAndRejectLegalOnes(tmp_path, label, source, expectHit):
    """词法闸与语法判据在合成样本上双向自证：正检五形都要报，反检两形不许误报。

    这格钉的是**预筛的充分性**：预筛一旦把某种真命中滤掉，主格就会在有人引入遮蔽时
    照样绿——那种绿比没有判据更糟（形态集 291/293 同族）。反检那两形钉的是另一侧：
    判据宽到能咬合法写法，红线就会被人来放宽。
    """
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    dups = ast_scan.shadowedTopLevelNames(tmp_path)
    if expectHit:
        assert len(dups) == 1, f"取法「{label}」没被认出来（预筛把它滤掉了？）：{dups}"
        assert dups[0].linenos and dups[0].rel.endswith("sample.py"), dups
    else:
        assert not dups, f"{label} 被误判成遮蔽——判据宽到能咬合法写法：{dups}"


def test_shapeFlagTellsProseDriftApartFromRealDivergence(tmp_path):
    """报错文本里的「同体／有分叉」按语法图判，四形各归各位。

    为什么要有这一格：分流处置要靠它——只差说明文字的两份是「同一件事写了两遍」，
    真分叉的两份得先比出哪半不可替代。把这两形混成一格读数，下一轮就会有人
    拿「反正一样」当理由把分叉也划掉。
    """
    cases = [
        # (档名, 函数名, 源码, 期望 sameIgnoringDocstring)
        ("same", "f", "def f():\n    return 1\n\n\ndef f():\n    return 1\n", True),
        ("prose", "g", 'def g():\n    """甲版说明"""\n    return 1\n\n\n'
                       'def g():\n    """乙版说明"""\n    return 1\n', True),
        ("diverge", "h", "def h():\n    return 1\n\n\ndef h():\n    return 2\n", False),
        ("deco", "k", "import functools\n\n\n@functools.cache\ndef k():\n    return 1\n\n\n"
                      "def k():\n    return 1\n", False),
    ]
    for i, (_stem, _name, source, _expect) in enumerate(cases):
        (tmp_path / f"s{i}.py").write_text(source, encoding="utf-8")
    dups = sorted(ast_scan.shadowedTopLevelNames(tmp_path), key=lambda d: d.rel)
    assert [d.name for d in dups] == [c[1] for c in cases], [d.rel for d in dups]
    assert [d.sameIgnoringDocstring for d in dups] == [c[3] for c in cases], \
        [(d.rel, d.name, d.sameIgnoringDocstring) for d in dups]
    # 跨文件同名不是遮蔽：四档各自一条，不得并成一条（并了就会有人以为"只剩一处"）
    assert len({d.rel for d in dups}) == 4, [d.rel for d in dups]
