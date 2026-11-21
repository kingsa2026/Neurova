# -*- coding: utf-8 -*-
"""ACP 官方 registry 接入（G1 卡）：拉取 → 解析归一 → 快照 → 目录合并。

- 数据源：官方 ACP registry（``REGISTRY_URL``）。真实形状（2026-11 现拉）：
  ``{"version": "1.0.0", "agents": [{id, name, version, description, repository,
  website, authors, license, license_url, distribution, icon, ...}], "extensions": []}``；
  ``distribution`` 三形态：``npx``（package+args）/ ``binary``（按平台档
  archive+cmd+args）/ ``uvx``（package+args）。当前线上条目**未声明**
  ``protocolVersion``——解析器按可选键读取（声明了就透传，缺省 "1"），
  为 ACP v2 registry 就绪后「按声明版本协商」留好接口。
- 只登记不安装：registry 条目只进目录（command argv / install_hint /
  保守能力缺省），下载安装不做；binary 形态的 install_hint 指向官方归档。
- 安全边界：拉取**默认关**（只有管理面显式 refresh，无定时任务，目录读取
  路径零网络请求）；网络失败 stale 降级（保留上次快照并标注，不用空表、
  不臆造条目）；载荷体积上限 5MiB 超限拒收；timeout ≤ 15s。
- 单例：懒创建 DCL + ``threading.RLock``（AGENTS.md §3 纪律）。
"""
import json
import threading
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from neurova.agent.neuacp.catalog import conservativeCapabilities
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 官方 ACP registry 最新版地址（T3 从此发现 agent）。
REGISTRY_URL = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"

#: 拉取超时上限（秒）：单次 admin 手动刷新的 blocking 上界。
FETCH_TIMEOUT_S = 15.0

#: 载荷体积上限：5MiB，超限拒收（防异常大载荷拖垮内存/请求）。
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024

#: binary 形态平台档优先序：当前宿主 Windows 优先，其余确定性排序兜底。
_BINARY_PLATFORM_PREFERENCE = ("windows-x86_64", "linux-x86_64", "darwin-x86_64")


class RegistryError(Exception):
    """registry 接入错误基类（诚实形态上抛，不吞不兜底改写）。"""


class RegistryFetchError(RegistryError):
    """拉取失败：网络不可达 / 超时 / 载荷超限 / 非 JSON。"""


class RegistryParseError(RegistryError):
    """解析失败：载荷不是对象 / 缺 agents 数组 / agents 不是列表。"""


#: 拉取用的 User-Agent：官方 CDN 对缺省 ``Python-urllib`` UA 返回 403
#: （无客户端标识被拒）——如实自报身份的请求头，不是对报错的规避。
FETCH_USER_AGENT = "Neurova-ACP-Registry-Fetcher/1.0"


