# -*- coding: utf-8 -*-
"""D-5 · `visual-parse` 退役守卫。

## 为什么是退役而不是补实现

`visual-parse` 承诺的是"截图 + UI 元素检测"，而本仓**已有同一能力的实现面**：
`computer_som_snapshot` 把截图标注成编号可交互区域，检测器注入缝留在
`som.mark_screenshot(png, detector=...)`（`som.default_detector` 注释明写
"真实检测器就绪后以 `detector=` 替换，上层零改动"）。留着这条 HTTP 面就是第二份定义，
按修复教义第 6 条收口到一处并删掉另一处（含其测试与死码）。

`smart-click` 不同：它承诺的"自然语言目标 → 元素"后端从未实现，属**未立项的新能力**，
按 D-6 走 T-08→T-10→T-11 接通，不在本单退役范围。

## 本文件自带的两条对照

- 正对照：注入一个假的 `visualParse` 前端封装，扫描判据必须报出来——否则"绿"不可信。
- 负对照：工具产物目录（`.mimosa` 这类 IDE 钩子基线快照）里的历史文案**不得**算作命中
  ——那 54 处假命中正是本判据初版的坑。该目录**从不入库**（`.gitignore` 的 `.*/` 整类排除），
  故对照在临时树上合成该形态：判据钉的是"排除谓词真的在排除"，而不是"这台机器上恰好
  留着某个编辑器的缓存"。初版直接 `rglob` 本机目录，CI 干净检出下必然红。
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
computer_ep = pytest.importorskip("neurova.api.endpoints.computer")

_FRONTEND_MODULE = REPO / "NeurUI" / "src" / "api" / "modules" / "computer.ts"
_LOCALE_DIR = REPO / "NeurUI" / "src" / "i18n" / "locales"


def _liveLocaleFiles(root: pathlib.Path = None) -> list:
    """真实 locale 文件：排除工具产物快照目录（`.mimosa` 这类）与备份。

    `root` 可注入：负对照要在临时树上合成产物目录来证排除谓词真的生效，
    不能在空集合上恒真（该目录从不入库）。
    """
    root = root if root is not None else _LOCALE_DIR
    return sorted(
        p for p in root.rglob("*.ts")
        if ".mimosa" not in p.parts and not p.name.endswith((".bak", ".orig"))
    )


def _visualParseSurface(path, text: str) -> list:
    """唯一命中谓词：真实判据与正对照共用它，避免"对照测的是另一段代码"。"""
    return [str(path)] if "visualParse" in text else []



class TestBackendSurfaceGone:
    def test_handlerSymbolIsGone(self):
        assert not hasattr(computer_ep, "visual_parse"), "占位处理函数仍在"

    def test_requestModelIsGone(self):
        assert not hasattr(computer_ep, "VisualParseRequest"), "请求模型仍在"

    def test_routeIsNotRegistered(self):
        paths = {getattr(r, "path", "") for r in computer_ep.router.routes}
        assert not any("visual-parse" in p for p in paths), f"路由仍登记：{sorted(paths)[:5]}"


class TestFrontendSurfaceGone:
    def test_wrapperFunctionIsRetired(self):
        assert _FRONTEND_MODULE.exists(), "前端模块路径变了，判据需同步"
        hits = _visualParseSurface(_FRONTEND_MODULE, _FRONTEND_MODULE.read_text(encoding="utf-8"))
        assert not hits, "前端封装仍在（它无调用方，属断点）"

    def test_noLocaleCarriesTheKey(self):
        locales = _liveLocaleFiles()
        assert locales, "没找到 locale 文件，判据在空集合上恒真"
        offenders = [
            hit for p in locales
            for hit in _visualParseSurface(p, p.read_text(encoding="utf-8"))
        ]
        assert not offenders, f"11 份 locale 未同批改：[n] {[o.split(chr(92))[-1] for o in offenders]}"

    def test_pluginBaselineIsNotCounted(self, tmp_path):
        """负对照：工具产物快照里确有历史文案，但不得进入判定面。

        合成该形态而不是扫本机目录——`.mimosa` 属 `.*/` 整类不入库，
        CI 干净检出下没有它，扫本机等于把"这台机器留过某个编辑器的缓存"
        当成判据前提（初版就是这样在 CI 上必然红）。临时树里同时放
        `zh-CN.ts`（真源）与 `.mimosa/`（产物副本），排除谓词必须只挑前者。
        """
        (tmp_path / "zh-CN.ts").write_text(
            "export const a = { visualParse: 'x' }\n", encoding="utf-8")
        snapshots = tmp_path / ".mimosa" / "hook-state"
        snapshots.mkdir(parents=True)
        (snapshots / "zh-CN.ts").write_text("visualParse\n", encoding="utf-8")
        (snapshots / "zh-CN.ts.source").write_text("visualParse\n", encoding="utf-8")

        allFiles = [p for p in tmp_path.rglob("*") if ".mimosa" in p.parts and p.is_file()]
        hits = [p for p in allFiles if "visualParse" in p.read_text(encoding="utf-8", errors="replace")]
        assert hits, "合成树里没有历史文案，本负对照失去意义，须换判据"

        picked = _liveLocaleFiles(tmp_path)
        assert [p.name for p in picked] == ["zh-CN.ts"], (
            f"排除谓词没有只挑真源：{[str(p.relative_to(tmp_path)) for p in picked]}")


class TestCompanionLedgersAgree:
    def test_honestyGuardNoLongerListsIt(self):
        src = (REPO / "tests" / "unit" / "api" / "test_computer_placeholder_honesty.py").read_text(
            encoding="utf-8"
        )
        listed = re.findall(r'\(\s*"(\w+)"\s*,\s*"code 0', src)
        assert "visual_parse" not in listed, "诚实性守卫仍把退役项列为存活占位面"
        assert listed, "一条都没列出——判据在空集合上恒真"


class TestGuardIsNotVacuous:
    def test_scannerCatchesInjectedSurface(self, tmp_path):
        """正对照：注入一个假前端封装，扫描必须报出来。"""
        fake = tmp_path / "computer.ts"
        fake.write_text("export function visualParse(a: string) { return a }\n", encoding="utf-8")
        assert _visualParseSurface(fake, fake.read_text(encoding="utf-8")), "扫描判据空转"
        clean = tmp_path / "ok.ts"
        clean.write_text("export function screenshot(a: string) { return a }\n", encoding="utf-8")
        assert _visualParseSurface(clean, clean.read_text(encoding="utf-8")) == [], "误报"
