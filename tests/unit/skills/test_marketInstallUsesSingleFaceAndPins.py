# -*- coding: utf-8 -*-
"""§6-172 批 32：市场安装这条活路上两条 P3 旁路的收口判据。

钉的是两件事，都在**现役**路径上（`marketplace.install_skill` → `market_importer.import_skill`
→ `market_sources.extract_remote_skill_zip`），不是适配器那张没人调的 install 面：

1. 解压判定此前有第二份实现（自己数条目、自己判路径、自己写盘），而仓内咽喉
   `security/safe_archive.safe_extract_zip` 已被 6 处生产点消费。两份并存各自演化就是教义
   第 6/7 条的反面。本批把**机制**收进咽喉（上限作为调用方给的参数——上限数值是市场安装
   这条路的策略，不是解包器的策略），把**判定**留在唯一一处。
2. 装完落盘的构件不钉摘要 ⇒ `call_skill` 那侧只能退回 TOFU 首钉，即"第一次调用时盘上是什么
   就采信什么"。这一钉把采信点从"首次调用"提前到"安装完成"，落位之后的改动因此翻红；
   它**不**防"取回时那份字节本身就被定向重算过"（与批 30 写死的三条边界同形，不夸成能力）。

上限用 monkeypatch 改模块常量来验，不是把 10MB/500 写死进判据——写死了就只证明判据自己。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) .venv/Scripts/python.exe -m pytest \
tests/unit/skills/test_marketInstallUsesSingleFaceAndPins.py -q`
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import warnings
import zipfile
from pathlib import Path

import pytest

from neurova.security import artifact_digest, safe_archive
from neurova.skills import market_sources
from neurova.skills.market_importer import BUILTIN_BUNDLE_DIR, ImportStatus, MarketImporter

REAL_BUNDLE = "multi-search-engine.zip"
NEUROVA_ROOT = Path(market_sources.__file__).resolve().parent.parent


def _extractallCalls(source: str) -> int:
    """按 AST 数"真的调了解包器"，不按文本——注释里那句「原 extractall 无成员校验」既会被
    文本守卫算成命中（假红），又会放过真调用旁边的任何写法；只有调用节点才是事实。"""
    tree = ast.parse(source)
    hits = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "extractall":
                hits += 1
    return hits


def _handRolledExtractallHits() -> list:
    hits = []
    for path in sorted(NEUROVA_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            count = _extractallCalls(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - 由收集卫生守卫兜
            continue
        if count:
            hits.append(path.relative_to(NEUROVA_ROOT).as_posix())
    return hits


# ── 1. 解压判定只剩一处 ──


def testExtractallSurvivesOnlyInsideTheSingleFace():
    """落盘解包只允许咽喉那一个文件；市场侧那份已随本批退役，别让它长回来。
    同根因扫荡的口径：`backup`／`skill_packager` 里的 `namelist()` 只把成员读进内存、
    不落盘，因此不算命中——算命中的只有"往目录里写成员"这一形。命中面按**文件**取，
    不按调用次数取（咽喉内部为 tar 的 filter 回退留了两次调用，那是实现细节不是纪律）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        assert _handRolledExtractallHits() == ["security/safe_archive.py"], (
            f"解包落盘必须只发生在咽喉一个文件里，实得 {_handRolledExtractallHits()}"
        )



def testExtractallProbeHasTeeth():
    """排除型断言在没有该功能时会绿得没道理——先证探针抓得到真调用、不会被注释骗。"""
    assert _extractallCalls("def f(zf, d):\n    zf.extractall(d)\n") == 1
    assert _extractallCalls("# 原 extractall 无成员校验\nPASS\n") == 0
    assert _extractallCalls("class A:\n    def extractall(self, d): pass\n") == 0



def _zipBytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in entries.items():
            zf.writestr(name, body)
    return buf.getvalue()


def _skillMeta(dest: Path) -> dict:
    return json.loads((dest / "skill.json").read_text(encoding="utf-8"))


