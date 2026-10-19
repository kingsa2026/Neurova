# -*- coding: utf-8 -*-
"""扫描型判据必须自证"这次真扫到了多少"——只降不升棘轮（§6-322 裁定乙的落地）。

**要防的那件事**：一条"全仓不得再出现 X"的判据，如果它实跑的根被改窄（或被写错成少上一层），
读数会变成**零命中**而不是红——"干净"与"没扫到"在断言里长得一模一样。本仓已有一例实证：
模块级重名定义那条守卫自建档起就在子集里，docstring 讲的是通用形状，而它唯一真跑整树的格子
喂的根只有 `neurova/`；`tests/` 下四处既存遮蔽（其中一处让 3 条用例连收集都不发生）
活了三批，没有任何东西变红。事后按档量了一遍覆盖面（取数口就是本文件的 `_faceFindings`）：
**能解出仓内扫描根的判据档里，把自己扫到的数量当断言比过的不到一半**，其余那批一直在赌
"根没写错、也没被改窄"。这里**不抄现值**——覆盖率是随批次动的量，写死一次就等着它讲假话；
要看今天的数，用本文件的取数口现跑，或查台账里那一批的落批读数。

**判据只认代码形状，不认词**（本仓的守卫被自家 docstring 撞红过，也被自己的措辞豁免过）：
"自证"＝本档里存在一条 `assert`，把**由这次扫描/计数得到的量**与一个数字下限比。计数名认这几种形：
`len(...)`／`sum(...)`／`ast_scan.<入口>(...)`／列表推导／`.get()`（共享入口回填面读数的写法，
见 `shadowedTopLevelNames` 的 `stats`）／循环里 `+= 1` 累加的计数器——**每种认形都配了一格合成正检**，
放宽不白给。以下两种**不算**：只 `assert findings == []`；有一条与扫描无关的 `assert len(rows) > 0`
（收紧规则多抓出来的正是后一形）。

**面读数怎么取（消化存量时踩出来的次序）**：优先由**被裁的那次扫描自己**给出计数——物化它的返回值
再 `len()`，或在循环里累加；这样"面"与"判据看到的量"必然同源。那次扫描带文本预筛时（预筛命中数不随
根的大小变，证不了面），另走一次共享枚举入口量根：`ast_scan.filesUnder(根)`。**但**如果本档别处还
自付 `ast.parse`，`filesUnder` 与它配成对正是 `test_ci_ast_scan_budget_guard` 报的形状（本会话三档
当场被拦：`test_manualScriptStdoutEncoding`／`test_ci_wallclock_assertion_ledger`／
`test_tool_parallelism_readout`）——那种档改用 `ast_scan.sourceRefsUnder(根, ".py")`（共享入口，
枚举与解析都在预算内），**不要**为了绕过门禁把私有解析留着、也不要退成弱读数。

**存量不豁免、只登记**：下表是本档建档那轮（2026-10-19）的 offender 名单——新增即红，
把某档补上自证后**必须**从表里摘掉（"降了要看得见"），与 `test_subprocessTextEncodingRatchet.py`
同一手法。基线**只由本文件的 `_faceFindings` 生成**：上一版我从另一把探针尺里抄过一次数，
当场错出"2 条漏登 ＋ 5 条多登"，所以取数与基线必须同一次扫描同源。名单已随四波存量收空，
本闸自此**零容忍**——这张空表本身就是裁决力，不是"治理结束"的墓碑。

**读数落在哪一格也要选**：把 `filesUnder` 塞进一条被消费的 helper，会让该 helper 的**调用闭包**
同时具备「枚举＋私有解析」两种落点——那正是 `test_ci_ast_scan_budget_guard` 点名要红的形状
（本批实测把读数放进 `declIndex()`，门禁当场报出两个落点）。门禁在这里的判断是对的：
面读数不该让判据多付一趟解析。那种档把面自证落成**独立一格**，只调枚举入口、不碰解析。

**本档认不到的形状（明写边界，不当已收口）**：分类器认"扫描入口调用"——
`ast_scan.<共享入口>`、`<路径>.rglob|glob|iterdir|listdir|scandir`、`os.walk`，并且要把根参数
解成仓内目录。**按清单逐行 `read_text` 去读、不经过这些入口的档不在面内**（本档自己就是这一形，
`test_ci_ast_scan_budget_guard.py` 也是）——它们没有"根参数"可解，也就无从判面有没有被改窄。
要覆盖那一形，得先给这类读法定出"根"的表示法，属另一张票。

**根的形状分六态**：仓内目录／仓内文件／仓外目录／指不到东西／动态值／**函数内局部名**。只有"仓内目录"要求面自证；
"仓内文件"坏得响（入口当场抛），"动态值"不承载面的声明；**"仓外"与"指不到"一律点名，且不看它在不在下表里**
（`test_staticRootsNeverPointOutsideOrNowhere`，不留存量豁免）。为什么单独钉：`test_ratchetDoesNotRise` 只比"比基线新增了什么"，
一档本来就在表里、后来把根写错了，失败集合反而一个字节都不变——本会话把 `parents[3]` 改成 `parents[4]` 实测过这一形，两格全绿。
"根写错"比"没自证"更重（前者让判据根本不说话，后者只是没留底单），不能由存量名单兜着。
第六态"函数内局部名"由 `test_scanRootsAreNeverBoundInsideAFunction` 管：它不是写错根，而是**本闸认不出根在哪**，
性质与建档那轮的存量相同 ⇒ 带一张 `LOCAL_BASELINE`，新增即红、消化必须摘行（批 98 实测过它的坏法：
把 8 档的根收进 `faceRoot` 之后，6 档的落点态只剩 `dynamic`，offender 仍是 0——绿在这里成了假事实源）。
"""

