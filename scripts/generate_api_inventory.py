# -*- coding: utf-8 -*-
"""从前端与后端代码树重生成前端 API 清单（`docs/09-dev-progress/api_inventory.md`）。

根因（不是形状）：那篇清单是一份**专职指路文档**（被 `docs/0-index/README.md` 列为
`09-dev-progress` 领域入口，导航可达），但它此前是**手写**的——手写的模块表必然随
代码改名/合并而漂移，实测 71 个声明模块里 29 个已不存在、现行 61 个模块里 20 个未列出。
逐条补路径只能得到一份「半对半错」的清单，而清单的价值全部在于**可信**。

故本脚本是它的**唯一写者**：清单正文由代码树取全集产出，人工不再手改。
判据只写一份（本文件），守卫 `tests/unit/test_api_inventory_freshness_guard.py`
只做「重算 + 比对 + 负向控制」。

两个方向的事实源：

- 前端模块全集：`NeurUI/src/api/modules/*.ts`（排除 barrel `index.ts`）；
- 后端挂载前缀：`neurova/api/endpoints/__init__.py` 的注册表 + `neurova/api/app.py`
  的直接 `include_router`，挂载点按「表内 prefix + 模块 router 自述 prefix」拼出。

生成日期用**显式参数**（默认当日）。已生成的文档重跑时从正文里读回自己的日期，
故写回是幂等的——不靠日历判断过期，靠**双向差集**（差集非空即说明代码树变了，守卫立红）。
"""
from __future__ import annotations

import ast
import datetime
import io
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

INVENTORY_PATH = PROJECT_ROOT / "docs" / "09-dev-progress" / "api_inventory.md"

FRONTEND_MODULES_DIR = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules"
ENDPOINT_PACKAGE = PROJECT_ROOT / "neurova" / "api" / "endpoints" / "__init__.py"
APP_MODULE = PROJECT_ROOT / "neurova" / "api" / "app.py"

#: 清单正文里机器区的边界标记（人写说明在标记之外，生成器只碰标记之内）
BLOCK_BEGIN = "<!-- API-INVENTORY:BEGIN -->"
BLOCK_END = "<!-- API-INVENTORY:END -->"

#: 前端请求方法（模块消费的后端前缀从这里取，不靠人工登记）
REQUEST_CALL_PATTERN = re.compile(r"api\.(?:get|post|put|delete|patch|request)\b")
BASE_CONST_PATTERN = re.compile(r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]")
CONSUME_PATTERN = re.compile(r"from\s+'@/api/modules/([^']+)'")
GENERATED_ON_PATTERN = re.compile(r"生成日期：(\d{4}-\d{2}-\d{2})")

#: app.py 里直接挂载的 router（不在注册表中，但同属注册事实）
DIRECT_MOUNT_PATTERN = re.compile(r"app\.include_router\([^)]*?prefix\s*=\s*\"([^\"]+)\"", re.S)

#: 各模块 router 自述的完整前缀（以 `/v1` 开头时不再叠加表内 prefix）
VERSIONED_PREFIX = "/v1"


class RegistrationRow:
    """注册表一行：模块 import 路径、表内挂载前缀、说明。"""

    def __init__(self, module: str, tablePrefix: str, description: str) -> None:
        self.module = module
        self.tablePrefix = tablePrefix
        self.description = description


def moduleFile(modulePath: str) -> str:
    """把 `neurova.api.endpoints.x` 映射到仓内文件路径（包用 `__init__.py`）。"""
    stem = modulePath.replace(".", "/")
    for candidate in (stem + ".py", stem + "/__init__.py"):
        if (PROJECT_ROOT / candidate).is_file():
            return candidate
    return stem + ".py"


def frontendModuleFiles() -> list:
    """前端模块全集（仓内路径，排除 barrel `index.ts`）。"""
    files = sorted(
        path.name for path in FRONTEND_MODULES_DIR.glob("*.ts")
        if path.name != "index.ts"
    )
    return [f"NeurUI/src/api/modules/{name}" for name in files]


