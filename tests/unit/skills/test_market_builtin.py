"""
内置技能包（market_bundles）契约测试（2026-09-08）

背景: skillhub.cn 技能按 zip 随包内置到本地技能市场——离线可装、
不依赖远端源、不需网络。已内置:
- multi-search-engine v2.1.5: 16 引擎聚合搜索, 纯 SKILL.md 指令型;
- adaptive-presentation-studio v1.0.24: 智能演示文稿生成器, 含本地
  渲染脚本（scripts/*.py, Agent Skills 标准语义）, 作者防提取授权门
  为本地加盐哈希, 腾讯 keen/sanbu 双扫描 benign。

契约:
1. 资产完整性: 每个 _BUILTIN_CATALOG 条目的 bundle_zip 都存在、可解压、
   含 SKILL.md、大小/条目数在 extract_remote_skill_zip 上限内;
2. catalog 补缺: 既有 catalog 缺失内置条目时载入后补齐
   （只补缺不覆盖——admin 对已有条目的改动不被回写）;
3. 离线安装: import_skill 对 bundle_zip 条目走本地解压（断言零网络）,
   落盘 SKILL.md + skill.json; 资产缺失时 FAIL（不静默模拟成功）。
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from neurova.skills.market_importer import MarketImporter, read_builtin_bundle
from neurova.skills.market_store import (
    MarketStore,
    _BUILTIN_CATALOG,
)
from neurova.skills.market_sources import MAX_SKILL_ZIP_BYTES, MAX_ZIP_ENTRIES

SEARCH_ENGINE_ID = "builtin--multi-search-engine"
PRESENTATION_ID = "builtin--adaptive-presentation-studio"
BUNDLE_NAME = "multi-search-engine.zip"


# ── 1. 资产完整性 ──


def test_builtin_catalog_bundles_valid():
    """每个内置条目的 zip 资产存在、可解压、含 SKILL.md、在上限内"""
    assert {e["skill_id"] for e in _BUILTIN_CATALOG} >= {SEARCH_ENGINE_ID, PRESENTATION_ID}
    for entry in _BUILTIN_CATALOG:
        payload = read_builtin_bundle(entry["bundle_zip"])
        assert payload is not None, f"内置技能包资产缺失: {entry['bundle_zip']}"
        assert len(payload) <= MAX_SKILL_ZIP_BYTES, f"{entry['bundle_zip']} 超过安装上限"
        zf = zipfile.ZipFile(io.BytesIO(payload))
        assert len(zf.namelist()) <= MAX_ZIP_ENTRIES, f"{entry['bundle_zip']} 条目数超上限"
        assert "SKILL.md" in zf.namelist(), f"{entry['bundle_zip']} 缺 SKILL.md"


def test_multi_search_engine_zip_is_doc_only():
    """search-engine 是纯文档包: 只允许 md/json, 不得夹带可执行脚本"""
    payload = read_builtin_bundle(BUNDLE_NAME)
    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = zf.namelist()
    assert all(n.endswith((".md", ".json")) for n in names), f"内置 zip 含非文档条目: {names}"
    skill_md = zf.read("SKILL.md").decode("utf-8")
    assert "slug: multi-search-engine" in skill_md


def test_presentation_studio_zip_has_scripts():
    """presentation-studio 是脚本型包: SKILL.md + 本地渲染脚本齐备"""
    payload = read_builtin_bundle("adaptive-presentation-studio.zip")
    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = zf.namelist()
    assert "scripts/build_deck.py" in names
    assert "scripts/analyze_materials.py" in names
    skill_md = zf.read("SKILL.md").decode("utf-8")
    assert "adaptive-presentation-studio" in skill_md


def test_read_builtin_bundle_rejects_path_escape():
    assert read_builtin_bundle("../secret.zip") is None
    assert read_builtin_bundle("sub/dir/x.zip") is None
    assert read_builtin_bundle("not-a-bundle.txt") is None
    assert read_builtin_bundle("missing.zip") is None


# ── 2. catalog 补缺 ──


def test_ensure_builtin_fills_missing(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps([{"skill_id": "web-search", "name": "Web Search", "version": "1.2.0"}]),
        encoding="utf-8",
    )
    store = MarketStore(catalog_path=catalog)
    ids = {i["skill_id"] for i in store.list_all()}
    assert SEARCH_ENGINE_ID in ids
    assert PRESENTATION_ID in ids
    entry = store.get(SEARCH_ENGINE_ID)
    assert entry["version"] == "2.1.5"
    assert entry["source"] == "builtin"
    assert entry["bundle_zip"] == BUNDLE_NAME
    entry2 = store.get(PRESENTATION_ID)
    assert entry2["version"] == "1.0.24"
    assert entry2["source"] == "builtin"


def test_ensure_builtin_preserves_admin_changes(tmp_path):
    catalog = tmp_path / "catalog.json"
    admin_view = {
        "skill_id": SEARCH_ENGINE_ID,
        "name": "管理员改名",
        "version": "9.9.9",
        "description": "管理员描述",
    }
    catalog.write_text(json.dumps([admin_view]), encoding="utf-8")
    store = MarketStore(catalog_path=catalog)
    entry = store.get(SEARCH_ENGINE_ID)
    assert entry["name"] == "管理员改名"
    assert entry["version"] == "9.9.9"
    assert entry["description"] == "管理员描述"


# ── 3. 离线安装链路 ──


@pytest.fixture
def builtin_store(tmp_path, monkeypatch):
    """MarketStore 隔离注入 importer 的调用时 import 点"""
    store = MarketStore(catalog_path=tmp_path / "catalog.json")
    import neurova.skills.market_store as ms

    monkeypatch.setattr(ms, "get_market_store", lambda: store)
    return store


@pytest.mark.parametrize(
    "skill_id,version,expect_files",
    [
        (SEARCH_ENGINE_ID, "2.1.5", ["SKILL.md"]),
        (PRESENTATION_ID, "1.0.24", ["SKILL.md", "scripts/build_deck.py"]),
    ],
    ids=["search-engine", "presentation-studio"],
)
def test_import_builtin_offline(tmp_path, monkeypatch, builtin_store, skill_id, version, expect_files):
    # 零网络断言: 任何 http 请求即失败
    import neurova.skills.market_sources as ms

    def _no_net(url):
        raise AssertionError(f"builtin install must not touch network, got {url}")

    monkeypatch.setattr(ms, "_http_get", _no_net)

    importer = MarketImporter(skills_dir=tmp_path / "skills")
    task = importer.import_skill(skill_id)
    assert task.status.value == "completed", task.error_message

    skill_dir = tmp_path / "skills" / skill_id
    for rel in expect_files:
        assert (skill_dir / rel).exists(), f"{rel} 未落盘"
    if "SKILL.md" in expect_files:
        assert (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    meta = json.loads((skill_dir / "skill.json").read_text(encoding="utf-8"))
    assert meta["skill_id"] == skill_id
    assert meta["version"] == version


def test_import_builtin_missing_bundle_fails(tmp_path, monkeypatch, builtin_store):
    builtin_store.create(
        {"skill_id": "builtin--ghost", "name": "Ghost", "bundle_zip": "ghost.zip"}
    )
    importer = MarketImporter(skills_dir=tmp_path / "skills")
    task = importer.import_skill("builtin--ghost")
    assert task.status.value == "failed"
    assert "bundle" in (task.error_message or "").lower()
