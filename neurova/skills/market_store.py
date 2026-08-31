"""
市场技能 Catalog 持久化存储

市场清单单一数据源: 管理端(上架/更新/下架)与 MarketImporter.search_skills
读取同源。数据落盘 data/marketplace/catalog.json (JSON 数组)。
首次访问无文件时用默认种子(web-search / code-analysis)初始化。

契约见 tests/unit/skills/test_market_store.py。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# 默认市场种子(与既有 MarketImporter 示例一致, 迁移为目录初值)
_DEFAULT_CATALOG: List[Dict[str, Any]] = [
    {
        "skill_id": "web-search",
        "name": "Web Search",
        "version": "1.2.0",
        "description": "搜索互联网获取实时信息",
        "author": "Neurova Team",
        "download_url": "https://api.neurova.dev/skills/web-search/download",
        "category": "utility",
        "tags": ["search", "web", "information"],
        "rating": 4.5,
        "downloads": 1000,
        "updated_at": 0,
    },
    {
        "skill_id": "code-analysis",
        "name": "Code Analysis",
        "version": "2.0.1",
        "description": "分析和审查代码质量",
        "author": "Neurova Team",
        "download_url": "https://api.neurova.dev/skills/code-analysis/download",
        "category": "development",
        "tags": ["code", "analysis", "review"],
        "rating": 4.8,
        "downloads": 500,
        "updated_at": 0,
    },
]


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
                except Exception as e:  # noqa: BLE001 — 损坏文件回退种子
                    logger.error("load market catalog failed: %s", e)
                    self._items = []
            else:
                self._items = [dict(item) for item in _DEFAULT_CATALOG]
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
                        os.environ.get("NEUROVA_MARKET_CATALOG", "data/marketplace/catalog.json")
                    )
                _market_store = MarketStore(catalog_path=catalog_path)
    return _market_store


def reset_market_store() -> None:
    """重置全局单例(用于测试)"""
    global _market_store
    with _store_lock:
        _market_store = None
