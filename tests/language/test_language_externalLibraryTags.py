# -*- coding: utf-8 -*-
"""外部译文库的语言码落点与读面口径（台账 §6-140 的 manager 侧）。

`Language.from_str` 原先把不认识的码折成 `AUTO`（`models.py`），而 `zh-CN` 这种带区域后缀的码
**恰恰是仓内实际流通的那一套**（前端 11 份 locale、`app_settings.json` 的 `"zh-CN"`）。
后果不是报错，是静默改桶：`_translations[ns][key][language.value]` 用的就是归一后的值，
于是按 `zh-CN` 存进去的文案落进了 `auto` 桶，按 `Language.CHINESE` 永远读不到。
本文件钉的是**存进去落哪个桶**与**一个坏码不许毁掉整份文件**。

注：`get_translation()` 只回 `is_approved` 的条目，而外部/用户上传的译文一律 `is_approved=False`
且**仓内没有审批动作**——那是"写完没人能读"的另一格，属管理面那一批的工作量，不在本文件范围。
"""

from __future__ import annotations

import json


def _managerAt(tmp_path):
    from neurova.language.manager import LanguageManager

    return LanguageManager(data_dir=str(tmp_path / "language"))


class TestRegionTaggedCodesLandInTheRightBucket:
    def test_savedUnderRegionTagLandsInItsOwnBucketNotASharedOne(self, tmp_path):
        """按 delta 判，不按"库里有没有 zh"判。

        首版这里写的是 `Language.CHINESE in get_available_languages()`——**恒真的空转格**：
        内置译文库本来就带 zh，无论区域码归不归一它都绿。改成"这一次写入新引入了哪个桶"，
        未归一时多出来的就是 `auto`，当场红。
        """
        from neurova.language.models import Language

        mgr = _managerAt(tmp_path)
        before = set(mgr.get_available_languages())

        ok = mgr.save_external_translations("ui", {"settings": {"zh-CN": "设置", "en-US": "Settings"}})

        assert ok is True
        added = set(mgr.get_available_languages()) - before
        assert added == set(), (
            "`zh-CN`/`en-US` 写入后新长出了 %s——区域码没归一，落进了别的桶（按枚举读不回来）：%s"
            % (sorted(str(x.value) for x in added), sorted(str(x.value) for x in added)))


    def testSavingWithRegionTagDoesNotFabricateAnAutoEntry(self, tmp_path):
        """`AUTO` 是"自动检测"这个合法值，不该成为未知/区域码的收容所。"""
        from neurova.language.models import Language

        fresh = _managerAt(tmp_path)
        before = set(fresh.get_available_languages())

        fresh.save_external_translations("messages", {"welcome": {"zh-CN": "欢迎"}})

        after = set(fresh.get_available_languages())
        assert Language.AUTO not in after - before, (
            "区域码被折成 AUTO 存进了库里（读数会显示「这个语言有文案」，实际永远命中不到）：%s"
            % sorted(str(x.value) for x in after))

    def testUnrecognizedCodeIsRejectedAndLeavesNoHalfWrittenFile(self, tmp_path):
        """不认识的码：点名 + 整批拒收，且**不许留下半写状态**（内存与盘都得没动过）。"""
        from neurova.language.models import Language

        mgr = _managerAt(tmp_path)
        before = set(mgr.get_available_languages())
        fileBefore = (mgr.data_dir / "ui.json").exists()

        ok = mgr.save_external_translations(
            "ui", {"settings": {"zh-CN": "设置", "klingon": "tlh"}})

        assert ok is False, "不识别的语言码被静默收下并写盘——写面替调用方兜了底"
        assert (mgr.data_dir / "ui.json").exists() == fileBefore, (
            "拒收却仍然动了文件：内存与盘上从此两套数")
        assert set(mgr.get_available_languages()) == before, (
            "半写进内存了：拒收返回 False，可 `zh-CN` 那一项已经进了库（读面与盘上不一致）：%s"
            % sorted(str(x.value) for x in set(mgr.get_available_languages()) - before))
        assert Language.CHINESE not in set(mgr.get_available_languages()) - before



class TestOneBadCodeDoesNotDropAWholeFile:
    def test_goodCodesSurviveWhileTheBadOneIsSkipped(self, tmp_path):
        from neurova.language.models import Language

        target = tmp_path / "language"
        target.mkdir(parents=True, exist_ok=True)
        (target / "messages.json").write_text(
            json.dumps({"welcome": {"zh": "欢迎", "en": "Welcome", "klingon": "tlh"}},
                       ensure_ascii=False),
            encoding="utf-8",
        )

        mgr = _managerAt(tmp_path)

        available = set(mgr.get_available_languages())
        assert Language.CHINESE in available and Language.ENGLISH in available, (
            "文件里一个坏码把整份译文库带崩了（装载面把异常吞在文件级）：%s"
            % sorted(str(x.value) for x in available))
        assert Language.AUTO not in available, (
            "坏码被折进 AUTO 桶留下了第三条语言：%s" % sorted(str(x.value) for x in available))

    def test_writtenFileIsReadBackByAFreshInstanceThroughTheRealPath(self, tmp_path):
        """写进去的必须能被**另一个实例从盘上读回**，且回读不落 `auto`。

        刻意新建一个 manager 走 `_load_external_translations()` 的真装载路径，而不是复用写的那个
        对象（记忆里"活体读盘要先证写侧与读侧同源"同族）。判据取"**不许多出 AUTO 这个桶**"，
        不取"有没有 zh"——内置表本来就带 zh，后者是一条恒真断言（本文件第一版就踩过）。
        """
        from neurova.language.models import Language

        writer = _managerAt(tmp_path)
        assert writer.save_external_translations("ui", {"settings": {"zh-CN": "设置"}}) is True
        assert (writer.data_dir / "ui.json").is_file(), "写面没真落盘，读回无从谈起"

        reader = _managerAt(tmp_path)
        languages = set(reader.get_available_languages())

        assert Language.AUTO not in languages, (
            "落盘/装载这一半没归一：从文件读回来多出了 auto 桶，重启后读面回到旧形态：%s"
            % sorted(str(x.value) for x in languages))




class TestBrowserDetectionSharesTheSingleNormalization:
    def test_regionTaggedAcceptLanguageHeaderResolves(self):
        from neurova.language.manager import LanguageManager
        from neurova.language.models import Language

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            mgr = LanguageManager(data_dir=td)
            assert mgr.detect_browser_language("zh-CN,zh;q=0.9,en;q=0.8") is Language.CHINESE
            assert mgr.detect_browser_language("en-US,en;q=0.9") is Language.ENGLISH

    def test_unknownBrowserTagFallsBackToTheNamedDefaultNotAuto(self):
        """兜底要走"调用方给的默认语言"，不是枚举自己那个 AUTO——两件事别混。"""
        from neurova.language.manager import LanguageManager
        from neurova.language.models import Language

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            mgr = LanguageManager(data_dir=td, default_language=Language.JAPANESE)

            assert mgr.detect_browser_language("klingon") is Language.JAPANESE
            assert mgr.detect_browser_language("") is Language.JAPANESE
