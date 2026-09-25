# -*- coding: utf-8 -*-
"""受保护子集里的跨文件 AST 判据必须走共享解析预算（Issue #148）。

根因（不是形状）：受保护子集里有若干个「单源 / 收口点」判据，判据内容是
「仓库里不得出现第二处实现」，实现方式却是**把全仓每个 `.py` 都 `ast.parse`
一遍、再 `ast.walk` 一遍**。实测解析成本 ≈ 1.4 ms/文件（本机 1000 文件 ≈ 1.4s、
2000 文件 ≈ 2.9s），词法遍历再叠 1.5 倍，于是**代码总量被编码成了时间上界**：

- 单跑这些用例本机 4–6s（`test_rsi_rollback_evidence` 4.4s、
  `test_write_boundary_closes_verification` 5.0s、`test_dead_cache_module_removed` 4.5s、
  `test_rsi_observation_surface` 5.4s、`test_capability_cache_single_source` 5.1s）；
- 与另外 170 个受保护文件共享机器、按 `-q` 一次性跑时，撞 `pytest-timeout`
  的默认 30s 墙钟——2026-09-22 构建 `cnb-2p6-1k347lfg1` 实测转红：
  `Failed: Timeout (>30.0s) from pytest-timeout`。

这不是「跑得慢」，是**判据与机器速度捆绑**（`AGENTS.md` 修复教义第 2 条点名的
「降级/绕开断言」的近亲）：判据本身与代码行数、与机器快慢都无关，墙钟上界
不会因为它变松而更成立，只会把真实的超时回归一起放行。

处置：解析单源到 `tests/ast_scan.py`（`AGENTS.md` 第 6 条：不新造平行体系）。
本守卫锁住**形态**而非具体秒数——判据不空转、不靠机器快慢：

1. **无预筛的全仓 `rglob + ast.parse` 归零**：受保护子集里出现新的一处即红；
2. **共享预算入口真实可用**：`callSites` / `importsOf` / `classDefsIn` 必须存在且
   能真报出命中（否则各守卫会退回各写一套，本门禁退化成空规则）；
3. **预筛不得漏报**：预筛是**充分条件**——谓词是 `X.<name>`，连 `<name>` 都没
   出现的文件不可能命中。故用「注入一个真实命中 + 一个不含关键词的文件」自证；
4. **解析面按语义覆盖**（Issue #197 批遗留）：不是「源码里恰好写了 `ast.parse`」，
   而是**凡把源码编译成语法树/字节码的入口**——`compile(..., PyCF_ONLY_AST)`、
   `py_compile` / `compileall`、第三方解析器（`parso` / `libcst` / `astroid`）、
   以及 `from ast import parse as X` 后的裸名。反例成对钉住：`re.compile` 与
   同名本地函数**不得**报出（受保护子集里「枚举 + 正则」的文件有一批，
   误报即门禁失效——这正是「口径扩大需各自的实证样本」那句话要防的）。
   实测：检测面成本在收齐 import 面后回到主线水平（266 个登记文件 1.42s vs
   主线 1.34s），不为「更宽」付墙钟账。
"""
from __future__ import annotations

import ast
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests import ast_scan

PROTECTED = PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt"

#: 允许保留的「枚举 + 解析」全仓扫描：**空集是默认政策**。
#: 确需保留者必须逐条写明理由，并说明为何不能走 `tests/ast_scan.py` 的预筛。
REPO_WIDE_SCAN_LEDGER: dict = {  # type: ignore[type-arg]
    "tests/unit/core/test_pytest_collection_hygiene.py": (
        "判据的对象**就是**每个测试文件的用例名（`def` / `class` 声明面），"
        "故必须逐个测试文件解析，且**预筛可证无效**：本仓 1783 个 `test_*.py` 里"
        "1752 个含 `def test` / `class Test` 字样（98%），预筛缩不掉解析量。"
        "路由到共享解析缓存实测**更慢**（本文件单跑 2.0s → 6.0s）："
        "`_cachedParse` 是 `maxsize=None`，保留全部语法树后 gen2 GC 要反复扫描"
        "这棵常驻图，成本仍随代码总量涨（实测 1783 文件：不保留 1.00s vs "
        "保留 4.74s；`gc.freeze()` 后 1.21s）。**这是共享缓存自身的保留策略问题**，"
        "不是本判据的形态问题 —— 修正缓存保留策略后再改路由，"
        "在此之前按教义第 2 条如实登记，不做 consumer 侧的规避。"
    ),
}


def protectedFiles() -> list:
    """CI 实际跑的受保护子集（唯一事实源，不另建清单）。"""
    return [line.split("#", 1)[0].strip()
            for line in io.open(PROTECTED, encoding="utf-8").read().splitlines()
            if line.split("#", 1)[0].strip()]


#: 文件系统枚举调用：属性形态（`X.rglob` / `X.iterdir` …）
ENUMERATION_ATTRS = frozenset({"rglob", "glob", "iglob", "iterdir", "listdir", "scandir"})
#: 文件系统枚举调用：裸名形态（`glob(...)` / `listdir(...)` …）
ENUMERATION_NAMES = frozenset({"glob", "iglob", "listdir", "scandir"})
#: 共享预算的**扫描**入口：枚举与解析都在预算内完成。调用它们即已走预算，
#: 既不计枚举也不计解析、且不再下潜（下潜会把预算实现自身报红）——
#: `tests/unit/test_dev_path_and_runtime_dep_guards.py::test_no_shell_out_to_ripgrep`
#: 正是走 `ast_scan.nodeScan(hints=...)` 的合规写法。
SHARED_BUDGET_ENTRIES = frozenset({
    "nodeScan", "sourceRefsUnder", "parsedModules", "walkedModules",
    "callSites", "callNodes", "classDefsIn",
})
#: 共享预算的**只枚举**入口：枚举（`rglob`）归共享，但解析仍由调用方自付。
#: 故它算枚举落点 —— 配私有 `ast.parse` 仍须报出（否则它成了免检通道）。
SHARED_ENUM_ENTRIES = frozenset({"filesUnder"})

