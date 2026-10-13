"""市场安装状态必须有真读侧，空装不得谎报成功（§6-188，2026-10-13 裁定「接线不退役」的第一半）。

探针实证的形状（写侧一直有，读侧从来没有）：市场缓存目录里包体与 `skill.json`
（记着 `version`/`installed_at`）都好好躺着，**重启后 `list_installed()` 仍返回空列表**。
⇒ 市场页把装过的技能说成没装；`/marketplace/skills/{id}/install` 那条"已装过就补链"的
幂等分支永远走不到，每次点击都重新下载一遍。本批给这本账接上读侧，并把测试里
拿 `skill.json` 文件名当"安装副本存在"的探针改指**读得回来的读数**。

另一半是 `SkillsMPAdapter.install` 的 `return True`（§6-176 就登记过）：它一行字节都没写却报成功。
之前没人调它所以谎没生效；本批把它改成如实——并按"成对格"纪律配一枚**真下载**适配器的正向格，
证明这不是把安装一关了之。
"""

import io
import json
import logging
import zipfile
from pathlib import Path

import pytest

from neurova.skills.market_adapters import SkillsMPAdapter, SkillsShAdapter, SkillInfo
from neurova.skills.market_importer import MarketImporter
from neurova.skills.market_store import reset_market_store


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """隔离 catalog（用默认种子：web-search / code-analysis）与缓存目录。"""
    monkeypatch.setenv("NEUROVA_MARKET_CATALOG", str(tmp_path / "catalog.json"))
    reset_market_store()
    root = tmp_path / "market-cache"
    yield root
    reset_market_store()


def _importer(root):
    return MarketImporter(skills_dir=root)


def _seedInstalled(root, skillId="demo--skill", body=None, raw=None):
    """按安装器自己写过的形状铺一份缓存副本（不假造字段名）。`raw=` 用来铺坏件。"""
    pkg = root / skillId
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text("# demo\n", encoding="utf-8")
    text = raw if raw is not None else json.dumps(
        body if body is not None else
        {"skill_id": skillId, "version": "1.2.3", "installed_at": "2026-10-13T00:00:00+00:00"})
    (pkg / "skill.json").write_text(text, encoding="utf-8")
    return pkg