from __future__ import annotations

import ast
import io
import os
import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 认作"扫描落点"的共享预算入口（枚举与解析都在预算内完成）。
SHARED_SCAN_ENTRIES = {
    "nodeScan", "sourceRefsUnder", "parsedModules", "walkedModules", "transientTree",
    "transientNodes", "callSites", "callNodes", "classDefsIn", "namesTakenFrom",
    "takenPerModule", "importersOfModule", "shadowedTopLevelNames", "filesUnder",
}
#: 私有文件系统枚举方法：这类调用的**根在接收者上**，第一个实参是模式。
FILE_ENUM_ATTRS = {"rglob", "glob", "iglob", "iterdir", "listdir", "scandir"}
#: 这些接收者上的同名方法不是文件枚举（`ast.walk` 与 `os.walk` 只差一个根）。
NON_PATH_RECEIVERS = {"ast", "re", "self", "node", "tree", "n"}
#: 仓根常量名：判据里这一族都指向"仓根"，因此 `<常量> / "子段"` 就是把面收窄的那一类写法。
REPO_ROOT_NAMES = {"REPO_ROOT", "PROJECT_ROOT", "REPO", "ROOT", "repoRoot"}
#: 参与面自证计数的构造：断言里跟数字比的量必须由这些得到，否则"自证"两字可以是任意的。
COUNT_CONSTRUCTORS = {"len", "sum"}

pytestmark = pytest.mark.timeout(120)

#: ── offender 基线：一律由本文件的 `_faceFindings` 现取生成，不在注释里抄数 ──────────
#: 建档口径与本文件的 `_faceFindings` 完全同源——**不要用别的规则量一遍再抄进来**，
#: 基线与判据不同源时，"存量在降"会被读成"治理有进展"（本仓同族账）。
#: 面读数与消化进度写在台账那一格（进账的数字背后必须有当轮跑过的命令），代码这里只留名单。
#:
#: 现值＝**空集**。四波存量（46 → 36 → 27 → 19 → 0）收干净之后，本闸是**零容忍**：
#: 新落一条「扫仓内根却不自证面」的判据即红。空表不代表这闸失去内容——它的裁决力就是"新增即红"，
#: 而 `test_ratchetRecordsImprovementLoudly` 继续留着，是为了让"名单与实际不同源"当场露形
#: （包括有人把真 offender 偷偷加回这张表来换取那一格变绿）。
BASELINE: set = set()

#: ── LOCAL 存量表：同样只由本文件的 `_faceFindings(localGaps=...)` 现取生成 ──────────
#: 建档那轮＝批 99（2026-10-19）。「面自证」那张表已收空，这张表记下的是**本闸认不出根位置**的档：
#: 根绑在函数内的名字上，`_constTable` 解不出 ⇒ 那档连"有没有面"都不再被问。
#: 纪律与 BASELINE 一致：新增即红、消化必须摘行；下一批把某一档的根提到模块级时，
#: **同批要给它补上面自证**（提到模块级之后它才进入「仓内目录」那一支，那时才要求自证）。
LOCAL_BASELINE = {
    "tests/unit/agent/test_tool_experience_loop_offline_probe.py",
    "tests/unit/api/test_experience_outcome_word_domain.py",
    "tests/unit/context/test_injectorLifecycleHooksNeverRan.py",
    "tests/unit/context/test_token_estimator_calibration.py",
    "tests/unit/deploy/test_image_model_assets.py",
    "tests/unit/evolution/rsi/test_rsi_proposal_activation.py",
    "tests/unit/evolution/rsi/test_rsi_rollback_evidence.py",
    "tests/unit/evolution/test_skill_gate_and_unified_identity_p0p1.py",
    "tests/unit/test_session_landing_guard.py",
}