#: 「解析」落点：**模块别名 → 该模块上属于解析原语的属性名**。
#: 靶点是「成本随代码总量涨」，故凡把源码编译成语法树/字节码的入口都算：
#: `ast.parse`、`builtins.compile`（`compile(..., PyCF_ONLY_AST)` 即它）、
#: `py_compile.compile`、`compileall.compile_dir` 一族。
#: 反例（不得报出）：`re.compile` —— 它编译的是**正则**，与源码解析无关，
#: 受保护子集里「枚举 + 正则」的文件有一批，按调用名判会把它们全报红。
PARSE_MODULE_ATTRS = {
    "ast": frozenset({"parse"}),
    "builtins": frozenset({"compile"}),
    "py_compile": frozenset({"compile"}),
    "compileall": frozenset({"compile_dir", "compile_file", "compile_path"}),
    # 第三方解析器：与标准库同契约（把源码编译成语法树）。只在**该模块真被
    # import** 时才算 —— 仓内当前无这些依赖，故不构成假阳性面，也不引入依赖。
    "parso": frozenset({"parse"}),
    "libcst": frozenset({"parse_module", "parse_expression", "parse_statement"}),
    "astroid": frozenset({"parse"}),
}
#: 解析原语的**裸名**形态（无模块前缀）：内建 `compile` 与 `ast.parse` 的裸名 `parse`。
BARE_PARSE_NAMES = frozenset({"compile", "parse"})


def _importSurface(tree) -> tuple:
    """**一趟**收齐 import 面：`({模块: {别名}}, {解析原语裸名})`。

    为什么必须一趟：本门禁自己也在受保护子集里（它被登记了）。若每认一种解析
    写法就多 `ast.walk` 一趟，那么「检测面越宽、门禁越慢」—— 判据成本又一次
    随**代码总量 × 判据种类**增长，正是本文件要防的那条根因的镜像。

    返回的两份口径：

    - 别名表：`import <模块> as X` / `from <模块> import Y as X` 引入的本地名。
      只有**表里有的模块**才算（`import widget` 之后的 `widget.compile` 不是解析）；
    - 解析原语裸名：`from ast import parse as X` 之后的 `X` —— 它**就是**解析原语，
      与写 `ast.parse(...)` 等价，只是把模块名省掉了。
    """
    wanted = set(PARSE_MODULE_ATTRS) | {"os"}
    aliases = {module: set() for module in wanted}
    parseMembers = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in wanted:
                    aliases[root].add(alias.asname or root)
        elif isinstance(node, ast.ImportFrom) and node.module in wanted:
            for alias in node.names:
                local = alias.asname or alias.name
                aliases[node.module].add(local)
                if alias.name in PARSE_MODULE_ATTRS[node.module]:
                    parseMembers.add(local)
    return aliases, parseMembers


def _boundInScope(statements) -> set:
    """这些语句在**本作用域**内绑定的名字（不下潜进 def / class 体）。

    类体**不是**作用域：`class Widget: compile = None` 绑的是类属性，
    模块级内建 `compile` 照旧可用 —— 把它算成遮蔽会造出假阴性面。
    """
    bound = set()
    stack = list(statements)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            continue
        if isinstance(node, ast.ClassDef):
            bound.add(node.name)
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                # `from ast import parse as X` 绑定的**正是**解析原语，不算遮蔽。
                if (node.module in PARSE_MODULE_ATTRS
                        and alias.name in PARSE_MODULE_ATTRS[node.module]):
                    continue
                bound.add(alias.asname or alias.name)
        stack.extend(ast.iter_child_nodes(node))
    return bound


def _parametersOf(fn) -> set:
    """函数签名里绑定的形参名（含 `*args` / `**kwargs`）。"""
    arguments = fn.args
    params = {arg.arg for arg in (list(arguments.posonlyargs) + list(arguments.args)
                                 + list(arguments.kwonlyargs))}
    if arguments.vararg:
        params.add(arguments.vararg.arg)
    if arguments.kwarg:
        params.add(arguments.kwarg.arg)
    return params


def _scanUnits(tree) -> tuple:
    """把文件拆成**扫描落点**与它们的遮蔽集：`([(标签, 语句, 遮蔽集)], {裸名: [...]})`。

    标签是给人读的落点名（类内函数记 `类.方法`，同名函数因此不再串味）；遮蔽集
    是**该作用域**里被改绑成非解析原语的 `compile` / `parse`（见 `_boundInScope`）。

    为什么要按作用域而不是整文件：整文件级遮蔽是**假阴性面** —— 一个 helper 里
    恰好有个局部 `def parse`，另一个 helper 的全仓扫描就被无声放行；而按**裸函数名**
    建表又会在同名函数处撞键（顺序一变结果就变）。闭包链一并并入（内层函数能看见
    外层函数与模块的绑定），类体**不是**作用域，故不进闭包链。
    """
    moduleBound = _boundInScope(tree.body)
    units = [("<模块级>", tree.body, moduleBound & BARE_PARSE_NAMES)]
    byFunction: dict = {}

    def visit(statement, inherited, prefix):
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            own = _boundInScope(statement.body) | _parametersOf(statement)
            visible = (own | inherited) & BARE_PARSE_NAMES
            label = prefix + statement.name
            units.append((label, statement.body, visible))
            byFunction.setdefault(statement.name, []).append(
                (label, statement, visible))
            for child in statement.body:
                visit(child, own | inherited, label + ".")
            return
        if isinstance(statement, ast.ClassDef):
            for child in statement.body:
                visit(child, inherited, prefix + statement.name + ".")
            return
        for child in ast.iter_child_nodes(statement):
            visit(child, inherited, prefix)

    for statement in tree.body:
        visit(statement, moduleBound, "")
    return units, byFunction


