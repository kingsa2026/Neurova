# -*- coding: utf-8 -*-
"""扫描面取数只准一处：`git ls-files` 的**全树枚举**不许各判据各抄一份（§6-232）。

建档实状（HEAD 树内按**本档同一把尺**现量：13 处／9 档，一处多档是因为有两档各抄了两份）——

| 落点 | 取法 | 差别 |
|---|---|---|
| `tests/ast_scan.py`（本批新增的单点） | `-z` + 显式 utf-8 | 基准 |
| `tests/unit/test_noFirstPartyImportPlaceholder.py` | `-z`，`cwd=`＋bytes decode | 自己解码头 |
| `tests/unit/test_noDeadImportSwallowFacadeBlocks.py` | 同上 | 同上 |
| `tests/unit/core/test_sourceEscapeSequenceHygiene.py` | `-z '*.py'` | 多一个 pathspec |
| `tests/unit/cognitive_layers/…/test_temperature_single_source.py` | `-c core.quotepath=false` ＋ `-z`，**不查退出码** | git 失败会读成"零命中"＝假绿 |
| `tests/unit/core/test_committed_tree_dependencies.py` | 普通输出 `split()` | **非 ASCII 路径被 git 打成带引号的八进制串**：本仓实测 181 条（全在 `docs/`，`.py` 侧 0 条）在这一形里根本不进扫描面；带空格的路径同理会断 |
| `tests/unit/core/test_packageInitBindsNoUnusedGenericNames.py` | `-z` 通用 helper（**2 处**） | 又一处解码口径 |
| `tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py` | `-z` ＋ `--others --exclude-standard`（**4 处**） | 两个面合成 |
| `tests/unit/test_dev_path_and_runtime_dep_guards.py` | `-z` 走 `self._git()` 包装 | 被调者是 `Attribute` 时最容易漏判的一形 |
| `tests/unit/test_weightEgressGateRefusesBeforeBytes.py` | `-z neurova` | 目录 pathspec |

另有两档 `tests/manual/*.py`（`deadImportFacade_batch42.py`／`facadeGenericNames_batch47.py`）里
也写着 `git ls-files`，但那段文本是**探针字符串**（`r'''…'''` 交给子进程跑的脚本源码），
不是本仓判据的取数口，AST 里根本没有该调用点 ⇒ 不在扫描面内，也不是豁免——这一区分写在本档的
`_SCOPED_SAMPLE` 里（嵌在字符串里的同形写法必须**不被抓到**，否则判据就变成扫词）。

**为什么这是缺陷而不是"重复几行"**：`git ls-files` 的输出编码在本仓是**真坑**（路径含中文时
缺省走平台码 GBK 会炸，`test_subprocessTextEncodingRatchet` 那族实测过三种坏法），
而上面每一份自抄都各自决定"怎么解码、查不查退出码、按不按空格切"。哪一份抄错，
红的是那条判据自己，别人看不出是取数坏了——`test_temperature_single_source` 那档**不查退出码**
就是现成的例子：git 一旦失败，它读到空清单，于是"没人 import 退役模块"当场**假绿**。

**顺带把两条容易混的口径分开**（本批另一条红格立的就是这条区分）：
- **"不许新增"型守卫**（棘轮、形状扫描）：扫描面取**工作树**——当场咬住新写的档，包括还没提交的；
- **"存量比对"型守卫**（表格、等号、豁免表）：扫描面取**已跟踪清单**——否则并发会话正在半写的
  在途档会被读成"我引入了新命中"（§6-225 的 A/B 第一轮就是这么误报一条假回归的）。

例外**不是**给谁开后门，而是它们本来就不是"全树枚举"：`--error-unmatch <某档>`（问"这个档跟没跟踪"）、
`ls-files -- <具体档或目录>`（查作用域内残留）、`ls-files <显式清单>`（核对登记面）。
本档按**参数形状**判，不按词判；表外新出现一处全树枚举即红。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TESTS = PROJECT_ROOT / "tests"
SINGLE_SOURCE = "tests/ast_scan.py"

#: 合法的"非全树枚举"用法（形状判据见 `_isScoped`）：显式路径/清单/存在性查询。
SCOPED_FORMS = ("--error-unmatch", "--")


def _argvStrings(node: ast.Call) -> tuple:
    """调用里能静态看出的 argv 片段 + 「有没有 `*` 展开的显式清单」。

    被调者名字也要认：HEAD 那 13 处里有 8 处不经 `subprocess.run` 而是走 `_git()`/
    `_gitLsFiles()` 包装，其中 `test_dev_path_and_runtime_dep_guards.py:779` 的被调者是
    `self._git`（`Attribute`）——只认 `Name.id` 就是我差点漏掉那一处的形状，
    它当时让整档读出"零命中"，而红字面上是绿的。

    反过来，**裸变量不得算 scoped**：`["git","-C",str(REPO),"ls-files","-z"]` 里那串
    `str(REPO)` 只是仓库根，清单依然是整棵树。第一版把它当"动态参数＝显式清单"放过，
    于是本批自己的活体探针（旧形复算档）静默掉出扫描面——只有 `*` 展开才是
    "由调用方显式传入一批路径"。
    """
    parts, starred = [], False

    def absorb(seq):
        nonlocal starred
        for element in seq:
            if isinstance(element, ast.List):
                absorb(element.elts)          # subprocess.run(["git","ls-files",…]) 的 argv 是个 list
            elif isinstance(element, ast.Constant) and isinstance(element.value, str):
                parts.append(element.value)
            elif isinstance(element, ast.Starred):
                starred = True                 # *files ⇒ 清单由调用方显式传入
            # 其余（str(ROOT)、变量、下标）静态看不见形状，既不证明 scoped 也不证明全树：忽略

    absorb(node.args)
    for kw in node.keywords:
        if kw.arg is None:
            starred = True                     # **kwargs：清单从外面来，按 scoped 处理
            continue
        if isinstance(kw.value, ast.List):
            absorb(kw.value.elts)
    return parts, starred


def _calleeName(node: ast.Call) -> str:
    """被调者的可静态判定名字，`self._git(...)` 取 `_git`（包装函数的调用点全靠它认出）。"""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _gitCallsWithLsFiles(tree: ast.AST) -> list:
    """`(行号, argv 文本, 有无 * 展开)`：所有把 `git ls-files` 当参数传的调用点（含包装函数的调用点）。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        parts, starred = _argvStrings(node)
        if "ls-files" not in parts:
            continue
        if "git" not in parts and "git" not in _calleeName(node).lower():
            continue      # 只把 "git ls-files" 当字符串提到别处的（报错文案、样本源码）不算调用点
        out.append((node.lineno, " ".join(p for p in parts if p != "git"), starred))
    return out