# ── 取数：三样小工具，各自只解一件事，便于逐形反检 ─────────────────────────────
def _constTable(tree: ast.AST) -> dict:
    """模块级 `NAME = <expr>`：根参数常写成 `NEUROVA_ROOT = PROJECT_ROOT / "neurova"`。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out[node.target.id] = node.value
    return out


def _scopedBindings(tree: ast.AST) -> dict:
    """**任意作用域**的 `NAME = <expr>`（同名取首次绑定）——只用来认"根绑在函数里"这一形。
    合规裁决不看它：认出来之后照样要求把根提到模块级，本闸不接受"函数里也算根"。
    取首次绑定而不是最后一次：同一名字在文件里被改写过时，最后一次往往已经是运行时值，
    那种档本来就不该被认成静态根（认成 LOCAL 反而会把修法指错）。
    """
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            out.setdefault(node.target.id, node.value)
    return out


def _rootStatus(expr, consts: dict, anchor: pathlib.Path, selfPath: pathlib.Path = None,
                scoped: dict = None) -> str:
    """一个根表达式的落点态。`scoped` 给了就多认一步：模块级解不出、按作用域解得出且落在
    **仓内真实目录** ⇒ LOCAL（"根写得对、只是绑错了地方"），交给零容忍那一格点名。
    """
    status = _classifyRoot(_resolveRoot(expr, consts, anchor, selfPath=selfPath), anchor)
    if status == DYNAMIC and scoped is not None and expr is not None:
        alt = _classifyRoot(_resolveRoot(expr, scoped, anchor, selfPath=selfPath), anchor)
        if alt == DIR:
            return LOCAL
    return status


#: 静态根解出来的落点态，加上「动态值」「函数内局部名」共六态。**只有 DIR 参与面自证裁决**；
#: OUTSIDE／MISSING 都是「根写错了」的形状，一律点名；FILE 与 DYNAMIC 不承载"面会被改窄"这件事，
#: 既不点名也不免罪。把六态分开的理由：原来「解不出」与「解到别处」与「解到一个文件」都折叠成
#: 同一个 None，于是"根少写一层"的那档会安静地掉出本闸的面——正是本闸要防的事，
#: 被本闸的取数路自己放过去。
#:   FILE 为什么免裁：单文件落点坏掉时 `transientTree` 一类入口当场抛 FileNotFoundError，是**响**的；
#:   目录落点坏掉时只给出「零命中」，与干净同形，是**哑**的。本闸只管哑的那一类。
#:   LOCAL（根绑在函数里的名字上）另开一格点名（`test_scanRootsAreNeverBoundInsideAFunction`）：
#:   它不是"根写错"，而是"根本来写得对，只是绑在函数作用域里，`_constTable` 那张**模块级**表认不出"。
#:   认不出＝那档整档掉出本闸的面。批 98 实测过这一形的价钱：把 19 档的根收进 `faceRoot` 之后，
#:   offender 读数仍是 0、摘表两格全绿——绿在这里是假事实源。
#:   修法只有一条：把根提到模块级，并把同档多处根写法收成同一个名字；提上去之后这档进入 DIR 那一支，
#:   面自证的要求随即生效，所以**两处要同批改**，别只提根不补读数。
DYNAMIC, LOCAL, DIR, FILE, OUTSIDE, MISSING = "dynamic", "local", "dir", "file", "outside", "missing"


def _resolveRoot(expr: ast.AST, consts: dict, anchor: pathlib.Path, depth: int = 0,
                 selfPath: pathlib.Path = None):
    """纯结构地把"根"表达式解成一个路径；解不出＝动态值，返 None。

    这里**不判存在、不判在不在仓内**——那是 `_classifyRoot` 的活。`Path(__file__)` 一形按
    **被档自己的路径**解（`selfPath`），因此 `parents[N]` 的含义随该档所在深度而定：
    `tests/unit/ci/x.py` 里的 `parents[3]` 是仓根，`tests/unit/x.py` 里的 `parents[2]` 才是仓根。
    第一版从没用过 `selfPath`，而是从仓根往上再数 N+1 层，把三档的根解成了 `E:\\`。
    深度上限也不能小：`REPO / "a" / "b" / "c" / "d"` 这一条链本身就吃掉五层，
    原来的 8 层上限会把这种**合法写法**降级成动态值，让那档安静地掉出本闸的面——
    与上一条同根因，实测由 `test_memoryWriteIdentityGate.py` 那档当场抓出。
    """
    if expr is None or depth > 64:
        return None
    if isinstance(expr, ast.Name):
        if expr.id == "__file__":
            return selfPath
        if expr.id in consts:
            return _resolveRoot(consts[expr.id], consts, anchor, depth + 1, selfPath)
        return anchor if expr.id in REPO_ROOT_NAMES else None
    if isinstance(expr, ast.Attribute):
        if expr.attr in {"resolve", "absolute"}:
            return _resolveRoot(expr.value, consts, anchor, depth + 1, selfPath)
        if expr.attr == "parent":
            base = _resolveRoot(expr.value, consts, anchor, depth + 1, selfPath)
            return None if base is None else base.parent
        if ast.unparse(expr) in consts:
            return _resolveRoot(consts[ast.unparse(expr)], consts, anchor, depth + 1, selfPath)
        if expr.attr in REPO_ROOT_NAMES:
            return anchor
        return None
    if isinstance(expr, ast.Call):
        func = expr.func
        if isinstance(func, ast.Attribute) and func.attr in {"resolve", "absolute"}:
            return _resolveRoot(func.value, consts, anchor, depth + 1, selfPath)
        name = ast.unparse(func)
        if name in {"Path", "pathlib.Path"} and expr.args:
            return _resolveRoot(expr.args[0], consts, anchor, depth + 1, selfPath)
        head = name.split(".")[0]
        return _resolveRoot(consts.get(head), consts, anchor, depth + 1, selfPath)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Div):
        left = _resolveRoot(expr.left, consts, anchor, depth + 1, selfPath)
        right = expr.right
        if left is None or not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
            return None
        return left / pathlib.PurePosixPath(right.value)
    if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Attribute) \
            and expr.value.attr == "parents" and isinstance(expr.slice, ast.Constant) \
            and isinstance(expr.slice.value, int):
        base = _resolveRoot(expr.value.value, consts, anchor, depth + 1, selfPath)
        if base is None:
            return None
        try:
            return base.parents[expr.slice.value]
        except IndexError:
            return pathlib.Path(base.anchor) if base.anchor else base
    return None


def _classifyRoot(path, anchor: pathlib.Path) -> str:
    """把解出来的路径归到五态之一。大小写与分隔符按 `os.path.normcase` 归一再比。"""
    if path is None:
        return DYNAMIC
    norm = pathlib.Path(os.path.normcase(str(path)))
    home = os.path.normcase(str(anchor))
    inside = str(norm) == home or home in (os.path.normcase(str(p)) for p in norm.parents)
    if norm.is_dir():
        return DIR if inside else OUTSIDE
    if norm.is_file():
        return FILE if inside else OUTSIDE
    return MISSING


def _scanSites(tree: ast.AST, consts: dict, anchor: pathlib.Path,
               selfPath: pathlib.Path = None, scoped: dict = None) -> list:
    """这档里每个扫描落点的 `(入口, 根的落点态)`——落点态见上面六态的注释。

    按「接收者＋属性名」两维认，不按属性名单认：`ast.walk(tree)` 与 `os.walk(dir)`
    只差一个接收者，把前者当全仓扫描会把读数放大一个量级（本档取数路自己踩过的第一版错）。
    """
    out = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        attr = call.func.attr
        recv = ast.unparse(call.func.value) if isinstance(call.func.value, ast.expr) else ""
        top = recv.split(".")[0].split("(")[0]
        if top == "ast_scan" and attr in SHARED_SCAN_ENTRIES:
            expr = call.args[0] if call.args else None
            out.append((attr, _rootStatus(expr, consts, anchor, selfPath, scoped)))
        elif attr in FILE_ENUM_ATTRS and top not in NON_PATH_RECEIVERS:
            out.append((attr, _rootStatus(call.func.value, consts, anchor, selfPath, scoped)))
        elif attr == "walk" and top == "os":
            expr = call.args[0] if call.args else None
            out.append(("os.walk", _rootStatus(expr, consts, anchor, selfPath, scoped)))
    return out


def _rootGap(sites: list) -> str:
    """这档有没有「静态根解到仓外／指不到目录」的落点——有就返回那一态，没有返回空串。"""
    for _entry, status in sites:
        if status in (OUTSIDE, MISSING):
            return status
    return ""


def _countNames(tree: ast.AST) -> set:
    """档内"由扫描/计数得到的名字"。

    认这四种形制，都是本仓现有判据真在用的写法（少认一种就会把已经自证的档错判成 offender——
    实测第一版就把自己刚建的那两格错判了：`surface.get("filesSeen")` 与循环里 `scanned += 1`）：
      * `x = len(...)` / `x = sum(...)`
      * `x = <统计袋>.get(...)`（共享入口回填面读数的写法，见 `shadowedTopLevelNames` 的 `stats`）
      * `x = ast_scan.<入口>(...)`（直接拿扫描结果本身）
      * `x = [...] for ... in ...`（列表推导收集出的落点清单）
      * 循环里 `x += 1` 累加出来的计数器
    """
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
            rhs = node.value
            if isinstance(rhs, ast.Call):
                fn = ast.unparse(rhs.func)
                if fn in COUNT_CONSTRUCTORS or fn.split(".")[0] == "ast_scan" or fn.endswith(".get"):
                    names.add(node.targets[0].id)
            elif isinstance(rhs, ast.ListComp):
                names.add(node.targets[0].id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) \
                and isinstance(node.op, ast.Add):
            names.add(node.target.id)
    return names


def _hasFaceProof(tree: ast.AST, counts: set) -> bool:
    """存在一条 `assert <扫描计数> > 数`（或 `>=`）——只认代码形状，不认词。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or not isinstance(node.test, ast.Compare):
            continue
        cmp_ = node.test
        if not any(isinstance(op, (ast.Gt, ast.GtE)) for op in cmp_.ops):
            continue
        if not any(isinstance(o, ast.Constant) and isinstance(o.value, (int, float))
                   for o in cmp_.comparators):
            continue
        operands = [cmp_.left] + list(cmp_.comparators)
        for side in operands:
            text = ast.unparse(side).strip()
            if text.startswith(("len(", "sum(")) or text in counts:
                return True
    return False


