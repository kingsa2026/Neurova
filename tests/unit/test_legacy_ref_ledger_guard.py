# -*- coding: utf-8 -*-
"""历史悬空引用登记台账守卫。

背景（根因，不是形状）：`docs/11-legacy/` 是归档层，内部大量失效引用——
它们不是「没人写文档」，而是**「用清空代替修复」留下的洞**。前序批次
`663faa5d` / `5f94b93d` 在清理第三方借鉴痕迹与重排目录时，把带行号的
引用直接删成空反引号 ``，或把路径删成 `docs/INDEX.md` →（空）。
这正是修复教义第 2 条禁止的「抹除表面报错」：报错没了，信息也没了。

归档层不就地改写（历史可追溯性优先），但也**不许静默遗留**（教义第 5 条）。
因此本单的落点是「登记台账 + 逐条可达性判定」，并由本守卫常驻锁住：

1. **台账必须与扫描口径同源** —— 台账的机器区由 `scripts/scan_docs_refs.py`
   生成；守卫重跑同一扫描器逐行比对。人在台账里手改一行、或新增一处悬空
   引用却没登记，都会红。
2. **每条悬空引用都必须有判定** —— 判定取自固定的四种形态
   （迁移可达 / 同名歧义 / 源已删除 / 空标签悬空），不允许留空、留「待定」。
3. **空标签必须回填前像** —— `[文字]()` / 空反引号是「删掉目标」的产物，
   信息本体还在 git 历史里。台账须逐条给出前像目标与其可达性；前像数量
   必须与扫描出的空标签数量相等（新增一处空标签而不登记前像即红）。
4. **不得谎报已修** —— 源文件里仍然存在的空标签，台账不得记成「已修复 /
   已还原」。这是「禁止表面抹除」的反向断言：不许用改台账代替改事实。

扫描器与被测台账都在本文件外，守卫只做「重算 + 比对」，不复制判据。
"""
import io
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SCANNER = PROJECT_ROOT / "scripts" / "scan_docs_refs.py"
LEDGER = PROJECT_ROOT / "docs" / "06-bugfix" / "历史悬空引用登记台账_2026-09-21.md"
LEGACY_DIR = PROJECT_ROOT / "docs" / "11-legacy"

scanner = pytest.importorskip("scripts.scan_docs_refs")

ALLOWED_VERDICTS = set(scanner.VERDICTS)


def _ledger_text() -> str:
    assert LEDGER.is_file(), (
        f"登记台账不存在: {LEDGER.relative_to(PROJECT_ROOT)}\n"
        "docs/11-legacy/ 的悬空引用必须登记成台账（教义第 5 条：不许静默遗留）。"
    )
    return io.open(LEDGER, encoding="utf-8").read()


def _block(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    assert start != -1, f"台账缺少区块起始标记 {begin}"
    stop = text.find(end, start)
    assert stop != -1, f"台账缺少区块结束标记 {end}"
    return text[start:stop + len(end)]


@pytest.fixture(scope="module")
def entries() -> list:
    return scanner.scanDirectory(LEGACY_DIR)


class TestLedgerIsRegenerable:
    """台账机器区必须能由扫描器原样复现——否则台账与事实各说各话。"""

    def test_ledger_machine_block_matches_scanner(self, entries):
        expected = scanner.renderTable(entries)
        actual = _block(_ledger_text(), scanner.TABLE_BEGIN, scanner.TABLE_END)
        assert actual.strip() == expected.strip(), (
            "台账的悬空引用表与扫描器输出不一致。\n"
            "台账是生成物，不要手改；改完源文件后重跑：\n"
            "  python scripts/scan_docs_refs.py --markdown\n"
            "期望行数 %d，实际行数 %d。"
            % (expected.count("\n"), actual.count("\n"))
        )

    def test_ledger_summary_matches_scanner(self, entries):
        """摘要区（总数 + 按文件分布）同样是生成物——手写的数字必然漂移。"""
        expected = scanner.renderSummary(entries)
        actual = _block(_ledger_text(), scanner.SUMMARY_BEGIN, scanner.SUMMARY_END)
        assert actual.strip() == expected.strip(), (
            "台账摘要区与扫描器输出不一致（总数或按文件分布漂移）。\n"
            "重跑：python scripts/scan_docs_refs.py --markdown"
        )

    def test_scanner_actually_finds_this_directory(self, entries):
        """反向控制：扫描器不得退化成恒返回空（那样上面的比对会空转通过）。"""
        assert entries, (
            "扫描器在 docs/11-legacy/ 上零命中：要么目录被清空，要么扫描器失效。\n"
            "禁止用「扫不到就算过」短路本守卫。"
        )

    def test_scanner_detects_injected_dangling_ref(self, tmp_path):
        """负向控制：注入一处空标签与一处已删除路径，扫描器必须报出来。"""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# 样例\n\n参见 `` 与 `neurova/这条路径并不存在_zzz.py`。\n",
            encoding="utf-8",
        )
        byBasename = scanner.indexByBasename(scanner.trackedFiles())
        found = scanner.scanFile(sample, byBasename)
        verdicts = {item["verdict"] for item in found}
        assert scanner.VERDICT_EMPTY in verdicts, "空反引号未被识别为悬空标签"
        assert scanner.VERDICT_DELETED in verdicts, "已删除路径未被识别"