def _callsOutsideDefs(statements, aliases, unitShadow: set) -> tuple:
    """这些语句里的调用，**不下潜**进 def / class 体。

    返回 `({被调名}, {文件系统枚举}, {解析})`（判据与口径见 `PARSE_MODULE_ATTRS`）：

    - 枚举：`X.rglob` / `X.iterdir` / `X.glob` / `X.listdir` / `X.scandir`，
      以及 `import os` 之后裸写的 `os.walk`（`X.walk` 只有落在 `os` 模块别名上
      才算 —— `ast.walk` 是词法遍历，`tests/unit/ci/` 里另有一批同名本地 `walk`
      递归函数，按名字判会把它们全算成枚举）；
    - 解析：`<ast 别名>.parse(...)`、`<builtins 别名>.compile(...)`（含
      `compile(..., PyCF_ONLY_AST)`）、`<py_compile 别名>.compile(...)`、
      `<compileall 别名>.compile_dir(...)` 一族、第三方解析器
      （`parso` / `libcst` / `astroid`，只在真被 import 时才算），以及裸
      `compile(...)` / `parse(...)` 与 `from ast import parse as X` 之后的
      裸名 `X` —— 凡把源码编译成语法树/字节码的入口都算（见
      `PARSE_MODULE_ATTRS`）；`re.compile`
      不算（它编译的是正则，不是源码解析）；`tests/ast_scan` 的共享预算入口
      一律**不算**解析落点（它是本门禁的推荐修法）。

    为什么要剪枝：模块级与函数级是**两个**扫描落点，混在一起判会让
    「模块级」分支把每个函数体都算进来，于是每个文件都被误报。
    """
    osAliases = aliases["os"]
    astAliases = aliases["ast"]
    callees, enumerations, parses = set(), set(), set()
    stack = list(statements)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                callees.add(func.attr)
                root = ast.unparse(func.value).split(".")[0].split("[")[0]
                parsePrimitive = _parseAttributePrimitive(root, func.attr, aliases)
                if parsePrimitive:
                    parses.add(parsePrimitive)
                elif func.attr == "walk" and root in osAliases:
                    enumerations.add("os.walk")
                elif func.attr in SHARED_BUDGET_ENTRIES:
                    pass  # 已走预算：既不计枚举也不计解析
                elif func.attr in SHARED_ENUM_ENTRIES:
                    enumerations.add(func.attr)
                elif func.attr in ENUMERATION_ATTRS and root not in astAliases:
                    enumerations.add(func.attr)
            elif isinstance(func, ast.Name):
                callees.add(func.id)
                if func.id in aliases["parseMembers"]:
                    parses.add(func.id)
                elif func.id in BARE_PARSE_NAMES and func.id not in unitShadow:
                    parses.add(func.id)
                elif func.id == "walk" and func.id in aliases["os"]:
                    enumerations.add("walk")
                elif func.id in ENUMERATION_NAMES:
                    enumerations.add(func.id)
        stack.extend(ast.iter_child_nodes(node))
    return callees, enumerations, parses


def _parseAttributePrimitive(root: str, attribute: str, aliases) -> str:
    """`<模块别名>.<属性>` 是否落在解析原语上；是则回名字，否则回空串。

    只有**别名表里**的模块才算（`import builtins as _bi` 之后的 `_bi.compile`
    是解析；`import widget` 之后的 `widget.compile` 不是）。
    `ast.walk` 是词法遍历、`ast.parse` 才是解析，故 `ast` 别名上只认 `parse`。
    """
    for module, attributes in PARSE_MODULE_ATTRS.items():
        if attribute in attributes and root in aliases[module]:
            return f"{module}.{attribute}"
    return ""


def _repoWideAstScans(source: str) -> list:
    """文件里「文件系统枚举 + 解析」的落点（函数名，模块级记 `<模块级>`）。

    判据的靶点是**成本随代码总量增长**，不是「源码里恰好写了哪两个名字」：

    - 落点**不限于** `test*` 函数：全仓扫描常被放在 helper 里，`test_x` 只是
      调用它的壳（`tests/unit/api/test_orphan_faces_retired_guard.py::_references`
      就落在这个盲区里，Issue #197 批遗留的同根形态）；
    - 枚举**不限于** `rglob`：`os.walk` 展开整棵树、`iterdir` / `glob` / `listdir`
      同样是枚举，只要后面跟着解析，成本照样随代码总量涨；
    - 解析**不限于**裸名 `parse`：`import ast as _ast` 之后是 `_ast.parse`；
    - 两者可以分处**两层 helper**：只在同一函数体里找名字同现会漏掉这种拆法。
      报出的落点是**发起枚举的那一层**；纯解析的 helper 不是扫描落点，不报。

    两条不得报出的形态（假阳性会训练人忽略门禁）：解析**单个函数自己的源码**
    （`ast.walk(ast.parse(inspect.getsource(func)))`，它枚举的是树、不是仓库）、
    以及走 `tests/ast_scan` 共享预算的写法。
    """
    tree = ast.parse(source)
    aliases, parseMembers = _importSurface(tree)
    # `<模块>.<成员>` 的裸名形态（`from ast import parse as X` 之后的 `X`）与
    # 模块别名同属一张表，见 `_importSurface`。
    aliases["parseMembers"] = parseMembers
    # `ast.parse` 未 import 也照判：写法等价，漏报比假阳性更坏（代价是成本照付）。
    aliases["ast"] = aliases["ast"] or {"ast"}
    units, byFunction = _scanUnits(tree)

    hits = []
    for label, body, shadow in units:
        if label in SHARED_BUDGET_ENTRIES:
            # 预算实现自身的定义不是「调用方落点」：它的枚举与解析都在预算内。
            continue
        callees, enumerations, parses = _callsOutsideDefs(body, aliases, shadow)
        seen = set()
        stack = [name for name in callees if name not in SHARED_BUDGET_ENTRIES]
        while stack:
            callee = stack.pop()
            if callee in seen or callee not in byFunction:
                continue
            seen.add(callee)
            for _label, fn, fnShadow in byFunction[callee]:
                more, enums2, parses2 = _callsOutsideDefs(
                    fn.body, aliases, fnShadow)
                enumerations |= enums2
                parses |= parses2
                stack.extend(n for n in more if n not in SHARED_BUDGET_ENTRIES)
        if enumerations and parses:
            hits.append(label)
    return sorted(set(hits))