def _faceFindings(root: pathlib.Path, manifest: list, gaps: dict = None,
                  localGaps: dict = None) -> list:
    """挑出两类档：① 静态根解到仓外／指不到目录；② 有仓内扫描根却无面自证。

    `gaps` 传一个字典就回填 `rel -> 落点态`，供报错文案说清红的是哪一条规则——两类都算
    offender，但**修法相反**（①是把根写对，②是补断言），混成一句话人就不知道该动哪一处。
    `localGaps` 回填第三类（根绑在函数里的名字上，`rel -> 那些入口名`）。它**不计进 offender**，
    由 `test_scanRootsAreNeverBoundInsideAFunction` 单独零容忍：同一档报两处，人就分不清先动哪一步
    （正确次序＝先把根提到模块级，那档随即进入 DIR 那一支，面自证的要求才落到它头上）。
    """
    offenders = []
    for rel in manifest:
        path = root / rel
        if not rel.endswith(".py") or not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        consts = _constTable(tree)
        sites = _scanSites(tree, consts, root, selfPath=path.resolve(), scoped=_scopedBindings(tree))
        if localGaps is not None:
            localEntries = sorted({entry for entry, st in sites if st == LOCAL})
            if localEntries:
                localGaps[rel] = localEntries
        gap = _rootGap(sites)
        if gap:
            if gaps is not None:
                gaps[rel] = gap
            offenders.append(rel)
            continue
        if not any(st == DIR for _e, st in sites):
            continue
        if not _hasFaceProof(tree, _countNames(tree)):
            offenders.append(rel)
    return sorted(offenders)


