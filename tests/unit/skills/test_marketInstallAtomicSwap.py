# -*- coding: utf-8 -*-
"""PLUG-03（2026-11-25 全仓审计·批次C）：市场安装先删后装，失败丢旧版。

审计实形（当前代码复核）：`MarketImporter.import_skill` 在内置包/远端下载
两条腿上先 `shutil.rmtree(已装目录)` 再解包——解包失败（坏包、下载损坏、
安全门拒）时旧版已删、无法回滚。修复：先解包进安装根下的临时 staging
目录，全部成功（解包 + 记账件落盘）后原子换名上位；失败保留旧版并如实
报错。
"""

import io
import json
import zipfile

import pytest

from neurova.skills.market_importer import MarketImporter

SKILL_ID = "swap-demo"


def _zipBytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, body in entries.items():
            zf.writestr(rel, body)
    return buf.getvalue()


GOOD_V1 = _zipBytes({
    "SKILL.md": "---\nname: swap-demo\ndescription: v1\n---\n\n# v1\n",
    "scripts/run.py": "def run(**kw):\n    return 'v1'\n",
})
GOOD_V2 = _zipBytes({
    "SKILL.md": "---\nname: swap-demo\ndescription: v2\n---\n\n# v2\n",
    "scripts/run.py": "def run(**kw):\n    return 'v2'\n",
    "extra.txt": "v2-only-member\n",
})
CORRUPT = b"this is definitely not a zip payload"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import neurova.skills.market_store as ms

    store = ms.MarketStore(catalog_path=tmp_path / "catalog.json")
    store.create({
        "skill_id": SKILL_ID, "name": "Swap Demo", "version": "1.0.0",
        "description": "d", "bundle_zip": "swap.zip",
    })
    monkeypatch.setattr(ms, "get_market_store", lambda: store)
    payloads = {"swap.zip": GOOD_V1}
    monkeypatch.setattr(
        "neurova.skills.market_importer.read_builtin_bundle",
        lambda name: payloads.get(name))
    importer = MarketImporter(skills_dir=tmp_path / "skills")
    return importer, payloads


def _skillJson(skillsRoot, skillId=SKILL_ID) -> dict:
    return json.loads((skillsRoot / skillId / "skill.json").read_text(encoding="utf-8"))


def test_failedReinstall_preservesOldVersion(env):
    """坏包 force 重装必须失败，且**旧版目录原样保留**（审计主判据）。"""
    imp, payloads = env
    skills = imp.marketSkillsDir()

    t1 = imp.import_skill(SKILL_ID, version="1.0.0")
    assert t1.status.value == "completed", t1.error_message
    assert _skillJson(skills)["version"] == "1.0.0"

    payloads["swap.zip"] = CORRUPT
    t2 = imp.import_skill(SKILL_ID, version="2.0.0", force=True)

    assert t2.status.value == "failed", "坏包重装必须失败"
    assert _skillJson(skills)["version"] == "1.0.0", (
        "安装失败不得丢旧版：先删后装把已装目录一起埋了")
    assert "v1" in (skills / SKILL_ID / "SKILL.md").read_text(encoding="utf-8"), (
        "旧版字节必须原样还在")
    assert not (skills / SKILL_ID / "extra.txt").exists(), (
        "失败安装的新版成员不得混进旧版目录")


def test_failedReinstall_keepsInstalledLedgerConsistent(env):
    """失败重装后内存账与盘上一致（仍是旧版），不产幽灵态。"""
    imp, payloads = env
    imp.import_skill(SKILL_ID, version="1.0.0")
    payloads["swap.zip"] = CORRUPT
    imp.import_skill(SKILL_ID, version="2.0.0", force=True)

    rows = {r["skill_id"]: r["version"] for r in imp.list_installed()}
    assert rows.get(SKILL_ID) == "1.0.0", rows


def test_successfulReinstall_swapsToNewVersion_andLeavesNoDebris(env):
    """正向配对格：成功重装换上新版，且安装根无临时/备份残留。"""
    imp, payloads = env
    skills = imp.marketSkillsDir()
    imp.import_skill(SKILL_ID, version="1.0.0")

    payloads["swap.zip"] = GOOD_V2
    t2 = imp.import_skill(SKILL_ID, version="2.0.0", force=True)

    assert t2.status.value == "completed", t2.error_message
    assert _skillJson(skills)["version"] == "2.0.0"
    assert (skills / SKILL_ID / "extra.txt").exists(), "新版成员应上位"
    assert "v2" in (skills / SKILL_ID / "SKILL.md").read_text(encoding="utf-8")
    tops = {p.name for p in skills.iterdir()}
    assert tops == {SKILL_ID, ".install_tmp"}, f"安装根出现意外残留: {tops}"
    assert list((skills / ".install_tmp").iterdir()) == [], (
        "staging 区不得残留工作/备份目录")


def test_failedFreshInstall_leavesNoShell(env):
    """首装失败（目录本无旧版）不得留下半具空壳。"""
    imp, payloads = env
    payloads["swap.zip"] = CORRUPT
    t = imp.import_skill(SKILL_ID, version="1.0.0")
    assert t.status.value == "failed"
    assert not (imp.marketSkillsDir() / SKILL_ID).exists(), (
        "失败的安装不得在安装根留空壳目录")