class TestNoUnprefilteredRepoWideScan:
    """受保护子集里的全仓 AST 扫描归零：判据不得与代码总量捆绑。"""

    def test_no_unledgered_repo_wide_ast_scan(self):
        live = {}
        for rel in protectedFiles():
            path = PROJECT_ROOT / rel
            if not path.is_file() or not rel.endswith(".py"):
                continue
            try:
                source = io.open(path, encoding="utf-8", errors="ignore").read()
                hits = _repoWideAstScans(source)
            except SyntaxError:
                continue
            if hits:
                live[rel] = hits
        unledgered = {rel: hits for rel, hits in live.items() if rel not in REPO_WIDE_SCAN_LEDGER}
        assert not unledgered, (
            "受保护子集里出现「rglob + ast.parse」全仓扫描（判据与代码总量、"
            "与机器速度捆绑，30s 默认墙钟下必偶发红）:\n  "
            + "\n  ".join(f"{rel} → {hits}" for rel, hits in sorted(unledgered.items()))
            + "\n修法：走 tests/ast_scan.py（callSites / importsOf / classDefsIn / nodeScan(hints=...)）;"
            "\n确需保留时登记进 REPO_WIDE_SCAN_LEDGER 并写明为何预筛不适用。"
        )

    def test_ledger_has_no_stale_entries(self):
        """台账里不得有已经不存在命中点的条目（清了扫描要同步销账）。"""
        live = {}
        for rel in protectedFiles():
            path = PROJECT_ROOT / rel
            if not path.is_file() or not rel.endswith(".py"):
                continue
            try:
                source = io.open(path, encoding="utf-8", errors="ignore").read()
                hits = _repoWideAstScans(source)
            except SyntaxError:
                continue
            if hits:
                live[rel] = hits
        stale = sorted(set(REPO_WIDE_SCAN_LEDGER) - set(live))
        assert not stale, f"台账登记了已不存在的全仓扫描：{stale}"


class TestDetectionSurfaceCoversHelpersNotJustTestNames:
    """检测面必须覆盖 helper：全仓扫描常被放进 helper，`test_x` 只是它的壳。

    根因（Issue #197 批遗留的同根剩余形态）：本门禁原先只认函数名以 `test`
    开头的落点。于是
    `tests/unit/api/test_orphan_faces_retired_guard.py::_references`（一个
    `_` 前缀的 helper，被 `test_no_reference_remains` 调用）**照旧全仓
    `rglob` + `ast.parse`**——成本照付（单次 5.2s，随仓库规模线性涨），
    门禁却看不见它。判据与它要守的事实（"不得与代码总量捆绑"）之间，
    差的就是这一个盲区。
    """

    def test_helper_holding_the_scan_is_reported(self):
        """反向锁：把扫描挪进 helper，检测仍必须报出它。"""
        source = (
            "def _scan():\n"
            "    import ast\n"
            "    return [ast.parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
            "\n\n"
            "def test_calls_it():\n"
            "    assert _scan() == []\n"
        )
        hits = _repoWideAstScans(source)
        assert "_scan" in hits, (
            f"helper 里的全仓扫描没被报出：{hits}"
            "（检测面退回「只认 test* 函数名」即红）"
        )
        assert "test_calls_it" in hits, (
            f"调用侧壳函数没被一并点名：{hits}"
            "（报错只指 helper 时，读者会以为把 helper 改掉即可，"
            "而真正付出成本的是每条调用路径）"
        )

    def test_module_level_scan_is_reported(self):
        """模块级的全仓扫描同样报出（它连函数壳都没有）。"""
        source = (
            "import ast\n"
            "TREES = [ast.parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["<模块级>"], (
            f"模块级全仓扫描没被报出：{_repoWideAstScans(source)}"
        )

    def test_script_local_scan_without_repo_root_is_not_reported(self):
        """单文件解析不算全仓扫描（否则门禁会因假阳性而失去区分力）。"""
        source = (
            "import ast\n"
            "def test_one_file():\n"
            "    return ast.parse(SOURCE.read_text())\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"单文件解析被误报成全仓扫描：{_repoWideAstScans(source)}"
        )