def _manifestOf(root: pathlib.Path) -> list:
    path = root / "scripts" / "ci" / "protected_tests.txt"
    if not path.is_file():
        return []
    return [ln.split("#", 1)[0].strip() for ln in io.open(path, encoding="utf-8").read().splitlines()
            if ln.split("#", 1)[0].strip()]


def test_ratchetDoesNotRise():
    """新增「扫仓内路径而不自证面」或「根写错」的判据档一律拦。"""
    gaps = {}
    now = set(_faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT), gaps))
    grew = sorted(now - set(BASELINE))
    wrongRoot = [rel for rel in grew if gaps.get(rel)]
    noProof = [rel for rel in grew if not gaps.get(rel)]
    assert not grew, (
        "**根写错了**（静态根解到仓外或指不到真实目录——它的「零命中」根本不来自代码）：\n  "
        + "\n  ".join("%s [%s]" % (rel, gaps[rel]) for rel in wrongRoot)
        + "\n**扫了仓内源码树却没把这次扫到的数量当断言比**（根被改窄时读数是「零命中」而不是红）：\n  "
        + "\n  ".join(noProof)
        + "\n修法分两条码：前者把根写对（`Path(__file__).resolve().parents[N]` 的 N 要按**本档所在深度**算）；"
        "\n后者一行即可，形如 `scanned = len(...); assert scanned > 500, f\"扫描面现读 {scanned}\"`，"
        "\n参考同档 `test_surfaceCoversAllThreeSourceFamilies`（先验面，再谈零命中）。"
        "\n别把新档加进基线表——那等于把这条棘轮又拆回各判各的。"
    )


