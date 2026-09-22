# -*- coding: utf-8 -*-
"""前端 API 清单生成器（Ref: Issue #112 / #68 归档层导航影响筛选·乙类销账）。

根因：`docs/09-dev-progress/api_inventory.md` 是一份**专职指路文档**——它被
`docs/0-index/README.md` 列为 `09-dev-progress` 领域入口，读者顺着它去找前端 API
模块。但它自 2026-06-06 起就没再对齐代码树：声明的模块里近半已改名或合并，另有
一批现行模块根本没进清单。逐条补路径只能得到一份「半对半错」的表——而清单的全部
价值在于可信，故正确处置是**重生成**（对现行代码树取全集），不是逐条改指。

本文件是这份清单的**唯一事实源**。被读的事实源是代码树本身：

- 前端模块：`NeurUI/src/api/modules/*.ts`，逐文件取它请求到的端点前缀；
- 前端客户端：`NeurUI/src/api/*.ts`（`auth` / `neuron` / `computer` 三个自持
  baseURL 的客户端，同属前端 API 面）；
- 后端注册：`create_app()` **装配后的真实路由表**（与 `tests/e2e/test_backend_boot.py`
  同一条装配路径）。不静态重建路由——那等于再实现一遍 FastAPI 的路由匹配，
  属第二套平行体系且必然逐版漂移；
- 三组差集：模块文件双向、前端调用 ↔ 后端路由（区分「路径未注册」/「方法不匹配」）、
  后端一级前缀 ↔ 前端消费方。

守卫 `tests/unit/test_api_inventory_guard.py` 只做「重算 + 比对 + 反向控制」，
判据全部取自本文件，不在测试里复制一套。

用法：
    python scripts/gen_api_inventory.py            # 打印概况
    python scripts/gen_api_inventory.py --update   # 重生成清单机器区
"""
from __future__ import annotations

import glob
import io
import re
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

API_DIR = PROJECT_ROOT / "NeurUI" / "src" / "api"
MODULES_DIR = API_DIR / "modules"

INVENTORY_PATH = PROJECT_ROOT / "docs" / "09-dev-progress" / "api_inventory.md"
INVENTORY_BEGIN = "<!-- API-INVENTORY:BEGIN -->"
INVENTORY_END = "<!-- API-INVENTORY:END -->"

#: 生成命令写进清单头部——快照纪律里可核的那一半
GENERATE_COMMAND = "python scripts/gen_api_inventory.py --update"
#: 快照周期：超过这个天数未重生成，头部须标注「可能过期」（由守卫做反向控制）
SNAPSHOT_MAX_AGE_DAYS = 120

#: 前端请求客户端：`api` 与 `request` 是同一个 axios 实例的两个导出名；
#: `axios` 是裸调用（`computer.ts` 这类自建客户端直接 `axios.get`）——
#: 不收它就会把一整个客户端的调用**静默漏掉**，那正是本项要杜绝的形态。
REQUEST_CLIENTS = ("api", "request", "axios")
HTTP_METHODS = {
    "get": "GET", "post": "POST", "put": "PUT",
    "delete": "DELETE", "patch": "PATCH", "head": "HEAD",
}

#: axios baseURL 兜底值（`NeurUI/src/config/index.ts` 的 VITE_API_BASE_URL 默认）
DEFAULT_API_BASE = "/api/v1"
#: 前端 baseURL 与后端注册路径之间的挂载层前缀
MOUNT_PREFIXES = ("/api/v1", "/api")

#: 桶文件：只做 re-export，本身不承载端点
NON_MODULE_FILES = frozenset({"index.ts"})

STRING_CONSTANT = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=\s*'([^']*)'",
    re.M,
)
BASE_URL_CONSTANT = re.compile(r"baseURL\s*:\s*'([^']*)'")

#: 调用实参里的插值：常量可还原的还原，其余归一成单段通配
TEMPLATE_CONST = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TEMPLATE_ANY = re.compile(r"\$\{[^}]*\}")
WILDCARD = "*"


