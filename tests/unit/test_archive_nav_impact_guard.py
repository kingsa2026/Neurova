# -*- coding: utf-8 -*-
"""归档层「是否影响当下导航」筛选守卫（Issue #68 下一层）。

背景（根因，不是形状）：归档层有 1800 余条失效引用，但它们**不是同一件事**。
此前几轮的口径是「归档层一律只登记、不就地改写」——理由成立（归档正文陈述的是
**当时**的代码结构与路径，改成今天的形态反而让历史记录与历史事实不符），
但这条口径把两类性质完全不同的东西混在了一起：

- 绝大多数条目所在的文档**今天没有任何读者走得到**（不在导航图里），改它等于改写历史；
- 少数条目所在的文档**当下打开就能走到**（导航可达），其中可点击的引用**点开就 404**。
  这类不是「历史留痕」，是**当下把人带错路**。

不筛这一轮，口径就只有两个极端：全改（破坏可追溯性）或全不改（把当下的坏导航
当成历史正当形态）。本单把「是否影响当下导航」变成**可复算的判据**，判据只写一份
（`scripts/scan_docs_refs.py` 的 `navigationImpactRefs`），本守卫只做「重算 + 比对 + 负向控制」。

两要件（全部成立才入筛）：

1. **载体在当下导航图里可达**：从 `NAVIGATION_ROOTS`（仓库入口文档 + `docs/0-index/README.md`）
   出发沿可解析链接与目录链接做传递闭包。
2. **载体满足二者之一**：
   - `甲·可点击引用`（Markdown 链接 / 图片 / HTML `src|href`）：点开即 404。**硬零**——
     与活跃层同一条纪律，没有「归档层不就地改写」的豁免。
   - `乙·指路条目`：载体是专职指路的文档（`INDEX.md` / `README.md`，或标题写明
     清单/索引/图谱/单一事实源）。失效条目把它指错地方，但**整篇级过期不是改路径
     能解决的**——故登记 + 单独立项，不得用改台账代替立项。

因此本守卫锁四件事：

1. **甲类硬零**：入筛的可点击引用必须修完（改指真实路径，或改显式文本交代去处）。
2. **乙类必须立项**：登记的每一条指路条目都要有**立项单**承接，不许停在「已登记」。
3. **豁免理由可复算**：被筛掉的每一条都能说出为什么（三条理由，不是「人工看过了」）。
4. **筛选不得空转**：范围与判据都做反向控制——缩成空集、误把归档层当活跃层、
   把不可达文档算进导航图，都会被本守卫抓住。
"""
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

scanner = pytest.importorskip("scripts.scan_docs_refs")

LEDGER = PROJECT_ROOT / "docs" / "06-bugfix" / "历史悬空引用登记台账_2026-09-21.md"
REPOINT_BASELINE = PROJECT_ROOT / "tests" / "unit" / "archiveNavImpactBaseline.txt"


def _ledger_text() -> str:
    assert LEDGER.is_file(), f"登记台账不存在: {LEDGER.relative_to(PROJECT_ROOT)}"
    return io.open(LEDGER, encoding="utf-8").read()


