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
import shutil
import tempfile
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


@pytest.fixture()
def shortSkillsRoot(request) -> Path:
    r"""内置包导入的落点根：不挂在 pytest 那串"用例名即目录名"的深根上。

    实测最长成员名 125 字符，而 `tmp_path` 那一段（含
    `test_import_builtin_offline[presentation-studio]0`）会让"根 + 成员"合计 273 字符，
    超过 Windows 的 260 上限（本机 `LongPathsEnabled=0`）——那样本格测的就是操作系统了。
    长根那一维另有专档钉住（`test_zipRefusalNamesItsCause.py`：失败必须点名"路径过长"并给出
    成员长／根长／合计三个数），这里只管它声称的那件事：内置包可离线导入且落盘内容正确。
    """
    root = Path(tempfile.mkdtemp(prefix="nvbm-")) / "skills"
    request.addfinalizer(lambda: shutil.rmtree(root.parent, ignore_errors=True))
    return root


@pytest.mark.parametrize(
    "skill_id,version,expect_files",
    [
        (SEARCH_ENGINE_ID, "2.1.5", ["SKILL.md"]),
        (PRESENTATION_ID, "1.0.24", ["SKILL.md", "scripts/build_deck.py"]),
    ],
    ids=["search-engine", "presentation-studio"],
)
def test_import_builtin_offline(shortSkillsRoot, monkeypatch, builtin_store,
                                     skill_id, version, expect_files):
    # 零网络断言: 任何 http 请求即失败
    import neurova.skills.market_sources as ms

    def _no_net(url):
        raise AssertionError(f"builtin install must not touch network, got {url}")

    monkeypatch.setattr(ms, "_http_get", _no_net)

    importer = MarketImporter(skills_dir=shortSkillsRoot)
    task = importer.import_skill(skill_id)
    assert task.status.value == "completed", task.error_message

    skill_dir = shortSkillsRoot / skill_id
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


# ── 4. Code Analysis 构件包（2026-10-24，用户裁乙：补的是**字节**，不是豁免）──

CODE_ANALYSIS_ID = "code-analysis"
CODE_ANALYSIS_BUNDLE = "code-analysis.zip"


def test_code_analysis_is_a_bundled_builtin_not_a_placeholder():
    """这只 id 的事实源挪进内置表——`_DEFAULT_CATALOG` 那两条种子带的是自造市场地址
    （`api.neurova.dev` 不在已注册远端源白名单），`import_skill` 对它**跳过下载照样
    COMPLETED**，落盘只有 skill.json ⇒ 读面按第③腿判"无构件"。留着那条占位行就是
    留第二个事实源（教义第 6 条），所以它进 `_BUILTIN_CATALOG`、出 `_DEFAULT_CATALOG`。
    """
    from neurova.skills.market_store import _DEFAULT_CATALOG

    assert CODE_ANALYSIS_ID not in {e["skill_id"] for e in _DEFAULT_CATALOG}
    entry = next(e for e in _BUILTIN_CATALOG if e["skill_id"] == CODE_ANALYSIS_ID)
    assert entry["bundle_zip"] == CODE_ANALYSIS_BUNDLE
    # 来源标签留空（读作 local）：`source` 现有语义是「条目从哪来」，这只仍是本仓自撰
    # 种子；打上 builtin 会把市场页「本地」页签里的这条挪走——产品可见变化不归本批。
    assert "source" not in entry


def test_code_analysis_offline_install_lands_instruction_body(shortSkillsRoot, monkeypatch, builtin_store):
    """离线装出来的目录里必须有**真**指令体：availabilityFor 第③腿吃的就是这份字节。

    下限不数长度，钉的是"这份指令真的可被照着执行"的四件结构物——缺任一件就是占位文本。
    """
    from neurova.skills.builtin.skill_doc_executor import parse_skill_md
    import neurova.skills.market_sources as ms

    def _no_net(url):
        raise AssertionError(f"内置包安装不得联网: {url}")

    monkeypatch.setattr(ms, "_http_get", _no_net)

    importer = MarketImporter(skills_dir=shortSkillsRoot)
    task = importer.import_skill(CODE_ANALYSIS_ID)
    assert task.status.value == "completed", task.error_message

    text = (shortSkillsRoot / CODE_ANALYSIS_ID / "SKILL.md").read_text(encoding="utf-8")
    meta, instructions = parse_skill_md(text)
    assert meta.get("name") and meta.get("description"), f"frontmatter 缺 name/description: {meta}"
    for anchor in ("何时启用", "审查次序", "发现格式", "禁止事项"):
        assert anchor in instructions, f"指令体缺结构物「{anchor}」——那它就是占位文本"


def test_stale_catalog_row_gets_bundle_pointer(tmp_path):
    """存量老库里的占位行：载入时补**构件指针**，但 admin 改过的文案不回写。

    "只补缺不覆盖"的既有边界守住的是 admin 的话语权，不是"空壳一旦落库就永久空壳"——
    后者会让这份资产在已有部署上永远装不出来（本机 catalog.json 正是这种存量形态）。
    """
    stale = {
        "skill_id": CODE_ANALYSIS_ID,
        "name": "Code Analysis",
        "version": "2.0.1",
        "description": "管理员描述",
        "download_url": "https://api.neurova.dev/skills/code-analysis/download",
    }
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([stale]), encoding="utf-8")
    MarketStore(catalog_path=catalog)

    entry = MarketStore(catalog_path=catalog).get(CODE_ANALYSIS_ID)
    assert entry["bundle_zip"] == CODE_ANALYSIS_BUNDLE
    assert entry["description"] == "管理员描述"
    assert entry["version"] == "2.0.1"


def test_code_analysis_bundle_passes_install_gate(tmp_path):
    """解出来的内容过安装安全门（`.md` 在扫描面内——SKILL.md 正是提示注入的主载体）。

    这格断的是"资产自己不再有危险形状"，不是给这只包开豁免：白名单面仍须为空。
    """
    from neurova.skills.skill_install_gate import reset_install_gate_scanner, scan_skill_for_install

    payload = read_builtin_bundle(CODE_ANALYSIS_BUNDLE)
    assert payload is not None, f"内置技能包资产缺失: {CODE_ANALYSIS_BUNDLE}"
    dest = tmp_path / CODE_ANALYSIS_ID
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        zf.extractall(dest)

    reset_install_gate_scanner()
    try:
        verdict = scan_skill_for_install(CODE_ANALYSIS_ID, str(dest))
        assert verdict.get("blocked") is False, f"安装门拒绝: {verdict}"
    finally:
        reset_install_gate_scanner()