def _isScoped(parts: str, starred: bool) -> bool:
    """scoped＝问"某个/某批具体路径跟没跟踪"，不是"把整棵树列一遍"。"""
    if starred:
        return True
    tokens = parts.split()[1:]
    if any(t in SCOPED_FORMS for t in tokens):
        return True
    # 带具体路径（含 `/`）的算 scoped；`*.py`、`neurova` 这类模式/整目录仍是全树枚举
    return any("/" in t and not t.startswith("*") for t in tokens)


def _trackedListCalls(probeDir: Path = None) -> list:
    """`(相对路径, 行号, 参数)`：全树/整目录取跟踪清单的调用点。

    取数走 `ast_scan.sourceRefsUnder(hints=("ls-files",))`——本仓唯一 AST 入口，也是
    `test_ci_ast_scan_budget_guard` 点名要求的形状（私有 glob + 全量 `ast.parse` 那族已在
    批 48 收口）。文本预筛的边界说清楚：靠字符串拼出 `"ls-" + "files"` 的写法这一档看不见；
    这一档钉的是"各处手抄同一份取数"，不是抗刻意规避——真要绕，直接写 subprocess 的别的形状
    同样绕得住。
    """
    hits = []
    for ref in ast_scan.sourceRefsUnder(probeDir or TESTS, hints=("ls-files",)):
        try:
            rel = ref.path.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            rel = ref.path.name        # 合成样本档（tmp_path）不在仓内，用文件名当标识就够
        if rel == SINGLE_SOURCE:
            continue
        try:
            tree = ast_scan.transientTree(ref.path)
        except (SyntaxError, ValueError):
            continue
        for lineno, parts, starred in _gitCallsWithLsFiles(tree):
            if not _isScoped(parts, starred):
                hits.append((rel, lineno, parts))
    return sorted(hits)