def test_staticRootsNeverPointOutsideOrNowhere():
    """静态根必须解得到**仓内真实目录**——这一条不留存量豁免。

    为什么要单开一格：`test_ratchetDoesNotRise` 只比"比基线新增了什么"，于是**本来就在表里**的
    一档把根写错时，它照样留在 offender 里、失败集合一个字节都没变——存量名单把「根错了」这件
    更重的事兜掉了。本会话实测：把 `test_route_vocabulary_is_single_source.py` 的 `parents[3]`
    改成 `parents[4]`，棘轮两格全绿。反证在册：`test_faceRulesPinDepthAndWrongRoots` 的
    parents[3].parent／no_such_dir 两格必须交出**非空**的 gaps，否则这里的零断言只说明探测器没在跑。
    """
    gaps = {}
    _faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT), gaps)
    assert not gaps, (
        "这些受保护子集里的判据，静态根解到了仓外或指不到真实目录（它的「零命中」不来自代码）：\n  "
        + "\n  ".join("%s [%s]" % (rel, st) for rel, st in sorted(gaps.items()))
        + "\n`Path(__file__).resolve().parents[N]` 的 N 要按**本档所在深度**算："
        "`tests/unit/ci/x.py` 是 3，`tests/unit/x.py` 是 2。"
    )


def test_scanRootsAreNeverBoundInsideAFunction():
    """扫描根不得绑在**函数内的名字**上——新增即红，存量按表登记、消化要显式摘。

    为什么单独一格：这种档的根写得没错，错在绑的位置。`_constTable` 只收模块级绑定，于是
    `faceRoot = PROJECT_ROOT / "neurova"` 这一行让整档的落点变成"动态值"——既不要求面自证，
    也不算根写错，**安静地掉出本闸的面**。批 98 就是当场踩中的：那次为了消掉"报错里的根是把
    被检表达式再抄一遍"，把 8 档的根收进函数局部，复算发现 6 档的落点态只剩 `dynamic`，
    而 offender 仍是 0、摘表两格全绿。
    为什么这一格允许带存量表（与「根写错」那格不同）：LOCAL 是本闸的**盲区**而不是写错的根，
    建档那轮的存量与 `BASELINE` 同性质——所以纪律也同：新增即红、消化必须摘表，
    两边的表都由本文件的 `_faceFindings` 现取，不从别处抄数。
    反证在册：`test_localRootIsNamedNotIgnored` 必须交出**非空**的 localGaps，
    否则这里的"零新增"只说明探测器没在跑。
    """
    locals_ = {}
    _faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT), localGaps=locals_)
    grew = sorted(set(locals_) - LOCAL_BASELINE)
    assert not grew, (
        "这些判据把扫描根绑在函数内的名字上（本闸按模块级常量解根，认不出＝那档整档不在面内）：\n  "
        + "\n  ".join("%s ← %s" % (rel, ", ".join(entries)) for rel, entries in
                      sorted((r, locals_[r]) for r in grew))
        + "\n修法：把根提到**模块级**常量，并让同档所有扫描落点与报错消息都向同一个名字要根；"
        "\n提到模块级之后这档就进入「仓内目录」那一支，面自证（`assert <扫描计数> > 数`）随即生效——"
        "两处要同批改完，别只提根不补读数。"
    )
    dropped = sorted(LOCAL_BASELINE - set(locals_))
    assert not dropped, (
        "以下档的扫描根已经提到模块级了——把 LOCAL_BASELINE 里那几行摘掉再提交，别让它悬着：\n  "
        + "\n  ".join(dropped)
    )


def test_ratchetRecordsImprovementLoudly():
    """存量被消化要**显式收表**：基线里有、现在不 offender 的档，必须从表里摘掉。"""
    now = set(_faceFindings(PROJECT_ROOT, _manifestOf(PROJECT_ROOT)))
    dropped = sorted(set(BASELINE) - now)
    assert not dropped, (
        "以下档已经自带面自证（或不再扫仓内路径）了——把 BASELINE 里那几行摘掉再提交，"
        "别让它悬着（悬着的后果：下一条真新增的 offender 会被旧表兜住而看不见）：\n  "
        + "\n  ".join(dropped)
    )


