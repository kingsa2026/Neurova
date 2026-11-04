"""装配后路由表的取数口径只许一份（§6-401，批 J）。

`tests/route_table.py` 的 docstring 自己写着「遍历只写这一份」。现行 FastAPI 的
`include_router` 不就地摊平子路由，而是往 `routes` 里塞一个惰性包装
（`_IncludedRouter`，带 `original_router`／`include_context`）。于是
`for r in app.routes: r.path` 这种取法两种下场都坏：直接取 `.path` 抛
`AttributeError`，或用 `getattr(r, "path", "")` 兜底时**静默取到近乎空集**。
本仓实测（本档第 2 格把它钉成读数）：同一份装配结果，朴素口径 **7** 条、
单源口径 **877** 条。

判据失明的方向比红更糟：**缺席型断言在空集上恒真**。本批抓到两枚——
- `tests/unit/core/test_steer_queue.py::test_steer_endpoint_registered`
  用朴素口径断"存在"⇒ 常驻假红（端点其实挂着：`/api/v1/console/chat/steer`，
  `endpoints/console.py:1140`，前端 `ChatPage.vue:646` 在调）；
- `tests/unit/api/test_channel_qrcode_generic_endpoints.py::test_legacy_wechat_ilink_routes_removed`
  用同一口径断"不存在"（防复活钉）⇒ **它从来没咬过任何东西**：即便那两个端点被加回来，
  空集里照样找不到。

同根扫荡（教义第 5 条）另收一枚"取数不判"的：`tests/test_api/test_api_route_conflicts_v2.py`
里三格只 print 不断言（其中一格还拿硬编码的 `backend_count = 75` 算"前端覆盖率"，
而现算挂载路径是 877 条）——这类"穿着测试衣服的采集脚本"计入通过数却守卫不了任何东西，
比 skip 更会骗人。

**本档第 1 格原先把 `module.router.routes` 整体豁免，理由是「模块自带的路由表不受本形态
影响」——这条理由被 2026-11-03 的一枚常驻红证伪**（§6-497）：
`neurova/api/endpoints/neurflow_api.py` 是**聚合器**，它在自己模块级就调
`router.include_router(_stores_router)` 等三条，于是它"自带"的 `router.routes` 与装配后的
`app.routes` 是同一个形状——朴素口径现算 **50** 条（47 叶子＋3 包装）、单源口径 **65** 条，
且对包装层取 `.endpoint` 直接 `AttributeError`。豁免判据不能是"名字里带 router"，只能是
"那个模块确实不挂子路由"，故现改为按 `include_router(` 现算聚合器集合，只豁免真叶子
（第 4、5 格）。同形态其余命中点逐档实测过：`agent_communication_api`／`context`／
`coordination_api`／`settings`／`computer`／`skill_pool_api`／`session_sync`／`chat`／
`media`／`memory` 十个模块面的裸读**包装层均为 0**，今天确实安全，故本批不扩面改动它们。

本档五格：
1. `test_取数口径只有一份`——AST 扫被收集的测试档，凡直接从**装配后的 app** 上取
   `.routes` 即红（`module.router.routes` 走第 4 格的条件豁免）；
2. `test_朴素口径确实看不见挂载面`——把"为什么要禁"钉成读数，两口径差一个量级；
   哪一天 FastAPI 改回就地摊平，这一格会先红，提示口径禁令可以撤；
3. `test_扫描器真会咬`——反向控制：朴素形必点名、单源形不误报（反向控制格自己得先跑绿，
   见形态 376）；
4. `test_聚合器模块的裸读同样失明`——按现算的聚合器集合扫全仓，命中即红；
5. `test_聚合器判据按挂载调用现算`——反向控制：聚合形必点名、真叶子不误报，
   且聚合器集合本身有读数自证（集合空＝本档第 4 格恒绿）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan
from tests.ast_scan import parseSource

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTE_TABLE = REPO_ROOT / "tests" / "route_table.py"
#: 聚合器扫描根提到模块级：绑在函数内的名字上时，本档的落点会安静地掉出
#: `test_scanCriterionMustProveItsOwnSurfaceRatchet` 的面（既不要求面自证，也不算根写错）。
ENDPOINTS_ROOT = REPO_ROOT / "neurova" / "api" / "endpoints"
#: 只扫会被 pytest 收集的目录；manual／archive／runners 是脚本区，本仓惯例不纳门禁
SCAN_DIRS = ("unit", "integration", "api", "test_api", "media", "cognitive_layers", "core")
#: 取装配后 app 路由表的合法出口——只此一家
SINGLE_SOURCE_IMPORT = "tests.route_table"

pytestmark = pytest.mark.timeout(120)


def _readsMountedAppRoutes(tree: ast.AST) -> list:
    """找出 `app.routes` / `client.app.routes` 这一形（不含 `.router.routes`）。"""
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "routes"):
            continue
        base = ast.unparse(node.value)
        if base == "app" or base.endswith(".app") or base in {"client.app", "c.app"}:
            hits.append(node.lineno)
    return sorted(set(hits))


def _dottedModuleName(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT).as_posix()[:-3]
    return rel.replace("/", ".").removesuffix(".__init__")


def _aggregatorModules() -> set:
    """模块级调过 `include_router` 的端点模块（点号路径）——按现算，不抄清单。

    这些模块"自带的路由表"就是挂载后的表：包装层长在它自己 `router.routes` 里，
    所以朴素读法在这里同样失明。真叶子模块（不挂子路由）不受本形态影响，可以继续豁免。
    """
    out = set()
    for ref in ast_scan.sourceRefsUnder(ENDPOINTS_ROOT, ".py", hints=("include_router",)):
        tree = ast_scan.transientTree(ref.path)
        for node in tree.body:
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "include_router"):
                out.add(_dottedModuleName(ref.path))
                break
    return out


def _importedModules(tree: ast.AST) -> dict:
    """测试档里的 alias → 它指向的模块点号路径。"""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                out[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out[(alias.asname or alias.name).split(".")[0]] = alias.name
    return out


def _moduleBehind(base: str, aliases: dict, aggregators: set) -> str:
    """`api.router.routes` 里的 `api.router` 追到真实模块；追不到返回空串。"""
    if base in aliases:
        target = aliases[base]
        return target if target in aggregators else target.rsplit(".", 1)[0]
    if base.endswith(".router"):
        head = base[: -len(".router")]
        return aliases.get(head, "")
    return ""


def test_取数口径只有一份():
    # 枚举与解析都走共享预算（tests/ast_scan.py）：本判据是一次性全仓扫描，
    # 私有 rglob + ast.parse 会把「代码总量」编码成墙钟上界
    # （tests/unit/test_ci_ast_scan_budget_guard.py 的根因，Issue #148）。
    offenders = []
    scannedRoots = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / "tests" / d
        if not root.is_dir():
            continue
        scannedRoots.append(root)
        # 枚举走共享预算；`routes` 字面串是判据谓词的必要条件，作预筛充分
        # （写窄成 `.routes` 会漏掉 `app . routes` 这类跨行/带空格的写法）。
        for ref in ast_scan.sourceRefsUnder(root, ".py", hints=("routes",)):
            path = ref.path
            if path == ROUTE_TABLE:
                continue
            source = ref.code
            if SINGLE_SOURCE_IMPORT in source:
                continue          # 已在用单源的档，不重复数
            hits = _readsMountedAppRoutes(ast_scan.transientTree(path))
            if hits:
                offenders.append(f"{path.relative_to(REPO_ROOT).as_posix()}:{hits}")
    corpusFiles = len(ast_scan.sourceRefsUnder(REPO_ROOT / "tests", ".py"))
    assert corpusFiles >= 1000, (
        "测试语料现读 %d 个 .py——REPO_ROOT 指错时本闸的『零命中』与『没扫到』长得一样" % corpusFiles)
    # 候选面读数＝**同一批扫描根、同一个预筛词**下被枚举的档数，从共享入口再数一遍
    # （现跑本机 87 档）。不在循环里累加，免得那个只增不读的计数器被写坏后判据当场变哑。
    scanned = sum(len(ast_scan.sourceRefsUnder(root, ".py", hints=("routes",)))
                  for root in scannedRoots)
    # 比全量小一个数量级是预筛的本意，但它掉到 0 只会有一种解释：预筛词或 SCAN_DIRS
    # 被改坏，而不是"没人再读 app.routes"。
    assert scanned >= 40, (
        "候选面现读 %d 个文件——SCAN_DIRS 被改窄或预筛写坏，此时『只有一份口径』是假绿（面自证）" % scanned)
    assert not offenders, (
        "这些判据直接从装配后的 app 上取 `.routes`，读到的是挂载包装而非叶子路径——"
        "「存在」型断言会假红、「不存在」型断言会恒真，请改走 `from tests.route_table "
        "import registeredPaths`（口径单源）：" + "; ".join(sorted(offenders))
    )


def test_朴素口径确实看不见挂载面():
    """禁令的事实基础：同一份装配结果，两种口径差一个量级。

    这一格同时是本禁令的**过期探针**——哪天 FastAPI 改回就地摊平子路由，
    两口径会等量，本格即红，提示第 1 格可以撤。
    """
    from neurova.api.app import create_app
    from tests.route_table import registeredPaths

    app = create_app(enable_memory=False, enable_channels=False)
    mounted = registeredPaths(app)
    naive = {getattr(r, "path", "") for r in app.routes}
    naiveReal = {p for p in naive if p}

    assert mounted, "单源口径一条路径都没取到——本档前提塌了，不是禁令的对象塌了"
    assert len(naiveReal) * 20 < len(mounted), (
        f"朴素口径取到 {len(naiveReal)} 条、单源 {len(mounted)} 条——差距已不足一个量级，"
        "说明挂载形态变了（多半是 FastAPI 改回就地摊平）。此时第 1 格的禁令失去依据，"
        "应当撤掉它并把两口径统一到新形态，而不是留着一条没有事实支撑的禁规。"
    )
    assert "/api/v1/console/chat/steer" in mounted, (
        "steer 端点不在挂载面里——那第 1 格抓到的就不是口径问题而是真断点，"
        "请回 `endpoints/console.py:1140` 与前端 `ChatPage.vue:646` 重新定性"
    )


def test_扫描器真会咬():
    naive = (
        "def t(client):\n"
        "    for r in client.app.routes:\n"
        "        print(r.path)\n"
    )
    assert _readsMountedAppRoutes(parseSource(naive)) == [2], "朴素形没被点名＝本守卫恒绿"

    singleSource = (
        "from tests.route_table import registeredPaths\n"
        "def t(app):\n"
        "    return registeredPaths(app)\n"
    )
    assert _readsMountedAppRoutes(parseSource(singleSource)) == [], "单源形被误报"

    routerOwned = (
        "def t(memoryRouter):\n"
        "    return [r.path for r in memoryRouter.routes]\n"
    )
    assert _readsMountedAppRoutes(parseSource(routerOwned)) == [], (
        "局部变量的裸读被误报——第 1 格只管**装配后的 app**，聚合器模块的裸读由第 4 格"
        "按 `include_router` 现算后点名；把它算进第 1 格会让守卫退化成「见 routes 就红」"
    )


def test_聚合器模块的裸读同样失明():
    """第 4 格：豁免必须是「那个模块真不挂子路由」，不是「名字里带 router」。

    成因（§6-497）：`tests/unit/neurflow/test_domain_split_contract.py` 读
    `api.router.routes`（api＝`neurflow_api`，聚合器）常驻红——朴素口径 50 条、
    单源 65 条，且对包装层取 `.endpoint` 直接 `AttributeError`。原第 3 格把这种
    形状当"不误报"写进了豁免理由，理由是错的。
    """
    aggregators = _aggregatorModules()
    assert aggregators, "现算没有任何聚合器模块——本档前提（聚合器自带挂载表）不成立"
    offenders, scanned = [], 0
    for d in SCAN_DIRS:
        root = REPO_ROOT / "tests" / d
        if not root.is_dir():
            continue
        for ref in ast_scan.sourceRefsUnder(root, ".py", hints=("routes",)):
            if ref.path == ROUTE_TABLE or SINGLE_SOURCE_IMPORT in ref.code:
                continue
            scanned += 1
            tree = ast_scan.transientTree(ref.path)
            aliases = _importedModules(tree)
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Attribute) and node.attr == "routes"):
                    continue
                mod = _moduleBehind(ast.unparse(node.value), aliases, aggregators)
                if mod in aggregators:
                    offenders.append(
                        f"{ref.path.relative_to(REPO_ROOT).as_posix()}:{node.lineno} 读 {mod}.routes")
    assert scanned >= 40, (
        f"候选面现读 {scanned} 个文件——预筛词或 SCAN_DIRS 被改窄时『没有裸读』是假绿（面自证）")
    assert not offenders, (
        "这些判据从**聚合器模块**上裸取 `.routes`：该模块自己就调了 include_router，"
        "所以它的 router.routes 里挂着 `_IncludedRouter`（无 .path/.endpoint），"
        "「存在」型断言会假红、「按条数比快照」型断言直接红在形状上。改走 "
        "`from tests.route_table import leafRoutes`：" + "; ".join(sorted(offenders)))


def test_聚合器判据按挂载调用现算():
    """第 5 格：反向控制——聚合形必点名、真叶子不误报，且集合本身有读数。"""
    aggregators = _aggregatorModules()
    leaves = [m for m in (_dottedModuleName(p)
                          for p in (REPO_ROOT / "neurova" / "api" / "endpoints").glob("*.py"))
              if m not in aggregators]
    assert aggregators and leaves, (
        f"聚合器 {len(aggregators)} 个／叶子 {len(leaves)} 个——一侧为空说明现算失效，"
        "第 4 格就此恒绿（本守卫自己的失明面）")
    aggregator, leaf = sorted(aggregators)[0], sorted(leaves)[0]

    assert _moduleBehind("api.router", {"api": aggregator}, aggregators) == aggregator, (
        "聚合器裸读没被点名——第 4 格放行它， neurflow 那枚红就还得靠人肉发现")
    assert _moduleBehind("ep.router", {"ep": leaf}, aggregators) == leaf and leaf not in aggregators, (
        "真叶子被算成聚合器——豁免面被收没了，判据会退化成「见 router.routes 就红」")

    pkg, _, stem = leaf.rpartition(".")
    tree = parseSource(f"from {pkg} import {stem} as api\n"
                       "def t():\n"
                       "    return [r.path for r in api.router.routes]\n")
    assert _moduleBehind("api.router", _importedModules(tree), aggregators) == leaf, (
        "`from <包> import <模块> as api` 这一形追不到模块，第 4 格会整类放行")