def _block(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    assert start != -1, f"台账缺少区块起始标记 {begin}"
    stop = text.find(end, start)
    assert stop != -1, f"台账缺少区块结束标记 {end}"
    return text[start:stop + len(end)]


class TestCriterionIsSingleSourced:
    """判据必须由扫描器提供，守卫不另写一套解析。"""

    def test_scanner_exposes_the_screening_surface(self):
        for name in ("navigationImpactRefs", "navigationImpactExemptions",
                     "readerReachableDocuments", "isNavigationBearing",
                     "archiveDanglingUnion"):
            assert hasattr(scanner, name), (
                f"扫描器未提供 {name}()：「是否影响当下导航」的判据缺位，"
                "本守卫会退化成一条空规则。"
            )

    def test_navigation_roots_are_declared(self):
        roots = scanner.NAVIGATION_ROOTS
        assert "README.md" in roots and "docs/INDEX.md" in roots, (
            "导航起点必须含仓库入口与文档索引——缺了它们，传递闭包从开始就断。"
        )
        assert "docs/0-index/README.md" in roots, (
            "`docs/0-index/README.md` 正文自述为 `docs/` 目录的唯一入口，"
            "且被 AGENTS.md 点名；不认它，按领域分层的文档全成「无人走得到」，筛选会空转。"
        )


class TestScreeningDoesNotRunVacuous:
    """反向控制：范围与判据都不得退化。"""

    def test_archive_scope_is_not_empty(self):
        """被筛的总体必须真实存在（否则下面的硬零断言会白通过）。"""
        total = len(scanner.archiveDanglingUnion())
        assert total > 1000, f"归档层只扫到 {total} 条悬空引用，范围疑似失效。"

    def test_reachable_scope_covers_navigation_graph(self):
        reached = scanner.readerReachableDocuments()
        assert len(reached) > 200, (
            f"导航图只覆盖 {len(reached)} 篇文档，疑似退化成仅入口文档。"
        )

    def test_archive_layers_are_not_treated_as_active(self):
        """归档层不得混进活跃层判据——两者口径不同（硬零 vs 登记）。"""
        reached = scanner.readerReachableDocuments()
        archives = [p for p in reached if p.startswith("docs/05-reports/")]
        assert archives, "归档层文档必须能出现在导航图里（否则筛选恒空）"
        assert not any(p.startswith("docs/11-legacy/") for p in scanner.activeLayerDocuments()), (
            "归档层文档混进了活跃层范围——口径混了会把历史留痕当成当下可读面。"
        )

    def test_injected_unreachable_document_is_exempt(self, tmp_path, monkeypatch):
        """负向控制：导航图外的载体不得入筛（那是历史留痕，不是当下导航）。"""
        unreachable = "docs/05-reports/这条路径并不存在的报告_zzz.md"
        assert unreachable not in scanner.readerReachableDocuments()
        byBasename = scanner.indexByBasename(scanner.trackedFiles())
        sample = tmp_path / "sample.md"
        sample.write_text("# 样例\n\n见 [目标](../并不存在的目标_zzz.md)。\n", encoding="utf-8")
        found = scanner.scanDocumentLinks(sample, byBasename)
        assert found, "注入的可点击悬空引用未被检出"

    def test_navigation_bearing_detection_is_real(self):
        assert scanner.isNavigationBearing("docs/11-legacy/INDEX.md"), "INDEX.md 判定为指路文档"
        assert scanner.isNavigationBearing("docs/09-dev-progress/api_inventory.md"), (
            "标题写明「清单」的文档判定为指路文档"
        )
        assert not scanner.isNavigationBearing("docs/05-reports/FIX_SUMMARY.md"), (
            "叙事型报告不得被判为指路文档——判错会把整批历史报告拖进立项范围"
        )

    def test_placeholder_paths_are_exempt(self):
        """占位/模板路径不是真实目标，改指无从谈起。"""
        assert scanner.PLACEHOLDER_PATH_PATTERN.search("daily_reports/YYYY-MM-DD.md")
        assert scanner.PLACEHOLDER_PATH_PATTERN.search("neurova/xxx/yyy.py")
        assert not scanner.PLACEHOLDER_PATH_PATTERN.search("neurova/api/endpoints/auth.py")


class TestClickableRefsAreFixed:
    """甲类（可点击引用）是硬零：点开就 404 的链接不适用「归档层不就地改写」。"""

    def test_no_clickable_dangling_in_reachable_archive(self):
        rows = [r for r in scanner.navigationImpactRefs()
                if r["form"] == scanner.IMPACT_FORM_CLICKABLE]
        rendered = "\n  ".join(
            f"{r['file']}:{r['line']} [{r['ref']}]（{r['verdict']}）" for r in rows[:20]
        )
        assert not rows, (
            f"导航可达的归档文档里仍有 {len(rows)} 处可点击死链——读者点开即 404。\n"
            "修法：改指真实可达的路径，或改显式文本交代去处；\n"
            "归档层「不就地改写」的豁免只适用于**不可点击的路径陈述**，不适用于可点击链接。\n  "
            + rendered
        )

    def test_repointed_links_point_at_real_targets(self):
        """上一类修完后的正向事实：这些链接必须真的解析得到。"""
        assert REPOINT_BASELINE.is_file(), (
            f"改指基线丢失: {REPOINT_BASELINE.relative_to(PROJECT_ROOT)}\n"
            "它记录本单改指过的位置（文件|行号|目标），用于防回退；删掉就无法对账。"
        )
        lines = [l for l in io.open(REPOINT_BASELINE, encoding="utf-8").read().splitlines()
                 if l.strip() and not l.startswith("#")]
        assert lines, "改指基线不得为空——本单确实改指过条目"
        byBasename = scanner.indexByBasename(scanner.trackedFiles())
        for line in lines:
            relative, lineNo, target = line.split("|")
            source = PROJECT_ROOT / relative
            assert source.is_file(), f"基线里的载体不存在: {relative}"
            verdict, hit = scanner.resolveTarget(target, source, byBasename)
            assert verdict == scanner.VERDICT_REACHABLE, (
                f"{relative}:{lineNo} 改指目标解析不到: `{target}` → {verdict} {hit}\n"
                "改指不是「换个写法」——必须真的指向存在的目标。"
            )


class TestPointerEntriesAreProjectInitiated:
    """乙类（指路条目）必须立项承接——登记不代替立项。"""

    def test_ledger_publishes_the_impact_section(self):
        text = _ledger_text()
        _block(text, scanner.NAV_IMPACT_SUMMARY_BEGIN, scanner.NAV_IMPACT_SUMMARY_END)
        _block(text, scanner.NAV_IMPACT_BEGIN, scanner.NAV_IMPACT_END)

    def test_summary_block_matches_scanner(self):
        expected = scanner.renderNavigationImpactSummary(scanner.navigationImpactRefs())
        actual = _block(_ledger_text(), scanner.NAV_IMPACT_SUMMARY_BEGIN,
                        scanner.NAV_IMPACT_SUMMARY_END)
        assert actual.strip() == expected.strip(), (
            "台账的筛选摘要与扫描器输出不一致。台账是生成物，不要手改；\n"
            "重跑：python scripts/scan_docs_refs.py --markdown"
        )

    def test_impact_table_matches_scanner(self):
        expected = scanner.renderNavigationImpact(scanner.navigationImpactRefs())
        actual = _block(_ledger_text(), scanner.NAV_IMPACT_BEGIN, scanner.NAV_IMPACT_END)
        assert actual.strip() == expected.strip(), (
            "台账的入筛条目表与扫描器输出不一致（重跑扫描器刷新）。"
        )

    def test_every_pointer_entry_is_registered_in_the_impact_table(self):
        rows = [r for r in scanner.navigationImpactRefs()
                if r["form"] == scanner.IMPACT_FORM_POINTER]
        block = _block(_ledger_text(), scanner.NAV_IMPACT_BEGIN, scanner.NAV_IMPACT_END)
        missing = [r for r in rows if f"`{r['file']}` | {r['line']} " not in block]
        assert not missing, (
            "有指路条目未登记进筛选表: "
            + str([(r["file"], r["line"], r["ref"]) for r in missing][:5])
        )

    def test_each_pointer_carrier_names_a_project_issue(self):
        """指路条目的载体必须逐篇给出立项单编号——「已登记」不是终点。"""
        rows = [r for r in scanner.navigationImpactRefs()
                if r["form"] == scanner.IMPACT_FORM_POINTER]
        if not rows:
            pytest.skip("本轮无指路条目入筛（甲类修完后可能如此）")
        text = _ledger_text()
        carriers = sorted({r["file"] for r in rows})
        for carrier in carriers:
            assert f"{carrier}` → 立项单" in text or f"`{carrier}` 立项单" in text, (
                f"指路条目载体 {carrier} 未登记立项单。\n"
                "整篇级过期不是改路径能解决的——必须单独立项由人决定去留，"
                "不许停在「已登记」了事（教义第 5 条：不许静默遗留）。"
            )

    def test_pointer_carrier_baseline_does_not_grow(self):
        """棘轮：入筛的指路条目只降不升——新增一处说明又有导航入口被写坏。"""
        baseline = scanner.POINTER_ENTRY_BASELINE
        assert baseline.is_file(), (
            f"指路条目基线丢失: {baseline.relative_to(PROJECT_ROOT)}\n"
            "恢复方式：从 git 取回该文件；确需调整时同批提交新值并说明原因。"
        )
        limit = int(io.open(baseline, encoding="utf-8").read().strip())
        current = len([r for r in scanner.navigationImpactRefs()
                       if r["form"] == scanner.IMPACT_FORM_POINTER])
        assert current <= limit, (
            f"入筛的指路条目从基线 {limit} 升到 {current}。\n"
            "新增 = 又有专职指路的文档被写坏，读者会顺着它走错路。\n"
            "修法：把条目改指真实目标，或把该篇从导航入口摘除并标注为历史快照。"
        )


class TestExemptionsAreAccountedFor:
    """豁免不是「眼不见为净」：每一条都能说出为什么，且账目闭合。"""

    def test_every_entry_lands_in_exactly_one_bucket(self):
        total = len(scanner.archiveDanglingUnion())
        assigned = len(scanner.navigationImpactRefs())
        counters = scanner.navigationImpactExemptions()
        assert assigned + sum(counters.values()) == total, (
            f"筛选账目未闭合：入筛 {assigned} + 豁免 {sum(counters.values())} != 总 {total}。\n"
            "有条目既不登记也不豁免——静默丢弃正是本单要杜绝的形态。"
        )

    def test_exemption_reasons_are_enumerated(self):
        counters = scanner.navigationImpactExemptions()
        assert set(counters) == {scanner.EXEMPT_UNREACHABLE, scanner.EXEMPT_NARRATIVE,
                                 scanner.EXEMPT_PLACEHOLDER}, (
            "豁免理由必须逐条枚举（三条），不得用「其他」兜底——兜底理由等于没理由。"
        )

    def test_majority_of_archive_is_exempt_for_a_statable_reason(self):
        """事实自证：归档层的绝大多数确实不构成当下导航问题。"""
        counters = scanner.navigationImpactExemptions()
        total = len(scanner.archiveDanglingUnion())
        assert counters[scanner.EXEMPT_UNREACHABLE] > total * 0.3, (
            "「无当下读者」占比过低，疑似导航图判定出了问题（把整个 docs/ 都算可达了）。"
        )
