"""认知层「现役组件表」的生成契约（§6-366）。

背景：`NEUROVA_CogArch_2.0.md` 的 §8.2 是一张 2026-05-12 的手工映射表，70 条路径里 44 条
今天已不存在（台账 §6-362）。按用户裁定它降为沿革档，同时要求补一份**现役认知层组件表**——
且必须由代码生成、不再手维护，否则下一轮重构又会把它写成历史。

本判据锁四件事：
1. 文档里的机读区与生成器**逐字一致**（漂了就跑 `--write`，不手贴）；
2. 表里每一行的路径都在跟踪态里真实存在；
3. 生成器不空转：模块数、子层数、状态三态的分区对账；
4. 聚合索引与**单目标取数口**（`tests.ast_scan.importersOfModule`）在抽样上给同一个数——
   否则"生产读者"这一列迟早会与仓内唯一导入口径分叉（形态集 293/316 那一族）。
"""
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT = REPO_ROOT / "scripts" / "ci" / "cognitive_component_table.py"
DOC = REPO_ROOT / "docs" / "01-architecture" / "cognitive-component-table.md"


def _loadGenerator():
    spec = importlib.util.spec_from_file_location("cognitiveComponentTable", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestGeneratorAndDocExist:
    def test_scriptExistsAndIsTracked(self):
        assert SCRIPT.is_file(), f"生成器不在场：{SCRIPT}"
        tracked = _gitLsFiles("scripts/ci/cognitive_component_table.py")
        assert tracked, "生成器在磁盘上但没进跟踪：别人的工作树与 CI 里它不存在"

    def test_docExistsAndIsTracked(self):
        assert DOC.is_file(), f"现役组件表不在场：{DOC}"
        assert _gitLsFiles("docs/01-architecture/cognitive-component-table.md"), \
            "文档在磁盘上但没进跟踪"


def _gitLsFiles(path: str):
    import subprocess
    return subprocess.run(
        ["git", "ls-files", "--", path], cwd=str(REPO_ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace").stdout.strip()


class TestMachineBlocksMatchGenerator:
    """文档里的两份机读区必须由生成器重算后逐字相等。"""

    def test_summaryBlockMatches(self):
        gen = _loadGenerator()
        actual = gen.extractBlock(DOC.read_text(encoding="utf-8"), gen.SUMMARY_BEGIN, gen.SUMMARY_END)
        expected = gen.renderSummary(gen.componentRows())
        assert actual.strip() == expected.strip(), (
            "组件表摘要与生成器不一致——跑 `python scripts/ci/cognitive_component_table.py --write`")

    def test_tableBlockMatches(self):
        gen = _loadGenerator()
        actual = gen.extractBlock(DOC.read_text(encoding="utf-8"), gen.TABLE_BEGIN, gen.TABLE_END)
        expected = gen.renderTable(gen.componentRows())
        assert actual.strip() == expected.strip(), (
            "组件表与生成器不一致——跑 `python scripts/ci/cognitive_component_table.py --write`")


class TestTableIsNotVacuous:
    def test_rowsCoverTheWholeLayer(self):
        rows = _loadGenerator().componentRows()
        # §6-379 退役 question_decomposer 后现值 92；下限随批次更新，不许无声塌缩。
        assert len(rows) >= 92, f"组件表只 {len(rows)} 行？认知层的模块远不止这些"
        sublayers = {r["sublayer"] for r in rows}
        assert len(sublayers) >= 4, f"只扫到 {len(sublayers)} 个子层：{sorted(sublayers)}"

    def test_statusesPartitionTheRows(self):
        gen = _loadGenerator()
        rows = gen.componentRows()
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        assert set(counts) <= set(gen.STATUSES), (
            f"出现未定义状态 {sorted(set(counts) - set(gen.STATUSES))}——四态口径被改就别再拿它做表")
        assert sum(counts.values()) == len(rows)
        assert len(counts) >= 3, f"只剩 {len(counts)} 种状态，表的区分度已塌：{counts}"

    def test_everyRowPathExists(self):
        rows = _loadGenerator().componentRows()
        missing = [r["path"] for r in rows if not (REPO_ROOT / r["path"]).is_file()]
        assert not missing, f"表里有不存在/未跟踪的路径：{missing[:6]}"


class TestAggregateAgreesWithTheSinglePoint:
    """聚合索引（单趟）与单目标取数口（`ast_scan.importersOfModule`）必须同数。"""

    def test_sampleRowsAgreeWithImportersOfModule(self):
        gen = _loadGenerator()
        from tests import ast_scan
        rows = gen.componentRows()
        #: 每个状态各取一条，取法固定（按路径排序）——换样本会换掉这条判据的复核面
        sample = []
        for status in gen.STATUSES:
            picked = sorted((r for r in rows if r["status"] == status),
                            key=lambda r: r["path"])[:1]
            sample.extend(picked)
        assert len(sample) >= 3, "四态里至少要有三态有行，否则本格失去抽样面"
        for row in sample:
            module = row["path"][:-3].replace("/", ".")
            hits = ast_scan.importersOfModule(REPO_ROOT, module)
            outside = {p for (p, _ln, _form) in hits
                       if p.startswith("neurova/") and not p.startswith(gen.LAYER + "/")}
            assert len(outside) == row["outsideReaders"], (
                f"{module}：聚合索引报 {row['outsideReaders']} 个层外读者，"
                f"单点取数口报 {len(outside)} 个——两把尺分叉了")


class TestComparisonItselfHasTeeth:
    def test_tamperedBlockIsDetected(self):
        gen = _loadGenerator()
        good = gen.renderTable(gen.componentRows())
        tampered = good.replace("在役", "在役 ", 1) if "在役" in good else good + " "
        assert tampered != good
        assert gen.extractBlock(tampered, gen.TABLE_BEGIN, gen.TABLE_END) != gen.renderTable(
            gen.componentRows()), "被篡改一个字符都检不出，逐字比对就是空转"