class TestDetectionSurfaceCoversEveryJudgedShape:
    """检测面必须覆盖**每一种**「枚举 + 解析」形态，而不是某一种字面组合。

    根因（Issue #197 批上轮未闭环第 2 条）：本门禁原先只认 `rglob` + `parse`
    两个**调用名**同处一处的写法。于是同一根因的其它形态 —— `os.walk` 展开整棵树、
    `import ast as _ast` 之后再解析 —— 照旧全仓扫，门禁一个字都不说。
    与上一轮补的 helper 盲区是同一件事的两半：**判据的靶点是「成本随代码总量涨」，
    不是「源码里恰好写了这两个名字」**。

    反向锁同样重要（假阳性会训练人忽略门禁）：解析**单个函数自己的源码**
    （`ast.walk(ast.parse(obj.getsource(func)))`）不是全仓扫描；文件名恰好叫
    `walk` 的本地函数不是标准库那一个；`tests/ast_scan` 的共享预算入口
    （`_cachedParse`）正是本门禁推荐的修法，不得反被它报出来。
    """

    def test_os_walk_enumeration_is_reported(self):
        source = (
            "import ast, os\n"
            "def test_x():\n"
            "    for root, dirs, files in os.walk('neurova'):\n"
            "        ast.parse(open(root).read())\n"
        )
        assert _repoWideAstScans(source) == ["test_x"], (
            f"`os.walk` 展开整棵树 + 解析没被报出：{_repoWideAstScans(source)}"
            "（检测面只认 `rglob` 字面名即红）"
        )

    def test_aliased_ast_module_is_reported(self):
        source = (
            "import ast as _ast\n"
            "def _scan():\n"
            "    return [_ast.parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"`import ast as _ast` 之后的解析漏报：{_repoWideAstScans(source)}"
        )

    def test_iterdir_enumeration_is_reported(self):
        source = (
            "import ast\n"
            "def test_x():\n"
            "    return [ast.parse(p.read_text()) for p in ROOT.iterdir()]\n"
        )
        assert _repoWideAstScans(source) == ["test_x"], (
            f"`iterdir` 枚举 + 解析漏报：{_repoWideAstScans(source)}"
        )

    def test_enumeration_and_parse_split_across_a_call_chain(self):
        """枚举与解析分处两层 helper：**发起枚举的那个落点**必须报出。

        只认「同一函数体里两个名字同现」的写法会漏掉这种拆法 —— 而它照样把
        代码总量编码成时间上界（枚举了一层树、又逐文件解析）。
        纯解析的 helper 本身不是扫描落点，不得被误报（假阳性会训练人忽略门禁）。
        """
        source = (
            "import ast\n"
            "def _inner(p):\n"
            "    return ast.parse(p.read_text())\n"
            "\n\n"
            "def _outer():\n"
            "    return [_inner(p) for p in ROOT.rglob('*.py')]\n"
            "\n\n"
            "def test_calls_it():\n"
            "    assert _outer() is None or True\n"
        )
        hits = _repoWideAstScans(source)
        assert "_outer" in hits, (
            f"跨层拆分的扫描没被报出：{hits}（只认同处一处即红）"
        )
        assert "_inner" not in hits, (
            f"只做解析、不做枚举的 helper 被误报：{hits}"
            "（报出纯解析 helper 会让门禁失去区分力）"
        )

    def test_walking_a_single_function_source_is_not_reported(self):
        """解析**单个函数自己的源码**不是全仓扫描（否则门禁会把合规写法报红）。"""
        source = (
            "import ast\n"
            "import inspect\n"
            "def test_x():\n"
            "    return ast.walk(ast.parse(inspect.getsource(func)))\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"单函数源码被误报成全仓扫描：{_repoWideAstScans(source)}"
        )

    def test_local_function_named_walk_is_not_reported(self):
        """本地定义的 `walk` 不是标准库那一个，不得据此判成枚举。"""
        source = (
            "import ast\n"
            "def walk(node):\n"
            "    return [node]\n"
            "\n\n"
            "def test_x():\n"
            "    return walk(ast.parse('X = 1'))\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"同名本地函数被误判成文件系统枚举：{_repoWideAstScans(source)}"
        )

    def test_shared_budget_entries_are_not_reported(self):
        """本门禁推荐的修法（调用 `tests/ast_scan` 的共享预算入口）不得反被报红。

        两臂都要钉：

        - 走 `ast_scan.nodeScan(hints=...)` 的合规写法（真实样本：
          `tests/unit/test_dev_path_and_runtime_dep_guards.py::test_no_shell_out_to_ripgrep`）
          必须零命中 —— 否则门禁把推荐修法报红，等于逼人绕开共享预算；
        - 但这不能变成免检通道：**自己**枚举后逐文件 `ast.parse` 仍须报出。
        """
        viaBudget = (
            "from tests import ast_scan\n"
            "def test_x():\n"
            "    for path, node in ast_scan.nodeScan(ROOT, hints=('x',)):\n"
            "        assert node is not None\n"
        )
        assert _repoWideAstScans(viaBudget) == [], (
            f"走共享预算的合规写法被误报：{_repoWideAstScans(viaBudget)}"
            "（门禁把推荐的修法报红，等于逼人绕开它）"
        )
        privateScan = (
            "from tests import ast_scan\n"
            "import ast\n"
            "def test_x():\n"
            "    for path in ast_scan.filesUnder(ROOT, '.py'):\n"
            "        ast.parse(path.read_text())\n"
        )
        assert _repoWideAstScans(privateScan) == ["test_x"], (
            f"共享预算入口成了免检通道：自己枚举后私有解析未被报出"
            f"（{_repoWideAstScans(privateScan)}）"
        )

    def test_shared_budget_module_itself_is_not_reported(self):
        """`tests/ast_scan.py` 自身不得被报红：它**就是**共享预算的实现。"""
        source = io.open(
            ast_scan.__file__, encoding="utf-8").read()
        assert _repoWideAstScans(source) == [], (
            f"共享预算实现自身被误报：{_repoWideAstScans(source)}"
            "（把预算实现报成违规，门禁就会逼人绕开它）"
        )


