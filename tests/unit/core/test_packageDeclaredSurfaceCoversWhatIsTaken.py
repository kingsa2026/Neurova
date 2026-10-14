# -*- coding: utf-8 -*-
"""包门面「声明的公开面」必须盖住「真被人经包路径取用的名字」（§6-220，批 49）。

批 46/47/48 修的是门面那条根因的**供给面**（挂了没人取的名字、绑了本文件不用的通用名、
取数口径自身有假死）。这一批评的是**声明面**那一侧：

> 有名字真被人经包路径取用，而包的 `__all__` 里没有它 ⇒ 取的人靠的是运气，不是契约。

这不只是"文档不好看"。§6-210 那一批刚把 45 个"零消费者再导出"从技能门面上摘掉——
那次动手安全，是因为那 45 名确实一个消费者都没有。但"谁在经包路径取这个名"这件事
**今天没有任何一格在钉**：下一次清理只要取数口径稍偏（§6-212 就实测过三种偏法：按别名记账、
不解析相对导入、不认属性读取），就会把一个真有人在用的名字当零消费者删掉，
而那时红的是删除者的判据、绿的是使用者——两边都看不出"契约本来就没写"。

现算（2026-10-15，全仓 3400 余档一次扫）：**12 个包 54 个名字**被经包路径取用而未声明。
本批修 5 个包（`llm.providers` 8、`memory` 补 2、`cognitive` 补 1、`api.endpoints.memory`
补 `router`、`admin` 明写 3 个公开面），其余 7 个包 45 个名字进登记表逐条给理由——
它们全是**实现就写在 `__init__.py` 里**的那一族（`api/endpoints` 368 行、`computer_use` 701、
`execution_layers` 706、`execution_engine`、`image_pipeline` 382…），
给它们定"哪些算公开面"是档案 `facade-reexport-triage-2026-10-15.md` 票二那一次裁定，
不在本批顺手定。

两条排除口径（都不是放过，是另一件事）：

- **子模块名**（`import neurova.agent_core` 之后 `neurova.agent_core.X`、
  `from neurova.api.endpoints.memory import crud`）：取的是子模块本身，列不列进 `__all__`
  都取得到；要列就得每加一个子模块改一次契约，漏改即假红。第一版只把"本包 `from . import x`
  绑到的那些"当子模块，漏掉这条，于是 `neurova.agent_core` 与 `__version__` 一起被误报。
- **下划线名**（`__version__` 这类模块级约定、`_logger` 这类私有名）：`__all__` 管的是
  `from pkg import *` 的可见集，双下划线名本来就不参与。

`__all__` 也不许写空话：第二格钉"声明了的名字本包必须真给得出"，堵"往契约里塞一个不存在的
名把判据喂绿"这条后门（与 §6-212 那条"通用名不得进 `__all__`"同族）。给得出的四条形：
包级 import（含顶层 `try:` 体里的可选依赖导入）、模块层赋值与类/函数定义、子模块、
以及**静态证不了**的动态供给（PEP 562 `__getattr__`、模块层 `globals()[name] = ...`）——
最后一形本格对该包放过，是口径边界，不是没看见。
"""
from __future__ import annotations

