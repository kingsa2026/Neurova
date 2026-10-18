# -*- coding: utf-8 -*-
"""共享入口 `ast_scan.importersOfModule` 的判据：四种导入取法都要认，且预筛必须取末段名。

「父包取名形」这一类含**两种写法**（`from a.b import c` 与相对的 `from . import c`），
共用一个取法标签；两种写法各配一例，另有一枚真面正控 `test_relativeParentFormIsReallyConsumedOnTheTree`
钉住"仓内真有人在用这一形"——没有那格时，这条通道只是实现碰巧对，重构一次就静默掉出面内。

来历（上一批复算时明记、当时未收的窄面）：`tests/` 里曾有约 17 处各写一份"谁还在导入这个模块"的谓词，
每一处都要独立决定认不认相对形、认不认父包取名形、预筛取哪个词——同一个问题十七个口径
（教义第 6 条点名的形态）。已复算的例子：`ast_scan.importsOf` 只比 `node.module` 原文，
`from neurova.core import multi_agent_manager` 与 `from .multi_agent_manager import X` 都不在它的面内，
而 `tests/unit/core/test_dead_cache_module_removed.py` 两格正是用它 ⇒ "零引用"可能是假零。

本批先把口径收回一处（`importFormForModule` 判定 ＋ `importersOfModule` 枚举＋预筛），
并让这个入口自己可证伪。**未迁的档**（仍各自写着私有导入谓词的那些）逐档迁移、一文件一笔，
命中面与剩余清单都记在审计台账。

三条易错处，各有一格对着：
① 判定要能吃合成节点——整棵树只有在仓内路径上才解得出相对形，所以判定与枚举分开，
   否则"四种形都认"只能靠往仓里种文件来验（会污染别的常驻判据）；
② 预筛词取**全名**时，只含相对形的那一档会在文本这一关被滤掉——这不是理论风险，
   是 `importersOfModule` 存在的理由，单列一格钉住；
③ 入口本身要能产生非零读数，否则"退役模块零引用"永远绿（形态集 283）。
"""

from __future__ import annotations

import ast
import pathlib

from tests import ast_scan

MODULE = "pkg.sub.leaf"
RETIRED = "neurova.core.multi_agent_manager"
LIVE = "neurova.core.agent_workspaces"
#: 真面正控的取样——仓内确实有人用 `from . import console` 取它
CONSOLE_MODULE = "neurova.api.endpoints.console"


def _firstImport(source: str) -> ast.AST:
    """取这段源码里的第一个 import 节点（合成样本一律走这里，判定与枚举因此分开）。"""
    tree = ast.parse(source)
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))


def test_detectorOwnsAllFourImportForms():
    """五种写法逐个给判定函数，各自要报出自己的取法名；三个"不是它"的形状不得误报。

    「父包取名形」有两种写法，都归同一个标签：`from pkg.sub import leaf`（绝对）与
    `from . import leaf`（相对，`node.module` 是 None，父包只能由发起文件位置解出）。
    这里刻意**不**给它拆新标签——八个消费方的判据正文都写着"四种取法都认"，
    拆标签会让那些口径集体过期，等于造一处新的名实分离。两写法各配一例即可。
    """
    cases = {
        "import 全名": ("import pkg.sub.leaf\n", "anywhere/x.py", "import 全名"),
        "from 全名": ("from pkg.sub.leaf import Thing\n", "anywhere/x.py", "from 全名"),
        "相对形": ("from .leaf import Thing\n", "pkg/sub/x.py", "相对形"),
        "父包取名形·绝对写法": ("from pkg.sub import leaf\n", "anywhere/x.py", "父包取名形"),
        "父包取名形·相对写法": ("from . import leaf\n", "pkg/sub/x.py", "父包取名形"),
    }
    for label, (source, rel, expected) in cases.items():
        got = ast_scan.importFormForModule(rel, _firstImport(source), MODULE)
        assert got == expected, \
            f"写法 {label} 的取法判成 {got!r}（应为 {expected!r}）——这个入口又在学旧口径只比一种形"

    negatives = {
        "同末段名但别的包": ("from other.pack import leaf\n", "anywhere/x.py"),
        "父包对但取的是符号": ("from pkg.sub import Thing\n", "anywhere/x.py"),
        "前缀相似的模块": ("import pkg.sub.leafter\n", "anywhere/x.py"),
    }
    for label, (source, rel) in negatives.items():
        assert ast_scan.importFormForModule(rel, _firstImport(source), MODULE) == "", \
            f"{label} 被误判成在取 {MODULE}——放宽到不可信的程度就没有格子能红了"


