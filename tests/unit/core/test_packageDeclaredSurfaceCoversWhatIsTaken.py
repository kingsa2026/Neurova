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
批 49 修 5 个包（`llm.providers` 6、`memory` 补 2、`cognitive` 补 1、`api.endpoints.memory`
补 `router`，另 `admin` 明写 3 个公开面但那 3 名原本不在隐式面里），其余 **8 个包 44 个名字**
进登记表逐条给理由。（批 49 建档时把这条写成"7 个包 45 个名字"——本批在 `b6d45de6^` 的仓外
工作树上用**同一把尺**重算得 44，勘误见 §6-224；那句"12 包 54 名"复核为真。）

批 50（§6-224）按档案票二**甲案**把这张登记表清零：8 个包逐个补 `__all__`，登记表收成
`{}` 并加一条零容忍格。清零之后，这条根因两侧都收完了——供给面（批 46/47/48）与声明面（本档）。

补 `__all__` 是**机械、零行为变更**那一案，前提两条都现读过：全仓跟踪 `.py` 里
`from X import *` **0 处**（3422 档一次扫），且没有任何生产代码**读** `__all__` 来决定注册
（读它的只有判据与活体档）。真正被推后的那是乙案——把实现从 `__init__.py` 挪出去。

登记表那 8 个包的实状也不该沿用建档时那句笼统的"全是实现写在门面里"：现算是 **6 包实现在
`__init__.py`**（`api/endpoints` 368 行、`computer_use` 701、`execution_layers` 706、
`image_pipeline` 382、`memory_ingest/converters` 23、`skills/builtin` 81），另 **2 包是纯再导出门面**
（`execution_engine` 69 行、`cognitive_layers/memory_layer` 的那个名字来自第 38 行的再导出）。
`execution_engine` 那一包在划契约前必须先修一处：它的再导出包在 `try/except ImportError` 里，
而 handler 里定义了**九个同名空桩**（八枚只有 docstring，`ToolStatus` 那枚另抄了四份状态常量）——
被包的 `tool_engine` 模块级闭包只碰 stdlib 与本仓，按批 43 已裁口径这条兜底永不可达。
给一个假门面划公开面＝把谎写进契约，故本批先摘桩、再声明。

三条排除口径（都不是放过，是另一件事）：

- **子模块名**（`import neurova.agent_core` 之后 `neurova.agent_core.X`、
  `from neurova.api.endpoints.memory import crud`）：取的是子模块本身，列不列进 `__all__`
  都取得到；要列就得每加一个子模块改一次契约，漏改即假红。第一版只把"本包 `from . import x`
  绑到的那些"当子模块，漏掉这条，于是 `neurova.agent_core` 与 `__version__` 一起被误报。
- **下划线名**（`__version__` 这类模块级约定、`_logger` 这类私有名）：`__all__` 管的是
  `from pkg import *` 的可见集，双下划线名本来就不参与。
- **非证据文件的取用**（批 50 加）：消费者表按工作树走，而工作树里有 `.gitignore` 豁免掉的散件
  （本仓实测 `.tmp_auth_bak.py` 就在取 `api.endpoints.get_app_state`）。这类文件**到不了 CI，
  也到不了别人的机器**，把它们当"有人在取"会让同一格在两台机器上给出不同读数——登记表清零之后
  这条更危险：读数差一个名字就是红。故取用面只认「已跟踪 ∪ 未跟踪但未被忽略」。

`__all__` 也不许写空话：第二格钉"声明了的名字本包必须真给得出"，堵"往契约里塞一个不存在的
名把判据喂绿"这条后门（与 §6-212 那条"通用名不得进 `__all__`"同族）。给得出的四条形：
包级 import（含顶层 `try:` 体里的可选依赖导入）、模块层赋值与类/函数定义、子模块、
以及**静态证不了**的动态供给（PEP 562 `__getattr__`、模块层 `globals()[name] = ...`）——
最后一形本格对该包放过，是口径边界，不是没看见。
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

