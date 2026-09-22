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

#: 真应用装配路径要走仓内包，脚本本身以 `python scripts/...` 直接运行时带不上仓根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

INVENTORY_PATH = PROJECT_ROOT / "docs" / "09-dev-progress" / "api_inventory.md"

FRONTEND_MODULES_DIR = PROJECT_ROOT / "NeurUI" / "src" / "api" / "modules"
#: 模块目录的短名（守卫按此名做「磁盘多出一个模块」的负向控制；同一对象，非第二份定义）
MODULES_DIR = FRONTEND_MODULES_DIR
ENDPOINT_PACKAGE = PROJECT_ROOT / "neurova" / "api" / "endpoints" / "__init__.py"
APP_MODULE = PROJECT_ROOT / "neurova" / "api" / "app.py"
#: 未挂载扫描的仓内源码根（收录口径是「**全仓**无挂载点」，不是「端点包内无挂载点」）。
#: 口径只写一份：台账与本常量同源。`tests/` 不在内——测试自建的应用不提供服务面。
SOURCE_ROOTS = ("neurova", "scripts", "tools", "examples")
#: 未挂载路由模块的棘轮台账（只降不升；逐条处置理由写在本文件头部）
WIRING_BASELINE = PROJECT_ROOT / "tests" / "unit" / "endpointWiringBaseline.txt"

#: 清单正文里机器区的边界标记（人写说明在标记之外，生成器只碰标记之内）
BLOCK_BEGIN = "<!-- API-INVENTORY:BEGIN -->"
BLOCK_END = "<!-- API-INVENTORY:END -->"
INVENTORY_BEGIN = BLOCK_BEGIN
INVENTORY_END = BLOCK_END

#: 前端请求方法（模块消费的后端前缀从这里取，不靠人工登记）
#: 前端 axios 客户端名（`api` 与 `request` 是同一实例的两个导出名；`axios` 是裸调用）
REQUEST_CLIENTS = ("api", "request", "axios")
#: HTTP 方法名 → 大写（差异形态按方法走查：路径在、方法不对 ≠ 路径不在）
HTTP_METHODS = {
    "get": "GET", "post": "POST", "put": "PUT",
    "delete": "DELETE", "patch": "PATCH", "head": "HEAD",
}
REQUEST_CALL_PATTERN = re.compile(
    r"\b(?:" + "|".join(REQUEST_CLIENTS) + r")\.(" + "|".join(HTTP_METHODS) + r")\b")
BASE_CONST_PATTERN = re.compile(r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]")
CONSUME_PATTERN = re.compile(r"from\s+'@/api/modules/([^']+)'")
GENERATED_ON_PATTERN = re.compile(r"快照日期：(\d{4}-\d{2}-\d{2})")

#: app.py 里直接挂载的 router（不在注册表中，但同属注册事实）
DIRECT_MOUNT_PATTERN = re.compile(r"app\.include_router\([^)]*?prefix\s*=\s*\"([^\"]+)\"", re.S)

#: 客户端自持基地址的两类写法（漏认任一类都会把整份差异表污染成假阳性）：
#: - 常量形态：`const BASE = '/api/neuron'`；
#: - 对象属性形态：`axios.create({ baseURL: '/api/neuron' })`。
BASE_URL_PROPERTY_PATTERN = re.compile(r"baseURL\s*:\s*['\"]([^'\"]+)['\"]")


def clientBaseUrl(text: str) -> str:
    """单个前端客户端文件的请求基地址（判据只写一份，取数与取前缀共用）。

    取数顺序：
    1. 自建 axios 实例的 `baseURL: '...'`（`neuron.ts` → `/api/neuron`）；
    2. 值为 `/api` 或 `/api/v1…` 的路径常量（`computer.ts` → `const API_BASE = '/api'`）；
    3. 全库默认 `/api/v1`（`NeurUI/src/config/index.ts` 的 VITE_API_BASE_URL 兜底）。
    """
    declared = BASE_URL_PROPERTY_PATTERN.search(text)
    if declared:
        return declared.group(1).rstrip("/")
    for value in dict(BASE_CONST_PATTERN.findall(text)).values():
        if value == "/api" or value.startswith("/api"):
            return value.rstrip("/")
    return DEFAULT_API_BASE


