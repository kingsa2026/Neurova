# -*- coding: utf-8 -*-
"""契约快照导出器：把当前后端 API 形状落成规范化 JSON 快照（实施计划项 5）。

事实源与取舍（docs/04-plans/2026-11-20-reference-aa-borrowable-mechanisms-plan.md 项 5）：
- 首选 `neurova.api.app.create_app()` **全量装配但不启动服务**——重量级装配
  （DB/Agent/渠道）发生在 startup 生命周期事件里，`create_app()` 本身只注册
  路由与中间件；取 `app.openapi()` 作为 API 形状。
- FastAPI 的 openapi 文档**不收录** websocket 路由与 `app.mount()` 的 ASGI 挂载，
  故 websocket 路径单独列进 `websocketPaths`，避免「活着的面在快照里不存在」。
- 若 `app.openapi()` 生成期失败（个别端点注解解析不了等），退化为「路由表提取器」：
  直接遍历 `app.routes`，只保 path + methods 的形状。`mode` 字段如实标注当次
  走的是哪条路（openapi / route-table），不谎报。

稳定性契约：快照里**不写任何时间戳/随机量**；序列化固定排序键 + 固定缩进 +
固定分隔符，同一代码树重复导出必须逐字节一致——否则 verify-diff 门
（`scripts/check_openapi_snapshot.py`）的 diff 无从谈起。

用法：
    python scripts/export_openapi.py                  # 写 contracts/openapi.snapshot.json
    python scripts/export_openapi.py --output <path>  # 写到指定路径
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

DEFAULT_SNAPSHOT_PATH = PROJECT_ROOT / "contracts" / "openapi.snapshot.json"

# 控制台若是 GBK，print 中文会 UnicodeEncodeError 打断导出。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _assembledApp():
    """装配真应用（不启动服务、不触发 startup 事件）。"""
    from neurova.api.app import create_app

    return create_app()


def _iterAppRoutes(app):
    """遍历装配后的全部路由，产出 `(route, 完整路径)`。

    新版 FastAPI 把 `include_router` 的产物包成 `_IncludedRouter`（懒挂载），
    直接遍历 `app.router.routes` 只能看到包裹层——必须经 `original_router`
    下钻，并拼上 `include_context.prefix` 才是真实挂载路径。
    """
    for route in app.router.routes:
        typeName = type(route).__name__
        if typeName == "_IncludedRouter":
            sub = getattr(route, "original_router", None)
            context = getattr(route, "include_context", None)
            prefix = (getattr(context, "prefix", "") or "") if context is not None else ""
            if sub is not None:
                for inner, innerPath in _iterAppRoutesFrom(sub.routes, prefix):
                    yield inner, innerPath
        else:
            yield route, getattr(route, "path", "")


def _iterAppRoutesFrom(routes, prefix: str):
    for route in routes:
        typeName = type(route).__name__
        if typeName == "_IncludedRouter":
            sub = getattr(route, "original_router", None)
            context = getattr(route, "include_context", None)
            nested = (getattr(context, "prefix", "") or "") if context is not None else ""
            if sub is not None:
                for inner, innerPath in _iterAppRoutesFrom(sub.routes, prefix + nested):
                    yield inner, innerPath
        else:
            yield route, prefix + getattr(route, "path", "")


def _websocketPaths(app) -> list:
    """openapi 文档不收录 websocket 路由，单独收集其完整路径（排序去重）。"""
    paths = set()
    for route, fullPath in _iterAppRoutes(app):
        if "WebSocket" in type(route).__name__ and fullPath:
            paths.add(fullPath)
    return sorted(paths)


def _normalizeOperationIds(app, schema: dict) -> None:
    """把多方法路由的 operationId 钉成确定性值（就地覆写）。

    根因：FastAPI 的 `generate_unique_id` 取 `list(route.methods)[0]`——
    `route.methods` 是**集合**，迭代序随进程哈希种子漂移，于是同一路由
    （如 /v1/mcp/agent-tools 的 GET+POST+DELETE）每次导出的 operationId
    都可能不同，快照无法逐字节稳定。这里按确定性公式覆写：
    `{name}_{path}_{sorted(methods)}`——单方法路由与 FastAPI 缺省公式同形
    （不受影响），多方法路由取排序拼接。显式声明了 operation_id 的路由
    尊重原值。
    """
    from fastapi.routing import APIRoute

    paths = schema.get("paths", {})
    for route, fullPath in _iterAppRoutes(app):
        if not isinstance(route, APIRoute) or getattr(route, "operation_id", None):
            continue
        pathItem = paths.get(fullPath)
        if not isinstance(pathItem, dict):
            continue
        base = re.sub(r"\W", "_", f"{route.name}{getattr(route, 'path_format', route.path)}")
        methods = "+".join(sorted(str(m).lower() for m in (route.methods or set())))
        deterministic = f"{base}_{methods}"
        for method in route.methods:
            operation = pathItem.get(str(method).lower())
            if isinstance(operation, dict) and "operationId" in operation:
                operation["operationId"] = deterministic


def _routeTablePaths(app) -> dict:
    """路由表提取器：遍历装配路由取 path → methods 形状（openapi 的兜底）。"""
    paths: dict = {}
    for route, fullPath in _iterAppRoutes(app):
        if not fullPath:
            continue
        methods = sorted(str(m).upper() for m in (getattr(route, "methods", None) or set()))
        if not methods:
            typeName = type(route).__name__
            if "WebSocket" in typeName:
                methods = ["WEBSOCKET"]
            elif typeName == "Mount":
                methods = ["MOUNT"]
            else:
                methods = ["UNKNOWN"]
        entry = paths.setdefault(fullPath, {"methods": []})
        for method in methods:
            if method not in entry["methods"]:
                entry["methods"].append(method)
    return {path: paths[path] for path in sorted(paths)}


def buildSnapshot() -> dict:
    """导出当前 API 形状快照（可被测试 monkeypatch 的单一入口）。"""
    app = _assembledApp()
    routeCount = len(app.router.routes)
    try:
        schema = app.openapi()
        _normalizeOperationIds(app, schema)
        return {
            "generator": "scripts/export_openapi.py",
            "mode": "openapi",
            "routeCount": routeCount,
            "websocketPaths": _websocketPaths(app),
            "openapi": schema,
        }
    except Exception as exc:  # noqa: BLE001 - openapi 生成失败时退化为路由表提取
        print(
            f"[export_openapi] app.openapi() 生成失败，退化为路由表提取器："
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "generator": "scripts/export_openapi.py",
            "mode": "route-table",
            "routeCount": routeCount,
            "paths": _routeTablePaths(app),
        }


def serializeSnapshot(snapshot: dict) -> str:
    """稳定序列化：排序键 + 固定缩进 + 换行收尾，重复导出逐字节一致。"""
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="导出后端 API 形状快照（实施计划项 5）")
    parser.add_argument("--output", default=str(DEFAULT_SNAPSHOT_PATH), help="快照落盘路径")
    parser.add_argument("--quiet", action="store_true", help="不打印过程信息")
    args = parser.parse_args(argv)

    snapshot = buildSnapshot()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serializeSnapshot(snapshot), encoding="utf-8", newline="\n")

    if snapshot.get("mode") == "openapi":
        pathCount = len(snapshot.get("openapi", {}).get("paths", {}))
    else:
        pathCount = len(snapshot.get("paths", {}))
    if not args.quiet:
        print(
            f"[export_openapi] mode={snapshot.get('mode')} "
            f"路由对象={snapshot.get('routeCount')} 路径数={pathCount} → {output}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
