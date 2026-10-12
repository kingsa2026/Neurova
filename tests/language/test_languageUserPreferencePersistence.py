# -*- coding: utf-8 -*-
"""用户语言偏好的落盘与读取（台账 §6-145 裁定乙：先接读面 + 补 `UserLanguagePreference` 落盘）。

## 这一格原来是什么形态

`LanguageManager` 把偏好放在实例字典 `self._user_preferences` 里（`manager.py:58`），
写点 `:400`、读点 `:417`——**进程重启即全失**，而 `get_statistics()`（`:509`）却在数它，
于是面板上"有 N 人设过语言"是一个每次启动都归零的读数。这是"只写内存不落盘"的教科书形态：
不是崩溃才丢，是**设计上就没打算留住**。

## 三条设计约束，每条都有对应的坑

1. **偏好文件必须落在译文 `*.json` glob 之外**。`_load_external_translations()`（`manager.py:152`）
   把 `self.data_dir/*.json` 的**每个文件**当一个 namespace 读进来，文件名就是 namespace。
   偏好文件若放同目录，重启后库里会白捡一个叫 `language_preferences` 的命名空间，
   `get_statistics()["namespaces"]` 从此多一格——那种多出来的读数不会报错，只会一直在那儿。
2. **写盘失败不许报成功**。`set_user_preference()` 原先恒回 True（except 分支除外）。
   接了盘之后，"内存写了、盘没写"必须当场 rollback 并回 False——
   否则调用方（HTTP 面）向用户承诺"已保存"，而重启后什么也没有（教义第 2 条禁的谎报形态）。
3. **坏文件改名隔离，不原地覆盖**（`core/atomic_io.py` 那对 `atomic_write_text`/
   `quarantine_corrupt_file` 的既有口径）。半截 JSON 留在原路径 = 下一次成功保存会用
   内存空态覆盖掉真数据，整库丢失。

`AUTO` 这一格另说：`Language.AUTO` 是合法成员，但它表达的是"自动检测"，而
`UserLanguagePreference` 里已经有 `auto_detect: bool` 专职这件事。允许
`primary_language = AUTO` 等于把 §6-140 刚拆掉的那条"不识别与自动检测共用一个合法值"
在新字段上重建一遍——所以在构造点就拒（与 §6-145 的「构造即归一、非法状态生产不出来」同形）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _managerAt(tmp_path, **kw):
    from neurova.language.manager import LanguageManager

    return LanguageManager(data_dir=str(tmp_path / "language"), **kw)


class TestThePreferenceActuallyLandsOnDisk:
    def testPreferenceSurvivesAFreshManagerOnTheSameRoot(self, tmp_path):
        """换实例＝模拟重启：读回来的必须是同一个语言，而不是数据类默认值。"""
        from neurova.language.models import Language, UserLanguagePreference

        writer = _managerAt(tmp_path)
        assert writer.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.JAPANESE)
        ) is True

        reader = _managerAt(tmp_path)
        loaded = reader.get_user_preference("u1")

        assert loaded is not None, (
            "偏好只活在写它的那个实例里——重启即全失，"
            "而 get_statistics() 还在数它（每次启动都归零的读数）")
        assert loaded.primary_language is Language.JAPANESE

    def testDefaultLandingIsTheDataRootSinglePoint(self):
        """不给 `data_dir` 时（生产形态）：偏好必须落数据根，不许是 CWD 相对名。

        §6-158 那枚「上传前门每次 `POST /save` 都 400」的起因就是默认值给了一个
        CWD 相对的裸名——同一形态在这里也会一次写偏，只不过写偏的是用户数据。
        """
        from neurova.core import data_root
        from neurova.language import manager as managerModule
        from neurova.language.manager import LanguageManager

        manager = LanguageManager()
        expected = Path(data_root.callerPath(None, managerModule.PREFERENCES_FILE_NAME))

        assert Path(manager.preferences_path) == expected, (
            "默认落点没走 `callerPath` 单点：现值 %r 期望 %r"
            % (str(manager.preferences_path), str(expected)))
        assert Path(manager.preferences_path).is_absolute()

    def testExplicitDataDirKeepsThePreferencesBesideIt(self, tmp_path):
        """显式给了译文目录时，偏好落在它的**同级**——这条同时钉住判据自身的隔离。

        如果实现把偏好路径写死成数据根，本目录每个用例都会往同一个共享文件里写，
        用例之间互相串（"夹具隔离是假的"那一族）；这条按 tmp 断，串了就读不到期望值。
        """
        manager = _managerAt(tmp_path)

        assert Path(manager.preferences_path) == tmp_path / "language_preferences.json"
        assert Path(manager.preferences_path).parent != manager.data_dir

    def testPreferencesFileSitsOutsideTheTranslationGlobDir(self, tmp_path):
        """偏好文件与译文命名空间目录必须分开——同目录会被当成一个 namespace 读进来。"""
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.ENGLISH))

        prefs = Path(manager.preferences_path)
        assert prefs.parent != manager.data_dir, (
            "偏好文件落在 `%s` 里，而 `_load_external_translations()` 把该目录每个 `*.json` "
            "当一个命名空间读——库里会长出一个假的 `language_preferences` 命名空间"
            % manager.data_dir)

    def testReloadingTranslationsDoesNotFabricateANamespace(self, tmp_path):
        """上一格的存在性证明：写进偏好之后重新装载，命名空间数不许 +1。"""
        from neurova.language.models import Language, UserLanguagePreference

        writer = _managerAt(tmp_path)
        writer.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language="en-US"))
        before = writer.get_statistics()["namespaces"]

        reader = _managerAt(tmp_path)

        assert reader.get_statistics()["namespaces"] == before, (
            "重启后命名空间从 %r 变成 %r——偏好文件被译文装载面当成译文库读进来了"
            % (before, reader.get_statistics()["namespaces"]))
        assert "language_preferences" not in str(reader.get_statistics())

    def testReadingDoesNotCreateTheFile(self, tmp_path):
        """读面不许有写副作用：查一个没设过偏好的人，不该在盘上留下任何东西。"""
        manager = _managerAt(tmp_path)

        assert manager.get_user_preference("ghost") is None
        assert not Path(manager.preferences_path).exists(), (
            "读一次就建一个文件——那会让「有多少人设过偏好」这个读数被读操作自己灌大")

    def testSecondWriteReplacesTheFirstOnDisk(self, tmp_path):
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.KOREAN))
        manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.FRENCH))

        reader = _managerAt(tmp_path)
        assert reader.get_user_preference("u1").primary_language is Language.FRENCH

    def testDifferentUsersDoNotOverwriteEachOther(self, tmp_path):
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        manager.set_user_preference(
            "a", UserLanguagePreference(user_id="a", primary_language=Language.GERMAN))
        manager.set_user_preference(
            "b", UserLanguagePreference(user_id="b", primary_language=Language.SPANISH))

        reader = _managerAt(tmp_path)
        assert reader.get_user_preference("a").primary_language is Language.GERMAN
        assert reader.get_user_preference("b").primary_language is Language.SPANISH

    def testStatisticsCountComesFromTheDurableStore(self, tmp_path):
        """统计里那格 `user_preferences` 从此有持久来源，而不是每次启动归零。"""
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        for who in ("a", "b"):
            manager.set_user_preference(
                who, UserLanguagePreference(user_id=who, primary_language=Language.ENGLISH))

        assert _managerAt(tmp_path).get_statistics()["user_preferences"] == 2


class TestWritesFailHonestly:
    def testDiskFailureRollsBackMemoryAndReportsFalse(self, tmp_path, monkeypatch):
        """盘上没写成 ⇒ 内存也得回到旧值、返回 False；不许"内存改了、告诉用户已保存"。"""
        from neurova.language import manager as managerModule
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        assert manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.CHINESE))

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(managerModule, "atomic_write_text", boom)

        ok = manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.ARABIC))

        assert ok is False, "写盘失败却回 True——HTTP 面会据此向用户承诺「已保存」"
        assert manager.get_user_preference("u1").primary_language is Language.CHINESE, (
            "内存留在新值而盘上是旧值：两侧从此两套数，重启后用户看到的又是旧的那个")

    def testTheWriteReallyGoesThroughTheAtomicWriter(self, tmp_path, monkeypatch):
        """反空转格：本文件的落盘断言必须真的经 `atomic_write_text`，
        否则上面那格「写盘失败」是在桩一条根本没人走的路。"""
        from neurova.language import manager as managerModule
        from neurova.language.models import Language, UserLanguagePreference

        calls = []
        real = managerModule.atomic_write_text

        def spy(path, text, **kw):
            calls.append(str(path))
            return real(path, text, **kw)

        monkeypatch.setattr(managerModule, "atomic_write_text", spy)
        manager = _managerAt(tmp_path)
        manager.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.ENGLISH))

        assert calls == [str(Path(manager.preferences_path))], (
            "偏好保存没走原子写单点（走了裸 open/别的helper）：写盘失败格因此是空转：%r" % calls)

    def testCorruptFileIsQuarantinedAndNeverOverwritten(self, tmp_path):
        """半截 JSON 不许原地留着——否则下一次保存会用内存空态覆盖掉真数据。"""
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        prefs = Path(manager.preferences_path)
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text("{\"preferences\": {\"u1\": {\"user_id\"", encoding="utf-8")  # 半截

        reader = _managerAt(tmp_path)
        assert reader.get_user_preference("u1") is None

        quarantined = list(prefs.parent.glob(prefs.name + ".corrupt-*"))
        assert quarantined, "损坏文件没被改名隔离——留着它，下一次成功写入会直接覆盖掉现场"
        assert not prefs.exists() or prefs.stat().st_size > 0

        assert reader.set_user_preference(
            "u1", UserLanguagePreference(user_id="u1", primary_language=Language.ENGLISH))
        assert len(list(prefs.parent.glob(prefs.name + ".corrupt-*"))) == 1, (
            "新写入把损坏现场也一起冲掉了——恢复的可能没了")

    def testOneUnknownTagSkipsOnlyThatUser(self, tmp_path):
        """坏值不许带崩整份文件（与 §6-145 装载面「一个坏码只跳它自己」同一条口径）。"""
        from neurova.language.models import Language

        manager = _managerAt(tmp_path)
        prefs = Path(manager.preferences_path)
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(json.dumps({
            "version": 1,
            "preferences": {
                "good": {"user_id": "good", "primary_language": "en"},
                "bad": {"user_id": "bad", "primary_language": "klingon"},
            },
        }), encoding="utf-8")

        reader = _managerAt(tmp_path)
        assert reader.get_user_preference("good").primary_language is Language.ENGLISH
        assert reader.get_user_preference("bad") is None, (
            "不识别的语言码被收进了库（或整份文件被丢掉）")
        assert reader.get_user_preference("good") is not None, (
            "一个人的坏条目把整份偏好文件带崩了")


class TestAutoIsNotAStorablePrimaryLanguage:
    def testAutoAsPrimaryIsRefusedAtConstruction(self):
        from neurova.language.models import Language, UserLanguagePreference

        with pytest.raises(ValueError):
            UserLanguagePreference(user_id="u1", primary_language=Language.AUTO)

    def testAutoAsFallbackIsRefusedAtConstruction(self):
        from neurova.language.models import Language, UserLanguagePreference

        with pytest.raises(ValueError):
            UserLanguagePreference(user_id="u1", fallback_language=Language.AUTO)

    def testAutoDetectBooleanStillCarriesThatMeaning(self):
        """拒掉 `primary=AUTO` 不是把能力删了：`auto_detect` 才是这件事的落点。"""
        from neurova.language.models import Language, UserLanguagePreference

        pref = UserLanguagePreference(user_id="u1", primary_language=Language.ENGLISH,
                                       auto_detect=True)
        assert pref.should_auto_detect() is True

    def testRegionTaggedPrimaryNormalizesAtConstruction(self, tmp_path):
        """现役 UI 递来的就是 `zh-CN` 这一族：构造即归一，落盘落 `zh`，重启读回同一个。"""
        from neurova.language.models import Language, UserLanguagePreference

        manager = _managerAt(tmp_path)
        pref = UserLanguagePreference(user_id="u1", primary_language="zh-CN",
                                       secondary_languages=["en-US", "ja-JP"],
                                       fallback_language="en")
        assert pref.primary_language is Language.CHINESE
        assert pref.secondary_languages == [Language.ENGLISH, Language.JAPANESE]
        assert manager.set_user_preference("u1", pref) is True

        disk = json.loads(Path(manager.preferences_path).read_text(encoding="utf-8"))
        assert disk["preferences"]["u1"]["primary_language"] == "zh"

        reader = _managerAt(tmp_path)
        assert reader.get_user_preference("u1").secondary_languages == [
            Language.ENGLISH, Language.JAPANESE]