@pytest.mark.parametrize("label, source, expectNamed", [
    ("根绑在函数里的名字上（值是对的、位置不对）＝必须点名",
     "from tests import ast_scan\nimport pathlib\n\n\n"
     "def test_shape():\n"
     "    faceRoot = pathlib.Path(__file__).resolve().parents[3] / 'neurova'\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(faceRoot, '.py')]\n"
     "    assert hits == []\n", True),
    ("控制格：根是**运行时形参**＝本来就不承载面的声明，不许误报",
     "from tests import ast_scan\n\n\ndef test_shape(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n", False),
    ("控制格：函数内的名字指向**不存在的目录**＝那是「根写错」那一支，不冒充 LOCAL",
     "from tests import ast_scan\nimport pathlib\n\n\n"
     "def test_shape():\n"
     "    faceRoot = pathlib.Path(__file__).resolve().parents[3] / 'no_such_dir'\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(faceRoot, '.py')]\n"
     "    assert hits == []\n", False),
    ("控制格：根在模块级＝走正常那一支（DIR＋面自证），不该被 LOCAL 格误报",
     "from tests import ast_scan\nimport pathlib\n"
     "_Target = pathlib.Path(__file__).resolve().parents[3] / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n"
     "    assert hits == []\n", False),
])
def test_localRootIsNamedNotIgnored(tmp_path, label, source, expectNamed):
    """第五态 LOCAL 要有牙：正检（函数内静态根）与三枚控制格（形参／指不到／模块级）各配一格。

    没有这一格，`test_scanRootsAreNeverBoundInsideAFunction` 那句"零命中"就分不清是干净还是探测器
    根本没在跑——本闸自己的三版失效（`parents[N]` 按仓根数、深度上限 8、存量表兜掉根写错）都是这一形。
    """
    (tmp_path / "neurova").mkdir()
    (tmp_path / "tests" / "unit" / "ci").mkdir(parents=True)
    (tmp_path / "tests" / "unit" / "ci" / "sample.py").write_text(source, encoding="utf-8")
    locals_ = {}
    _faceFindings(tmp_path, ["tests/unit/ci/sample.py"], localGaps=locals_)
    assert bool(locals_) is expectNamed, f"{label} ⇒ 判错：{locals_}"


def test_surfaceReadingIsNotVacuous():
    """反空转：扫描面本身要先在场——"一条 offender 都没有"可能只是清单没读到。

    这条格专防本仓反复吃过的那一形：清单路径写错 ⇒ 空 manifest ⇒ offender 恒空 ⇒ 两条断言全绿。
    """
    manifest = _manifestOf(PROJECT_ROOT)
    assert len(manifest) > 500, f"受保护子集清单现读 {len(manifest)} 条，量级不对＝没读到"
    parsed = 0
    for rel in manifest:
        if (PROJECT_ROOT / rel).is_file():
            parsed += 1
    assert parsed == len(manifest), (
        f"清单里有 {len(manifest) - parsed} 条指不到真实文件——offender 读数会偏小且偏干净")


_PROOF_TAIL = (
    "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n"
    "    scanned = len(hits)\n"
    "    assert scanned > 500\n"
    "    assert hits == []\n"
)
_NO_PROOF_TAIL = "    hits = [p for p, _n in ast_scan.nodeScan(_Target, '.py')]\n    assert hits == []\n"