def frontendConsumedPrefixes(relative: str) -> list:
    """单篇前端模块消费的后端一级前缀（请求字面量 + BASE 常量，均取首段）。"""
    path = PROJECT_ROOT / relative
    text = io.open(path, encoding="utf-8", errors="replace").read()
    prefixes = set()
    for match in REQUEST_CALL_PATTERN.finditer(text):
        open_ = text.find("(", match.end())
        if open_ == -1:
            continue
        index = open_ + 1
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
        if index >= len(text) or text[index] not in "`'\"":
            continue
        quote = text[index]
        stop = text.find(quote, index + 1)
        if stop == -1:
            continue
        literal = text[index + 1:stop].split("${")[0]
        if literal.startswith("/"):
            prefixes.add("/" + literal.strip("/").split("/")[0])
    for name, value in BASE_CONST_PATTERN.findall(text):
        if value.startswith("/") and "${" + name + "}" in text:
            prefixes.add("/" + value.strip("/").split("/")[0])
    return sorted(prefixes)


def frontendBarrelExports() -> set:
    """barrel `index.ts` 里被 re-export 的模块名（缺导出即前端拿不到的模块）。"""
    barrel = FRONTEND_MODULES_DIR / "index.ts"
    if not barrel.is_file():
        return set()
    return set(re.findall(r"from\s+'\./([^']+)'", io.open(barrel, encoding="utf-8").read()))


def frontendModuleName(relative: str) -> str:
    return Path(relative).stem


def consumerCounts() -> dict:
    """一次性统计每个前端模块的仓内引用处数（barrel 自身不计——它只是转出口）。"""
    counts = {}
    for path in (PROJECT_ROOT / "NeurUI" / "src").rglob("*"):
        if path.suffix not in (".ts", ".vue") or path.name == "index.ts":
            continue
        text = io.open(path, encoding="utf-8", errors="replace").read()
        for target in CONSUME_PATTERN.findall(text):
            if Path(target).stem == path.stem:
                continue
            counts[target] = counts.get(target, 0) + 1
    return counts


def registrationRows() -> list:
    """注册表逐行（`endpoint_modules` 表，唯一事实源）。"""
    tree = ast.parse(io.open(ENDPOINT_PACKAGE, encoding="utf-8").read())
    rows = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "endpoint_modules"):
            continue
        for element in node.value.elts:
            module, prefix, description = (part.value for part in element.elts)
            rows.append(RegistrationRow(module, prefix, description))
    return rows


def moduleRouterPrefix(modulePath: str) -> str:
    """模块内 `router` 自述的 prefix（无声明返回空串）。"""
    relative = moduleFile(modulePath)
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return ""
    tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read())
    for node in tree.body:
        if not (isinstance(node, ast.Assign)
                and any(getattr(target, "id", "") == "router" for target in node.targets)):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                return keyword.value.value
    return ""


def mountPoint(tablePrefix: str, routerPrefix: str) -> str:
    """挂载点 = 表内 prefix 与模块 router 自述 prefix 的拼接（自述含 `/v1` 时不再叠加）。"""
    if routerPrefix.startswith(VERSIONED_PREFIX):
        return ("/api" + routerPrefix).rstrip("/")
    return ("/api" + tablePrefix.rstrip("/") + routerPrefix.rstrip("/")) or "/api"


#: 路由注册语句：装饰器形态 `@router.get(...)` 与 `router.add_api_route(...)`
ROUTE_DECORATOR_PATTERN = re.compile(r"@\s*([A-Za-z_][A-Za-z0-9_]*)\.(?:get|post|put|patch|delete|head|options|trace)\b")

#: app.py 的直接挂载：`app.include_router(<名字>, prefix="...")`
DIRECT_MOUNT_VERB_PATTERN = re.compile(
    r"app\.include_router\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:,[^)]*?)?prefix\s*=\s*\"([^\"]+)\"", re.S
)

