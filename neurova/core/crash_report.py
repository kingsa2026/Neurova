# -*- coding: utf-8 -*-
"""后端启动崩溃远程上报：复用前端 errorReporter → 官网 error-report.php 链路。

背景（2026-09-04 安装机启动崩溃）：后端在干净机器上启动失败只写本地日志，
无人知晓。前端已有完整上报链路（errorReporter.ts → error-report.php →
SQLite + admin 查询页），后端复用同一端点与 schema，零服务端改动。

schema 对齐（web/includes/ErrorLogs.php 白名单）：
- client_id: UUID 形（前端 nv_client_id 同款生成与持久化策略）
- error_at:  秒级 ISO-8601 UTC（YYYY-MM-DDTHH:MM:SSZ）
- platform:  白名单内（desktop-windows / desktop-linux / linux / mac / web）
- source:    恒 'app'（后端来源，与前端 window/promise/vue 区分）
- error_code: [a-zA-Z0-9_:.-]{1,64}
- message/stack/app_version/ua: 长度封顶 500/4000/40/256

纪律：上报是尽力而为——任何失败（无网/限流/开关关闭）都只吞掉，
绝不影响启动或退出流程。开关：环境变量 NEUROVA_ERROR_REPORT=off 关闭。
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import sys
import uuid
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# 与前端 errorReporter.ts 同一端点（官网 nginx rewrite 白名单已登记）
REPORT_URL = "https://www.neurova.top/error-report.php"
_HTTP_TIMEOUT = 5.0  # 秒——启动失败场景不能卡死退出流程
_CLIENT_ID_FILE = Path("data") / "nv_client_id"

_PLATFORM_MAP = {
    "win32": "desktop-windows",
    "linux": "desktop-linux",
    "darwin": "mac",
}
_PLATFORM = _PLATFORM_MAP.get(sys.platform, "unknown")


def get_or_create_client_id(path: Path | None = None) -> str:
    """客户端代号：首次生成 UUID 持久化，此后永久复用（与前端同策略）。"""
    p = path or _CLIENT_ID_FILE
    try:
        if p.exists():
            cid = p.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-fA-F\-]{8,64}", cid):
                return cid
    except OSError:
        pass
    cid = str(uuid.uuid4())
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(cid, encoding="utf-8")
    except OSError:
        pass  # 不可写则退化为内存一次性 ID
    return cid


def _sanitize_error_code(code: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_:.\-]", "_", code)[:64]
    return safe or "unknown"


def build_report(
    error_code: str,
    message: str,
    stack: str = "",
    app_version: str = "",
    extra: dict | None = None,
) -> dict:
    """构造服务端 schema 兼容的报文（字段长度与前端封顶一致）。"""
    return {
        "error_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "client_id": get_or_create_client_id(),
        "platform": _PLATFORM,
        "source": "app",
        "error_code": _sanitize_error_code(error_code),
        "location": "backend-startup",
        "message": message[:500],
        "stack": stack[:4000],
        "app_version": app_version[:40],
        "ua": f"NeurovaBackend/{app_version} Python/{platform.python_version()}",
        "extra": extra,
    }


def _http_post(url: str, body: dict, timeout: float) -> dict:
    """seam：POST JSON（测试注入点）。返回解析后的响应 JSON。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "NeurovaBackend/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def report_startup_failure(
    exc: BaseException,
    stage: str = "startup",
    app_version: str = "",
    client_id_path: Path | None = None,
) -> bool:
    """上报启动失败。返回是否成功；永不抛异常。

    上报失败（无网/限流/关闭）只 debug 级记日志——它本身发生在故障路径上，
    不能再引入故障。
    """
    try:
        if os.environ.get("NEUROVA_ERROR_REPORT", "").strip().lower() == "off":
            return False
        body = build_report(
            error_code="backend_startup_failed",
            message=f"{type(exc).__name__}: {exc}",
            stack=_format_traceback(exc),
            app_version=app_version,
            extra={"stage": stage, "os": sys.platform},
        )
        # 优先用持久化的 client_id 文件（build_report 内默认全局路径，
        # 测试注入 client_id_path 时走显式参数）
        if client_id_path is not None:
            body["client_id"] = get_or_create_client_id(client_id_path)
        resp = _http_post(REPORT_URL, body, _HTTP_TIMEOUT)
        ok = bool(resp.get("ok"))
        if ok:
            logger.info("启动失败已上报远程错误日志（id=%s）", resp.get("id"))
        else:
            logger.debug("启动失败上报被拒: %s", resp.get("reason"))
        return ok
    except Exception as e:  # noqa: BLE001 - 上报失败绝不影响退出流程
        logger.debug("启动失败上报异常（忽略）: %s", e)
        return False


def _format_traceback(exc: BaseException) -> str:
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