class TestEveryEntryIsClassified:
    """每条悬空引用都要有判定，不允许留空或「待定」。"""

    def test_all_rows_carry_allowlisted_verdict(self, entries):
        bad = [e for e in entries if e["verdict"] not in ALLOWED_VERDICTS]
        assert not bad, f"存在非法判定: {bad[:5]}"

    def test_ledger_documents_every_verdict(self, entries):
        text = _ledger_text()
        missing = sorted({e["verdict"] for e in entries} - {v for v in ALLOWED_VERDICTS if v in text})
        assert not missing, (
            f"台账未定义这些判定形态的处置口径: {missing}\n"
            "每种形态都要写明「谁负责、怎么处理」，否则判定等于没做。"
        )

    def test_every_row_is_in_the_ledger_block(self, entries):
        """按「文件 + 行号」判定登记，不比对引用原文。

        引用原文会被表格渲染规范化（空反引号渲染成文字占位），拿它做包含判断
        会得出假阳性——本守卫自己就踩过一次。行号是稳定身份。
        """
        block = _block(_ledger_text(), scanner.TABLE_BEGIN, scanner.TABLE_END)
        missing = [
            e for e in entries
            if f"`{e['file']}` | {e['line']} " not in block
        ]
        assert not missing, (
            f"有悬空引用未登记进台账: {[(e['file'], e['line'], e['ref']) for e in missing][:5]}"
        )


class TestEmptyLabelsCarryPreimage:
    """空标签是「删掉目标」的产物——必须回填前像，否则信息永久丢失。"""

    PREIMAGE_BEGIN = "<!-- LEDGER:PREIMAGE:BEGIN -->"
    PREIMAGE_END = "<!-- LEDGER:PREIMAGE:END -->"

    @staticmethod
    def _rows() -> list:
        block = _block(_ledger_text(), TestEmptyLabelsCarryPreimage.PREIMAGE_BEGIN,
                       TestEmptyLabelsCarryPreimage.PREIMAGE_END)
        rows = []
        for line in block.splitlines():
            line = line.strip()
            if not line.startswith("|") or set(line) <= set("|-: "):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if cells[0] == "文件":
                continue
            rows.append(cells)
        return rows

    def test_preimage_count_matches_empty_labels(self, entries):
        empties = [e for e in entries if e["verdict"] == scanner.VERDICT_EMPTY]
        rows = self._rows()
        assert len(rows) == len(empties), (
            "前像表行数（%d）与扫描出的空标签数（%d）不等。\n"
            "新增一处空标签就必须补一行前像（从 git 历史取被删掉的目标）。"
            % (len(rows), len(empties))
        )

    def test_preimage_targets_are_non_empty(self):
        for row in self._rows():
            assert len(row) >= 4, f"前像表列数不足: {row}"
            target = row[2].strip("`").strip()
            assert target and target not in ("—", "-", "无", "N/A"), (
                f"空标签前像未回填: {row}\n"
                "「前像无对应」不是可接受的判定——需要人工核到具体目标，"
                "或在台账正文写明为何确实无处可指。"
            )

    def test_preimage_status_is_judged(self):
        allowed = {"前像可达", "前像亦已删除"}
        for row in self._rows():
            assert row[3].strip() in allowed, (
                f"前像可达性判定非法: {row}\n应为 {sorted(allowed)} 之一。"
            )


class TestLedgerExposesHonestState:
    """台账必须以诚实形态暴露「洞还在」，不得被读成一次修复。

    修复教义第 2 条：报错要么被根修，要么以诚实形态暴露。归档层选择的是后者
    （历史可追溯性优先，不就地改写），那就必须**写明**这一点——
    否则读者会把「登记台账」误读成「已处置」，这正是本次要禁止的表面抹除。
    """

    DEVICE_WORDS = ("已修复", "已还原", "已补齐")

    def test_ledger_states_holes_remain(self):
        """必须明写归档层不就地改写 / 未修复，读者才不会误判。"""
        text = _ledger_text()
        assert re.search(r"不就地改写|未修复|不承诺", text), (
            "台账未写明「归档层不就地改写、洞仍在」——"
            "读者会把登记误读成修复，等于用台账代替修事实。"
        )

    def test_no_entry_is_marked_as_repaired(self, entries):
        """逐行核对：任何一条悬空引用的判定，都不许是「已修复」形态。

        这是上一版守卫踩过的坑——按散文关键词扫「已修复」会把
        『不得记成已修复』这句规范本身扫成违规（假阳性）。改为**逐行判定**：
        稳定的身份是「文件 + 行号」，稳定的判据是判定列取值。
        """
        block = _block(_ledger_text(), scanner.TABLE_BEGIN, scanner.TABLE_END)
        offenders = []
        for line in block.splitlines():
            if not line.startswith("|"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4 or cells[0] == "文件":
                continue
            verdict = cells[3]
            if any(word in verdict for word in self.DEVICE_WORDS):
                offenders.append(cells[:4])
        assert not offenders, (
            "台账把悬空引用记成了已修复形态（源文件里引用仍然悬空）:\n  "
            + "\n  ".join(str(o) for o in offenders[:5])
            + "\n登记台账不得代替修事实。"
        )