class TestDetectionSurfaceCoversCompileFamily:
    """解析面必须覆盖 `compile` 家族，而不是只认 `ast.parse` 两个字面名。

    根因（Issue #197 批上轮自陈的未闭环第 2 条）：`_repoWideAstScans` 的解析面
    只认 `<ast 别名>.parse` 与裸 `parse`。同一件事的其它写法照旧全仓扫、成本照旧
    随代码总量涨，门禁却一个字都不说：

    - `compile(source, filename, mode, flags=ast.PyCF_ONLY_AST)`（标准库的另一条
      解析入口，`builtins.compile` 即它）；
    - `import builtins as _bi` 之后的 `_bi.compile(...)`；
    - `py_compile.compile(...)` / `compileall.compile_dir(...)`（把文件编译成
      语法树/字节码，成本同样随代码总量涨）；
    - `from ast import parse as p` 之后的裸 `p(...)`。

    判据的靶点仍是「枚举 + 解析**同现**」（成本随代码总量涨），不是「源码里恰好
    写了哪个调用名」。故反向锁与正向锁成对：`re.compile(...)` 与本地同名函数
    **不得**被报出 —— 受保护子集里「枚举 + 正则」的文件有一批，误报会让门禁
    失去区分力，正是上一轮「口径扩大需各自的实证样本」这句话要防的。
    """

    def test_builtin_compile_with_pycf_flag_is_reported(self):
        """`compile(..., PyCF_ONLY_AST)` 与 `ast.parse` 是同一件事，必须同判。"""
        source = (
            "import ast\n"
            "def test_x():\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        compile(p.read_text(), str(p), 'exec', ast.PyCF_ONLY_AST)\n"
        )
        assert _repoWideAstScans(source) == ["test_x"], (
            f"`compile(..., PyCF_ONLY_AST)` 没被报出：{_repoWideAstScans(source)}"
            "（解析面只认 `ast.parse` 字面名即红）"
        )

    def test_bare_compile_is_reported(self):
        """裸名 `compile(...)`（内建）即 `compile(..., PyCF_ONLY_AST)` 的同一条链。"""
        source = (
            "def _scan():\n"
            "    return [compile(p.read_text(), str(p), 'exec')\n"
            "            for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"裸名 `compile(...)` 漏报：{_repoWideAstScans(source)}"
        )

    def test_aliased_builtins_compile_is_reported(self):
        """`import builtins as _bi` 之后的 `_bi.compile(...)` 同为解析落点。"""
        source = (
            "import builtins as _bi\n"
            "def _scan():\n"
            "    return [_bi.compile(p.read_text(), str(p), 'exec')\n"
            "            for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"`builtins` 别名后的 `compile` 漏报：{_repoWideAstScans(source)}"
        )

    def test_py_compile_helper_is_reported(self):
        """`py_compile.compile(...)` 逐文件编译，成本同样随代码总量涨。"""
        source = (
            "import py_compile\n"
            "def test_x():\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        py_compile.compile(str(p), doraise=True)\n"
        )
        assert _repoWideAstScans(source) == ["test_x"], (
            f"`py_compile.compile` 漏报：{_repoWideAstScans(source)}"
        )

    def test_aliased_parse_import_is_reported(self):
        """`from ast import parse as p` 之后的裸 `p(...)` 就是解析原语本身。"""
        source = (
            "from ast import parse as astParse\n"
            "def _scan():\n"
            "    return [astParse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"`from ast import parse as ...` 之后的裸名漏报：{_repoWideAstScans(source)}"
        )

    def test_re_compile_is_not_reported(self):
        """`re.compile` 与「解析源码」无关：按调用名判会把「枚举 + 正则」全报红。"""
        source = (
            "import re\n"
            "def test_x():\n"
            "    pattern = re.compile('def ')\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        assert pattern.search(p.read_text()) is not None\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"`re.compile` 被误报成解析落点：{_repoWideAstScans(source)}"
            "（受保护子集里这类文件有一批，误报即门禁失效）"
        )

    def test_compile_imported_from_other_module_is_not_reported(self):
        """`from re import compile` 之后的裸 `compile(...)` 是正则，不是解析。"""
        source = (
            "from re import compile\n"
            "def test_x():\n"
            "    pattern = compile('def ')\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        assert pattern.search(p.read_text()) is not None\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"被非解析模块 import 遮蔽的裸名被误报：{_repoWideAstScans(source)}"
        )

    def test_local_function_named_compile_is_not_reported(self):
        """本地 `def compile` 不是内建那一个，不得据此判成解析。"""
        source = (
            "def compile(source):\n"
            "    return source\n"
            "\n\n"
            "def test_x():\n"
            "    return [compile(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"同名本地函数被误判成解析原语：{_repoWideAstScans(source)}"
        )

    def test_shadow_scope_is_per_unit_not_whole_file(self):
        """遮蔽要按**作用域**判：别处函数里的同名局部量不得遮住本文件的解析原语。

        整文件级遮蔽是**假阴性面**：一个 helper 里恰好有个局部 `def parse`，
        另一个 helper 的全仓 `rglob` + `parse(...)` 就会被无声放行。
        """
        source = (
            "def _helper():\n"
            "    def parse(text):\n"
            "        return text\n"
            "    return parse('x')\n"
            "\n\n"
            "def _scan():\n"
            "    return [parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"别处的同名局部量把解析原语遮住了（假阴性）：{_repoWideAstScans(source)}"
        )

    def test_own_scope_shadow_still_suppresses_the_bare_name(self):
        """本作用域内真的重绑了该名字时，裸名调用不是解析原语（不报）。"""
        source = (
            "def parse(text):\n"
            "    return text\n"
            "\n\n"
            "def test_x():\n"
            "    return [parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"本作用域重绑的裸名被当成解析原语：{_repoWideAstScans(source)}"
        )

    def test_module_scope_shadow_does_not_leak_into_a_manager_by_default(self):
        """类体不是作用域：类里的 `compile = ...` 不得遮住模块级的解析原语。

        `class C: compile = None` 之后模块级仍可用内建 `compile`；把它当成
        遮蔽会造出假阴性面。
        """
        source = (
            "class Widget:\n"
            "    compile = None\n"
            "\n\n"
            "def _scan():\n"
            "    return [compile(p.read_text(), str(p), 'exec')\n"
            "            for p in ROOT.rglob('*.py')]\n"
        )
        assert _repoWideAstScans(source) == ["_scan"], (
            f"类属性把模块级解析原语遮住了（假阴性）：{_repoWideAstScans(source)}"
        )

    def test_same_named_functions_do_not_share_a_shadow_set(self):
        """同名函数（不同作用域）各判各的遮蔽，不得互相串味。

        把遮蔽按**函数名**建表会在同名处撞键：一个 `_scan` 里有局部 `parse`、
        另一个 `_scan` 里全仓 `rglob` + `parse(...)`，后者会被前者遮住而无声放行。
        """
        source = (
            "def _scan():\n"
            "    def parse(text):\n"
            "        return text\n"
            "    return parse('x')\n"
            "\n\n"
            "class Wrapper:\n"
            "    def _scan(self):\n"
            "        return [parse(p.read_text()) for p in ROOT.rglob('*.py')]\n"
        )
        hits = _repoWideAstScans(source)
        assert "Wrapper._scan" in hits, (
            f"同名嵌套函数被外层同名函数的遮蔽串味：{hits}"
        )

    def test_detector_scans_each_file_in_a_bounded_number_of_passes(self):
        """检测面自身的成本不得随**判据种类数**膨胀：每文件只走有限趟。

        这是同一条根因的镜像：门禁自己也在受保护子集里（它被登记了），
        若每多认一种解析模块就多 `ast.walk` 一趟，那么「检测面越宽、门禁越慢」
        —— 判据成本又一次随**代码总量 × 判据种类**增长。故口径表
        （`PARSE_MODULE_ATTRS`）必须**一趟收齐**，不得按模块逐个重扫。
        """
        source = (
            "import ast, builtins, os, re\n"
            "def test_x():\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        ast.parse(p.read_text())\n"
        )
        calls = {"n": 0}
        realWalk = ast.walk

        def countingWalk(node):
            calls["n"] += 1
            return realWalk(node)

        ast.walk = countingWalk
        try:
            _repoWideAstScans(source)
        finally:
            ast.walk = realWalk
        assert calls["n"] <= 3, (
            f"检测面按模块逐个重扫（`ast.walk` 走了 {calls['n']} 趟）："
            "口径表要一趟收齐；否则每扩一种解析写法，门禁自身成本就再涨一档。"
        )

    def test_third_party_parser_modules_are_reported(self):
        """第三方解析器与标准库同契约：枚举文件后逐份解析，成本照样随代码总量涨。

        只在**该模块真被 import** 时才算（别名表口径），故不构成假阳性面；
        仓内当前无这些依赖，本判据是前瞻锁：一旦有人引入即被点名。
        """
        cases = {
            "import parso\n": "parso.parse(p.read_text())\n",
            "import libcst\n": "libcst.parse_module(p.read_text())\n",
            "import astroid\n": "astroid.parse(p.read_text())\n",
        }
        for header, call in cases.items():
            source = (
                header
                + "def _scan():\n"
                + "    for p in ROOT.rglob('*.py'):\n"
                + "        " + call
            )
            assert _repoWideAstScans(source) == ["_scan"], (
                f"第三方解析器漏报：{header.strip()} -> {_repoWideAstScans(source)}"
            )

    def test_third_party_mention_without_import_is_not_reported(self):
        """只提名字、没 import：不是解析落点（模块别名口径的必然结果）。"""
        source = (
            "def test_x():\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        assert 'parso.parse' not in p.read_text()\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"文本提及被当成解析落点：{_repoWideAstScans(source)}"
        )

    def test_unrelated_module_compile_attribute_is_not_reported(self):
        """`widget.compile(...)` 不落在任何解析模块别名上，不得报出。"""
        source = (
            "import widget\n"
            "def test_x():\n"
            "    for p in ROOT.rglob('*.py'):\n"
            "        widget.compile(p.read_text())\n"
        )
        assert _repoWideAstScans(source) == [], (
            f"无关模块的同名方法被误报：{_repoWideAstScans(source)}"
        )