class TestInstalledStateHasAReader:
    def testRealImportIsListedByAFreshInstance(self, cache):
        """真走一次安装 ⇒ 新开一个实例（＝重启）必须读得回来，而不是只剩内存。"""
        importer = _importer(cache)
        task = importer.import_skill(skill_id="web-search", version=None, force=False)
        assert importer.list_installed(), "安装后连内存读数都是空的，本批无从谈起"

        assert any(item["skill_id"] == "web-search" for item in _importer(cache).list_installed()), (
            "包体与 skill.json 都在盘上，重启后却报告'什么都没装'——写侧没人读，"
            "市场页与幂等补链分支就此失真")

    def testUninstallIsNotReadBackAsInstalled(self, cache):
        _seedInstalled(cache, "demo--skill")
        importer = _importer(cache)
        assert importer.uninstall_skill("demo--skill") is True, (
            "读侧接通之前这条本来就走不通：内存里看不见，卸载就回 False——"
            "本批接的就是这个「已装」的口径，卸载面是它的第二个消费者")

        assert not any(item["skill_id"] == "demo--skill" for item in _importer(cache).list_installed()), (
            "卸载后又被盘上残留读回来 ⇒ 读侧把已删的东西当成现役，比零读者更坏")

    def testCorruptRecordIsNotTrustedAndNotRewritten(self, cache, caplog):
        pkg = _seedInstalled(cache, "demo--skill", raw="{ 这不是合法 json")
        with caplog.at_level(logging.WARNING):
            items = _importer(cache).list_installed()

        assert not any(item["skill_id"] == "demo--skill" for item in items), (
            "坏记账件被当成'已装'或干脆跳过而不点名——读侧必须fail-visible，"
            "不能把'我读不懂'读成'没装'或'装了'")
        assert any("读不懂" in str(rec.getMessage()) for rec in caplog.records), (
            "跳过却没出声＝静默把'我读不懂'读成'没装'，这一条就是 fail-visible 的全部意义")
        assert (pkg / "skill.json").read_text(encoding="utf-8") == "{ 这不是合法 json", (
            "读侧顺手覆盖写了别人的坏文件＝毁证据；本批只读不修")

    def testKeyIsTheDirectoryNotWhatTheFileClaims(self, cache):
        """口径钉死：采信**目录名**，不采信文件里自报的 `skill_id`。

        `uninstall_skill` 删的是目录；键若跟着文件自报走，复制/改名目录就会读出幽灵条目
        或删不掉——记账与删除不同源正是这类账最容易烂的地方。
        """
        pkg = _seedInstalled(cache, "demo--skill",
                             body={"skill_id": "someone--else", "version": "9.9.9"})

        items = _importer(cache).list_installed()
        ids = {item["skill_id"] for item in items}

        assert pkg.name in ids and "someone--else" not in ids, (
            f"读回来的键不是目录名（{sorted(ids)}）——卸载面按目录删，两边不同源就是幽灵条目")

    def testRecordThatIsNotAnObjectIsSkippedWithVoice(self, cache, caplog):
        """合法 JSON 却不该被采信的形状（字符串/数组）——`version` 取不出来就是没有版本，不是版本空串。"""
        _seedInstalled(cache, "demo--skill", raw=json.dumps(["skill.json 被谁写成数组了"]))
        with caplog.at_level(logging.WARNING):
            items = _importer(cache).list_installed()

        assert not any(item["skill_id"] == "demo--skill" for item in items)

    def testPackageWithoutARecordIsNotClaimedInstalled(self, cache):
        """口径写死：只认安装器自己写过的记账件，不拿"目录存在"猜已装。"""
        pkg = cache / "stranger--pkg"
        pkg.mkdir(parents=True)
        (pkg / "SKILL.md").write_text("# hi\n", encoding="utf-8")

        assert not any(item["skill_id"] == "stranger--pkg" for item in _importer(cache).list_installed())

    def testMissingVersionIsReportedAsUnknownNotInvented(self, cache):
        _seedInstalled(cache, "demo--skill",
                       body={"skill_id": "demo--skill", "installed_at": "2026-10-13T00:00:00+00:00"})

        hit = next((item for item in _importer(cache).list_installed()
                    if item["skill_id"] == "demo--skill"), None)

        assert hit is not None and hit["version"] == "unknown", (
            f"账上没写版本却替它编一个（{hit}）——下游 force/升级判定会拿这枚假版本比")


class TestEmptyInstallStopsLying:
    def _info(self):
        return SkillInfo(name="mp--demo", source="skillsmp", description="d",
                         download_url="https://skillsmp.invalid/mp--demo.zip")

    def testSkillsMpInstallDoesNotClaimSuccessWhileWritingNothing(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()

        assert SkillsMPAdapter().install(self._info(), str(out)) is False, (
            "`return True` 空装：一行字节都没写却报安装成功。接线之前它至少没被调用，"
            "本批把读侧接上后这类谎会直接进账本")
        assert not any(out.iterdir()), "没落字节才是本节的重点：失败必须真的什么都没留下"

    def testAdapterThatActuallyFetchesStillInstalls(self, monkeypatch, tmp_path):
        """成对正向格：收紧不能把真能下载的适配器一起焊死。"""
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("SKILL.md", "---\nname: sh-demo\n---\n\n# SH 正文\n")
        blob = payload.getvalue()

        def fakeDownload(url, target_path):
            Path(target_path).write_bytes(blob)
            return True

        monkeypatch.setattr(SkillsShAdapter, "_download_file", lambda self, url, dest: fakeDownload(url, dest))
        out = tmp_path / "out2"
        out.mkdir()

        assert SkillsShAdapter().install(
            SkillInfo(name="sh--demo", source="skills.sh", download_url="https://skills.sh/x.zip"),
            str(out)) is True
        assert (out / "SKILL.md").is_file() and "# SH 正文" in (out / "SKILL.md").read_text(encoding="utf-8")