import ast
import functools
import subprocess
from pathlib import Path

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 本批承认"暂时隐式"的存量表：包 → 那包里被取用却未声明的名字。
#: **两侧都要相等**——新长出一个名字要红，把某个包补进 `__all__` 之后忘了销行也要红
#: （与 §6-197 那张"落点已消失必须销行"同一手法）。
IMPLICIT_SURFACE: dict = {  # type: ignore[type-arg]
    # ── 以下 7 个包全是"实现写在 __init__.py 里"那一族：哪些名字算公开面＝档案票二那次裁定
    "neurova.api.endpoints": {
        "DEFAULT_AGENT_ID", "ENDPOINT_MODULES", "defaultAgentId", "get_agent_instance",
        "get_app_state", "get_health_checker", "get_llm_client", "get_provider_manager",
        "get_startup_manager", "register_endpoint_routers", "setDefaultAgentId",
        "set_app_state"},
    "neurova.computer_use": {
        "ComputerUseManager", "bind_remote_desktop", "get_active_remote_desktop",
        "get_computer_use_manager", "reset_computer_use_manager", "screen_point_to_screenshot_px",
        "screenshot_px_to_screen_point", "scroll_semantics", "unbind_remote_desktop"},
    "neurova.execution_engine": {
        "ToolCallingContext", "ToolDefinition", "ToolDiscoveryResult", "ToolEngine",
        "ToolInvocation", "ToolParameter", "ToolSelection", "ToolStatus", "ToolVersion"},
    "neurova.execution_layers": {
        "DockerExecutor", "ExecutionResult", "LocalExecutor", "RuntimeFactory", "RuntimeManager",
        "RuntimeType", "get_runtime_manager", "reset_runtime_manager"},
    "neurova.image_pipeline": {
        "BuildStatus", "ImagePipelineManager", "get_image_pipeline_manager"},
    "neurova.cognitive_layers.memory_layer": {"TemperatureEngine"},
    "neurova.skills.builtin": {"create_builtin_skills"},
    "neurova.memory_ingest.converters": {"CONVERTERS"},
}


def _gitLsFiles(*extra: str) -> list:
    """`git ls-files` 取数必须显式 utf-8——本仓路径含中文，缺省走平台码（GBK）当场炸。"""
    out = subprocess.run(["git", "-C", str(PROJECT_ROOT), *extra],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace").stdout
    return [p for p in out.split("\0") if p] if "-z" in extra else out.splitlines()


def submodulesOf(pkgDir: Path) -> set:
    """包目录下真实存在的子模块名（`collector.py` 供的是 `collector`，不带后缀）。"""
    names = {f.stem for f in pkgDir.glob("*.py") if f.stem != "__init__"}
    names |= {d.name for d in pkgDir.iterdir() if d.is_dir() and (d / "__init__.py").exists()}
    return names


def _moduleLevelStatements(tree: ast.AST) -> list:
    """模块层语句，**含顶层 `try:` 体里的那几条**。

    不展开 try 就把 `neurova/cognitive_layers/memory_layer/__init__.py` 那种正当形状
    （可选依赖包在 `try: from .volume_renderer import (...) except ImportError`）读成
    "声明了给不出的名字"——第一版正是这么误报的。展开不放宽判据：那些名字确实绑在本包上。
    """
    out = []
    for node in tree.body:
        if isinstance(node, ast.Try):
            out.extend(node.body)
            out.extend(node.orelse or [])
            out.extend(node.finalbody or [])
        out.append(node)
    return out


def undeclaredFor(supplied: set, subs: set, declared: set, refs: dict, ownInit: str) -> list:
    """一个包的裁决，纯函数——第四/五格按形状正反两头钉它。

    `refs`：`{名字: [(取用所在文件, 行号)]}`（`ast_scan.takenPerModule` 已收好四种取法）。
    报的条件：本包给得出 ∧ 不是子模块 ∧ 不是下划线名 ∧ 不在 `__all__` ∧ 存在**包外**取用。
    """
    out = []
    for name, places in sorted(refs.items()):
        if name not in supplied or name in subs or name in declared:
            continue
        if name.startswith("_"):
            continue
        if any(p[0] != ownInit for p in places):
            out.append((name, [p for p in places if p[0] != ownInit]))
    return out


@functools.lru_cache(maxsize=1)
def _packages() -> dict:
    """`{包名: {"init","bound","defs","all","subs","dynamicSupply"}}`，只看被跟踪的包门面。"""
    found = {}
    for rel in sorted(p for p in _gitLsFiles("ls-files", "-z")
                      if p.startswith("neurova/") and p.endswith("__init__.py")):
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        try:
            tree = ast_scan.transientTree(path)
        except SyntaxError:
            continue
        bound, declared, subs, defs = {}, set(), set(), set()
        pkgDir = path.parent
        for node in _moduleLevelStatements(tree):
            if isinstance(node, ast.ImportFrom) and node.module != "__future__":
                for a in node.names:
                    if a.name == "*":
                        continue
                    bound.setdefault(a.asname or a.name, node.lineno)
                    if node.level > 0 and node.module is None and (
                            (pkgDir / (a.name + ".py")).exists()
                            or (pkgDir / a.name / "__init__.py").exists()):
                        subs.add(a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    bound.setdefault((a.asname or a.name).split(".")[0], node.lineno)
            elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                defs.add(node.name)
            targets = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                       if isinstance(node, ast.Assign)
                       else ([node.target.id]
                             if isinstance(getattr(node, "target", None), ast.Name) else []))
            defs |= set(targets)
            if "__all__" in targets:
                declared |= {e.value for e in getattr(node.value, "elts", [])
                             if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        found[rel[:-len("/__init__.py")].replace("/", ".")] = {
            "init": rel, "bound": bound, "all": declared, "subs": subs, "defs": defs,
            # 动态供给两形，静态证不了供出的是什么：PEP 562 `__getattr__`、模块层
            # `globals()[alias] = importlib.import_module(...)`（`neurova/memory/__init__.py:107`）
            "dynamicSupply": any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__getattr__"
                for n in tree.body) or any(
                isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                and t.value.id == "globals"
                for node in ast.walk(tree)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]))}
    return found