def moduleFile(modulePath: str) -> str:
    """把 `neurova.api.endpoints.x` 映射到仓内文件路径（包用 `__init__.py`）。"""
    stem = modulePath.replace(".", "/")
    for candidate in (stem + ".py", stem + "/__init__.py"):
        if (PROJECT_ROOT / candidate).is_file():
            return candidate
    return stem + ".py"


def frontendModuleFiles() -> list:
    """前端模块全集（仓内路径，排除 barrel `index.ts`）。

    目录取 `MODULES_DIR`（与 `FRONTEND_MODULES_DIR` 同一对象）：守卫据此替换目录
    做「磁盘多出一个模块」的负向控制，无需另开一条取数路径。
    """
    files = sorted(
        path.name for path in Path(MODULES_DIR).glob("*.ts")
        if path.name != "index.ts"
    )
    return [f"NeurUI/src/api/modules/{name}" for name in files]


#: 调用实参插值：常量可还原的还原，其余归一成单段通配（取值由调用方决定，清单不臆造）
TEMPLATE_CONST = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TEMPLATE_ANY = re.compile(r"\$\{[^}]*\}")
WILDCARD = "*"
#: 前端 baseURL 兜底值（`config.apiBaseUrl` 默认 `/api/v1`）
DEFAULT_API_BASE = "/api/v1"
#: 挂载层前缀：调用路径已带挂载层时不再叠加
MOUNT_PREFIXES = ("/api/v1", "/api")


def callArgument(text: str, index: int) -> tuple:
    """取调用第一个实参：跳过泛型参数，返回 `(原文, 定界符)`；认不出返回 None。"""
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    if index < len(text) and text[index] == "<":
        depth = 0
        while index < len(text):
            if text[index] == "<":
                depth += 1
            elif text[index] == ">":
                depth -= 1
                if depth == 0:
                    index += 1
                    break
            index += 1
        while index < len(text) and text[index] in " \t\r\n":
            index += 1
    if index >= len(text) or text[index] != "(":
        return None
    index += 1
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    if index >= len(text):
        return None
    if text[index] in "'\"`":
        quote = text[index]
        cursor = index + 1
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == quote:
                return text[index + 1:cursor], quote
            cursor += 1
        return None
    if text[index].isalpha() or text[index] == "_":
        cursor = index
        while cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "_"):
            cursor += 1
        return text[index:cursor], "identifier"
    return None


def resolveCallPath(raw: str, quote: str, constants: dict) -> str:
    """把实参原文解析成调用路径（模板串按常量表还原，其余插值归一成 `*`）。"""
    if quote == "identifier":
        return constants.get(raw, "")
    if quote == "'":
        return raw
    resolved = TEMPLATE_CONST.sub(lambda match: constants.get(match.group(1), WILDCARD), raw)
    return TEMPLATE_ANY.sub(WILDCARD, resolved)


def joinApiPath(base: str, raw: str) -> str:
    """客户端基地址 + 调用路径 → 完整请求路径（已带挂载层时不叠一层）。"""
    for prefix in MOUNT_PREFIXES:
        if raw == prefix or raw.startswith(prefix + "/"):
            return raw
    return base + raw


def frontendModuleCalls(relative: str) -> list:
    """单篇前端模块的逐条调用：`(方法, 完整请求路径, 原始路径)`。

    完整路径按模块自持的 baseURL 语义换算（`computer.ts` 的路径常量就是 `/api`，
    再叠一层会得到 `/api/api/...` 这种并不存在的路径，把差异表污染成假阳性）。
    """
    path = PROJECT_ROOT / relative
    text = io.open(path, encoding="utf-8", errors="replace").read()
    constants = dict(BASE_CONST_PATTERN.findall(text))
    base = clientBaseUrl(text)
    calls = []
    for match in REQUEST_CALL_PATTERN.finditer(text):
        method = HTTP_METHODS.get(match.group(1))
        if not method:
            continue
        argument = callArgument(text, match.end(1))
        if not argument:
            continue
        raw = resolveCallPath(argument[0], argument[1], constants)
        if not raw.startswith("/"):
            continue
        calls.append((method, joinApiPath(base, raw), raw))
    return sorted(set(calls))


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
    base = clientBaseUrl(text)
    if base not in MOUNT_PREFIXES and base.startswith("/api/"):
        prefixes.add("/" + base.strip("/").split("/", 1)[1])
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


