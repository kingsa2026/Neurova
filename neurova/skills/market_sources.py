"""
远端市场源适配层：阿里云 skills.aliyun.com + 讯飞 skill.xfyun.cn

两个源均为 SKILL.md 格式技能包、匿名只读 API（2026-08-31 实测）：
- 阿里云: GET /api/public/skills           → {code,message,data:[{categoryCode,total,list:[...]}]}
          GET /api/public/skills/{name}/download → ZIP
- 讯飞:   GET /api/v1/skills?page=0&size=N  → {items:[{slug,summary,stats,latestVersion,...}], nextCursor}
          GET /api/v1/skills/{ns}/{slug}/download → ZIP（列表 slug 形如 "ns--slug"）
          GET /api/v1/search?q=             → {results:[{slug,...}]}（ClawHub 兼容）

设计: 源条目映射为 catalog entry（skill_id 加 "{key}--" 命名空间前缀防碰撞，
带 source 标记），sync 时 upsert 进 MarketStore —— 浏览/安装/联邦注册全部
复用既有 marketplace 链路。同步白名单只覆盖远端字段，admin 本地改动
（rating 等）不被覆盖。

契约见 tests/unit/skills/test_market_sources.py。
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 单技能包大小上限（与讯飞官方规范一致 10MB）
MAX_SKILL_ZIP_BYTES = 10 * 1024 * 1024
# 安全解压条目上限
MAX_ZIP_ENTRIES = 500
HTTP_TIMEOUT = 20


def _http_get(url: str) -> bytes:
    """GET 指定 URL，非 200 抛 OSError。仅允许已注册市场源白名单域。"""
    host = (urlparse(url).hostname or "").lower()
    if host not in _remote_hosts():
        raise ValueError(f"blocked non-whitelisted market host: {host}")
    req = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "Neurova-Market/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        if resp.status != 200:
            raise OSError(f"HTTP {resp.status} for {url}")
        return resp.read()


class RemoteSkillSource:
    """远端源基类：fetch_entries(原始条目) + map_entry(catalog entry)"""

    key: str = ""
    base_url: str = ""

    def list_url(self, page: int, size: int) -> str:
        raise NotImplementedError

    def fetch_entries(self) -> List[Dict[str, Any]]:
        """拉取远端原始条目列表"""
        raise NotImplementedError

    def map_entry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """远端原始条目 → catalog entry（子类必须实现映射字段）"""
        raise NotImplementedError

    def download(self, url: str) -> Any:
        """下载技能包（返回带 data 属性的响应对象；测试可替换）"""
        payload = _http_get(url)
        return type("R", (), {"data": payload})()

    # catalog entry 同步白名单（远端可控字段；rating 等本地字段不在列）
    SYNC_FIELDS = ("name", "description", "author", "version", "category", "tags", "downloads", "download_url", "updated_at")

    def qualified_id(self, slug: str) -> str:
        return f"{self.key}--{slug}"

    def sync_fields(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {k: entry[k] for k in self.SYNC_FIELDS if k in entry}


class AliyunSkillsSource(RemoteSkillSource):
    """阿里云官方 Agent Skills 门户 (skills.aliyun.com)

    官方文档: help.aliyun.com/zh/skillsportal/ ；技能包源仓库
    github.com/aliyun/alibabacloud-aiops-skills。/api/public/* 实测免鉴权，
    全量 22 类目 ~258 技能单响应返回。
    """

    key = "aliyun"
    base_url = "https://skills.aliyun.com/api/public"

    def list_url(self, page: int, size: int) -> str:
        return f"{self.base_url}/skills"

    def fetch_entries(self) -> List[Dict[str, Any]]:
        body = json.loads(_http_get(self.list_url(0, 0)).decode("utf-8"))
        data = body.get("data") or []
        entries: List[Dict[str, Any]] = []
        for group in data:
            entries.extend(group.get("list") or [])
        return entries

    def map_entry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        slug = str(raw.get("skillName") or "").strip()
        name = str(raw.get("displayName") or slug)
        desc = str(raw.get("description") or raw.get("descriptionEn") or "")
        # 中英双语描述：中文优先，英文补充
        if raw.get("descriptionEn") and desc and raw["descriptionEn"] != desc:
            desc = f"{desc}\n{raw['descriptionEn']}" if not desc.endswith(raw["descriptionEn"]) else desc
        return {
            "skill_id": self.qualified_id(slug),
            "source": self.key,
            "name": name,
            "description": desc,
            "author": "阿里云",
            "version": str(raw.get("version") or "1.0.0"),
            "category": str(raw.get("categoryCode") or "others"),
            "tags": [t for t in [raw.get("categoryName")] if t],
            "downloads": int(raw.get("totalInstallCount") or raw.get("installCount") or 0),
            "rating": 0.0,
            "download_url": f"{self.base_url}/skills/{slug}/download",
            "updated_at": raw.get("updatedAt"),
        }


class XfyunSkillsSource(RemoteSkillSource):
    """科大讯飞 Astron SkillHub (skill.xfyun.cn)

    开源实现 github.com/iflytek/skillhub（Apache 2.0），API 设计文档
    docs/06-api-design.md。列表/详情/下载实测匿名可用；slug 形如
    "ns--slug"，详情/下载路径为 /api/v1/skills/{ns}/{slug}。
    """

    key = "xfyun"
    base_url = "https://skill.xfyun.cn/api/v1"

    def list_url(self, page: int, size: int) -> str:
        return f"{self.base_url}/skills?page={page}&size={size}"

    def fetch_entries(self) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        page = 0
        while True:
            body = json.loads(_http_get(self.list_url(page, 50)).decode("utf-8"))
            items = body.get("items") or []
            entries.extend(items)
            cursor = body.get("nextCursor")
            if not items or not cursor:
                break
            page += 1
            if page >= 40:  # 防御上限
                break
        return entries

    @staticmethod
    def split_slug(slug: str) -> tuple:
        """"ns--slug" → (ns, slug)；无 ns 前缀返回 (None, slug)"""
        if "--" in slug:
            ns, _, rest = slug.partition("--")
            return ns, rest
        return None, slug

    def map_entry(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        slug = str(raw.get("slug") or "").strip()
        ns, bare = self.split_slug(slug)
        latest = raw.get("latestVersion") or {}
        stats = raw.get("stats") or {}
        author = str(ns or raw.get("ownerDisplayName") or "xfyun")
        # 下载路径: 有 ns 前缀走 /skills/{ns}/{slug}/download；
        # 裸 slug 走 ClawHub 兼容端点 /download/{slug}（实测匿名可用）
        if ns:
            download_url = f"{self.base_url}/skills/{ns}/{bare}/download"
        else:
            download_url = f"{self.base_url}/download/{slug}"
        return {
            "skill_id": self.qualified_id(slug),
            "source": self.key,
            "name": str(raw.get("displayName") or bare),
            "description": str(raw.get("summary") or ""),
            "author": author,
            "version": str(latest.get("version") or "1.0.0"),
            "category": "agent",
            "tags": list(raw.get("tags") or [])[:5] if isinstance(raw.get("tags"), (list, dict)) else [],
            "downloads": int(stats.get("downloads") or 0),
            "rating": 0.0,
            "download_url": download_url,
            "updated_at": raw.get("updatedAt"),
        }


# ── 注册表 ──

_SOURCES: Dict[str, RemoteSkillSource] = {}


def _registry() -> Dict[str, RemoteSkillSource]:
    global _SOURCES
    if not _SOURCES:
        for src in (AliyunSkillsSource(), XfyunSkillsSource()):
            _SOURCES[src.key] = src
    return _SOURCES


def get_source(key: str) -> RemoteSkillSource:
    src = _registry().get(key)
    if src is None:
        raise ValueError(f"unknown market source: {key}. available: {sorted(_registry())}")
    return src


def list_sources() -> List[RemoteSkillSource]:
    return list(_registry().values())


def _remote_hosts() -> set:
    """已注册市场源的域名白名单"""
    hosts = set()
    for src in list_sources():
        try:
            hosts.add((urlparse(src.base_url).hostname or "").lower())
        except Exception:  # noqa: BLE001
            continue
    return hosts


def is_remote_market_url(url: str) -> bool:
    """URL 是否指向已注册远端市场源（决定安装走真实下载还是本地模拟）"""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return host in _remote_hosts()


# ── 同步 ──


def sync_source(source_key: str, store: Any) -> Dict[str, Any]:
    """把远端源条目 upsert 进 MarketStore。

    - 新条目 create；已有 source 条目按白名单字段 update；
    - 远端已消失的 source 条目 remove（保留非 source 条目与 admin 侧改动）；
    - 上游失败不抛异常，返回 {created, updated, removed, errors}。
    """
    src = get_source(source_key)
    stats = {"source": source_key, "created": 0, "updated": 0, "removed": 0, "errors": 0}
    try:
        raw_entries = src.fetch_entries()
    except Exception as e:  # noqa: BLE001 — 上游失败降级
        logger.warning("market source %s fetch failed: %s", source_key, e)
        stats["errors"] += 1
        return stats

    prefix = f"{source_key}--"
    seen_ids = set()
    for raw in raw_entries:
        try:
            entry = src.map_entry(raw)
            skill_id = entry["skill_id"]
            seen_ids.add(skill_id)
            existing = store.get(skill_id)
            if existing is None:
                store.create(entry)
                stats["created"] += 1
            else:
                patch = src.sync_fields(entry)
                current = {k: existing.get(k) for k in patch}
                if current != patch:
                    store.update(skill_id, patch)
                    stats["updated"] += 1
        except Exception as e:  # noqa: BLE001 — 单条失败不中断整批
            stats["errors"] += 1
            logger.warning("map/upsert entry failed in %s: %s", source_key, e)

    # 清理远端已下架条目（只动本 source 命名空间）
    try:
        for item in store.list_all():
            sid = item.get("skill_id", "")
            if sid.startswith(prefix) and sid not in seen_ids:
                if store.remove(sid):
                    stats["removed"] += 1
    except Exception as e:  # noqa: BLE001
        logger.warning("prune source entries failed: %s", e)

    logger.info(
        "market source %s synced: +%(created)d ~%(updated)d -%(removed)d err=%(errors)d",
        {**stats},
    )
    return stats


# ── 安装下载（zip 安全解压）──


def extract_remote_skill_zip(skill_id: str, payload: bytes, dest: Path) -> bool:
    """把远端技能 zip 安全解压到 dest。

    防护: 总大小上限(MAX_SKILL_ZIP_BYTES)、条目数上限、zip-slip 路径逃逸拒绝。
    失败返回 False（可能留下部分文件，调用方 uninstall 可清理）。
    """
    if len(payload) > MAX_SKILL_ZIP_BYTES:
        logger.warning("skill %s zip too large: %d bytes", skill_id, len(payload))
        return False
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        logger.warning("skill %s payload is not a zip", skill_id)
        return False

    names = zf.namelist()
    if len(names) > MAX_ZIP_ENTRIES:
        logger.warning("skill %s zip has too many entries: %d", skill_id, len(names))
        return False

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        for info in zf.infolist():
            # 拒绝绝对路径与 .. 逃逸（zip-slip）
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts or ":" in name:
                logger.warning("skill %s zip entry rejected: %s", skill_id, info.filename)
                return False
            target = dest / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("extract skill %s failed: %s", skill_id, e)
        return False


def download_and_extract(skill_id: str, url: str, dest: Path) -> bool:
    """下载 + 解压一条龙；host 白名单在 _http_get 内校验"""
    try:
        payload = _http_get(url)
    except Exception as e:  # noqa: BLE001
        logger.warning("download skill %s from %s failed: %s", skill_id, url, e)
        return False
    return extract_remote_skill_zip(skill_id, payload, dest)