def suppliedNames(info: dict, pkgDir: Path) -> set:
    """这个包"给得出"的名字全集（见模块 docstring 的四条形）。"""
    return set(info["bound"]) | set(info["subs"]) | set(info["defs"]) | submodulesOf(pkgDir)


@functools.lru_cache(maxsize=1)
def _scan() -> dict:
    """全仓"谁从哪个模块取了哪个名字"一张表，跑一次给所有格共用。"""
    return ast_scan.takenPerModule(PROJECT_ROOT)


def undeclaredTakeaways() -> dict:
    """`{包名: {名字: [(文件, 行号)]}}`——本包给得出、被包外取用、却没进 `__all__`。"""
    out = {}
    for pkg, info in _packages().items():
        pkgDir = (PROJECT_ROOT / info["init"]).parent
        for name, places in undeclaredFor(suppliedNames(info, pkgDir),
                                          info["subs"] | submodulesOf(pkgDir),
                                          info["all"], _scan().get(pkg, {}), info["init"]):
            out.setdefault(pkg, {})[name] = places
    return out


def test_implicitSurfaceIsExactlyTheRegisteredOnes():
    """登记表两侧相等：新长出隐式公开面要红，补了 `__all__` 却忘了销行也要红。"""
    got = {pkg: set(names) for pkg, names in undeclaredTakeaways().items()}
    extra = {p: sorted(n - IMPLICIT_SURFACE.get(p, set())) for p, n in got.items()
             if n - IMPLICIT_SURFACE.get(p, set())}
    stale = {p: sorted(IMPLICIT_SURFACE[p] - got.get(p, set()))
             for p in IMPLICIT_SURFACE if IMPLICIT_SURFACE[p] - got.get(p, set())}
    assert not extra and not stale, (
        f"隐式公开面与登记表不符。新长出来的（补 __all__ 或改直取子模块）：{extra}；"
        f"已消失却没销行的（别留过期豁免）：{stale}")


def test_declaredNamesAreActuallySupplyableByThePackage():
    """`__all__` 不许写本包给不出的名字（往契约里塞空名就是把判据喂绿）。"""
    phantoms = []
    for pkg, info in _packages().items():
        if info.get("dynamicSupply"):
            continue     # 动态供给（PEP 562 / globals() 赋值）静态证不了——口径边界，写在注释里
        phantoms += [(pkg, n) for n in sorted(
            info["all"] - suppliedNames(info, (PROJECT_ROOT / info["init"]).parent))]
    assert not phantoms, f"这些包声明了自己给不出的名字：{phantoms[:8]}"


