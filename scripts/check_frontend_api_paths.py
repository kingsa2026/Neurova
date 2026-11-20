# -*- coding: utf-8 -*-
"""前端 API 路径守卫：扫描请求路径字面量并逐条核对契约快照（实施计划项 5）。

防「前端路径漂移 404」：`NeurUI/src/api/modules/*.ts` 与 `NeurUI/src/api/index.ts`
里的请求路径字面量（`'/xxx'`、`"/xxx"`、`` `/xxx/${id}` `` 模板串、axios/fetch 调用）
逐条核对存在于 `contracts/openapi.snapshot.json` 的路径集合；不存在的路径即红。

比对口径：前端 axios baseURL 已含 `/api/v1`，字面量形如 `/audio/transcribe`；
快照路径形如 `/api/v1/audio/transcribe`——比对时把快照的 `/api/v1` 前缀剥掉，
且两侧的路径参数段（`{agent_id}` / `${id}`）统一归一成 `*`，只比结构。

扫描器说明：手写一个轻量词法扫描而非裸正则——模块里存在嵌套模板串
（`` `${base}/x${qs ? `?${qs}` : ''}` ``），裸正则会截断；且需跳过注释、
解析模块级 `const BASE = '/xxx'` 前缀常量（其字面量本身不是请求路径，
只有被 `${BASE}` 引用或被 `api.get(BASE)` 直呼时才参与比对）。

用法：
    python scripts/check_frontend_api_paths.py                 # 扫仓内真实前端
    python scripts/check_frontend_api_paths.py --project-root <p>

退出码：0 = 全部命中；1 = 存在快照里没有的路径 / 快照缺失。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

#: 前端 axios baseURL 前缀（NeurUI/src/config/index.ts 的 apiBaseUrl 缺省值）
API_PREFIX = "/api/v1"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# 轻量词法扫描
# ---------------------------------------------------------------------------

#: 模块级路径前缀常量：`const BASE = '/console'`（开引号紧随 `= ` 之后）
_CONST_PREFIX_RE = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*$")
#: 非字面量右值的常量：`const base = config.apiBaseUrl`（baseURL 形）
_CONST_ANY_RE = re.compile(r"(?:const|let|var)\s+(\w+)\s*=\s*([^;\n]+)")
_BASEURL_HINTS = ("apiBaseUrl", "VITE_API_BASE_URL")


def _skipQuoted(text: str, i: int) -> tuple:
    """跳过一个引号字符串（i 停在开引号），返回 (内容, 结束下标)。"""
    quote = text[i]
    n = len(text)
    j = i + 1
    buf = []
    while j < n:
        ch = text[j]
        if ch == "\\":
            buf.append(text[j : j + 2])
            j += 2
            continue
        if ch == quote:
            break
        buf.append(ch)
        j += 1
    return "".join(buf), min(j + 1, n)


def _readInterp(text: str, i: int) -> tuple:
    """读 `${` 之后的插值表达式，返回 (表达式文本, 越过配对 `}` 的下标)。

    支持嵌套花括号、嵌套字符串与嵌套模板串。
    """
    depth = 1
    start = i
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ("'", '"'):
            _, i = _skipQuoted(text, i)
            continue
        if ch == "`":
            _, i = _scanTemplate(text, i + 1)
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "{":
            depth += 1
            i += 2
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return text[start:i], i


def _scanTemplate(text: str, i: int) -> tuple:
    """扫一个模板串（i 停在开反引号之后），返回 (分段列表, 结束下标)。

    分段列表是 [("s", 静态文本) / ("i", 插值表达式), ...] 交替序列。
    """
    parts = []
    buf = []
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            buf.append(text[i : i + 2])
            i += 2
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "{":
            parts.append(("s", "".join(buf)))
            expr, i = _readInterp(text, i + 2)
            parts.append(("i", expr))
            buf = []
            continue
        if ch == "`":
            parts.append(("s", "".join(buf)))
            return parts, i + 1
        buf.append(ch)
        i += 1
    parts.append(("s", "".join(buf)))
    return parts, i


def _baseConsts(text: str) -> dict:
    """模块级前缀常量映射：名字 -> 字面量值（'/console'）或 None（baseURL 形）。"""
    consts: dict = {}
    for match in _CONST_ANY_RE.finditer(text):
        name, rhs = match.group(1), (match.group(2) or "").strip()
        if name in consts:
            continue
        if rhs.startswith("'") or rhs.startswith('"'):
            value = rhs.strip("'\"")
            consts[name] = value if value.startswith("/") else None
        elif any(hint in rhs for hint in _BASEURL_HINTS):
            consts[name] = None  # baseURL 形：运行时等于 /api/v1，比对时剥掉
    # 传播：右值引用了已知 baseURL 常量的派生常量（如
    # `const wsBase = base.replace(/^http/, 'ws')`）同样是 baseURL 形。
    for match in _CONST_ANY_RE.finditer(text):
        name, rhs = match.group(1), (match.group(2) or "")
        if name in consts:
            continue
        for known in list(consts):
            if consts[known] is None and re.search(r"\b" + known + r"\b", rhs):
                consts[name] = None
                break
    return consts


def _interpToken(expr: str, consts: dict, prevChar: str, nextChar: str) -> str:
    """把一个插值表达式换算成路径片段。

    - 已知前缀常量（BASE='/console'）→ 替换为其值；
    - baseURL 形（config.apiBaseUrl / env）→ 丢弃（快照侧已剥 /api/v1）；
    - 其余：前后任一侧带 '/' 视为路径参数 → '*'；否则视为查询串等非路径
      插值 → 丢弃。
    """
    name = expr.strip()
    if name in consts:
        return consts[name] or ""
    if any(hint in expr for hint in _BASEURL_HINTS):
        return ""
    if prevChar == "/" or nextChar == "/":
        return "*"
    return ""


def _scanLiterals(text: str) -> set:
    """扫出文件里所有请求路径候选字面量（未归一的原始串）。"""
    consts = _baseConsts(text)
    candidates: set = set()
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "/" and i + 1 < n and text[i + 1] == "/":  # 行注释
            newline = text.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":  # 块注释
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if ch in ("'", '"'):
            value, i = _skipQuoted(text, i)
            if value.startswith("/") and not value.startswith("//") and "://" not in value:
                # 常量右值（`const BASE = '/console'`）不是请求路径；
                # 除非该常量被 api.get(BASE) 这类调用直接使用。
                openQuote = i - len(value) - 2
                prefixMatch = _CONST_PREFIX_RE.search(text[max(0, openQuote - 200) : openQuote])
                if prefixMatch:
                    constName = prefixMatch.group(1)
                    if re.search(r"\.\w+\(\s*" + constName + r"\b", text):
                        candidates.add(value)
                else:
                    candidates.add(value)
            continue
        if ch == "`":
            parts, i = _scanTemplate(text, i + 1)
            pieces = []
            for index, (kind, value) in enumerate(parts):
                if kind == "s":
                    pieces.append(value)
                    continue
                prevChar = pieces[-1][-1] if pieces and pieces[-1] else ""
                nextChar = ""
                if index + 1 < len(parts) and parts[index + 1][1]:
                    nextChar = parts[index + 1][1][0]
                pieces.append(_interpToken(value, consts, prevChar, nextChar))
            joined = "".join(pieces)
            if joined.startswith("/") and not joined.startswith("//") and "://" not in joined:
                candidates.add(joined)
            continue
        i += 1
    return candidates


# ---------------------------------------------------------------------------
# 归一与比对
# ---------------------------------------------------------------------------


def normalizePath(path: str) -> str:
    """路径归一：剥查询/锚点、剥 /api/v1 前缀、参数段统一成 `*`、去空段与尾斜杠。"""
    p = path.split("?", 1)[0].split("#", 1)[0].strip()
    if p == API_PREFIX or p.startswith(API_PREFIX + "/"):
        p = p[len(API_PREFIX) :] or "/"
    segments = []
    for seg in p.split("/"):
        if not seg:
            continue
        if seg == "*" or (seg.startswith("{") and seg.endswith("}")):
            segments.append("*")
        else:
            segments.append(seg)
    return "/" + "/".join(segments) if segments else "/"


def extractFrontendPaths(text: str) -> set:
    """从一段前端源码里抽出归一后的请求路径集合。"""
    paths = set()
    for raw in _scanLiterals(text):
        normalized = normalizePath(raw)
        if normalized and normalized != "/":
            paths.add(normalized)
    return paths


def snapshotPathSet(snapshot: dict) -> set:
    """快照 → 归一路径集合（openapi paths 或路由表 paths，外加 websocket 路径）。"""
    paths = set()
    if snapshot.get("mode") == "openapi":
        paths |= set((snapshot.get("openapi") or {}).get("paths") or {})
    else:
        paths |= set(snapshot.get("paths") or {})
    paths |= set(snapshot.get("websocketPaths") or [])
    return {normalizePath(p) for p in paths if p}


def iterFrontendFiles(projectRoot: Path) -> list:
    """被守卫覆盖的前端文件：api/modules/*.ts 全集 + api/index.ts。"""
    root = Path(projectRoot)
    files = []
    modulesDir = root / "NeurUI" / "src" / "api" / "modules"
    if modulesDir.is_dir():
        files.extend(sorted(modulesDir.glob("*.ts")))
    barrel = root / "NeurUI" / "src" / "api" / "index.ts"
    if barrel.is_file():
        files.append(barrel)
    return files


def _segmentsCovered(frontendSegs: list, snapshotSegs: list) -> bool:
    """逐段比对：字面段须相等，任一侧为参数段（`*`）即放行。"""
    if len(frontendSegs) != len(snapshotSegs):
        return False
    for front, snap in zip(frontendSegs, snapshotSegs):
        if front == snap or front == "*" or snap == "*":
            continue
        return False
    return True


def missingPaths(frontendPaths, snapshotPaths) -> list:
    """前端路径集合里不被快照支持的条目（排序返回，便于输出稳定）。

    覆盖判据：前端路径存在一条段数相同的快照路径，且逐段字面相等或任一侧
    为参数段——前端 `` `${BASE}/x/${id}/${action}` `` 这类参数化模板，只要
    后端为该动作提供了具体路由（如 `/x/{sid}/approve`）即算命中。
    """
    snapshotSegs = [path.strip("/").split("/") for path in snapshotPaths if path.strip("/")]
    missing = []
    for path in sorted(frontendPaths):
        segs = path.strip("/").split("/")
        if not segs or not any(_segmentsCovered(segs, candidate) for candidate in snapshotSegs):
            missing.append(path)
    return missing


def collectMissingPaths(projectRoot, known=None) -> dict:
    """返回 {缺失路径: [引用文件, ...]}；known 缺省时读仓库真快照。"""
    root = Path(projectRoot)
    if known is None:
        snapshotPath = root / "contracts" / "openapi.snapshot.json"
        known = snapshotPathSet(loadSnapshot(snapshotPath))
    missing: dict = {}
    for file in iterFrontendFiles(root):
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file.read_text(encoding="utf-8", errors="replace")
        for path in missingPaths(extractFrontendPaths(text), known):
            relative = str(file.relative_to(root)).replace("\\", "/")
            missing.setdefault(path, []).append(relative)
    return missing


def loadSnapshot(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="前端 API 路径守卫（实施计划项 5）")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="仓库根目录")
    parser.add_argument("--snapshot", default=None, help="快照路径（缺省 <root>/contracts/openapi.snapshot.json）")
    args = parser.parse_args(argv)

    root = Path(args.project_root)
    snapshotPath = Path(args.snapshot) if args.snapshot else root / "contracts" / "openapi.snapshot.json"
    if not snapshotPath.is_file():
        print(f"[check_frontend_api_paths] 快照不存在：{snapshotPath}")
        print("修法：python scripts/export_openapi.py 生成并提交 contracts/openapi.snapshot.json")
        return 1
    try:
        known = snapshotPathSet(loadSnapshot(snapshotPath))
    except Exception as exc:  # noqa: BLE001 - 快照损坏必须红，不许静默
        print(f"[check_frontend_api_paths] 快照不是合法 JSON：{exc}")
        return 1

    files = iterFrontendFiles(root)
    extracted = 0
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = file.read_text(encoding="utf-8", errors="replace")
        extracted += len(extractFrontendPaths(text))

    missing = collectMissingPaths(root, known)
    if not missing:
        print(
            f"[check_frontend_api_paths] 前端 {len(files)} 个文件、{extracted} 条请求路径"
            f"全部命中契约快照（快照路径 {len(known)} 条）"
        )
        return 0

    print(f"[check_frontend_api_paths] 前端引用了 {len(missing)} 条快照里不存在的请求路径（必 404）：")
    for path in sorted(missing):
        print(f"  {path}  ←  {', '.join(missing[path])}")
    print("修法：修正前端路径；若后端确已提供该路由，则重新导出快照（python scripts/export_openapi.py）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
