"""
市场技能 Catalog 持久化测试（2026-08-31）

根因: 市场技能数据是 MarketImporter.search_skills 硬编码示例,
无存储层 → 管理员"新增/更新/删除"无处落盘, 且无法持久。

契约:
1. 首次访问以默认种子(catalog 缺失时)初始化, seed 包含 web-search 等示例;
2. create: 新增条目落盘; 重复 skill_id 抛 ValueError;
3. update: 字段更新 + version 变更检测(version_changed=True/False);
4. remove: 删除条目, 不存在的 id 返回 False;
5. 持久化: 重新实例化(新 store 加载同一文件)后数据仍在。
"""

import json

import pytest

from neurova.skills.market_store import (
    MarketStore,
    get_market_store,
    reset_market_store,
    _DEFAULT_CATALOG,
)


@pytest.fixture
def store(tmp_path):
    s = MarketStore(catalog_path=tmp_path / "catalog.json")
    return s


def test_seed_on_first_access(store):
    items = store.list_all()
    assert len(items) >= 2
    assert any(i["skill_id"] == "web-search" for i in items)
    # 种子落盘
    assert store.catalog_path.exists()


def test_create_persists_and_duplicate_raises(store):
    entry = {
        "skill_id": "translate-plus",
        "name": "Translate Plus",
        "version": "1.0.0",
        "description": "多语言翻译",
        "author": "Neurova Team",
    }
    created = store.create(entry)
    assert created["skill_id"] == "translate-plus"
    # 持久化: 重新加载后仍在
    reloaded = MarketStore(catalog_path=store.catalog_path)
    assert any(i["skill_id"] == "translate-plus" for i in reloaded.list_all())
    with pytest.raises(ValueError):
        store.create(entry)


def test_update_version_change_detection(store):
    before = store.get("web-search")
    r1 = store.update("web-search", {"version": "1.3.0"})
    assert r1["version_changed"] is True
    assert store.get("web-search")["version"] == "1.3.0"
    # 同版本更新不改动 version_changed
    r2 = store.update("web-search", {"description": "新描述"})
    assert r2["version_changed"] is False
    assert store.get("web-search")["description"] == "新描述"
    # 未知 id
    assert store.update("nope", {"version": "9.9.9"}) is None


def test_remove(store):
    assert store.remove("code-analysis") is True
    assert store.get("code-analysis") is None
    assert store.remove("code-analysis") is False


def test_singleton_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()
    s = get_market_store()
    assert isinstance(s, MarketStore)
    assert s.catalog_path == tmp_path / "catalog.json"
    reset_market_store()