def _defaultOpen(url: str, timeout_s: float):
    """缺省打开器：带 User-Agent 的 ``urllib`` GET（超时由调用方 bounded）。"""
    request = urllib.request.Request(url, headers={"User-Agent": FETCH_USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout_s)


def _readCapped(stream: Any, max_bytes: int) -> bytes:
    """有界读取：累计超过 ``max_bytes`` 立即拒绝（不整读进内存再判）。"""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise RegistryFetchError(
                f"registry 载荷超过体积上限 {max_bytes} 字节，已拒收（防异常大载荷）")
        chunks.append(chunk)
    return b"".join(chunks)


def fetchRegistry(url: str = REGISTRY_URL, timeout_s: float = FETCH_TIMEOUT_S,
                  max_bytes: int = MAX_PAYLOAD_BYTES,
                  opener: Optional[Callable[[str, float], Any]] = None) -> dict:
    """拉取 registry 原始 JSON 载荷（有界超时 + 有界体积）。

    opener 供测试注入（缺省 ``urllib.request.urlopen``）；返回解析后的 dict。
    网络/超时/超限/JSON 错误一律以 ``RegistryFetchError`` 诚实上抛。
    """
    openFn = opener or _defaultOpen
    try:
        stream = openFn(url, timeout_s)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryFetchError(f"registry 拉取失败: {exc}") from exc
    try:
        raw = _readCapped(stream, max_bytes)
    except RegistryError:
        raise
    except Exception as exc:
        raise RegistryFetchError(f"registry 读取失败: {exc}") from exc
    finally:
        try:
            stream.close()
        except Exception:
            pass
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RegistryFetchError(f"registry 载荷不是合法 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RegistryFetchError("registry 载荷顶层不是 JSON 对象")
    return payload


def normalizeProtocolVersion(declared: Any) -> str:
    """条目声明的 protocolVersion → 目录透传值（缺省/非法保守回落 "1"）。

    acp_client.start 线上要求整数：声明须是纯数字（int/纯数字字符串）；
    其余（缺省、"2.0-beta"、布尔等）一律保守回落 "1"——v1 全量保持，
    绝不把不可协商的声明值往下传。
    """
    if declared is None or isinstance(declared, bool):
        return "1"
    text = str(declared).strip()
    return text if text.isdigit() else "1"


def _deriveLaunch(dist: Dict[str, Any], raw: Dict[str, Any]) -> tuple:
    """distribution → (command argv, requires_node, install_hint)。

    只登记不安装：npx/uvx 直接给出可运行 argv；binary 形态给出当前平台档的
    cmd+args（未下载安装前 which 探测诚实返回未安装），install_hint 指向
    官方归档下载地址；三者皆缺 → 空 argv + 网站/仓库线索。
    """
    website = str(raw.get("website") or raw.get("repository") or "")
    npx = dist.get("npx")
    if isinstance(npx, dict):
        package = str(npx.get("package") or "").strip()
        if package:
            args = [str(arg) for arg in (npx.get("args") or [])]
            return ["npx", package, *args], True, f"npx {package}"
    uvx = dist.get("uvx")
    if isinstance(uvx, dict):
        package = str(uvx.get("package") or "").strip()
        if package:
            args = [str(arg) for arg in (uvx.get("args") or [])]
            return ["uvx", package, *args], False, f"uvx {package}"
    binary = dist.get("binary")
    if isinstance(binary, dict) and binary:
        platform_keys = list(binary.keys())
        chosen = None
        for preferred in _BINARY_PLATFORM_PREFERENCE:
            if preferred in binary:
                chosen = preferred
                break
        if chosen is None:
            chosen = sorted(platform_keys)[0]
        spec = binary.get(chosen)
        if isinstance(spec, dict):
            cmd = str(spec.get("cmd") or "").strip()
            if cmd:
                args = [str(arg) for arg in (spec.get("args") or [])]
                archive = str(spec.get("archive") or "")
                return [cmd, *args], False, (archive or website)
    return [], False, website


def normalizeRegistryEntry(raw: Any) -> Optional[Dict[str, Any]]:
    """单条 registry agent → 目录条目（归一）；缺关键字段保守返回 None 丢弃。

    归一键：tool（=registry id）/ name / kind=acp / transport=stdio /
    command argv / requires_node / install_hint / capabilities（保守缺省单源）
    / protocol_version（声明缺省 "1"）/ source="registry" / origin="registry"
    / description / agent_version / website / repository。
    """
    if not isinstance(raw, dict):
        return None
    tool = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not tool or not name:
        return None
    dist = raw.get("distribution")
    dist = dist if isinstance(dist, dict) else {}
    command, requiresNode, installHint = _deriveLaunch(dist, raw)
    return {
        "tool": tool,
        "name": name,
        "kind": "acp",
        "transport": "stdio",
        "command": command,
        "requires_node": requiresNode,
        "install_hint": installHint,
        "capabilities": conservativeCapabilities(),
        "protocol_version": normalizeProtocolVersion(raw.get("protocolVersion")),
        "source": "registry",
        "origin": "registry",
        "description": str(raw.get("description") or "")[:500],
        "agent_version": str(raw.get("version") or ""),
        "website": str(raw.get("website") or ""),
        "repository": str(raw.get("repository") or ""),
    }


def parseRegistry(payload: Any) -> List[Dict[str, Any]]:
    """registry 载荷 → 归一目录条目列表（缺 agents 数组即解析失败）。

    非法条目保守跳过；同 id 重复取首个（保守，不静默覆盖）。
    """
    if not isinstance(payload, dict):
        raise RegistryParseError("registry 载荷顶层不是 JSON 对象")
    agents = payload.get("agents")
    if not isinstance(agents, list):
        raise RegistryParseError("registry 载荷缺 agents 数组（形状不符）")
    entries: List[Dict[str, Any]] = []
    seen = set()
    for raw in agents:
        entry = normalizeRegistryEntry(raw)
        if entry is None:
            continue
        if entry["tool"] in seen:
            continue
        seen.add(entry["tool"])
        entries.append(entry)
    return entries


class AcpRegistry:
    """registry 快照持有者：refresh（手动触发）/ entries / snapshotStatus。

    线程安全：快照换入与读取走 ``self._lock``（RLock）；网络 IO 在锁外做，
    不持锁拉取。失败路径**保留上次快照**并标注 stale（stale 降级，不用空表）。
    """

    def __init__(self, url: str = REGISTRY_URL, timeout_s: float = FETCH_TIMEOUT_S,
                 fetch_fn: Optional[Callable[[str, float], dict]] = None) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._fetch_fn = fetch_fn or fetchRegistry
        self._lock = threading.RLock()
        self._entries: List[Dict[str, Any]] = []
        self._status: Dict[str, Any] = {
            "fetched_at": None,
            "stale": False,
            "entry_count": 0,
            "error": None,
            "source_url": url,
        }

    def refresh(self, *, fetch_fn: Optional[Callable[[str, float], dict]] = None) -> Dict[str, Any]:
        """手动刷新快照（admin 端点触发；默认关，无定时任务）。

        成功 → 换入新快照，stale=False；失败 → 保留上次快照，标注 stale=True
        并回填 error（诚实形态，不吞错不臆造）。返回快照状态 dict。
        """
        fn = fetch_fn or self._fetch_fn
        try:
            payload = fn(self._url, self._timeout_s)
            entries = parseRegistry(payload)
        except Exception as exc:  # noqa: BLE001 - 失败按 stale 降级并诚实回填原因
            logger.warning("ACP registry 刷新失败（保留上次快照并标注 stale）: %s", exc)
            with self._lock:
                self._status = {
                    **self._status,
                    "stale": True,
                    "error": f"registry 刷新失败: {exc}",
                }
            return dict(self._status)
        with self._lock:
            self._entries = entries
            self._status = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "stale": False,
                "entry_count": len(entries),
                "error": None,
                "source_url": self._url,
            }
        return dict(self._status)

    def entries(self) -> List[Dict[str, Any]]:
        """当前快照条目（深拷贝；未刷新过返回空表——默认关）。"""
        with self._lock:
            return deepcopy(self._entries)

    def snapshotStatus(self) -> Dict[str, Any]:
        """快照状态：fetched_at / stale / entry_count / error / source_url。"""
        with self._lock:
            return dict(self._status)


#: 模块级单例（懒创建 DCL + RLock，AGENTS.md §3）。
_INSTANCE: Optional[AcpRegistry] = None
_INSTANCE_LOCK = threading.RLock()


def getAcpRegistry() -> AcpRegistry:
    """registry 单例（DCL + RLock）：目录合并与管理面共用一个快照源。"""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = AcpRegistry()
    return _INSTANCE


def resetAcpRegistry() -> None:
    """复位单例（测试隔离用）：下次 getAcpRegistry 重建空白快照。"""
    global _INSTANCE
    with _INSTANCE_LOCK:
        _INSTANCE = None