class TestTextCacheIsOnTheHotPath:
    """跨判据复用的文本缓存必须真被热路径读到（写了不读 = 断点）。

    根因（同根新命中点）：`sourceRefsUnder` 一度**绕开**本模块自己的
    `_cachedCode`，逐次 `path.read_text()`。于是「同进程里 N 个跨文件判据
    只读盘一次」是纸面承诺 —— 实测 20 个登记符号读盘 **20140 次**
    （生产树里只有 1007 个文件）。读写同源一处定义，却只有写侧（缓存）
    没有读侧（消费），正是协作红线点名的断点。
    """

    def test_sourceRefsUnder_reuses_the_text_cache(self, tmp_path):
        for i in range(3):
            (tmp_path / f"m{i}.py").write_text(f"V{i} = {i}\n", encoding="utf-8")
        ast_scan._cachedCode.cache_clear()
        ast_scan.sourceRefsUnder(tmp_path, hints=("V0",))
        info = ast_scan._cachedCode.cache_info()
        assert info.misses == 3, (
            "`sourceRefsUnder` 没走 `_cachedCode`：它把每份源码都重新读盘一次，"
            f"文本缓存形同不存在（实测 misses={info.misses}，应为文件数 3）。\n"
            "修法：`sourceRefsUnder` 用 `_cachedCode(_cacheKey(path))` 取文本，"
            "与 `sourceCode` 同源。"
        )

    def test_repeated_hint_scans_read_each_file_once(self, tmp_path):
        for i in range(4):
            (tmp_path / f"m{i}.py").write_text(f"TARGET_{i} = {i}\n", encoding="utf-8")
        ast_scan._cachedCode.cache_clear()
        for hint in ("TARGET_0", "TARGET_1", "TARGET_2", "TARGET_3"):
            ast_scan.sourceRefsUnder(tmp_path, hints=(hint,))
        info = ast_scan._cachedCode.cache_info()
        assert info.misses == 4, (
            "同一棵树被 4 个判据各读一遍：读盘次数随**判据数**增长而不是随"
            f"**文件数**收敛（实测 misses={info.misses}，应为 4）。"
        )


class TestRelativeToRepoIsMemoized:
    """`relativeToRepo` 必须按路径记忆化：调用次数不得与**节点数**挂钩。

    根因：调用方（如 `context_deadline_ledger._rawNodes`）在**逐节点**的循环里
    调它，`Path.relative_to` 每次都要重新解析路径（实测 249547 次调用 ≈ 2.2s，
    占该取数整体耗时的一半）。

    收口点必须在**共享源**：若只在某个消费方加一层镜像缓存，别的消费方
    （`tests/unit/llm/test_capability_cache_single_source.py` 等也逐节点取它）
    照样按节点付账 —— 那是 consumer-only guard 的形态。
    """

    def test_same_path_is_computed_once(self):
        target = ast_scan.REPO_ROOT / "tests" / "ast_scan.py"
        ast_scan.relativeToRepo.cache_clear()
        calls = {"n": 0}
        real = Path.relative_to

        def counting(self, *args, **kwargs):
            calls["n"] += 1
            return real(self, *args, **kwargs)

        Path.relative_to = counting
        try:
            for _ in range(50):
                ast_scan.relativeToRepo(target)
        finally:
            Path.relative_to = real
        assert calls["n"] == 1, (
            f"同一路径调 50 次却算了 {calls['n']} 次相对路径——未记忆化，"
            "调用方一旦在逐节点循环里用它，耗时即与节点数成正比。"
        )

    def test_call_count_does_not_track_node_count(self):
        """反向控制：**节点数**涨时，`relativeToRepo` 调用次数不得涨。"""
        path = ast_scan.REPO_ROOT / "neurova" / "context" / "orchestrator.py"
        nodes = list(ast_scan._cachedNodes(ast_scan.SourceRef(
            path, ast_scan._cacheKey(path), ast_scan.sourceCode(path))))
        assert len(nodes) > 1000, f"夹具节点数太少（{len(nodes)}），判不出随节点增长"

        ast_scan.relativeToRepo.cache_clear()
        seen = []
        real = Path.relative_to

        def counting(self, *args, **kwargs):
            seen.append(self)
            return real(self, *args, **kwargs)

        Path.relative_to = counting
        try:
            for _ in nodes:
                ast_scan.relativeToRepo(path)
        finally:
            Path.relative_to = real
        assert len(seen) == 1, (
            f"{len(nodes)} 个节点调了 {len(seen)} 次相对路径——调用次数随节点数增长，"
            "正是墙钟超时的来源（缓存清空后，同一路径只该真实计算一次）。"
        )


