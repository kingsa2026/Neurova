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

本档三格：
1. `test_取数口径只有一份`——AST 扫被收集的测试档，凡直接从**装配后的 app** 上取
   `.routes` 即红（`module.router.routes` 不算：那是模块自带的路由表，不含挂载前缀，
   也不受本次那个失明形态影响）；
2. `test_朴素口径确实看不见挂载面`——把"为什么要禁"钉成读数，两口径差一个量级；
   哪一天 FastAPI 改回就地摊平，这一格会先红，提示口径禁令可以撤；
3. `test_扫描器真会咬`——反向控制：朴素形必点名、单源形与 `router.routes` 不误报
   （反向控制格自己得先跑绿，见形态 376）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests import ast_scan

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTE_TABLE = REPO_ROOT / "tests" / "route_table.py"
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


def test_取数口径只有一份():
    offenders = []
    for d in SCAN_DIRS:
        root = REPO_ROOT / "tests" / d
        if not root.is_dir():
            continue
        # 枚举与解析走共享一次性入口（`tests/ast_scan`）：本判据只扫一次，
        # 自付 `rglob + ast.parse` 等于把成本绑成「代码总量」。
        # 文本预筛取 `.routes`——连它的文件不可能命中下面的谓词。
        for ref in ast_scan.sourceRefsUnder(root, hints=(".routes",)):
            if ref.path == ROUTE_TABLE:
                continue
            if SINGLE_SOURCE_IMPORT in ref.code:
                continue          # 已在用单源的档，不重复数
            hits = _readsMountedAppRoutes(ast_scan.transientTree(ref.path))
            if hits:
                offenders.append(f"{ref.path.relative_to(REPO_ROOT).as_posix()}:{hits}")
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
    from fastapi import FastAPI

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
    assert _readsMountedAppRoutes(ast.parse(naive)) == [2], "朴素形没被点名＝本守卫恒绿"

    singleSource = (
        "from tests.route_table import registeredPaths\n"
        "def t(app):\n"
        "    return registeredPaths(app)\n"
    )
    assert _readsMountedAppRoutes(ast.parse(singleSource)) == [], "单源形被误报"

    routerOwned = (
        "def t(memoryRouter):\n"
        "    return [r.path for r in memoryRouter.routes]\n"
    )
    assert _readsMountedAppRoutes(ast.parse(routerOwned)) == [], (
        "模块自带路由表被误报——它不含挂载前缀，也不受 _IncludedRouter 形态影响，"
        "把它算进来会让守卫退化成「见 routes 就红」的假判据"
    )