def unwiredRouters() -> list:
    """**未接线 router**：挂载动作在、路由一条没有 —— 断点，不是「已注册」。

    返回 `(挂载点, router 自述前缀, 操作标识)`。取数走 `mountedRouterAudit()`
    （同一份判据），不另写一套解析。
    """
    return mountedRouterAudit()["零路由挂载"]


def zeroRouteMountPoints() -> list:
    """零路由挂载点中**不承载任何其它挂载点**的那些（可一把断言「该前缀零路由」）。

    伞形前缀被排除在外：它下面还挂着别的模块，说它「零路由」是错的；
    那种情形由 `unwiredRouters()` 以操作标识指名，不靠前缀说话。
    """
    points = sorted({point for point, _own, _operation in unwiredRouters()})
    occupied = {operation["挂载前缀"] for operation in mountOperations()}
    return [point for point in points
            if not any(other.startswith(point + "/") and other != point for other in occupied)]


def backendMountPoints() -> list:
    """（挂载前缀, router 自述前缀）逐条 —— 取**装配后**的真实 `include_router` 操作。

    为什么不静态重建：真实挂载前缀由 `include_router(prefix=...)` 与 router 自述
    `prefix` 共同决定（本仓两者并用），静态解析等于再实现一遍 FastAPI 的挂载语义——
    第二套平行体系，必然逐版漂移。既然 `app.py` 与注册表都走真装配，判据也取真装配。

    零路由挂载点（`zeroRouteMountPoints()`）**不入表**：挂载动作在、路由一条没有，
    是断点而非「已注册前缀」，混进表里会让读者以为它可用。
    """
    empties = set(zeroRouteMountPoints())
    points = {(operation["挂载前缀"], operation["自述前缀"], operation["模块"])
              for operation in mountOperations()}
    return sorted(row for row in points if row[0] not in empties)



def mountedRouterAudit(app=None) -> dict:
    """挂载契约审计：装配后逐条 `include_router` 核对它挂出的前缀是否成立。

    三类断点（判据只写一份，守卫与清单同源取数）：

    - **零路由挂载**：router 的 `routes` 为空却仍被挂到某前缀——对外声称该前缀可用、
      实际全 404。挂载动作不报错、静态导入也不失败，只有装配后才看得见。
    - **前缀重复**：挂载前缀以 router 自述前缀结尾，真实路径多出一段重复段
      （本仓实测 `/api/neuron/neuron/*`、`/api/coordination/coordination/*`），
      前端按单段路径请求即 404。
    - **重复挂载**：同一个 router 被挂到两个前缀——同一件事两个写入点，改一处漏一处
      （本仓实测 `neuron` 被注册表与 `app.py` 各挂一次）。

    为什么不静态解析：真实挂载前缀由 `include_router(prefix=...)` 与 router 自述
    `prefix` 共同决定，静态重建等于再实现一遍 FastAPI 的挂载语义——第二套平行体系，
    必然逐版漂移。故取装配后的真实 include 操作。
    """
    empties, duplicates, repeats = [], [], []
    firstMount = {}
    operations = mountOperations(app)
    for operation in operations:
        point = operation["挂载前缀"]
        if operation["路由条数"] == 0:
            empties.append((point, operation["自述前缀"], operation["操作标识"]))
            continue
        own = operation["自述前缀"].strip("/")
        if own and operation["include前缀"].rstrip("/").endswith("/" + own):
            duplicates.append((point, operation["自述前缀"], operation["操作标识"]))
        routerId = operation["router标识"]
        if routerId in firstMount:
            repeats.append((point, operation["自述前缀"], firstMount[routerId]))
        else:
            firstMount[routerId] = operation["操作标识"]
    key = lambda row: (row[0], row[2])
    return {
        "零路由挂载": sorted(set(empties), key=key),
        "前缀重复": sorted(set(duplicates), key=key),
        "重复挂载": sorted(set(repeats), key=key),
        "挂载操作数": len(operations),
    }