def readSource(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


def displayPath(path: Path) -> str:
    """仓内用相对路径，仓外（如测试夹具临时目录）用绝对路径。"""
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _tsFiles(directory: Path) -> list:
    return sorted(
        Path(item) for item in glob.glob(str(directory / "*.ts"))
        if Path(item).name not in NON_MODULE_FILES
    )


def moduleFiles() -> list:
    """前端 API 模块文件（`NeurUI/src/api/modules/*.ts`，排除桶文件）。"""
    return _tsFiles(MODULES_DIR)


def clientFiles() -> list:
    """前端 API 客户端文件（模块面 + 自持 baseURL 的根客户端）。"""
    return sorted(set(moduleFiles()) | set(_tsFiles(API_DIR)))


def _skipWhitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def callArgument(text: str, index: int) -> tuple:
    """取调用第一个实参：跳过泛型参数，返回 `(原文, 定界符)`。

    定界符为 `'` / `"` / `` ` ``（字面字符串）或 `identifier`（标识符引用）。
    """
    index = _skipWhitespace(text, index)
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
        index = _skipWhitespace(text, index)
    if index >= len(text) or text[index] != "(":
        return None
    index = _skipWhitespace(text, index + 1)
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
    """把实参原文解析成前端视角的端点路径。

    模板串里的 `${CONST}` 按常量表还原；其余插值（`${encodeURIComponent(id)}`）
    归一成单段通配 `*`——它们的取值由调用方决定，本清单不臆造。
    """
    if quote == "identifier":
        return constants.get(raw, "")
    if quote == "'":
        return raw
    resolved = TEMPLATE_CONST.sub(lambda match: constants.get(match.group(1), WILDCARD), raw)
    return TEMPLATE_ANY.sub(WILDCARD, resolved)


def _clientBase(text: str) -> str:
    """该客户端文件使用的 API 基地址。

    取数顺序（只此一份，三处形态都要认）：
    1. 自建 axios 实例的 `baseURL: '...'`（`neuron.ts` → `/api/neuron`）；
    2. 值为 `/api` 或 `/api/v1…` 的路径常量（`computer.ts` → `const API_BASE = '/api'`）；
    3. 全库默认 `/api/v1`（`NeurUI/src/config/index.ts` 的 VITE_API_BASE_URL 兜底）。
    """
    match = BASE_URL_CONSTANT.search(text)
    if match:
        return match.group(1).rstrip("/")
    for name, value in STRING_CONSTANT.findall(text):
        if value == "/api" or value.startswith(("/api/", "/api")):
            if not value.startswith("/api/"):
                return value.rstrip("/")
    return DEFAULT_API_BASE


def clientCalls(path: Path) -> list:
    """单个前端客户端文件 → `(方法, 完整路径, 原始路径)` 调用列表。"""
    text = readSource(path)
    constants = dict(STRING_CONSTANT.findall(text))
    base = _clientBase(text)
    calls = []
    for match in re.finditer(r"\b(%s)\.(\w+)" % "|".join(REQUEST_CLIENTS), text):
        method = HTTP_METHODS.get(match.group(2))
        if not method:
            continue
        argument = callArgument(text, match.end(2))
        if not argument:
            continue
        raw = resolveCallPath(argument[0], argument[1], constants)
        if not raw.startswith("/"):
            continue
        calls.append((method, joinApiPath(base, raw), raw))
    return calls


def joinApiPath(base: str, raw: str) -> str:
    """把客户端基地址与调用路径拼成完整路径。

    调用路径**已经带挂载层前缀**时不再叠一层：`computer.ts` 的路径常量就是
    `/api`（`axios.get('/api/computers')`），再拼 base 会得到 `/api/api/computers`
    ——一个并不存在的路径，会把整份清单的差异表污染成假阳性。
    """
    for prefix in MOUNT_PREFIXES:
        if raw == prefix or raw.startswith(prefix + "/"):
            return raw
    return base + raw


def prefixOf(fullPath: str) -> str:
    """完整路径 → 一级端点前缀（去挂载层，空则空串）。

    必须从**完整路径**取，不能从原始路径取：自持 baseURL 的客户端
    （`neuron.ts` 的 `/api/neuron`、`computer.ts` 的 `/api`）原始路径不带
    自己的前缀，从原始路径取会把 `/neuron` 的前缀读成 `/entities`——
    于是「后端已注册无前端消费」会误报 `/neuron`。
    """
    segments = [segment for segment in normalizePrefix(fullPath).split("/") if segment]
    if not segments or segments[0].startswith("{"):
        return ""
    return "/" + segments[0]


def frontPrefixes(path: Path) -> list:
    """单个前端客户端文件请求到的一级端点前缀（去重排序）。"""
    heads = {prefixOf(call[1]) for call in clientCalls(path)}
    return sorted(head for head in heads if head)


def frontModules() -> list:
    """清单主体：每个前端 API 模块文件、它请求到的一级前缀、调用条数。"""
    return [{
        "name": path.name,
        "file": displayPath(path),
        "prefixes": frontPrefixes(path),
        "callCount": len(clientCalls(path)),
    } for path in moduleFiles()]


def normalizePrefix(path: str) -> str:
    """去掉挂载层前缀，返回前端 axios 视角下的相对前缀。"""
    for prefix in MOUNT_PREFIXES:
        if path == prefix:
            return "/"
        if path.startswith(prefix + "/"):
            return path[len(prefix):]
    return path


def registeredRoutes() -> list:
    """后端**实际注册的路由**：`(路径, {方法})`，直接走 FastAPI 装配后的 router 表。

    为什么不静态重建：本仓路由由三层构成——`endpoint_modules` 挂载表、各模块
    `APIRouter(prefix=...)` 自持前缀、以及聚合器 `include_router(...)` 内嵌的
    子 router（`knowledge.py` include 5 个、`neurflow_api.py` include 3 个，
    还含 `add_api_route("")` 这类直挂形态）。静态解析等于**再实现一遍 FastAPI 的
    路由匹配**——那是第二套平行体系，且必然逐版漂移。实测静态侧比真实路由表少认 40 余条：
    静态侧会把真实存在的端点报成「后端未注册」，而假阳性比漏报更坏，
    它会训练人忽略这张差异表。

    故事实源取**装配后的真实路由表**（`create_app()` 后遍历 `app.router.routes`），
    与 `tests/e2e/test_backend_boot.py` 走同一条装配路径。方法一并取回：
    「路径在、方法不对」与「路径不在」是两种不同的差异，混作一种就是不诚实。
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
            full = prefix + path
            routes.setdefault(full, set()).update(getattr(route, "methods", None) or ())

    walk(app.router.routes)
    return sorted((path, frozenset(methods)) for path, methods in routes.items())


def pathPattern(path: str):
    """把路径编译成正则：`{x}` 与 `*` 视作单段通配。"""
    segments = [segment for segment in path.strip("/").split("/") if segment]
    parts = ["[^/]+" if segment.startswith("{") or segment == WILDCARD else re.escape(segment)
             for segment in segments]
    return re.compile("^/" + "/".join(parts) + "/?$")


def unmatchedFrontCalls() -> list:
    """前端发出、后端注册表里无对应路由的调用（显式列表，不静默）。"""
    routes = [(pathPattern(route), methods) for route, methods in registeredRoutes()]
    missing = []
    for path in clientFiles():
        for method, fullPath, rawPath in clientCalls(path):
            hit = next((methods for pattern, methods in routes if pattern.match(fullPath)), None)
            if hit is not None and method in hit:
                continue
            missing.append({
                "module": path.name,
                "method": method,
                "path": fullPath,
                "rawPath": rawPath,
                "verdict": "方法不匹配" if hit is not None else "路径未注册",
            })
    return sorted(missing, key=lambda row: (row["module"], row["path"], row["method"]))


def unconsumedBackendPrefixes() -> list:
    """后端已注册、却无任何前端客户端请求的一级前缀（显式列表，不静默）。"""
    declared = {head for path in clientFiles() for head in frontPrefixes(path)}
    roots = {prefixOf(route) for route, _ in registeredRoutes()}
    return sorted(root for root in roots if root and root not in declared)


def declaredModuleNames() -> list:
    """从清单**模块清单区**解析出清单声明的模块名。

    范围只取机器区第一节（模块清单）：第二节的差异表也逐行带模块名，
    不限定范围会把差异行当成模块声明，双向差集随即失真。

    与 `moduleFiles()`（磁盘实际）分开取数：两侧都读磁盘的话，
    「双向差集为空」会退化成恒真断言（自己与自己比，永远相等）。
    """
    if not INVENTORY_PATH.is_file():
        return []
    text = readSource(INVENTORY_PATH)
    start = text.find(INVENTORY_BEGIN)
    stop = text.find(INVENTORY_END, start)
    if start == -1 or stop == -1:
        return []
    body = text[start:stop]
    heading = MODULE_SECTION_HEADING
    if heading not in body:
        return []
    section = body[body.index(heading):]
    names = []
    for line in section.splitlines():
        match = re.match(r"\| [^|]+ \| `NeurUI/src/api/modules/([^`]+)` \|", line)
        if match:
            names.append(match.group(1))
    return sorted(names)


def moduleNameDiff() -> dict:
    """清单声明模块 ←→ 磁盘模块文件的双向差集（验收判据 1）。

    - `missingOnDisk`：清单声明了、磁盘上不存在（读者会照着找不到）；
    - `undeclared`：磁盘上有、清单没写（读者会漏掉）。
    """
    onDisk = {path.name for path in moduleFiles()}
    declared = set(declaredModuleNames())
    return {"missingOnDisk": sorted(declared - onDisk), "undeclared": sorted(onDisk - declared)}


# ---------------------------------------------------------------------------
# 清单机器区渲染（本文件是唯一事实源，这里是它的写侧）
# ---------------------------------------------------------------------------
# 根因回看：清单此前**只有手写正文、没有写者**。代码树一变它就漂移，而没有任何
# 命令能把它拉回来。故把写侧补齐：机器区的每一行都由本文件的判据产出，
# `--update` 落盘；守卫据此才能真做「重算 → 比对」。

SNAPSHOT_DATE_PATTERN = re.compile(r"快照日期\*\*：\s*(\d{4}-\d{2}-\d{2})")
#: 机器区第一节（模块清单）的标题——声明侧取数范围由它界定
MODULE_SECTION_HEADING = "## 一、前端 API 模块清单"


def extractSnapshotDate(text: str):
    """从清单机器区取快照日期；取不到或不可解析返回 None。"""
    found = SNAPSHOT_DATE_PATTERN.search(text)
    if not found:
        return None
    try:
        return datetime.strptime(found.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def renderInventoryTables() -> str:
    """清单机器区正文：模块清单 + 两组差集 + 快照纪律。

    本区整体由生成器产出，人只在区块之外补叙述性说明——这一段正是守卫
    「重算 + 逐字比对」的对象。
    """
    modules = frontModules()
    calls = sum(module["callCount"] for module in modules)
    gaps = unmatchedFrontCalls()
    roots = unconsumedBackendPrefixes()
    routes = registeredRoutes()
    lines = [
        INVENTORY_BEGIN,
        f"**生成命令**：`{GENERATE_COMMAND}`",
        f"**快照日期**：{date.today().isoformat()}",
        "",
        "本区为**生成物**，请勿手改；重跑上面的命令即可刷新。"
        f"快照周期上限 {SNAPSHOT_MAX_AGE_DAYS} 天，逾期由守卫点名。",
        "",
        f"事实源：前端 `NeurUI/src/api/modules/*.ts`（{len(modules)} 个模块 · {calls} 处调用），"
        f"后端 `create_app()` 装配后的真实路由表（{len(routes)} 条路由）。",
        "",
        "## 一、前端 API 模块清单",
        "",
        "| 模块 | 边界 | 请求到的一级前缀 | 调用数 |",
        "|------|------|------|------|",
    ]
    for module in modules:
        prefixes = "、".join(f"`{item}`" for item in module["prefixes"]) or "（无）"
        # 模块名不带 `.ts` 后缀：裸文件名会被引用扫描器读成「路径过期」的失效引用，
        # 而这里只是模块标识。边界列给全仓相对路径，读者顺着它能直接打开文件。
        lines.append(f"| {module['name'][:-3]} | `{module['file']}` | {prefixes} | {module['callCount']} |")
    lines += [
        "",
        "## 二、前端调用 ↔ 后端注册 差集",
        "",
    ]
    if gaps:
        lines += [
            f"下列 **{len(gaps)}** 处调用在本轮后端注册表里没有对应路由。"
            "这不等于「后端漏注册」——差异以显式列表暴露，由人去核；",
            "**删条目不等于修好**（清单的价值在于可信，藏差异则整表不可信）。",
            "",
            "| 模块 | 方法 | 调用路径 | 差异形态 |",
            "|------|------|------|------|",
        ]
        for row in gaps:
            # 模块名不带 `.ts`：此处标识的是模块，不是路径（路径见第一节边界列）
            lines.append(f"| {row['module'][:-3]} | {row['method']} | `{row['path']}` | {row['verdict']} |")
    else:
        lines.append("本轮前端调用**全部命中**后端注册表（差集为空）。")
    lines += [
        "",
        "## 三、后端已注册 ↔ 前端消费方 差集",
        "",
    ]
    if roots:
        lines += [
            f"下列 **{len(roots)}** 个后端一级前缀无任何前端客户端请求，属"
            "「后端已就位、前端待补消费方」的显式清单：",
            "",
            "| 后端一级前缀 |",
            "|------|",
        ]
        for root in roots:
            lines.append(f"| `{root}` |")
    else:
        lines.append("本轮后端前缀**全部有**前端消费方（差集为空）。")
    lines.append(INVENTORY_END)
    return "\n".join(lines)


def applyInventoryBlocks(text: str) -> str:
    """把机器区替换成生成器输出，区间之外一字不动。

    与 `writeInventory` 共用同一段替换逻辑——生成器与守卫因此可以对**同一份文本**
    做「注入漂移 → 拉回」的反向控制，不必各自实现一遍替换。
    缺标记时原样返回（缺区由守卫点名，生成器不替它造结构）。
    """
    rendered = renderInventoryTables()
    start = text.find(INVENTORY_BEGIN)
    stop = text.find(INVENTORY_END, start) if start != -1 else -1
    if start == -1 or stop == -1:
        return text
    return text[:start] + rendered + text[stop + len(INVENTORY_END):]


def writeInventory() -> int:
    """把机器区写回清单，区间之外一字不动；返回写入的区块数。"""
    current = readSource(INVENTORY_PATH)
    updated = applyInventoryBlocks(current)
    if updated != current:
        with io.open(INVENTORY_PATH, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
    return 1


def main(argv: list) -> int:
    if "--update" in argv:
        count = writeInventory()
        print(f"清单机器区已重生成：{displayPath(INVENTORY_PATH)}（{count} 个区块）")
        return 0
    modules = frontModules()
    gaps = unmatchedFrontCalls()
    roots = unconsumedBackendPrefixes()
    print(f"前端模块 {len(modules)} 个 · 调用 {sum(item['callCount'] for item in modules)} 处")
    print(f"后端真实路由 {len(registeredRoutes())} 条")
    print(f"模块双向差集 {moduleNameDiff()}")
    print(f"前端调用未命中后端 {len(gaps)} 处")
    print(f"后端前缀无前端消费 {len(roots)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
