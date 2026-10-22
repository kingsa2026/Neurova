# -*- coding: utf-8 -*-
"""插件远程源的注册表与取回咽喉（§6-390 票二乙，用户 2026-10-22 拍「开，复用市场链」）。

## 这一层只为三件事存在

1. **白名单在取回之前**：只认已注册源的域名；未注册 host、非 http(s) 协议、
   以及**重定向到别的 host**，一律在发出/接受字节之前拒（拒因是结构化标识）。
2. **取回即受预算约束**：单包上限与条目上限在解包那一步由 `security/safe_archive`
   执行；本模块只负责"把字节拿回来且不超过 MAX_PLUGIN_ZIP_BYTES"。上限数值不在这里
   另写一份——传参进 `safe_extract_zip(maxPayloadBytes=…)` 时取本模块常量。
3. **来源可追溯**：取回成功后把 `{url, host, bytes, fetched_at}` 交给调用方（安装链）
   用于审计与读数；这里不落安装状态（那是 `state.json` 的事，单点不重复）。

## 与市场侧那份的关系（教义第 7 条：不新造一套）

市场侧已有 `skills/market_sources._http_get`（域名白名单 + 超时）；插件侧**不 import 它**，
因为它的白名单来自"技能市场注册源表"，与插件源是两本不同的授权目录——共用代码会把
两张表混成一张。**共用的部分是机制与数值口径**：协议只认 http(s)、先判 host 再发请求、
重定向后再判一次 host、大小/条目上限沿用 `safe_archive` 的参数面。

## 存储

`<插件根>/sources.json`：`{"version": 1, "sources": [{"host": "...", "baseUrl": "..."}]}`。
写盘走 `core/atomic_io.atomic_write_text`，坏文件改名隔离并**响亮报**（不把"读不懂"读成
"没有任何源"——那会让所有远程安装静默变成 403，而没人知道为什么）。
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from neurova.core.atomic_io import atomic_write_text, quarantine_corrupt_file
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 插件包单包上限（压缩字节数）。与技能市场那 10MB 不同源、也不同值：插件带前端资源，
#: 但"不同"要写在这里而不是散在调用点——两条通道各有自己的预算，不互相借用。
MAX_PLUGIN_ZIP_BYTES = 50 * 1024 * 1024
#: 解包条目上限（透传给 `safe_extract_zip(maxEntries=…)`）。
MAX_PLUGIN_ZIP_ENTRIES = 2000
#: 取回超时（秒）。
PLUGIN_FETCH_TIMEOUT_SECONDS = 30

SOURCE_FILE_NAME = "sources.json"
SOURCE_STORE_VERSION = 1

#: 结构化拒因（进 `plugin.py` 的 `_REASON_TO_STATUS` 闭集）。
REASON_SOURCE_NOT_ALLOWED = "plugin_source_not_allowed"
REASON_FETCH_FAILED = "plugin_fetch_failed"
REASON_FETCH_TOO_LARGE = "plugin_fetch_too_large"
REASON_ARCHIVE_UNSAFE = "plugin_archive_unsafe"


class PluginSourceError(Exception):
    """取回侧的具名失败：`reason` 是闭集标识，`detail` 给人读。"""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail


def sourcesPath(pluginRoot: Any) -> Path:
    return Path(pluginRoot) / SOURCE_FILE_NAME


def loadSources(pluginRoot: Any) -> List[Dict[str, str]]:
    """读注册源表；坏文件隔离并响亮报（返回空表，但日志里点名原因）。"""
    path = sourcesPath(pluginRoot)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        quarantined = quarantine_corrupt_file(path)
        logger.error("插件源表无法解析，已隔离 %s：%s（本轮按空表起，原文件未覆盖）",
                     quarantined, e)
        return []
    if not isinstance(data, dict) or data.get("version") != SOURCE_STORE_VERSION:
        quarantined = quarantine_corrupt_file(path)
        logger.error("插件源表版本不认识（现值 %r，期望 %r），已隔离 %s——不做自动映射",
                     data.get("version") if isinstance(data, dict) else "<非映射>",
                     SOURCE_STORE_VERSION, quarantined)
        return []
    entries = data.get("sources")
    if not isinstance(entries, list):
        return []
    cleaned: List[Dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("跳过格式不合法的插件源条目：%r", entry)
            continue
        host = str(entry.get("host") or "").strip().lower()
        baseUrl = str(entry.get("baseUrl") or "").strip()
        if not host or not baseUrl:
            logger.warning("跳过缺 host/baseUrl 的插件源条目：%r", entry)
            continue
        cleaned.append({"host": host, "baseUrl": baseUrl})
    return cleaned


def saveSources(pluginRoot: Any, entries: List[Dict[str, str]]) -> bool:
    payload = {"version": SOURCE_STORE_VERSION, "sources": entries}
    try:
        atomic_write_text(sourcesPath(pluginRoot),
                          json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("插件源表写入失败：%s", e)
        return False


def registerSource(pluginRoot: Any, host: str, baseUrl: str) -> bool:
    """登记一个源：host 与 baseUrl 的 host 必须一致（否则登记的是一张假名单）。"""
    host = str(host or "").strip().lower()
    baseUrl = str(baseUrl or "").strip()
    parsed = urlparse(baseUrl)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise PluginSourceError(REASON_SOURCE_NOT_ALLOWED,
                                "源地址必须是 http(s)：%r" % baseUrl)
    if parsed.hostname.lower() != host:
        raise PluginSourceError(REASON_SOURCE_NOT_ALLOWED,
                                "host 与 baseUrl 不一致：%r vs %r" % (host, parsed.hostname))
    entries = [e for e in loadSources(pluginRoot) if e["host"] != host]
    entries.append({"host": host, "baseUrl": baseUrl})
    entries.sort(key=lambda e: e["host"])
    return saveSources(pluginRoot, entries)


def removeSource(pluginRoot: Any, host: str) -> bool:
    host = str(host or "").strip().lower()
    entries = [e for e in loadSources(pluginRoot) if e["host"] != host]
    return saveSources(pluginRoot, entries)


def allowedHosts(pluginRoot: Any) -> List[str]:
    return sorted({e["host"] for e in loadSources(pluginRoot)})


def isAllowedSource(pluginRoot: Any, url: str) -> bool:
    """发请求**之前**的那道判：协议 + host 必须在已注册表里。"""
    try:
        parsed = urlparse(str(url or ""))
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    return bool(host) and host in set(allowedHosts(pluginRoot))


def fetchArchive(pluginRoot: Any, url: str) -> Dict[str, Any]:
    """按白名单取回一个插件包的字节。

    顺序是刻意的：**先判 host → 再发请求 → 读完后再判一次最终 URL 的 host**
    （urllib 默认跟随重定向；不复查的话，一个白名单 host 可以 302 到任意地方）。
    超过 `MAX_PLUGIN_ZIP_BYTES` 立即中止，不把超限字节读进内存。
    """
    if not isAllowedSource(pluginRoot, url):
        raise PluginSourceError(
            REASON_SOURCE_NOT_ALLOWED,
            "插件源未注册：%s（已注册：%s）" % (url, allowedHosts(pluginRoot) or "无"))

    request = urllib.request.Request(
        str(url), headers={"Accept": "*/*", "User-Agent": "Neurova-Plugin/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=PLUGIN_FETCH_TIMEOUT_SECONDS) as response:
            finalHost = (urlparse(response.geturl()).hostname or "").lower()
            if finalHost not in set(allowedHosts(pluginRoot)):
                raise PluginSourceError(
                    REASON_SOURCE_NOT_ALLOWED,
                    "取回被重定向到未注册 host：%s" % finalHost)
            status = getattr(response, "status", 200)
            if status != 200:
                raise PluginSourceError(REASON_FETCH_FAILED, "HTTP %s for %s" % (status, url))
            payload = response.read(MAX_PLUGIN_ZIP_BYTES + 1)
            if len(payload) > MAX_PLUGIN_ZIP_BYTES:
                raise PluginSourceError(
                    REASON_FETCH_TOO_LARGE,
                    "插件包超过单包上限 %s 字节：%s" % (MAX_PLUGIN_ZIP_BYTES, url))
    except PluginSourceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise PluginSourceError(REASON_FETCH_FAILED, "取回失败：%s（%s）" % (url, e))

    return {
        "url": str(url),
        "host": (urlparse(str(url)).hostname or "").lower(),
        "bytes": payload,
        "size": len(payload),
        "fetched_at": time.time(),
    }


__all__ = [
    "MAX_PLUGIN_ZIP_BYTES",
    "MAX_PLUGIN_ZIP_ENTRIES",
    "PLUGIN_FETCH_TIMEOUT_SECONDS",
    "REASON_ARCHIVE_UNSAFE",
    "REASON_FETCH_FAILED",
    "REASON_FETCH_TOO_LARGE",
    "REASON_SOURCE_NOT_ALLOWED",
    "PluginSourceError",
    "allowedHosts",
    "fetchArchive",
    "isAllowedSource",
    "loadSources",
    "registerSource",
    "removeSource",
    "saveSources",
    "sourcesPath",
]