def mountOperations(app=None) -> list:
    """逐条 `include_router` 操作字典。

    字段：`模块`（该挂载下叶子处理函数所属模块，多来源时取首个）、`挂载前缀`、
    `自述前缀`（router 自己的 `prefix=`）、`路由条数`、`操作标识`。

    只取**一层**：本仓的嵌套 include 都发生在模块内部（聚合器包含叶子），
    装配结果里它们已被展开成同一层的多个 include 操作，逐层递归会把同一条
    路由数两遍。
    """
    app = app if app is not None else assembledApp()
    operations = []
    for index, route in enumerate(app.router.routes):
        inner = getattr(route, "original_router", None)
        if inner is None:
            continue
        context = getattr(route, "include_context", None)
        ownPrefix = getattr(inner, "prefix", "") or ""
        leaves = list(getattr(inner, "routes", []) or ())
        modules = sorted({getattr(getattr(leaf, "endpoint", None), "__module__", "")
                          for leaf in leaves} - {""})
        includePrefix = (context.prefix if context else "").rstrip("/")
        operations.append({
            "模块": modules[0] if modules else "",
            # 有效挂载前缀 = include 前缀 + router 自述前缀 —— 这才是路由真实落在的
            # 位置，也是本表要答的问题。（重复段是断点，由 mountedRouterAudit 拦下。）
            "挂载前缀": (includePrefix + ownPrefix.rstrip("/")) or "/",
            "include前缀": includePrefix,
            "自述前缀": ownPrefix,
            "路由条数": len(leaves),
            "操作标识": f"{ownPrefix or '<无自述前缀>'} #{index}",
            # router 对象标识：同一 router 被挂两次时两块读数同源 —— 那正是
            # 「同一件事两个写入点」，由 mountedRouterAudit 拦下。
            "router标识": id(inner),
        })
    return operations


def auditMountsFor(app) -> dict:
    """对给定 app 做挂载审计（守卫反向控制入口：注入探针 router 后必须报出来）。"""
    return mountedRouterAudit(app)


def servedModules(app=None) -> set:
    """装配后**真的在提供服务的模块**集合（叶子处理函数所属模块）。

    嵌套 include 在装配结果里是包装对象，得逐层展开才能取到叶子。
    """
    served = set()
    pending = list((app if app is not None else assembledApp()).router.routes)
    while pending:
        route = pending.pop()
        inner = getattr(route, "original_router", None)
        if inner is not None:
            pending.extend(getattr(inner, "routes", []) or ())
            continue
        served.add(getattr(getattr(route, "endpoint", None), "__module__", ""))
    return served


def servesOwnAsgiApp(tree) -> bool:
    """该模块是否自建 ASGI 应用（`FastAPI(...)`）——由自己的进程提供服务。

    报成「未接线」是假阳性，而假阳性会训练人忽略这份名单。
    """
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
               and node.func.id == "FastAPI" for node in ast.walk(tree))


def unmountedEndpointModules() -> list:
    """定义了路由、却从未出现在装配后路由表里的模块（显式名单，不静默遗留）。

    收录口径是**全仓**（台账头部即如此声明，`SOURCE_ROOTS` 为唯一事实源）：
    口径若只扫端点包，同一形态在包外就永远看不见——「登记不代替修复」的前提是
    先被看见。判据：AST 找出所有带 `@router.<verb>` 装饰器的模块；装配后取
    「真的在提供服务的模块」集合；两者之差即从未挂载者。自带 `FastAPI()` 应用的
    模块排除（它由自己的进程服务，不是孤儿）。
    名单进清单供人排期，不在本项顺手接线。
    """
    served = servedModules()
    dead = []
    for root in SOURCE_ROOTS:
        for path in sorted((PROJECT_ROOT / root).rglob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read())
            except SyntaxError:
                continue
            if not definesRoutes(tree) or servesOwnAsgiApp(tree):
                continue
            module = ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)
            if module not in served:
                dead.append(module)
    return sorted(dead)