@pytest.fixture
def importer(tmp_path):
    return MarketImporter(tmp_path / "skills")


# ── 1. 解压判定只剩一处 ──


def testExtractionGoesThroughTheSingleFaceWithCallerCaps(monkeypatch, tmp_path):
    """市场侧不许自己判条目/判路径：必须把活儿交给咽喉，并把自己那两条上限递过去。"""
    seen = []

    def spy(source, target_dir, *, maxPayloadBytes=None, maxEntries=None):
        seen.append({"maxPayloadBytes": maxPayloadBytes, "maxEntries": maxEntries})
        return Path(target_dir)

    monkeypatch.setattr(safe_archive, "safe_extract_zip", spy)
    ok = market_sources.extract_remote_skill_zip(
        "s1", _zipBytes({"SKILL.md": "hi"}), tmp_path / "dest"
    )

    assert ok is True, "咽喉正常返回时市场侧必须报成功"
    assert len(seen) == 1, f"解压必须只走咽喉一次，实得 {len(seen)} 次"
    assert seen[0] == {
        "maxPayloadBytes": market_sources.MAX_SKILL_ZIP_BYTES,
        "maxEntries": market_sources.MAX_ZIP_ENTRIES,
    }, f"上限必须由调用方现取模块常量递进咽喉，实得 {seen[0]}"


def testEntryCapIsEnforcedBeforeAnythingIsWritten(monkeypatch, tmp_path):
    """条目数超上限 ⇒ False 且一个文件都不落（判完再写，不是写一半才发现越限）。"""
    monkeypatch.setattr(market_sources, "MAX_ZIP_ENTRIES", 2)
    dest = tmp_path / "dest"
    payload = _zipBytes({"a.txt": "1", "b.txt": "2", "c.txt": "3"})

    assert market_sources.extract_remote_skill_zip("s2", payload, dest) is False
    assert [p.name for p in dest.rglob("*") if p.is_file()] == [], "拒绝必须是写盘之前发生"


def testOversizedPayloadIsRefusedAsTooLargeNotAsBadZip(monkeypatch, tmp_path):
    """两种拒因不许互相盖：过大与"不是 zip"是两条不同的路，日志要能分辨。"""
    monkeypatch.setattr(market_sources, "MAX_SKILL_ZIP_BYTES", 16)
    dest = tmp_path / "dest"
    garbage = b"x" * 17  # 既超限又根本不是 zip

    assert market_sources.extract_remote_skill_zip("s3", garbage, dest) is False
    with pytest.raises(safe_archive.UnsafeArchiveError) as oversized:
        safe_archive.safe_extract_zip(garbage, tmp_path / "direct", maxPayloadBytes=16)
    assert "字节" in str(oversized.value), f"拒因必须点名字节数，实得 {oversized.value}"
    with pytest.raises(zipfile.BadZipFile):
        safe_archive.safe_extract_zip(b"definitely not a zip", tmp_path / "direct2")


def testPathEscapeStillRefusesAndCreatesNothingOutsideDest(monkeypatch, tmp_path):
    """收敛之后 zip-slip 那条牙必须在（这是两份实现合一后最容易被悄悄削掉的一牙）。"""
    dest = tmp_path / "skills" / "s4"
    escaped = tmp_path / "escaped.txt"
    payload = _zipBytes({"../escaped.txt": "pwned", "SKILL.md": "hi"})

    assert market_sources.extract_remote_skill_zip("s4", payload, dest) is False
    assert not escaped.exists(), "越界成员必须整体拒绝，而不是丢掉那一条继续解"
    assert not (dest / "SKILL.md").exists(), "任一成员越界即 fail-closed"