def test_relativeParentFormIsReallyConsumedOnTheTree():
    """真面正控：这一形不是纸面形状，仓内真有人在用，两个入口都必须现读到它。

    取样 `neurova.api.endpoints.console`——它被同目录的 `console_files.py` 等以
    `from . import console` 取用。这条通道此前是**实现碰巧对**：没有任何格子钉它，
    所以重构一次 `resolveImportModule` 就会静默掉出面内而无人报（§6-318 那句
    "110 处隐形"的错读数也是这么来的——没有读数可看，只能凭叙述）。
    """
    consumers = ast_scan.importersOfModule(ast_scan.REPO_ROOT, CONSOLE_MODULE)
    atConsoleFiles = [h for h in consumers if h[0].endswith("neurova/api/endpoints/console_files.py")]
    assert atConsoleFiles, f"`from . import console` 没被认成消费者：{consumers[:5]}"
    assert {h[2] for h in atConsoleFiles} == {"父包取名形"}, \
        f"认上了但走的不是父包那条分支（判据换形状就会漏）：{atConsoleFiles}"

    # `namesTakenFrom` 走的是另一条问句（谁从这个包取了哪些名），同一形也必须记到
    scan = ast_scan.nodeScan(ast_scan.REPO_ROOT / "neurova" / "api" / "endpoints", ".py")
    taken = {n for n, _p, _l in ast_scan.namesTakenFrom(scan, "neurova.api.endpoints")}
    assert "console" in taken, \
        "namesTakenFrom 没把 `from . import console` 记成从包里取的名字——门面判据的 import 图会少走边"


def test_endToEndSeesWhatTheNarrowPredicateMisses(tmp_path):
    """差分：同一棵树，宽入口报三处、旧口径（只比 `node.module`）只报两处。

    没有这格，"我修好了"只是叙述——它证的是**这轮确实把漏的那条形补进了面**，
    而不是换了个名字写同一份逻辑。
    """
    (tmp_path / "a.py").write_text("import pkg.sub.leaf\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from pkg.sub.leaf import Thing\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("from pkg.sub import leaf\n", encoding="utf-8")
    (tmp_path / "d.py").write_text("from pkg.sub import Thing\n", encoding="utf-8")

    wide = ast_scan.importersOfModule(tmp_path, MODULE)
    narrow = [(ast_scan.relativeToRepo(p) if p.is_relative_to(ast_scan.REPO_ROOT) else p.as_posix(), ln)
              for p, ln in ast_scan.importsOf(ast_scan.transientNodes(tmp_path, ".py"), MODULE)]
    assert len(wide) == 3, f"宽入口应认三处（含父包取名形），实得 {wide}"
    assert len(narrow) == 2, f"旧口径的读数变了（本该恰好漏掉父包那一形）：{narrow}"
    assert {w[0].rsplit("/", 1)[-1] for w in wide} == {"a.py", "b.py", "c.py"}, wide
    assert not any(w[0].endswith("d.py") for w in wide), "取同名符号被算成取同名子模块"


def test_prefilterIsBasenameNotFullname(tmp_path):
    """②预筛那一格：只含相对形引用的文件，按全名预筛会被滤掉、按末段名不会。

    这一格不测判定，测的是"枚举面"——旧写法把全名当预筛词时，相对形连 parse 都轮不到。
    """
    (tmp_path / "onlyrel.py").write_text("from .leaf import Thing\n", encoding="utf-8")
    fullNamed = ast_scan.sourceRefsUnder(tmp_path, ".py", ast_scan.textHints(MODULE))
    baseNamed = ast_scan.sourceRefsUnder(tmp_path, ".py", ast_scan.textHints(MODULE.split(".")[-1]))
    assert not fullNamed, "全名预筛竟然保留了这个文件——这格要的是那条漏检的证据"
    assert [r.path.name for r in baseNamed] == ["onlyrel.py"], (
        f"末段名预筛没把这个相对形留在面内：{[r.path.name for r in baseNamed]}")


def test_entryProducesNonZeroOnTheRealTree():
    """③正控：入口在真生产面上要能报出非零——否则"退役模块零引用"是恒绿。

    拿一个**在役**模块（`core/agent_workspaces`）验"能报出东西"，再拿批 81 退役的那座岛验"现在报零"；
    顺序不能反：没有前者，后者的零什么都说明不了（形态集 283）。
    """
    liveHits = ast_scan.importersOfModule(ast_scan.PRODUCTION_ROOT, LIVE)
    assert liveHits, f"在役模块 {LIVE} 竟被判零引用 ⇒ 探测器坏了，别拿退役格那个零当结论"
    assert all("neurova/core/agent_workspaces.py" != h[0] for h in liveHits), \
        f"模块自己的文件被算成自己的消费者：{liveHits[:3]}"

    retired = ast_scan.importersOfModule(ast_scan.PRODUCTION_ROOT, RETIRED)
    assert not retired, f"批 81 退役的岛又被导入了：{retired}"
    wholeRepo = ast_scan.importersOfModule(ast_scan.REPO_ROOT, RETIRED)
    assert not wholeRepo, f"测试/脚本侧又出现对已退役岛的导入通道：{wholeRepo}"