def unwiredEndpointModuleNames() -> list:
    """未挂载模块清单（台账文件用的口径，`unmountedEndpointModules()` 的投影）。

    用**完整点分模块路径**而非末段短名：口径已扩到全仓后，末段短名不保证唯一
    （同一包下可有同名叶子），作台账键会产生歧义。
    """
    return unmountedEndpointModules()


def readWiringBaseline() -> set:
    """未挂载台账当前登记项（`#` 起为注释，空行忽略）。"""
    if not WIRING_BASELINE.is_file():
        return set()
    names = set()
    for line in io.open(WIRING_BASELINE, encoding="utf-8"):
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            names.add(stripped)
    return names


def definesRoutes(tree) -> bool:
    """该模块是否声明了路由（装饰器形态），不依赖 import 副作用。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if isinstance(target, ast.Attribute) and target.attr in HTTP_METHODS:
                    return True
    return False


def assembledApp():
    """装配后的真实应用（唯一取数路径：不静态重建路由语义）。"""
    from neurova.api.app import create_app

    return create_app(enable_memory=False, enable_channels=False)


def registeredBackendPrefixes() -> list:
    """后端挂载前缀集合（注册表 + `app.py` 直接挂载；零路由挂载点不入表）。"""
    return sorted({point for point, _ownPrefix, _module in backendMountPoints()})


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
    routes = registeredRoutePaths()
    breaks = []
    for relative, expected in frontendRequestedPaths():
        if not any(route == expected or route.startswith(expected + "/") for route in routes):
            breaks.append((relative, expected))
    return breaks


def backendMountPointsWithoutFrontendConsumer() -> list:
    """后端已注册、但没有任何前端模块直连的挂载点（内部/平台面，逐条点名）。"""
    requested = {expected for _relative, expected in frontendRequestedPaths()}
    orphans = []
    for point, _ownPrefix, _module in backendMountPoints():
        if not any(expected == point or expected.startswith(point + "/")
                   for expected in requested):
            orphans.append(point)
    return sorted(set(orphans))



def declaredFrontendModules(text: str) -> list:
    """清单里声明的前端模块路径集合。"""
    return sorted(set(re.findall(r"NeurUI/src/api/modules/[\w.-]+\.ts", text)))


def declaredBackendPrefixes(text: str) -> list:
    """清单「后端挂载前缀」表里声明的挂载点（表行第二列）。

    声明侧从**清单正文**解析，不直接读注册表——两侧同源的话，「表与代码树一致」
    会退化成恒真断言（自己与自己比，永远相等）。
    """
    section = _machineSection(text, "## 二、后端挂载前缀", "## 三")
    return sorted(set(re.findall(r"\|\s*`(/api[\w/{}.-]*)`\s*\|\s*$", section, re.M)))


def _machineSection(text: str, heading: str, stopHeading: str) -> str:
    """取机器区内某一节正文（缺区返回空串，由守卫点名缺失，生成器不替它造结构）。"""
    block = text.split(BLOCK_BEGIN)[-1].split(BLOCK_END)[0]
    if heading not in block:
        return ""
    return block.split(heading)[-1].split(stopHeading)[0]


def declaredModuleNames(text: str) -> list:
    """清单第一节声明的模块名（磁盘文件名口径，声明侧独立于磁盘取数）。"""
    section = _machineSection(text, "## 一、前端 API 模块", "## 二")
    return sorted(set(re.findall(r"`NeurUI/src/api/modules/([\w.-]+\.ts)`", section)))


def moduleNameDiff(text: str = None) -> dict:
    """清单声明模块 ←→ 磁盘模块文件的双向差集（验收判据 1）。

    声明侧**从清单正文解析**（`declaredModuleNames`），不直接读磁盘——
    两侧同源的话这条断言会退化成恒真（自己与自己比，永远相等）。
    """
    if text is None:
        text = io.open(INVENTORY_PATH, encoding="utf-8").read()
    onDisk = {Path(relative).name for relative in frontendModuleFiles()}
    declared = set(declaredModuleNames(text))
    return {"missingOnDisk": sorted(declared - onDisk),
            "undeclared": sorted(onDisk - declared)}


def renderInventory(generatedOn: str) -> str:
    """整篇清单正文（唯一写者的产出）。"""
    modules = frontendModuleFiles()
    barrel = frontendBarrelExports()
    consumers = consumerCounts()
    lines = [
        "# Neurova 前端 API 清单（生成物）",
        "",
        "> **生成命令**：`python scripts/generate_api_inventory.py --write`",
        "> **快照日期**：" + generatedOn,
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
    ]
    lines += backendMountPointLines()
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
        "**未接线 router**（挂载动作在、路由一条没有）："
        + (", ".join(f"挂载点 `{point}`（操作 `{operation}`）"
                     for point, _own, operation in unwiredRouters()) or "无"),
        "",
        "**未挂载路由模块**（全仓定义了路由、装配后却不在路由表里 —— 运行时不提供服务）："
        + (", ".join("`" + name + "`" for name in unmountedEndpointModules()) or "无"),
        "",
        "**后端已注册、前端无模块直连的挂载点**（内部/平台面，通常由控制台或 SDK 消费）："
        + (", ".join("`" + item + "`" for item in backendMountPointsWithoutFrontendConsumer())
           or "无"),
        "",
        *unmatchedFrontCallLines(),
        *unconsumedBackendPrefixLines(),
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


def unmatchedFrontCallLines() -> list:
    """「前端调用 ↔ 后端注册」逐条差异行（显式列表，不删条目掩盖）。

    差异不是问题，**被藏起来的差异**才是：删条目只是把洞换个位置。
    差异形态逐行走查**真实路由表**（`create_app()` 装配后），静态重建属第二套平行体系。
    """
    lines = [
        "",
        "## 四、前端调用 ↔ 后端注册 差集",
        "",
    ]
    rows = unmatchedFrontCallRows()
    if rows:
        lines += [
            "下列 **" + str(len(rows)) + "** 处调用在本轮后端注册表里没有对应路由。"
            "这不等于「后端漏注册」——差异以显式列表暴露，由人去核：",
            "",
            "| 模块 | 方法 | 调用路径 | 差异形态 |",
            "|------|------|------|------|",
        ]
        for row in rows:
            lines.append("| " + row["module"] + " | " + row["method"] + " | `" + row["path"]
                         + "` | " + row["verdict"] + " |")
    else:
        lines.append("本轮前端调用**全部命中**后端注册表（差集为空）。")
    return lines


def backendMountPointLines() -> list:
    """后端挂载点表：逐条「端点模块 → 挂载前缀」。

    这一节答「后端**挂出了哪些挂载点**」；「前端调用是否真能落到路由」由第四节的
    真实路由表逐条比对回答。两者分工明确：挂载表取**装配后的 include 操作**
    （模块 + 实际挂载前缀），差异面取**真实执行面**。
    """
    backend = backendMountPoints()
    lines = [
        "",
        "## 二、后端挂载前缀（" + str(len(backend)) + " 条）",
        "",
        "| 端点模块 | 挂载前缀 |",
        "|------|------|",
    ]
    for point, _ownPrefix, module in backend:
        lines.append("| `" + moduleFile(module) + "` | `" + point + "` |")
    return lines


def unconsumedBackendPrefixLines() -> list:
    """「后端已注册 ↔ 前端消费方」逐条差异行（「前端待补消费方」的显式清单）。"""
    lines = [
        "",
        "## 五、后端已注册 ↔ 前端消费方 差集",
        "",
    ]
    roots = backendPrefixesWithoutConsumer()
    if roots:
        lines += [
            "下列 **" + str(len(roots)) + "** 个后端挂载前缀无任何前端模块直连，属"
            "「后端已就位、前端待补消费方」的显式清单：",
            "",
            "| 后端挂载前缀 |",
            "|------|",
        ]
        for root in roots:
            lines.append("| `" + root + "` |")
    else:
        lines.append("本轮后端前缀**全部有**前端消费方（差集为空）。")
    return lines


#: 前端面文件：模块目录 + 模块目录之外自持 baseURL 的单文件客户端
FRONTEND_CLIENT_FILES = ("NeurUI/src/api/auth.ts", "NeurUI/src/api/computer.ts",
                         "NeurUI/src/api/index.ts", "NeurUI/src/api/neuron.ts")


def frontendClientFiles() -> list:
    """前端 API 面的全部客户端文件（含模块目录之外的单文件客户端）。"""
    return sorted(set(frontendModuleFiles()) | set(FRONTEND_CLIENT_FILES))


def registeredRoutePaths() -> frozenset:
    """后端**真实注册的路由表**（`create_app()` 装配后），路径参数段归一成 `*`。

    为什么不静态重建：路由由三层构成——`endpoint_modules` 挂载表、各模块
    `APIRouter(prefix=...)` 自述前缀、聚合器 `include_router(...)` 内嵌的子 router。
    静态解析等于再实现一遍 FastAPI 的路由匹配，属第二套平行体系且必然逐版漂移：
    实测静态侧比真实表少认 40 余条，会把真实端点报成「未注册」——而假阳性比漏报更坏，
    它会训练人忽略这张差异表。故逐条比对的判据取装配后的真实表。
    """
    return frozenset(registeredRouteMethods())


def registeredRouteMethods() -> dict:
    """真实路由表：`归一化路径 → 该路径上注册的 HTTP 方法集合`。

    「路径在、方法不对」与「路径不在」是两种差异（前者多半是后端换过方法、
    前端没跟上），混作一种就是不诚实，故方法一并取回。
    """
    from neurova.api.app import create_app

    app = create_app(enable_memory=False, enable_channels=False)
    routes = {}

    def walk(items, prefix=""):
        for route in items:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                context = getattr(route, "include_context", None)
                walk(getattr(inner, "routes", []), prefix + (context.prefix if context else ""))
                continue
            path = getattr(route, "path", None)
            if path is None:
                continue
            routes.setdefault(_normalizePath(prefix + path), set()).update(
                getattr(route, "methods", None) or ())

    walk(app.router.routes)
    return routes


def _normalizePath(path: str) -> str:
    """路径参数段统一成 `*`，只比结构不比参数名。"""
    return "/".join("*" if part.startswith("{") else part
                    for part in path.rstrip("/").split("/")) or "/"


def unmatchedFrontCallRows() -> list:
    """逐条比对：前端发出的每个调用是否命中真实路由表。

    「路径在、方法不对」与「路径不在」是两种差异，混作一种就是不诚实；故分别走查。
    """
    registered = registeredRouteMethods()
    patterns = [(route, _pathPattern(route)) for route in registered]
    rows = []
    for relative in frontendClientFiles():
        for method, fullPath, _raw in frontendModuleCalls(relative):
            # 通配段会与更具体的同前缀路由重叠（`/plugins/*` 也匹配 `/plugins/discover`），
            # 故按**具体度**取最具体的那条判方法：具体度高者才是该调用真正落到的那条。
            hits = [(route, registered[route]) for route, pattern in patterns if pattern.match(fullPath)]
            if hits:
                best = max(len(route) for route, _methods in hits)
                methods = set().union(*(m for route, m in hits if len(route) == best))
                if method in methods:
                    continue
            rows.append({"module": frontendModuleName(relative), "method": method,
                         "path": fullPath,
                         "verdict": "方法不匹配" if hits else "路径未注册"})
    return sorted(rows, key=lambda row: (row["module"], row["path"], row["method"]))


def _pathPattern(path: str):
    segments = [segment for segment in path.strip("/").split("/") if segment]
    parts = ["[^/]+" if segment.startswith("{") or segment == "*" else re.escape(segment)
             for segment in segments]
    return re.compile("^/" + "/".join(parts) + "/?$")



def backendPrefixesWithoutConsumer() -> list:
    """后端已注册、却无任何前端客户端请求的一级前缀（「前端待补消费方」显式清单）。"""
    declared = {frontendPrefixOf(full) for relative in frontendClientFiles()
                for _method, full, _raw in frontendModuleCalls(relative)}
    roots = {backendPrefixOf(route) for route in registeredRoutePaths()}
    return sorted(root for root in roots if root and root not in declared)


def frontendPrefixOf(fullPath: str) -> str:
    """完整请求路径 → 一级前缀（去挂载层）。"""
    segments = [segment for segment in _normalizePath(fullPath).split("/") if segment]
    while segments and segments[0] in ("api", "v1", "v2"):
        segments.pop(0)
    return "/" + segments[0] if segments and not segments[0].startswith("{") else ""


def backendPrefixOf(fullPath: str) -> str:
    """后端真实路由路径 → 一级前缀（去挂载层）。"""
    return frontendPrefixOf(fullPath)


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
    """重生成落盘，返回写入日期。

    落盘走 `applyInventory`（区块替换）而非整篇重渲染：说明性正文是人的叙述，
    生成器只在区块内**追加/取舍条目**，不替人重写整篇（教义第 2 条：
    不许把「人写的东西」当成漂移抹掉）。
    """
    text = io.open(INVENTORY_PATH, encoding="utf-8").read()
    updated = applyInventory(text)
    if updated != text:
        with io.open(INVENTORY_PATH, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
    return snapshotDate(text)


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


# ---------------------------------------------------------------------------
# 事实源单源暴露面（别名，不是第二份实现）
# ---------------------------------------------------------------------------
# 判据只写一份：上面是本文件的实现，以下全部是**同一对象的别名**——
# 让守卫按「生成器暴露面」这套命名直接取用，不在测试里各写一套解析。
# 新增别名只允许指向已有函数，不得在此另写实现（教义第 6 条：不新造平行体系）。

#: 生成命令写进清单头部——快照纪律里可核的那一半
GENERATE_COMMAND = "python scripts/generate_api_inventory.py --write"
#: 快照周期：超过这个天数未重生成，由守卫点名（日期口径，与双向差集并列的两个判据）
SNAPSHOT_MAX_AGE_DAYS = 120
SNAPSHOT_DATE_PATTERN = re.compile(r"快照日期\*\*：\s*(\d{4}-\d{2}-\d{2})")


def extractSnapshotDate(text: str) -> "datetime.date | None":
    """从清单机器区取快照日期；取不到或不可解析返回 None（由守卫点名缺失）。"""
    found = SNAPSHOT_DATE_PATTERN.search(text)
    if not found:
        return None
    try:
        return datetime.datetime.strptime(found.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def frontModules() -> list:
    """清单主体：每个前端 API 模块文件、它请求到的一级前缀、调用条数。"""
    return [{
        "name": relative,
        "file": relative,
        "prefixes": frontendConsumedPrefixes(relative),
        "callCount": len(frontendModuleCalls(relative)),
    } for relative in frontendModuleFiles()]


def registeredRoutes() -> list:
    """真实路由表：`(归一化路径, 该路径上注册的 HTTP 方法集合)` 逐条（装配后取）。"""
    return sorted(registeredRouteMethods().items())


def unmatchedFrontCalls() -> list:
    """前端发出、后端注册表里无对应路由的调用（显式列表，不静默）。"""
    return unmatchedFrontCallRows()


def unconsumedBackendPrefixes() -> list:
    """后端已注册、却无任何前端客户端请求的一级前缀（显式列表，不静默）。"""
    return backendPrefixesWithoutConsumer()


def renderInventoryTables() -> str:
    """清单**机器区**正文（含起止标记），与 `--write` 落盘的区块逐字同源。

    只出机器区、不带人写的说明性正文——守卫要比的是生成物那一半，
    把叙述性正文一起比会把「人改了一句话」也判成漂移（那是越界）。
    """
    text = renderInventory(snapshotDate(io.open(INVENTORY_PATH, encoding="utf-8").read()))
    start = text.index(BLOCK_BEGIN)
    return text[start:text.index(BLOCK_END, start) + len(BLOCK_END)]


def applyInventoryBlocks(text: str) -> str:
    """把机器区替换成生成器输出，区间之外一字不动（守卫反向控制用）。"""
    return applyInventory(text)