def testFaceCapsAreOptInSoOtherSixCallSitesDoNotMove(tmp_path):
    """上限是调用方策略：不递参数时咽喉不得自己设限（hub_client／skill_packager 等 6 处
    今天就没有这两条上限，凭空加上去会让大一点的本地包在别的批里莫名炸掉）。"""
    payload = _zipBytes({f"f{i}.txt": "x" for i in range(501)})

    base = safe_archive.safe_extract_zip(payload, tmp_path / "noCaps")
    assert len([p for p in base.rglob("*") if p.is_file()]) == 501
    with pytest.raises(safe_archive.UnsafeArchiveError) as capped:
        safe_archive.safe_extract_zip(payload, tmp_path / "capped", maxEntries=2)
    assert "成员" in str(capped.value)
    # 缺省位也钉住：只看行为的话，"默认 500 条"这种暗设的上限要在 501 条样本上才露头，
    # 而签名才是那句"默认不设限"的出处。
    params = inspect.signature(safe_archive.safe_extract_zip).parameters
    assert params["maxPayloadBytes"].default is None, "字节上限不得在咽喉里缺省设值"
    assert params["maxEntries"].default is None, "成员数上限不得在咽喉里缺省设值"


# ── 2. 装完的构件在装这一侧钉摘要 ──


def testRealBuiltinBundleInstallPinsDigestAtInstallTime(monkeypatch, importer):
    """用**真**包内资产走完整安装路（零网络）：skill.json 必须带摘要，且与盘上那份字节相等。"""
    assert (BUILTIN_BUNDLE_DIR / REAL_BUNDLE).exists(), "判据前提：内置技能包资产得在"
    monkeypatch.setattr(
        MarketImporter, "_lookup_catalog_entry",
        lambda self, skill_id: {"bundle_zip": REAL_BUNDLE, "version": "1.0.0"},
    )

    task = importer.import_skill("real-bundle-skill")
    assert task.status is ImportStatus.COMPLETED, task.error_message

    dest = importer._skills_dir / "real-bundle-skill"
    pinned = _skillMeta(dest).get(artifact_digest.DIGEST_FIELD)
    assert pinned, f"装完不钉摘要 ⇒ 读侧只能退回 TOFU 首钉，实得键值 {pinned!r}"
    assert pinned == artifact_digest.digestDir(dest), "钉的必须是刚落位那份字节的摘要"
    status, _ = artifact_digest.checkArtifact(dest, pinned)
    assert status == artifact_digest.STATUS_MATCH


def testPinnedMarketSkillTurnsRedWhenBytesChange(monkeypatch, importer):
    """这一钉得有牙：装完之后往构件目录加一个文件，读侧必须报不符（不是"多一个文件不算改"）。"""
    monkeypatch.setattr(
        MarketImporter, "_lookup_catalog_entry",
        lambda self, skill_id: {"bundle_zip": REAL_BUNDLE, "version": "1.0.0"},
    )
    importer.import_skill("teeth-skill")
    dest = importer._skills_dir / "teeth-skill"
    pinned = _skillMeta(dest)[artifact_digest.DIGEST_FIELD]

    (dest / "extra.py").write_text("print('injected')", encoding="utf-8")
    status, actual = artifact_digest.checkArtifact(dest, pinned)
    assert status == artifact_digest.STATUS_MISMATCH, f"改了字节必须翻红，实得 {status}"
    assert actual and actual != pinned


def testSimulatedSeedInstallDoesNotPin(monkeypatch, importer):
    """没从远端取回任何字节的那支不许钉——盘上是空目录时钉下去就是给"来源不明的构件"背书。"""
    monkeypatch.setattr(
        MarketImporter, "_lookup_catalog_entry",
        lambda self, skill_id: {"version": "1.0.0"},
    )

    task = importer.import_skill("seed-skill")
    assert task.status is ImportStatus.COMPLETED, task.error_message
    meta = _skillMeta(importer._skills_dir / "seed-skill")
    assert artifact_digest.DIGEST_FIELD not in meta, "模拟链路没有取回字节，钉它＝伪造采信点"