@pytest.mark.parametrize("rel, source, label, expectOffender, expectGap", [
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'neurova'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "档在 ci/ 下（深度 3），parents[3] 就是仓根——这一档扫的是仓内路径，缺自证必须点名", True, ""),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3].parent\n_Target = _Repo\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "根上溯到仓外（`parents[3].parent`＝仓根的上一层），面根本不在代码上；带了自证也照样红", True, OUTSIDE),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo.parent\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "根解到仓外的**真实目录**（这里是仓根的上一层）：目录存在但不在仓内，带自证也照样红", True, OUTSIDE),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'neurova'\n\n\n"
     "def test_shape():\n" + _PROOF_TAIL,
     "控制格：深度解对、自证在场＝不点名（防把规则做成『凡 parents 写法皆红』）", False, ""),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'no_such_dir'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "静态根指不到真实目录——与『目录被改名/删掉』同形，零命中是假的，必须点名", True, MISSING),
    ("tests/unit/ci/sample.py",
     "from tests import ast_scan\nimport pathlib\n"
     "_Repo = pathlib.Path(__file__).resolve().parents[3]\n_Target = _Repo / 'one.py'\n\n\n"
     "def test_shape():\n" + _NO_PROOF_TAIL,
     "根指到仓内一个真实文件＝面很窄，但坏得**响**（入口当场抛 FileNotFoundError），本闸不管这一形", False, ""),
    ("tests/sample.py",
     "from tests import ast_scan\n\n\ndef test_shape(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n",
     "运行时才定的根不承载面的声明：既不点名也不免罪，维持原设计", False, ""),
])
def test_faceRulesPinDepthAndWrongRoots(tmp_path, rel, source, label, expectOffender, expectGap):
    """根的形状要按**被档自身深度**解，且「静态根解到仓外／指不到目录」必须点名。

    建档那轮现扫时，两档（`test_route_vocabulary_is_single_source.py`、`test_deploy_config_guard.py`）
    的根被解成了 `E:\\`——`Path(__file__).resolve().parents[N]` 这一形当时是**从仓根往上再数 N+1 层**，
    与档所在深度无关。第一版只把这当成"读数不准"，但它真正的坏法是：**把根少写一层的那档会安静地
    掉出本闸的面**（解出来的目录存在就不算动态值），于是"零命中"既可能来自干净、也可能来自
    根根本没指到代码——正是本档要防的那件事，被本档自己的取数路放过去了。
    """
    (tmp_path / "neurova").mkdir()
    (tmp_path / "one.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(source, encoding="utf-8")

    gaps = {}
    offenders = _faceFindings(tmp_path, [rel], gaps)
    assert bool(offenders) is expectOffender, f"{label} ⇒ 判错：{offenders}"
    assert gaps.get(rel, "") == expectGap, (
        f"{label} ⇒ 落点态判错：{gaps} 里要的是 {expectGap!r}")


@pytest.mark.parametrize("label, source, expectOffender", [
    ("只断零命中，没断面＝正是要拦的形状",
     "from tests import ast_scan\n"
     "import pathlib\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(ROOT, '.py')]\n"
     "    assert hits == []\n", True),
    ("把这次扫到的数量当断言比＝合规",
     "from tests import ast_scan\n"
     "import pathlib\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    pairs = list(ast_scan.nodeScan(ROOT, '.py'))\n"
     "    scanned = len(pairs)\n"
     "    assert scanned > 500, f'扫描面现读 {scanned}'\n"
     "    assert [p for p, _n in pairs] == []\n", False),
    ("有一条与扫描无关的数断言不算自证（6 档新增就是这形）",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_noBadThingAnywhere():\n"
     "    hits = list(ast_scan.nodeScan(ROOT, '.py'))\n"
     "    rows = [1, 2, 3]\n"
     "    assert len(rows) == 3\n"
     "    assert hits == []\n", True),
    ("根是真动态值（循环里的名字）＝不承载面的声明，不参与裁决",
     "from tests import ast_scan\n\n\n"
     "def test_perFamily(root):\n"
     "    hits = [p for p, _n in ast_scan.nodeScan(root, '.py')]\n"
     "    assert hits == []\n", False),
    ("`ast.walk(tree)` 不是文件扫描：别把它算成落点",
     "import ast\n\n\n"
     "def test_shape(source):\n"
     "    nodes = list(ast.walk(ast.parse(source)))\n"
     "    assert nodes\n", False),
    ("循环里累加出来的计数器算自证",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    scanned = 0\n"
     "    for path, tree in ast_scan.parsedModules(ROOT, '.py'):\n"
     "        scanned += 1\n"
     "    assert scanned > 500, f'扫描面现读 {scanned}'\n", False),
    ("共享入口回填的统计袋算自证（面读数与被裁的那次扫描同源）",
     "from tests import ast_scan\n"
     "ROOT = ast_scan.REPO_ROOT / 'neurova'\n\n\n"
     "def test_shape():\n"
     "    surface = {}\n"
     "    dups = ast_scan.shadowedTopLevelNames(ROOT, stats=surface)\n"
     "    seen = surface.get('filesSeen', 0)\n"
     "    assert seen > 3000, f'现读 {seen}'\n"
     "    assert dups == []\n", False),
])
def test_classifierJudgesEveryShapeItClaims(tmp_path, label, source, expectOffender):
    """判据自身的分类器逐形自证：正检、反检都要有，且新认的形制各配一格。

    合成样本一律落在 `tmp_path`（自带一份子集清单），不往真仓里种文件——
    种进去会被其余常驻判据双计（仓内任何一份代码副本都是这条根因的账单）。
    `tmp_path/neurova/` 要真的建出来：根解析按"该目录存在"判，不建就等于让样本走一条
    与真仓不同的分支，那种绿不算证到。
    """
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "neurova").mkdir()
    (tmp_path / "scripts" / "ci" / "protected_tests.txt").write_text("tests/sample.py\n", encoding="utf-8")
    (tmp_path / "tests" / "sample.py").write_text(source, encoding="utf-8")

    offenders = _faceFindings(tmp_path, ["tests/sample.py"])
    assert bool(offenders) is expectOffender, f"{label} ⇒ 分类判错：{offenders}"
