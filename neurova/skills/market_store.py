"""
市场技能 Catalog 持久化存储

市场清单单一数据源: 管理端(上架/更新/下架)与 MarketImporter.search_skills
读取同源。数据落盘 data/marketplace/catalog.json (JSON 数组)。
首次访问无文件时用默认种子(web-search) + 内置技能包表补齐初始化。

契约见 tests/unit/skills/test_market_store.py。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.core.data_root import dataPath

logger = get_logger(__name__)

# 默认市场种子(与既有 MarketImporter 示例一致, 迁移为目录初值)
_DEFAULT_CATALOG: List[Dict[str, Any]] = [
    {
        "skill_id": "web-search",
        "name": "Web Search",
        "version": "1.2.0",
        "description": "搜索互联网获取实时信息",
        "author": "Neurova Team",
        # 不填可取件地址：这条的能力在代码侧执行体映射里，装出来本就没有字节。
        # 过去这里挂着一个从不存在的域名，于是读面永远"看着有来源"。
        "category": "utility",
        "tags": ["search", "web", "information"],
        "rating": 4.5,
        "downloads": 1000,
        "updated_at": 0,
    },
]

# 内置技能包（随包分发, 离线可装）: zip 资产在 neurova/skills/market_bundles/
# 下, 条目以 bundle_zip 指向文件名; 安装走本地解压（market_importer）。
# skillhub.cn multi-search-engine v2.1.5（腾讯 keen/sanbu 双扫描 benign）
_BUILTIN_CATALOG: List[Dict[str, Any]] = [
    {
        "skill_id": "builtin--multi-search-engine",
        "name": "搜索引擎",
        "version": "2.1.5",
        "description": "多搜索引擎集成, 16 引擎(7 国内+9 全球)聚合搜索。Multi search engine integration with 16 engines (7 CN + 9 Global)。",
        "author": "智创未来 (skillhub.cn)",
        "download_url": "https://api.skillhub.cn/api/v1/download?slug=multi-search-engine",
        "category": "utility",
        "tags": ["search", "搜索", "检索", "工具", "web_fetch"],
        "rating": 0.0,
        "downloads": 390049,
        "updated_at": 0,
        "source": "builtin",
        "bundle_zip": "multi-search-engine.zip",
    },
    {
        "skill_id": "builtin--adaptive-presentation-studio",
        "name": "智能演示文稿生成器",
        "version": "1.0.24",
        "description": "上传 Word/Excel/CSV/PDF/PPT/Markdown/图片等办公资料，理解受众与目的，动态规划叙事、版式、配色与图表，输出可编辑 16:9 PowerPoint。含本地渲染脚本与断点续跑。",
        "author": "WorkBuddy 实名权利人 (skillhub.cn)",
        "download_url": "https://api.skillhub.cn/api/v1/download?slug=adaptive-presentation-studio",
        "category": "productivity",
        "tags": ["PPT", "演示文稿", "办公", "文档转换", "office"],
        "rating": 0.0,
        "downloads": 22825,
        "updated_at": 0,
        "source": "builtin",
        "bundle_zip": "adaptive-presentation-studio.zip",
    },
    {
        # 本仓自撰的指令体（不是外部授权包）。它曾与 web-search 并列在 `_DEFAULT_CATALOG`，
        # 带的是自造市场地址 `api.neurova.dev`——该域名不在已注册远端源白名单里，于是
        # `import_skill` 跳过下载、照样 COMPLETED，落盘只有 skill.json：装"成功"了，目录里
        # 什么都没有。指令体的字节只能随包分发；来源标签留空（读作 local），不重分类市场页
        # 的本地页签。
        "skill_id": "code-analysis",
        "name": "Code Analysis",
        "version": "2.0.1",
        "description": "分析和审查代码质量",
        "author": "Neurova Team",
        "category": "development",
        "tags": ["code", "analysis", "review"],
        "rating": 4.8,
        "downloads": 500,
        "updated_at": 0,
        "bundle_zip": "code-analysis.zip",
    },
]


# 构件指针字段：内置表是这些字段的唯一事实源，存量 catalog 行按它回写。
_BUNDLE_POINTER_FIELDS = ("bundle_zip",)


def _ensure_builtin_entries(items: List[Dict[str, Any]]) -> bool:
    """原地把 catalog 对齐内置表：缺条目补齐，构件指针回写，其余不动。返回是否有变化。

    admin 改过的文案（name/description/version/tags）不回写——那是他的话语权重。
    但 `bundle_zip` 不是话语，是"这件能力的字节从哪里取"，只能以代码那一份为事实源：
    把"只补缺不覆盖"沿用到它头上，存量部署就会永远持有一行装不出字节的空壳（本机
    catalog 里的 code-analysis 正是这种形态）。
    """
    known = {i.get("skill_id") for i in items}
    added = [dict(e) for e in _BUILTIN_CATALOG if e["skill_id"] not in known]
    items.extend(added)
    changed = bool(added)

    rows = {i.get("skill_id"): i for i in items}
    for decl in _BUILTIN_CATALOG:
        row = rows.get(decl["skill_id"])
        if row is None:
            continue
        for pointer in _BUNDLE_POINTER_FIELDS:
            if pointer in decl and row.get(pointer) != decl[pointer]:
                row[pointer] = decl[pointer]
                changed = True

    # 同一句「有没有来源」在存量数据上的另一半：本仓自带条目（种子＋内置表）里那些不属于
    # 任何注册源的 download_url，永远取不到东西，却会让读面显示一个能骗人的来源。新建种子
    # 已经不写了，这一支管的是已经躺在各部署 catalog 里的旧行。
    from neurova.skills import market_sources

    ownIds = {e["skill_id"] for e in _BUILTIN_CATALOG} | {e["skill_id"] for e in _DEFAULT_CATALOG}
    for ownId in ownIds:
        row = rows.get(ownId)
        if row is None:
            continue
        url = str(row.get("download_url") or "")
        if url and not market_sources.is_remote_market_url(url):
            row["download_url"] = ""
            changed = True
    return changed


class MarketStore:
    """市场清单存储: JSON 持久化 + RLock 并发保护"""

    def __init__(self, catalog_path: Path):
        self.catalog_path = Path(catalog_path)
        self._lock = threading.RLock()
        self._items: List[Dict[str, Any]] = []
        self._load_or_seed()

    def _load_or_seed(self) -> None:
        with self._lock:
            if self.catalog_path.exists():
                try:
                    with open(self.catalog_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    self._items = raw if isinstance(raw, list) else []
                    # 内置技能包补缺（只补缺不覆盖既有/admin 改动）
                    if _ensure_builtin_entries(self._items):
                        self._save()
                except Exception as e:  # noqa: BLE001 — 损坏文件回退种子
                    logger.error("load market catalog failed: %s", e)
                    self._items = []
            else:
                self._items = [dict(item) for item in _DEFAULT_CATALOG]
                _ensure_builtin_entries(self._items)
                self._save()
                logger.info("seeded market catalog at %s", self.catalog_path)

    def _save(self) -> bool:
        try:
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.catalog_path, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("save market catalog failed: %s", e)
            return False

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def get(self, skill_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for item in self._items:
                if item.get("skill_id") == skill_id:
                    return dict(item)
        return None

    def create(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            skill_id = entry.get("skill_id", "").strip()
            if not skill_id:
                raise ValueError("skill_id is required")
            if self.get(skill_id) is not None:
                raise ValueError(f"skill '{skill_id}' already exists")
            item = dict(entry)
            item.setdefault("skill_id", skill_id)
            item.setdefault("version", "1.0.0")
            item.setdefault("updated_at", time.time())
            self._items.append(item)
            self._save()
            return dict(item)

    def update(self, skill_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新条目; 返回 {entry, version_changed}; 未知 id 返回 None"""
        with self._lock:
            for item in self._items:
                if item.get("skill_id") != skill_id:
                    continue
                version_changed = False
                if "version" in patch and patch["version"] != item.get("version"):
                    version_changed = True
                item.update({k: v for k, v in patch.items() if k != "skill_id"})
                item["updated_at"] = time.time()
                self._save()
                return {"entry": dict(item), "version_changed": version_changed}
        return None

    def remove(self, skill_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i.get("skill_id") != skill_id]
            if len(self._items) == before:
                return False
            self._save()
            return True


# ── 全局单例 ──
_market_store: Optional[MarketStore] = None
_store_lock = threading.Lock()


def get_market_store(catalog_path: Optional[Path] = None) -> MarketStore:
    """全局市场清单单例; catalog_path 缺省: 环境变量 NEUROVA_MARKET_CATALOG
    或 data/marketplace/catalog.json"""
    global _market_store
    if _market_store is None:
        with _store_lock:
            if _market_store is None:
                if catalog_path is None:
                    import os

                    catalog_path = Path(
                        os.environ.get("NEUROVA_MARKET_CATALOG") or dataPath("marketplace/catalog.json")
                    )
                _market_store = MarketStore(catalog_path=catalog_path)
    return _market_store


def reset_market_store() -> None:
    """重置全局单例(用于测试)"""
    global _market_store
    with _store_lock:
        _market_store = None