def test_theScanCoversTheTrackedTreeAndThePackageSet():
    """地板格：包集合与扫描集合都不许收窄（与批 22/47 同形）。"""
    pkgs = _packages()
    assert len(pkgs) >= 60, f"包门面数量现读 {len(pkgs)}，历史地板 60 被打破＝口径变了"
    for pkg in ("neurova.llm.providers", "neurova.admin", "neurova.cognitive",
                "neurova.api.endpoints.memory", "neurova.skills"):
        assert pkg in pkgs, f"{pkg} 不在包集合里——取数口径被收窄了"
    tracked = [p for p in _gitLsFiles("ls-files", "-z") if p.endswith(".py")]
    assert len(tracked) >= 3000, f"扫描面现读 {len(tracked)} 个 .py，地板 3000 被打破"
    assert _scan(), "消费者表是空的——那是『没人取用』的假绿，不是全绿"


def test_thePredicateReportsASymbolTakenButNotDeclared():
    """反空转正头：符号名被包外取用而未声明 ⇒ 必报（否则第一条恒真）。"""
    got = undeclaredFor({"Widget"}, set(), set(),
                        {"Widget": [("neurova/other/place.py", 77)]},
                        "neurova/pkg/__init__.py")
    assert [n for n, _p in got] == ["Widget"], f"探测器漏报『隐式公开面』：{got}"


def test_thePredicateIgnoresSubmodulesSelfRefsAndUnderscores():
    """反空转反头：三条排除口径各自都不得顺手放过别的东西。"""
    own = "neurova/api/endpoints/memory/__init__.py"
    supplied = {"crud", "router", "__version__", "_helper"}
    assert undeclaredFor(supplied, set(), set(),
                         {"crud": [(own, 24)]}, own) == [], (
        "包自己那几条 `from . import x` 是路由聚合，不是外部消费者")
    assert undeclaredFor(supplied, {"crud"}, set(),
                         {"crud": [("neurova/elsewhere.py", 5)]}, own) == [], (
        "子模块名被算进契约里了（每加一个子模块就得改一次 __all__，漏改即假红）")
    assert undeclaredFor(supplied, set(), set(),
                         {"__version__": [("start_server.py", 46)]}, own) == [], (
        "双下划线的模块级约定名不该由 __all__ 管")
    assert undeclaredFor(supplied, set(), set(),
                         {"router": [("tests/integration/x.py", 9)]}, own) and \
        [n for n, _ in undeclaredFor(supplied, set(), set(),
                                     {"router": [("tests/integration/x.py", 9)]}, own)] == ["router"], (
        "同一包里的符号名被排除口径一起吞掉了")


def test_adminAndProvidersSurfacesAreDeclaredAsPromise():
    """本批动过的那 5 个包：明写的公开面必须真在包上取得到（行为读数，不是只读文本）。"""
    import importlib

    expected = {
        "neurova.llm.providers": {"AnthropicProvider", "BaseProvider", "ConnectionResult",
                                  "GeminiProvider", "OllamaProvider", "OpenAIProvider",
                                  "OpenCodeProvider", "OpenRouterProvider"},
        "neurova.admin": {"AdminService", "ResourceQuotaManager", "ResourceUsage"},
        "neurova.cognitive": {"Memory"},
        "neurova.api.endpoints.memory": {"router"},
    }
    for pkg, names in expected.items():
        mod = importlib.import_module(pkg)
        assert set(mod.__all__) == names, f"{pkg} 的 __all__ 与本批读数不符：{set(mod.__all__)}"
        missing = [n for n in names if getattr(mod, n, None) is None]
        assert not missing, f"{pkg} 声明了却取不到：{missing}"
    mem = importlib.import_module("neurova.memory")
    for n in ("GraphTraversal", "UnifiedVectorStore"):
        assert n in mem.__all__ and getattr(mem, n, None) is not None, (
            f"neurova.memory 的 {n} 该既在 __all__ 里又真取到")