from tests import ast_scan

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 批 50 之前"承认暂时隐式"的那 8 包 44 名。登记表清零后它换了一个身份：**票二甲的交付清单**，
#: 由最后一条格按**导入后的真对象**复核（不是读文本）——名字既得进 `__all__`，又得真从包上取到，
#: 免得补契约时手抖漏一个还能全绿。
EXPECTED_FACES: dict = {  # type: ignore[type-arg]
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

#: 隐式公开面的**豁免台账**。批 50 起为零——票二甲案已把当时全部的 8 包 44 名补进 `__all__`。
#: 留空不是"没有存量"的口头话，而是第一条格咬着的**零容忍政策**：将来新长出一个隐式公开面，
#: 出路只有「补 `__all__`」或「改直取子模块」两种；往这里登记一行＝替人补裁，同一格会红。
IMPLICIT_SURFACE: dict = {}  # type: ignore[type-arg]


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
    for rel in [p for p in ast_scan.trackedPaths()
                if p.startswith("neurova/") and p.endswith("__init__.py")]:
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
def evidencePaths() -> frozenset:
    """「证据面」＝已跟踪 ∪ 未跟踪但未被 `.gitignore` 豁免的仓内文件。

    为什么不含被忽略的散件：那些文件到不了 CI，也到不了别人的机器。把它们算成消费者，
    同一条格就会在两处给出不同读数（本仓实测 `.tmp_auth_bak.py` 正在取 `get_app_state`）。
    """
    return frozenset(list(ast_scan.trackedPaths()) + ast_scan.untrackedNotIgnoredPaths())


def pruneNonEvidence(table: dict, evidence: frozenset) -> dict:
    """把消费者表里落在证据面之外的取用剔掉；剔空的名字整条消失（纯函数，第四/五格按形状钉它）。"""
    out = {}
    for mod, names in table.items():
        for name, places in names.items():
            keep = [p for p in places if p[0] in evidence]
            if keep:
                out.setdefault(mod, {})[name] = keep
    return out


@functools.lru_cache(maxsize=1)
def _scan() -> dict:
    """全仓"谁从哪个模块取了哪个名字"一张表，跑一次给所有格共用（只认证据面）。"""
    return pruneNonEvidence(ast_scan.takenPerModule(PROJECT_ROOT), evidencePaths())


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
    tracked = ast_scan.trackedPyPaths()
    assert len(tracked) >= 3000, f"扫描面现读 {len(tracked)} 个 .py，地板 3000 被打破"
    assert _scan(), "消费者表是空的——那是『没人取用』的假绿，不是全绿"
    # 登记表清零后，"扫出来一片空"与"确实干净"两种读法都让第一条格绿 ⇒ 规模必须有地板。
    # 数取本批复算的现值（消费者 5356 名 / 93908 处），只留下限不上限。
    taken = sum(len(v) for v in _scan().values())
    assert taken >= 5000, f"消费者表现读 {taken} 个（模块,名字）对，地板 5000 被打破＝取数面塌了"


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


def test_theExemptionLedgerIsStillEmpty():
    """零容忍格：隐式公开面的豁免台账不许再长行（这条是政策，不是存量表）。

    批 50 之前这里躺着 8 包 44 名；清零之后，新长出一个隐式公开面的两种正当出路是
    「补 `__all__`」与「改直取子模块」。**登记一行**看起来也能让第一条格绿，但那等于
    把"这个包的公开面是什么"这件本来要人拍板的事，由写代码的人在判据里替他拍了。
    """
    assert not IMPLICIT_SURFACE, (
        "隐式公开面豁免台账被人加行了。要么把名字补进那包的 `__all__`（票二甲的做法），"
        f"要么让取用方直取子模块；实得 {IMPLICIT_SURFACE}")


def test_scratchFilesOutsideTheEvidenceFaceAreNotConsumers():
    """证据面正反两头：被 `.gitignore` 豁免的散件不算"有人在取"，跟踪文件里的取用照算。

    没有这一格，登记表清零之后的读数就取决于谁的机器上躺着哪个 `.tmp_*.py`——
    同一条格在我机器上红、在 CI 上绿，那种红既不是回归也修不掉。
    """
    evidence = frozenset({"neurova/live.py", "tests/unit/live_test.py"})
    table = {
        "neurova.pkg": {
            "Live": [("neurova/live.py", 9)],
            "ScratchOnly": [(".tmp_auth_bak.py", 208)],
            "Mixed": [(".tmp_auth_bak.py", 7), ("tests/unit/live_test.py", 3)]},
    }
    pruned = pruneNonEvidence(table, evidence)
    assert "Live" in pruned["neurova.pkg"], "跟踪文件里的取用被剔掉了（探测器过窄）"
    assert "ScratchOnly" not in pruned["neurova.pkg"], (
        "只被 ignored 散件取用的名字仍算消费者——那会让同一条格在两台机器上给不同读数")
    assert pruned["neurova.pkg"]["Mixed"] == [("tests/unit/live_test.py", 3)], (
        "混合取用没剔净：剩下的必须是证据面内的那几条")
    assert len(evidencePaths()) >= 3000, (
        f"证据面现读 {len(evidencePaths())} 个文件，地板 3000 被打破＝取用面塌了")


def test_theClearedFacesAreDeclaredAndReachableThroughThePackage():
    """票二甲的交付格：那 44 名逐个既在 `__all__` 里、又能从包上真取到对象（读对象不读文本）。"""
    import importlib

    failures = []
    for pkg, names in sorted(EXPECTED_FACES.items()):
        mod = importlib.import_module(pkg)
        declared = set(getattr(mod, "__all__", []) or [])
        failures += [(pkg, n) for n in sorted(names) if n not in declared]
        failures += [(pkg, n) for n in sorted(names & declared)
                     if getattr(mod, n, None) is None]
    assert not failures, (
        f"这些名字该已进包契约且真给得出，实得缺项：{failures[:10]}")


def test_executionEngineReexportsTheRealToolEngineNotStubs():
    """门面划了公开面，就得证它给的是真身——`execution_engine` 曾给的是九个同名空桩。

    建档实状（`neurova/execution_engine/__init__.py:17-69`）：再导出包在 `try/except ImportError`
    里，handler 定义 `ToolEngine`/`ToolParameter`/… 九个**同名空 class**（八枚只有 docstring，
    `ToolStatus` 那枚另抄四份状态常量）。被包的 `tool_engine` 模块级闭包只碰 stdlib 与本仓，
    按批 43 已裁口径这条兜底永不可达；而它一旦真触发（循环导入、路径没装好），调用方拿到的是
    一个"看着像"的空类，比拿到 `None` 更难查——`None` 下一行就炸，空类能一路走下去。
    """
    import importlib

    engine = importlib.import_module("neurova.execution_engine")
    wrong = {}
    for name in sorted(EXPECTED_FACES["neurova.execution_engine"]):
        obj = getattr(engine, name)
        if obj.__module__ != "neurova.execution_engine.tool_engine":
            wrong[name] = obj.__module__
    assert not wrong, (
        f"这些名字不是来自 tool_engine 真身，而是门面 handler 里的桩：{wrong}")
