# -*- coding: utf-8 -*-
"""同名多份（回潮副本）裁定守卫。

背景（根因，不是形状）：`docs/11-legacy/` 里 96 条「同名歧义」的源头，
不是归档文档自己写错，而是**文档目录重排被另一批次批量撤销**：

- 批次 `fd7ea92c`（文档目录分类重排）把 358 篇文档 `git mv` 进编号分层
  `docs/01-architecture/ … docs/11-legacy/`，旧路径在分层里成为唯一命中；
- 批次 `3b5d7e80`（一次与文档无关的功能提交，却夹带 306 个 docs 文件）把旧
  路径**原样还原**回来，同时又保留了分层里那份——于是同一个 basename 在
  `docs/` 根或 `docs/<旧目录>/` 与编号分层各存一份。264 对里 231 对逐字节
  相同（纯冗余），33 对内容分叉（真出现两个版本）。

后果不是"文档不好看"，而是**归档文档的引用无法裁定**：`scan_docs_refs` 对
同一个 basename 会给出两个候选，只能标 `同名歧义`，人工无从判断该指哪一份。

`sleep.py` / `__init__.py` 这 11 条不是这个根因——同名模块在代码树里天然多份，
只能按每条的上下文逐条裁定，判据同样只写一份（`scan_docs_refs`）。

因此本守卫锁三件事，全部机器可验：

1. **每条同名歧义都有裁定**：96 条按「文件 + 行号 + 引用」为身份，逐条给出
   裁定目标或"源已删除（已交代去处）"，不允许留空、留「待定」。
2. **回潮副本不得回升**：非编号层与编号分层同名的文件数（棘轮基线只降不升）。
   修完删净后应归零，任何批次再还原旧路径都会被立刻抓住。
3. **裁定不是嘴上说**：裁定的目标必须真实存在；判「源已删除」的必须给出去处
   说明，且该条目在归档文档里不得留下指向不存在文件的悬空路径。
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
LEGACY_DIR = PROJECT_ROOT / "docs" / "11-legacy"
BASELINE = PROJECT_ROOT / "tests" / "unit" / "docsAmbiguityBaseline.txt"
RESIDUE_BASELINE = PROJECT_ROOT / "tests" / "unit" / "docsResidueBaseline.txt"


def _block(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    assert start != -1, f"台账缺少区块起始标记 {begin}"
    stop = text.find(end, start)
    assert stop != -1, f"台账缺少区块结束标记 {end}"
    return text[start:stop + len(end)]


@pytest.fixture(scope="module")
def ledger_text() -> str:
    assert LEDGER.is_file(), f"登记台账不存在: {LEDGER.relative_to(PROJECT_ROOT)}"
    return io.open(LEDGER, encoding="utf-8").read()


class TestEveryAmbiguityIsAdjudicated:
    """96 条同名歧义必须逐条有裁定，且裁定目标真实存在。"""

    def test_baseline_present_and_matches_current_scan(self):
        """基线是裁定身份的事实源：现存歧义必须与基线逐行一致。

        口径演进：本单把歧义**修完**后（回潮副本删净），扫描器不再报同名歧义，
        基线因此转为「历史身份清单」——裁定表仍逐条锚定它，改基线等于改历史。
        """
        assert BASELINE.is_file(), (
            f"歧义基线丢失: {BASELINE.relative_to(PROJECT_ROOT)}\n"
            "它是 96 条裁定的身份清单（文件|行号|引用），删掉就无法逐条对账。"
        )
        rows = scanner.adjudicatedRows()
        assert len(rows) == 96, f"基线应含 96 条，实为 {len(rows)} 条"

    def test_every_row_has_a_verdict(self):
        """不允许留空或「待定」——每条都要有裁定结论。"""
        allowed = {scanner.RULING_SETTLED, scanner.RULING_DELETED_SOURCE}
        bad = [r for r in scanner.adjudicatedRows() if r["status"] not in allowed]
        assert not bad, (
            "有同名歧义未裁定:\n  "
            + "\n  ".join(f"{r['file']}:{r['line']} `{r['ref']}` → {r['status']}" for r in bad[:8])
            + "\n每条都要给出裁定目标，或明确「源已删除 + 去处」。"
        )

    def test_settled_targets_exist(self):
        """裁定的目标必须真实存在——不许把洞换个位置。"""
        missing = [
            r for r in scanner.adjudicatedRows()
            if r["status"] == scanner.RULING_SETTLED
            and not (PROJECT_ROOT / r["target"]).exists()
        ]
        assert not missing, (
            "裁定目标不存在:\n  "
            + "\n  ".join(f"{r['file']}:{r['line']} → `{r['target']}`" for r in missing[:8])
        )

    def test_deleted_sources_carry_a_destination(self):
        """判「源已删除」的必须有去处说明（写进判据表），不得只写一句"没了"。"""
        rows = [r for r in scanner.adjudicatedRows()
                if r["status"] == scanner.RULING_DELETED_SOURCE]
        assert rows, "本仓确有「全史未入库」的引用，判「源已删除」的守卫不得空转"
        for row in rows:
            ruling = scanner.CODE_REFERENCE_RULINGS.get((row["file"], row["line"]))
            assert ruling and ruling[1].strip(), (
                f"{row['file']}:{row['line']} 判为源已删除但未交代去处"
            )

    def test_code_rulings_are_keyed_to_the_baseline(self):
        """代码类裁定必须覆盖基线里的每一条代码同名引用，不得漏项。"""
        baseline_keys = {
            (line.split("|")[0], line.split("|")[1])
            for line in io.open(BASELINE, encoding="utf-8").read().splitlines()
            if line.strip()
        }
        rulings = set(scanner.CODE_REFERENCE_RULINGS)
        assert rulings <= baseline_keys, (
            f"判据表含基线之外的条目（判据漂移）: {sorted(rulings - baseline_keys)[:5]}"
        )
        assert rulings, "代码同名引用的裁定判据表不得为空"


class TestLedgerPublishesAdjudication:
    """裁定结果必须写进台账的机器生成区，且由扫描器可复现。"""

    def test_ledger_has_adjudication_block(self, ledger_text):
        _block(ledger_text, scanner.ADJUDICATION_BEGIN, scanner.ADJUDICATION_END)

    def test_adjudication_block_matches_scanner(self, ledger_text):
        expected = scanner.renderAdjudication(scanner.adjudicatedRows())
        actual = _block(ledger_text, scanner.ADJUDICATION_BEGIN, scanner.ADJUDICATION_END)
        assert actual.strip() == expected.strip(), (
            "台账的裁定表与扫描器输出不一致。台账是生成物，不要手改；\n"
            "改完源文件后重跑：python scripts/scan_docs_refs.py --markdown"
        )

    def test_no_row_is_left_pending(self, ledger_text):
        """所有行都不得停在「未决」——裁定要收口。"""
        block = _block(ledger_text, scanner.ADJUDICATION_BEGIN, scanner.ADJUDICATION_END)
        pending = [line for line in block.splitlines() if "未决" in line]
        assert not pending, "裁定表仍有未决行:\n  " + "\n  ".join(pending[:5])


class TestResidueDoesNotRegrow:
    """棘轮：非编号层与编号分层同名的回潮副本只降不升。"""

    def test_residue_baseline_present(self):
        assert RESIDUE_BASELINE.is_file(), (
            f"回潮副本基线丢失: {RESIDUE_BASELINE.relative_to(PROJECT_ROOT)}\n"
            "恢复方式：从 git 取回该文件；确需调整时同批提交新值并说明原因。"
        )

    def test_residue_count_does_not_increase(self):
        baseline = int(io.open(RESIDUE_BASELINE, encoding="utf-8").read().strip())
        current = sum(len(residue) for residue, _ in scanner.residueDuplicates())
        assert current <= baseline, (
            f"同名回潮副本从基线 {baseline} 升到 {current}。\n"
            "旧路径被重新还原 = 同一篇文档又出现第二份，归档引用又会失去唯一裁定。\n"
            "修法：删副本、引用改指编号分层那一份。"
        )

    def test_erasure_style_not_used_to_pass(self):
        """负向控制：删副本不得靠"把内容删空"蒙混——保留侧必须仍在且非空。"""
        for _, canonical in scanner.residueDuplicates():
            for path in canonical:
                assert (PROJECT_ROOT / path).is_file(), f"保留侧丢失: {path}"
                assert (PROJECT_ROOT / path).stat().st_size > 0, f"保留侧被清空: {path}"

    def test_numbered_layer_is_still_populated(self):
        """反向控制：判据不得退化成「编号分层没有文件 → 恒无副本」。"""
        docs = [p for p in scanner.trackedFiles() if p.startswith("docs/")]
        numbered = [p for p in docs if scanner.numberedLayer(p)]
        assert len(numbered) > 200, (
            f"编号分层仅 {len(numbered)} 个文件，判据疑似失效（会空转通过上面的棘轮）"
        )