#: 种进临时目录的两份样本档：左边三形**必须**被抓，右边三形**不许**被抓。
#: 三形是实测漏过的写法——第一版探测器只认 `Name` 被调者、把裸变量当显式清单，
#: 于是 `self._git("ls-files","-z")` 与 `-C root` 那两处静默掉出扫描面（假绿）。
_FULL_TREE_SAMPLE = (
    "import subprocess\n"
    'subprocess.run(["git", "ls-files", "-z"], capture_output=True)\n'
    'subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True)\n'
    "class Guard:\n"
    '    def probe(self): self._git("ls-files", "-z")\n')

_SCOPED_SAMPLE = (
    "import subprocess\n"
    'subprocess.run(["git", "ls-files", "--error-unmatch", "--", rel])\n'
    'subprocess.run(["git", "ls-files", "--", "neurova/expected"])\n'
    'subprocess.run(["git", "ls-files", *files])\n'
    'subprocess.run(["git", "ls-files", "some/explicit/dir"])\n'
    "SOURCE = '''\n"
    'subprocess.run(["git", "ls-files", "-z"], cwd=sys.argv[1])\n'    # 嵌在探针字符串里的子脚本：不是调用点
    "'''\n")


def test_fullTreeLsFilesEnumerationHasExactlyOneHome(tmp_path):
    """全树取跟踪清单只准 `ast_scan` 一处；其余落点必须改走单点。

    探测器先自证：种一份合成样本档，必须被抓到（本仓实测过"扫了个空却报绿"——
    `PROJECT_ROOT` 少算一层时这里的命中数直接归零，断言就恒真，所以我不用"某个已知档
    必须在读数里"当探针，那种写法在收口之后必然变成假红）。自证要**两边都种**：
    只断"抓得到坏的"会鼓励把判据写宽，那样合法 scoped 用法也会红——那些落点一旦红，
    下一个人就会去摘扫描面而不是改取数，等于把单点又拆回各抄一份。
    """
    scanned = [p for p in ast_scan.filesUnder(TESTS) if p.suffix == ".py"]
    assert len(scanned) > 500, f"扫描面现读 {len(scanned)} 档 .py，地板 500 被打破＝口径没跑起来"

    full = tmp_path / "sampleFullTree.py"
    full.write_text(_FULL_TREE_SAMPLE, encoding="utf-8")
    scoped = tmp_path / "sampleScoped.py"
    scoped.write_text(_SCOPED_SAMPLE, encoding="utf-8")

    probed = _trackedListCalls(tmp_path)
    caught = [h[1] for h in probed if h[0].startswith("sampleFullTree")]
    assert caught == [2, 3, 5], (
        f"三形全树写法应各抓一次（行 2/3/5），实抓 {caught}；完整读数 {probed}")
    assert not [h for h in probed if h[0].startswith("sampleScoped")], (
        f"scoped 用法被误伤，判据过宽会把人推回去摘扫描面：{probed}")

    offenders = _trackedListCalls()
    assert not offenders, (
        "这些判据还在自己抄一份全树 `git ls-files`（解码口径/退出码各自决定，抄错的一侧会假绿）：\n  "
        + "\n  ".join("%s:%d  %s" % (r, l, a) for r, l, a in offenders[:12])
        + "\n改法：用 `ast_scan.trackedPyPaths(*pathspecs)`（-z 分隔、显式 utf-8、退出码非 0 即抛）。")


def test_singleSourceItselfIsReachableAndBitesOnBadReads():
    """单点存在且行为正确：解码、-z 分列、git 失败必须抛而不是回空表（回空表＝假绿）。"""
    import pytest

    paths = ast_scan.trackedPyPaths()
    assert len(paths) > 3000, f"跟踪 .py 现读 {len(paths)}，地板 3000 被打破＝单点没跑起来"
    assert all(p.endswith(".py") for p in paths)
    assert any(p.startswith("neurova/") for p in paths), "单点读不到生产根——扫描面塌了"
    with pytest.raises(RuntimeError):
        ast_scan.trackedPyPaths("--no-such-flag-b54")     # git 失败必须抛，不许回空清单