#: `X = APIRouter(...)` / `X = some.APIRouter(...)`
ROUTER_ASSIGN_PATTERN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[\w.]*APIRouter\(", re.M)


def _importedRouters(relative: str) -> dict:
    """单篇文件里 `router 变量 → (来源模块, 原变量名, 是否相对导入)`。

    用 AST 取 import，不靠正则——本仓的 `from X import (a, b, c)` 多行括号形态
    在 `app.py` 里就是主流写法，正则版本会把它们整批漏掉。
    """
    text = io.open(PROJECT_ROOT / relative, encoding="utf-8", errors="replace").read()
    mapping = {}
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            local = alias.asname or alias.name
            if alias.name == "router" or alias.name.endswith("_router") or local.endswith("_router"):
                mapping[local] = (("." * node.level) + (node.module or ""),
                                  alias.name, node.level > 0)
    return mapping


def _moduleRelative(modulePath: str) -> str:
    return moduleFile(modulePath)


def displayRelative(path: Path) -> str:
    """仓内相对路径（与 `trackedFiles` 同一书写口径）。"""
    return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def relativeModuleName(relative: str) -> str:
    """仓内文件路径 → 包内点分模块名（包用其包名，非 `__init__`）。"""
    stem = relative[:-3] if relative.endswith(".py") else relative
    parts = stem.split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolveImportModule(modulePath: str, importer: str) -> str:
    """把 `from .base import router` 这类相对导入解析成仓内文件路径。"""
    if not modulePath.startswith("."):
        return moduleFile(modulePath)
    importerPackage = relativeModuleName(importer)
    package = importerPackage if importer.endswith("__init__.py") else importerPackage.rsplit(".", 1)[0]
    depth = len(modulePath) - len(modulePath.lstrip("."))
    suffix = modulePath.lstrip(".")
    baseParts = package.split(".")
    if depth > 1:
        baseParts = baseParts[:len(baseParts) - (depth - 1)]
    dotted = ".".join([part for part in baseParts if part] + ([suffix] if suffix else []))
    return moduleFile(dotted)


ROUTE_VERBS = "get|post|put|patch|delete|head|options|trace"


def routerRoutePaths(name: str, relative: str, base: str, seen: set = None) -> list:
    """静态收集某个 router 注册的**完整路由路径**（含跨模块 include_router）。

    三类载体都要认，否则会把「统计能力不足」误判成断点：

    - 本文件里的装饰器注册（`@router.get("/x")`）；
    - 本文件里 `router.include_router(<子 router>)` 的递归跟随；
    - **转发出口**（`from .base import router` / `from .x import router as y`）
      ——注册语句在别的模块里，不跟随就永远数出空；
    - 同包同级模块各自持有的共享 router（本仓 `endpoints/memory/`）。

    `base` 是该 router 的挂载点；返回路径已拼上 base，可直接与前端请求比对。
    """
    seen = seen or set()
    key = (relative, name)
    if key in seen:
        return []
    seen.add(key)
    path = PROJECT_ROOT / relative
    if not path.is_file():
        return []
    text = io.open(path, encoding="utf-8", errors="replace").read()
    found = []
    for verb, route in re.findall(
            r"@\s*" + re.escape(name) + r"\.(" + ROUTE_VERBS + r")\(\s*[\"']([^\"']*)[\"']", text):
        found.append((base.rstrip("/") + "/" + route.strip("/")).rstrip("/") or base)
    imports = _importedRouters(relative)
    for inner in re.findall(re.escape(name)
                            + r"\.include_router\(\s*([A-Za-z_][A-Za-z0-9_]*)", text):
        if inner in imports:
            modulePath, original, _isRelative = imports[inner]
            innerPrefix = moduleRouterPrefix(modulePath)
            innerBase = base + (innerPrefix if not innerPrefix.startswith(VERSIONED_PREFIX) else "")
            found += routerRoutePaths(original, resolveImportModule(modulePath, relative),
                                      innerBase, seen)
        else:
            found += routerRoutePaths(inner, relative, base, seen)
    if not found:
        imported = imports.get(name)
        if imported:
            modulePath, original, isRelative = imported
            innerPrefix = moduleRouterPrefix(modulePath)
            innerBase = base + (innerPrefix if not innerPrefix.startswith(VERSIONED_PREFIX) else "")
            found += routerRoutePaths(original, resolveImportModule(modulePath, relative),
                                      innerBase, seen)
            if not found and name == "router" and isRelative:
                packageDir = (PROJECT_ROOT / relative).parent
                for sibling in sorted(packageDir.glob("*.py")):
                    siblingRelative = displayRelative(sibling)
                    if siblingRelative == relative:
                        continue
                    found += routerRoutePaths(name, siblingRelative, base, seen)
    return sorted(set(found))


def backendRoutePaths() -> list:
    """（端点模块, 完整路由路径）逐条 —— 静态口径，可与运行时 openapi 复核。"""
    rows = []
    for row in registrationRows():
        relative = moduleFile(row.module)
        base = mountPoint(row.tablePrefix, moduleRouterPrefix(row.module))
        for route in routerRoutePaths("router", relative, base):
            rows.append((relative, route))
    for relative, name, original, base in directMountRows():
        for route in routerRoutePaths(original, relative, base):
            rows.append((relative, route))
    return sorted(set(rows))


def directMountRows() -> list:
    """`app.py` 直接挂载的（来源模块, 变量名, 挂载点）。

    挂载点 = `include_router` 的 prefix + 该 router 自述 prefix
    （例：`budget_router` 自述 `/budgets`，被挂到 `/api` → 实为 `/api/budgets`）。
    """
    appText = io.open(APP_MODULE, encoding="utf-8").read()
    imports = _importedRouters("neurova/api/app.py")
    rows = []
    for name, prefix in DIRECT_MOUNT_VERB_PATTERN.findall(appText):
        modulePath, original, _isRelative = imports.get(name, ("", name, False))
        source = moduleFile(modulePath) if modulePath else ""
        point = (prefix.rstrip("/") + moduleRouterPrefix(modulePath)) if modulePath else prefix
        rows.append((source or "neurova/api/app.py", name, original, point.rstrip("/") or "/api"))
    return rows


def unwiredRouters() -> list:
    """**未接线 router**：注册动作在、路由一条没有 —— 断点，不是「已注册」。

    三种载体都会命中：

    - 注册表里某模块的 `router` 零路由（模块整体是壳）；
    - 模块级空对象被挂到具体前缀——本仓实测 `evolution_router` / `rag_router`
      是**零路由空 router**（全仓无任何注册语句），却挂成 `/api/evolution`、`/api/rag`；
    - `endpoints/__init__.py` 的顶层 `router` 同样零路由，被挂在 `/api`。

    返回 (来源模块, 变量名, 挂载点)，按来源去重。
    """
    unwired = []
    for row in registrationRows():
        relative = moduleFile(row.module)
        base = mountPoint(row.tablePrefix, moduleRouterPrefix(row.module))
        if not routerRoutePaths("router", relative, base):
            unwired.append((relative, "router", base))
    for relative, name, original, prefix in directMountRows():
        if not routerRoutePaths(original, relative, prefix):
            unwired.append((relative, name, prefix))
    return sorted(set(unwired))


def zeroRouteMountPoints() -> list:
    """零路由挂载点中**不承载任何其它挂载点**的那些（可一把断言「该前缀零路由」）。

    伞形前缀（`/api`）被排除在外：它下面还挂着别的模块，说「`/api` 零路由」是
    错的；那种情形由 `unwiredRouters()` 以（来源模块, 变量名）指名，不靠前缀说话。
    """
    points = sorted({point.rstrip("/") or "/" for _relative, _name, point in unwiredRouters()})
    occupied = {point for _relative, point in backendMountPoints()}
    return [point for point in points
            if not any(other.startswith(point + "/") and other != point for other in occupied)]


def backendMountPoints() -> list:
    """（模块文件, 挂载前缀）逐条，含 `app.py` 的直接挂载。

    零路由挂载点（`zeroRouteMountPoints()`）**不入表**——那是断点，
    与「已注册前缀」不是一回事，混在一起会让读者以为它可用。
    """
    unwired = {(relative, name) for relative, name, _point in unwiredRouters()}
    points = []
    for row in registrationRows():
        relative = moduleFile(row.module)
        if (relative, "router") in unwired:
            continue
        points.append((relative, mountPoint(row.tablePrefix, moduleRouterPrefix(row.module))))
    for relative, name, _original, prefix in directMountRows():
        if (relative, name) in unwired:
            continue
        points.append((relative, prefix.rstrip("/")))
    return [(path, point) for path, point in sorted(set(points)) if point != "/api"]


def registeredBackendPrefixes() -> list:
    """后端挂载前缀集合（注册表 + `app.py` 直接挂载；零路由挂载点不入表）。"""
    return sorted({point for _, point in backendMountPoints()})


def frontendRequestedPaths() -> list:
    """前端模块实际请求的路径前缀（按 `baseURL` 语义换算成 `/api/v1/...`）。"""
    wanted = []
    for relative in frontendModuleFiles():
        for segment in frontendConsumedPrefixes(relative):
            wanted.append((relative, "/api/v1" + segment))
    return sorted(set(wanted))


def frontendContractBreaks() -> list:
    """前端请求路径在后端**无对应路由**的条目 —— 契约断点，逐条点名。

    前端 `baseURL` 是 `config.apiBaseUrl`（默认 `/api/v1`），故模块里的 `/xxx`
    实际请求 `/api/v1/xxx`。后端若把它挂在别处（如 `/api/xxx`，缺 `v1`）或不挂，
    请求即 404；这类断点界面上不报错，只会「页面正常渲染、数据全空」。
    """
    routes = {route for _relative, route in backendRoutePaths()}
    breaks = []
    for relative, expected in frontendRequestedPaths():
        if not any(route == expected or route.startswith(expected + "/") for route in routes):
            breaks.append((relative, expected))
    return breaks


def backendMountPointsWithoutFrontendConsumer() -> list:
    """后端已注册、但没有任何前端模块直连的挂载点（内部/平台面，逐条点名）。"""
    requested = {expected for _relative, expected in frontendRequestedPaths()}
    orphans = []
    for _relative, point in backendMountPoints():
        if not any(expected == point or expected.startswith(point + "/")
                   for expected in requested):
            orphans.append(point)
    return sorted(set(orphans))



def declaredFrontendModules(text: str) -> list:
    """清单里声明的前端模块路径集合。"""
    return sorted(set(re.findall(r"NeurUI/src/api/modules/[\w.-]+\.ts", text)))


def declaredBackendPrefixes(text: str) -> list:
    """清单「后端挂载前缀」表里声明的挂载点（表行第二列）。"""
    block = text.split(BLOCK_BEGIN)[-1].split(BLOCK_END)[0]
    section = block.split("## 二、后端挂载前缀")[-1].split("## 三")[0]
    return sorted(set(re.findall(r"\|\s*`(/api[\w/{}.-]*)`\s*\|\s*$", section, re.M)))


def renderInventory(generatedOn: str) -> str:
    """整篇清单正文（唯一写者的产出）。"""
    modules = frontendModuleFiles()
    barrel = frontendBarrelExports()
    backend = backendMountPoints()
    consumers = consumerCounts()
    lines = [
        "# Neurova 前端 API 清单（生成物）",
        "",
        "> **生成日期：" + generatedOn + "**",
        "> **生成命令**：`python scripts/generate_api_inventory.py --write`",
        "> **事实源**：前端模块 `NeurUI/src/api/modules/`；后端端点 `neurova/api/endpoints/`",
        "> （注册表 `neurova/api/endpoints/__init__.py` 加 `neurova/api/app.py` 直接挂载）。",
        "> 本表**由脚本产出，不要手改**；接口报文与字段以"
        " [API_REFERENCE.md](../02-api/API_REFERENCE.md) 为准。",
        "",
        "过期判据不是日历而是**双向差集**：代码树增删一个模块，本表与代码树的差集即非空，"
        "守卫 `tests/unit/test_api_inventory_freshness_guard.py` 立刻报红并给出差集两侧的名单。",
        "",
        BLOCK_BEGIN,
        "## 一、前端 API 模块（" + str(len(modules)) + " 个）",
        "",
        "| 模块文件 | 消费的后端前缀 | barrel 导出 | 仓内引用处 |",
        "|------|------|------|------|",
    ]
    for relative in modules:
        name = frontendModuleName(relative)
        prefixes = frontendConsumedPrefixes(relative)
        lines.append(
            "| `" + relative + "` | "
            + (", ".join("`" + item + "`" for item in prefixes) or "—")
            + " | " + ("是" if name in barrel else "**否**")
            + " | " + str(consumers.get(name, 0)) + " |"
        )
    lines += [
        "",
        "> `NeurUI/src/api/index.ts` 是 axios 实例与鉴权拦截器，"
        "`NeurUI/src/api/auth.ts` / `NeurUI/src/api/neuron.ts` 是模块目录之外的单文件客户端，"
        "三者不属本表模块口径。",
        "",
        "## 二、后端挂载前缀（" + str(len(backend)) + " 条）",
        "",
        "| 端点模块 | 挂载前缀 |",
        "|------|------|",
    ]
    for path, point in backend:
        lines.append("| `" + path + "` | `" + point + "` |")
    lines += [
        "",
        "## 三、差集（断点以显式名单暴露，不用「大致一致」带过）",
        "",
        "**barrel 未导出的模块**："
        + (", ".join("`" + relative + "`" for relative in modules
                     if frontendModuleName(relative) not in barrel) or "无"),
        "",
        "**前后端前缀契约断点**（前端按 `baseURL=/api/v1` 请求，后端无对应挂载点 → 404）："
        + (", ".join(f"`{module}` 请求 `{expected}`" for module, expected in frontendContractBreaks())
           or "无"),
        "",
        "**零路由挂载点**（注册动作在、路由一条没有 —— 断点，待接线或删除）："
        + (", ".join("`" + point + "`" for point in zeroRouteMountPoints()) or "无"),
        "",
        "**未接线 router**（含被旁路注册掩盖的顶层空对象）："
        + (", ".join(f"`{module}` 的 `{name}`（挂 `{point}`）"
                     for module, name, point in unwiredRouters()) or "无"),
        "",
        "**后端已注册、前端无模块直连的挂载点**（内部/平台面，通常由控制台或 SDK 消费）："
        + (", ".join("`" + item + "`" for item in backendMountPointsWithoutFrontendConsumer())
           or "无"),
        "",
        BLOCK_END,
        "",
        "## 口径说明",
        "",
        "1. **后台逐端点清单已退役**：旧表逐条列「方法 / 路径 / 功能 / 是否实现」，"
        "那是人工维护的第二份事实源，必然漂移。逐条端点以 `docs/02-api/API_REFERENCE.md`"
        "（接口事实源）与运行时 `/docs` 为准。",
        "2. **导航归属**：本表定位仍是**现行清单**，保留在 `docs/0-index/README.md` 的"
        " `09-dev-progress` 领域入口表内；重生成后其路径引用全部可解析，"
        "不再构成「指路条目」形态的失效引用。",
        "3. **快照纪律**：头部生成日期与生成命令必须同时在场；"
        "超过约定周期未重生成时，以代码树差集（而非日期）判定是否过期。",
        "",
    ]
    return "\n".join(lines)


def snapshotDate(text: str) -> str:
    """从已生成正文里读回生成日期；读不到才退回当日（保证写回幂等）。"""
    match = GENERATED_ON_PATTERN.search(text)
    if match:
        return match.group(1)
    return datetime.date.today().isoformat()


def applyInventory(text: str) -> str:
    """写回清单：以生成器产出为准（本脚本是唯一写者）。"""
    return renderInventory(snapshotDate(text))


def writeInventory() -> str:
    """按当日日期重生成并落盘，返回写入日期。"""
    generatedOn = datetime.date.today().isoformat()
    rendered = renderInventory(generatedOn)
    with io.open(INVENTORY_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    return generatedOn


def report() -> list:
    """双向差集（空表示清单与代码树一致）。"""
    text = io.open(INVENTORY_PATH, encoding="utf-8").read()
    messages = []
    for label, declared, actual in (
        ("前端模块", declaredFrontendModules(text), frontendModuleFiles()),
        ("后端挂载前缀", declaredBackendPrefixes(text), registeredBackendPrefixes()),
    ):
        onlyDeclared = sorted(set(declared) - set(actual))
        onlyActual = sorted(set(actual) - set(declared))
        if onlyDeclared or onlyActual:
            messages.append(
                f"{label}双向差集非空：只在清单里 {onlyDeclared}；只在代码树里 {onlyActual}"
            )
    return messages


def main(argv: list) -> int:
    if "--write" in argv:
        print("清单已重生成："
              + str(INVENTORY_PATH.relative_to(PROJECT_ROOT))
              + f"（生成日期 {writeInventory()}）")
        return 0
    problems = report()
    if problems:
        for problem in problems:
            print(problem)
        return 1
    print("清单与代码树双向差集为空："
          + str(INVENTORY_PATH.relative_to(PROJECT_ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