class TestSharedParseBudgetIsReal:
    """共享预算入口必须真能用，否则各守卫会退回各写一套（门禁空转）。"""

    def test_helper_surface_exists(self):
        for name in ("callSites", "importsOf", "classDefsIn", "nodeScan",
                     "sourceRefsUnder", "relativeToRepo", "filesUnder"):
            assert hasattr(ast_scan, name), (
                f"tests/ast_scan.py 未提供 {name}：跨文件判据没有共享入口，"
                "本门禁会退化成一条空规则。"
            )

    def test_prefilter_is_sufficient_not_a_loophole(self, tmp_path):
        """预筛是**充分条件**：命中必定在，未命中的文件确实不含关键词。

        反向控制：注入一个真实命中（含关键词）必须被报出；同时确认
        `sourceRefsUnder` 的预筛**只**按关键词缩面，不是把所有文件都丢掉。
        """
        (tmp_path / "hit.py").write_text(
            "def f(x):\n    return x.attest()\n", encoding="utf-8")
        (tmp_path / "miss.py").write_text(
            "def g(x):\n    return x.other()\n", encoding="utf-8")

        hits = ast_scan.callSites(tmp_path, "attest")
        assert [path.name for path, _line in hits] == ["hit.py"], (
            f"预筛漏掉了真实命中或放行了未命中文件：{hits}"
        )
        assert {ref.path.name for ref in ast_scan.sourceRefsUnder(tmp_path, hints=("attest",))} \
            == {"hit.py"}, "文本预筛口径失效（应只留下一处含关键词的文件）"

    def test_class_defs_helper_finds_top_level_only(self, tmp_path):
        """`classDefsIn` 只认顶层类定义：嵌套同名类不算「另一份实现」。"""
        (tmp_path / "mod.py").write_text(
            "class Probe:\n    pass\n\n\ndef f():\n    class Probe:\n        pass\n",
            encoding="utf-8")
        hits = ast_scan.classDefsIn(tmp_path, "Probe")
        assert [line for _path, line in hits] == [1], (
            f"`classDefsIn` 应只认顶层定义，实际：{hits}"
        )

    def test_imports_helper_ignores_mentions_in_strings_and_comments(self, tmp_path):
        """判据是 `import` 语句：字符串/注释里提一句不算引用。"""
        (tmp_path / "mention.py").write_text(
            '# import neurova.performance\n'
            'NOTE = "neurova.performance"\n',
            encoding="utf-8")
        (tmp_path / "real.py").write_text(
            "import neurova.performance\n", encoding="utf-8")
        hits = ast_scan.importsOf(
            ast_scan.nodeScan(tmp_path, hints=("neurova.performance",)),
            "neurova.performance")
        assert [path.name for path, _line in hits] == ["real.py"], (
            f"`importsOf` 把文本提及当成了引用（假阳性）或漏了真实 import：{hits}"
        )


class TestSharedBudgetIsReusedWithinOneProcess:
    """同进程内 N 个判据扫同一棵子树，解析只付一次（这正是「预算」的含义）。"""

    def test_repeated_scan_hits_the_cache(self, tmp_path):
        (tmp_path / "a.py").write_text("def f(x):\n    return x.attest()\n", encoding="utf-8")
        ast_scan.callSites(tmp_path, "attest")
        before = ast_scan._cachedNodes.cache_info()
        ast_scan.callSites(tmp_path, "attest")
        after = ast_scan._cachedNodes.cache_info()
        assert after.hits > before.hits, (
            "第二次扫描没有命中节点缓存——「跨用例复用一次解析」不成立，"
            "本预算就成了纸面承诺。"
        )


@pytest.mark.parametrize("rel", [
    "tests/unit/knowledge/test_write_boundary_closes_verification.py",
    "tests/unit/core/test_dead_cache_module_removed.py",
    "tests/unit/evolution/rsi/test_rsi_observation_surface.py",
    "tests/unit/evolution/rsi/test_rsi_rollback_evidence.py",
    "tests/unit/llm/test_capability_cache_single_source.py",
    "tests/unit/test_ci_thin_env_guards.py",
    "tests/unit/test_dev_path_and_runtime_dep_guards.py",
    "tests/unit/api/test_orphan_faces_retired_guard.py",
])
def test_known_hit_points_use_the_shared_budget(rel):
    """本次收口的命中点必须一直用共享预算（改回全仓 rglob+parse 即红）。"""
    source = io.open(PROJECT_ROOT / rel, encoding="utf-8").read()
    assert "ast_scan" in source, (
        f"{rel} 不再使用 tests/ast_scan.py 的共享解析预算——"
        "跨文件 AST 判据又各写一套，Issue #148 的根因会回来。"
    )
    assert not _repoWideAstScans(source), (
        f"{rel} 又出现了 rglob + ast.parse 的同用例组合：{_repoWideAstScans(source)}"
    )
