# -*- coding: utf-8 -*-
"""票集正文与索引表的一致性守卫（Issue #80 工具↔经验环路批）。

背景（根因，不是形状）：本批 001–011 的**票面正文**（每张票的收工判据）
此前只存在于 Issue #80 的附件里，仓库内只有 `000-索引.md`。于是：

- 索引表里 11 行「主要落点」把人指向 11 份**仓库内不存在**的票面；
- 复核者无法在仓内读到「这张票到底要求什么」，
  只能拿合并后的代码去猜判据——「收工判据」在该批实际是不可复核的；
- 本轮之前没有任何机器判据会发现这件事：索引表是 Markdown 表格，
  悬空引用扫描器只认**具体路径**（`docs/x/y.md`）与可点击链接，
  「表格里写了个不存在的票号」不在任何判据内。

这正是协作红线点名的那类断点：写了索引、没有可读的票面，
写入→读取的环在「读者」这一环断掉。

本守卫只锁两件事，判据取自索引表本体（不另写一份票号清单）：

1. **索引表里每个票号都必须有对应的票面文件**（`NNN-*.md`，同名唯一）；
2. **反向控制**：索引表必须真的含多行（解析器失效时不许静默通过），
   且抽出票号的解析逻辑必须能识别「缺一份」的形态。
"""
import io
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TICKETS = PROJECT_ROOT / "docs" / "specs" / "2026-09-21-tool-experience-loop" / "tickets"
INDEX = TICKETS / "000-索引.md"

#: 索引表行首的票号单元格（`| 001 | 标题 |`）
ROW = re.compile(r"^\|\s*(\d{2,3}[a-z0-9]*)\s*\|")

#: 断点编号索引表的行（`| L-02 | 003 | … |`）
DEFECT_ROW = re.compile(r"^\|\s*(L-\d{2}[a-z]?)\s*\|\s*([^|]*)\|")


def _declaredNumbers() -> list:
    """索引表声明的票号（按出现顺序）。"""
    assert INDEX.is_file(), f"票集索引缺失：{INDEX.relative_to(PROJECT_ROOT)}"
    text = io.open(INDEX, encoding="utf-8").read()
    numbers = []
    for line in text.splitlines():
        match = ROW.match(line.strip())
        if match:
            numbers.append(match.group(1))
    return numbers


def _missingBodies(declared: list, existing: dict) -> list:
    """声明了票号、目录里却没有票面正文的那些号（判据本体，纯函数）。"""
    return [number for number in declared if number not in existing]


def _filesByNumber() -> dict:
    """目录内每一份票面正文，按票号归档（同号多份即歧义）。"""
    found: dict = {}
    for path in sorted(TICKETS.glob("*.md")):
        number = path.name.split("-")[0]
        if not number.isdigit():
            continue
        found.setdefault(number, []).append(path.name)
    return found


class TestTicketBodiesExistInRepo:
    def test_indexTableIsNotEmpty(self):
        numbers = _declaredNumbers()
        assert len(numbers) >= 10, (
            f"索引表只解析出 {len(numbers)} 个票号——解析口径失效时本守卫会静默空转，"
            "先修解析再谈票面齐不齐"
        )

    def test_everyDeclaredTicketHasABody(self):
        missing = _missingBodies(_declaredNumbers(), _filesByNumber())
        assert missing == [], (
            "索引表声明的票号在仓库内没有对应的票面正文，"
            "「收工判据」因此不可复核（票面正文必须随索引一起入库）:\n  "
            + "\n  ".join(f"{n} → 缺 {n}-*.md" for n in missing)
        )

    def test_bodiesAreUniqueAndNonTrivial(self):
        existing = _filesByNumber()
        duplicated = {n: names for n, names in existing.items() if len(names) > 1}
        assert duplicated == {}, f"同一票号有多份票面正文（事实源分叉）：{duplicated}"
        thin = []
        for names in existing.values():
            path = TICKETS / names[0]
            text = io.open(path, encoding="utf-8").read()
            if len(text.strip()) < 200 or "## " not in text:
                thin.append(names[0])
        assert thin == [], f"票面正文过薄（无任何小节，等于占位）：{thin}"

    def test_resultSectionsAreFilledNotPlaceholders(self):
        """票面的「执行结果」不得停在占位符上。

        票面入库只是把判据变成可读的；判据旁边**留着一格空白的「执行结果」**，
        等于「写出字段、没人读」——读者拿到票面还是得去别处找读数。票面既然进仓，
        这一格就必须填上（读数、或诚实的「未做到 + 原因」，二选一，不留"待填"）。
        """
        empty = []
        for path in sorted(TICKETS.glob("[0-9][0-9][0-9]-*.md")):
            if path.name.startswith("000-"):
                continue  # 索引不是票面：它本身就写着「不许留占位」这条口径
            text = io.open(path, encoding="utf-8").read()
            for number, line in enumerate(text.splitlines(), 1):
                if "待填" in line:
                    empty.append(f"{path.name}:{number}")
        assert empty == [], (
            "票面的执行结果仍是占位符——票面进仓了，判据旁边的读数格却空着，"
            "读者还得去别处找:\n  " + "\n  ".join(empty)
        )

    def test_placeholderCriterionIsNotVacuous(self):
        """反向控制：占位符判据必须真的认得占位符（合成输入，不看仓库现状）。"""
        assert "待填" in "```\n待填：xxx\n```"
        assert "待填" not in "实测 3 failed → 5 passed，读数见 §8.1"

    def test_detectorActuallyNoticesAMissingBody(self):
        """反向控制：判据必须真的看得出「索引有号、目录无文」。

        不拿仓库现状当输入——否则这条用例会随「票面齐没齐」变色，
        变成复述配置的恒真断言。这里只喂合成输入。
        """
        missing = _missingBodies(["001", "099"], {"001": ["001-a.md"]})
        assert missing == ["099"], "判据认不出缺号——真缺票面时本守卫会放它过去"


# ---------------------------------------------------------------------------
# 判据二：本批文档里写出的**仓库路径引用**必须可达
# ---------------------------------------------------------------------------
# 票集与规格是「收工判据」的事实源。里面点名 `docs/adr/0018-*.md` 这类落点，
# 读者按它去找就必须找得到——指到已退役目录（`docs/adr/`）或已改名的文件
# （ADR 0018 → 0019）同样是「把人带错路」，与悬空链接同一个性质。
# 判据复用仓库既有的引用判定（`scripts/scan_docs_refs.py`），不另写一套解析。
#
# 不入判据的三类（可复算，非人工放行）：
#   - 生产库路径（`data/...`）：`data/` 不进版本控制，缺席是设计而非缺陷；
#   - 通配 / 占位形态（`tests/unit/tool_tools_*.py`、`<FILE>`）：描述的是模式；
#   - 行号后缀（`file.py:253`）：去掉行号后按普通路径判定。

def _batchDocuments() -> list:
    """判据覆盖面：规格 + 台账 + 索引 + **每一份票面正文**。

    票面正文进仓后就是「收工判据」的事实源，其中的落点引用与人读的入口同等重要——
    只判索引不判票面，等于把新入库的 11 份正文留在判据之外。
    """
    root = "docs/specs/2026-09-21-tool-experience-loop"
    documents = [
        "docs/specs/2026-09-21-tool-experience-loop-repair.md",
        f"{root}/入口迁移台账.md",
    ]
    documents += [f"{root}/tickets/{path.name}" for path in sorted(TICKETS.glob("*.md"))]
    return documents


BATCH_DOCUMENTS = _batchDocuments()

REPO_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./\-]*\.(?:py|md|ts|vue|json|ya?ml|txt|sh)$")
PRODUCTION_PREFIX = ("data/",)


def _repoRefs(text: str) -> list:
    """文档里以行内码写出的仓库路径引用（已去掉行号后缀）。"""
    refs = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in re.finditer(r"`([^`\n]+)`", line):
            token = match.group(1)
            if "/" not in token or any(ch in token for ch in "*{}<>"):
                continue
            token = token.split(":")[0].strip()
            if not REPO_PATH.match(token) or token.startswith(PRODUCTION_PREFIX):
                continue
            refs.append((number, token))
    return refs


class TestBatchDocRepoRefsResolve:
    @staticmethod
    def _scanner():
        return pytest.importorskip("scripts.scan_docs_refs")

    def test_everyRepoRefResolves(self):
        scanner = self._scanner()
        byBasename = scanner.indexByBasename(scanner.trackedFiles())
        unresolved = []
        for relative in _batchDocuments():
            source = PROJECT_ROOT / relative
            assert source.is_file(), f"本批文档缺失：{relative}"
            text = io.open(source, encoding="utf-8").read()
            for number, token in _repoRefs(text):
                verdict, hit = scanner.resolveTarget(token, source, byBasename)
                if verdict in (scanner.VERDICT_DELETED, scanner.VERDICT_AMBIGUOUS):
                    unresolved.append(f"{relative}:{number} `{token}` → {verdict} / {hit}")
        assert unresolved == [], (
            "本批文档里的仓库路径引用**真断链**（零命中或多候选，读者按「收工判据」"
            "去找必然扑空）——改指真实路径，或改用显式文本交代去处:\n  "
            + "\n  ".join(unresolved)
        )

    def test_coverageIncludesEveryTicketBody(self):
        """判据覆盖面必须含每一份票面正文（缩成只剩索引会被这条抓住）。"""
        covered = _batchDocuments()
        missing = [path.name for path in sorted(TICKETS.glob("*.md"))
                   if not any(entry.endswith(path.name) for entry in covered)]
        assert missing == [], f"票面正文未进引用判据覆盖面：{missing}"

    def test_criterionActuallyFlagsADeadPath(self):
        """反向控制：判据必须真的把不可达路径判出来（合成输入，不看仓库现状）。"""
        scanner = self._scanner()
        byBasename = scanner.indexByBasename(scanner.trackedFiles())
        verdict, _ = scanner.resolveTarget(
            "docs/adr/0018-does-not-exist.md", PROJECT_ROOT / BATCH_DOCUMENTS[0], byBasename
        )
        assert verdict == scanner.VERDICT_DELETED, (
            "判据认不出死路径，本守卫会空转（判定口径变了要跟着改）"
        )
        moved, _ = scanner.resolveTarget(
            "agent/chat_pipeline.py", PROJECT_ROOT / BATCH_DOCUMENTS[0], byBasename
        )
        assert moved == scanner.VERDICT_MOVED, (
            "唯一可解的旧路径被判成「真断链」——会把改指前的正常引用当故障，"
            "假阳性会训练人忽略这道门禁"
        )

class TestBatchDocSectionRefsResolve:
    """判据三：本批文档里的**章节号引用**必须指向真实存在的章节。

    规格文档被本批各处按 `§8.10` 这类编号引用（票集索引写"明细见规格文档 §8.10"）。
    章节号不是文件路径，悬空扫描器看不见它——于是「重写文档时删了一节、
    引用还留着」不会有任何机器判据发现。同批删除漏改的同一根因，
    只是消费方换成了章节编号。判据只覆盖本批的两份事实源，不扫全仓：
    别处的 `§N` 大量指**他文档**的章节（如"spec §4"），全仓判会制造假阳性。
    """

    SPEC = PROJECT_ROOT / "docs/specs/2026-09-21-tool-experience-loop-repair.md"
    INDEX = TICKETS / "000-索引.md"

    @staticmethod
    def _headings(text: str) -> set:
        return {m.group(1) for m in re.finditer(r"^#{2,6}\s+(\d+(?:\.\d+)*)", text, re.M)}

    @staticmethod
    def _sectionRefs(text: str) -> list:
        return [(n, m.group(1))
                for n, line in enumerate(text.splitlines(), 1)
                for m in re.finditer(r"§(\d+(?:\.\d+)*)", line)]

    def test_selfRefsInSpecResolve(self):
        text = io.open(self.SPEC, encoding="utf-8").read()
        headings = self._headings(text)
        dangling = [f"{self.SPEC.name}:{n} §{num}"
                    for n, num in self._sectionRefs(text) if num not in headings]
        assert dangling == [], (
            "规格文档引用了自己并不存在的章节号——读者按编号找不到那一节:\n  "
            + "\n  ".join(dangling)
        )

    def test_crossDocRefsIntoTheSpecResolve(self):
        specHeadings = self._headings(io.open(self.SPEC, encoding="utf-8").read())
        text = io.open(self.INDEX, encoding="utf-8").read()
        dangling = [f"{self.INDEX.name}:{n} §{num}"
                    for n, num in self._sectionRefs(text) if num not in specHeadings]
        assert dangling == [], (
            "票集索引按编号指向规格文档的某一节，那一节不存在:\n  " + "\n  ".join(dangling)
        )

    def test_sectionCriterionIsNotVacuous(self):
        """反向控制：判据必须真的认得悬空章节号（合成输入，不看仓库现状）。"""
        headings = self._headings("## 8 章\n### 8.1 节\n")
        assert self._sectionRefs("见 §8.1") == [(1, "8.1")]
        assert "8.2" not in headings
        assert "8.1" in headings


class TestBatchDocRepoRefsResolvePlaceholder:
    def test_extractionIgnoresProductionAndGlobForms(self):
        text = "见 `data/agents/default/skills/manifest.json`、`tests/unit/tool_tools_*.py`"
        assert _repoRefs(text) == [], "生产库路径与通配形态不该进判据（会制造假阳性）"


# ---------------------------------------------------------------------------
# 判据四：**批次级判据**（全局约束 / 硬次序 / 整批完成判据 / 断点编号出处）
# ---------------------------------------------------------------------------
# 第四轮把 001–011 的**票面正文**入了库，判据在「每张票」这一层可读了。
# 但这一批还有**更高一层的判据**：每张票都必须遵守的全局约束（11 条）、
# 不可调换的硬次序（002 早于 003、007 早于 008）、以及整批的完成判据
# （三条探针全绿 + 经验质量门禁两格读数不变差）。它们此前同样只存在于
# Issue #80 的附件里，仓内索引只有一节「全局约束**遵守情况**」——那是
# 实现方的自陈报告，不是约束本体；读者拿不到「约束到底写了哪 11 条」，
# 也就无从复核每张票是不是在同一个契约下完成的。
#
# 同型断点的第二处：票面正文里大量出现 `审计 L-02` / `L-04 / L-05 / L-10`
# 这类**断点编号**，其出处（工具↔经验环路的深度审计）从未入库。读者在仓内
# 查不到「L-06b 到底指什么」。出处无法凭空复原，但**编号到票的索引**可以
# 从票面自陈回填，并显式交代出处形态——「查不到」与「没人写」必须分得开。

BATCH_SECTION_HEADINGS = ("全局约束", "硬次序", "完成判据")
DEFECT_NUMBER = re.compile(r"\bL-\d{2}[a-z]?\b")
CONSTRAINT_ITEM = re.compile(r"^\s*(\d{1,2})\.\s+\*\*", re.M)


def _batchContractText() -> str:
    """批次级判据的事实源 = 票集索引本体（不另立一份）。"""
    return io.open(INDEX, encoding="utf-8").read()


def _ticketDefectNumbers() -> dict:
    """每份票面正文里出现的断点编号 → 出现的票（票面自陈，唯一可核的出处）。"""
    found: dict = {}
    for path in sorted(TICKETS.glob("[0-9][0-9][0-9]-*.md")):
        if path.name.startswith("000-"):
            continue
        text = io.open(path, encoding="utf-8").read()
        for number in DEFECT_NUMBER.findall(text):
            found.setdefault(number, set()).add(path.name.split("-")[0])
    return found


def _indexedDefectNumbers(text: str) -> dict:
    """索引里的编号索引表：编号 → 承载它的票号。"""
    indexed: dict = {}
    for line in text.splitlines():
        row = DEFECT_ROW.match(line.strip())
        if row:
            indexed.setdefault(row.group(1), set()).update(
                re.findall(r"\b\d{3}\b", row.group(2))
            )
    return indexed


def _unindexedDefectNumbers(tickets: dict, indexed: dict) -> list:
    """票面里出现、索引却没有登记出处的编号（纯函数，供反向控制复算）。"""
    return sorted(
        number for number, carriers in tickets.items()
        if not carriers.issubset(indexed.get(number, set()))
    )


class TestBatchLevelContractIsReadableInRepo:
    """批次级判据必须在仓内可读——否则每张票的「完成」是在两套口径下裁的。"""

    def test_batchConstraintsBlockExists(self):
        text = _batchContractText()
        assert "## 批次级判据" in text, (
            "票集索引里没有「批次级判据」这一节：全局约束/硬次序/整批完成判据"
            "只存在于 Issue 附件，复核者在仓内无从判断各票是否在同一契约下完成"
        )

    def test_everyBatchHeadingIsPresent(self):
        text = _batchContractText()
        missing = [name for name in BATCH_SECTION_HEADINGS if f"### {name}" not in text]
        assert missing == [], f"批次级判据缺节：{missing}"

    def test_globalConstraintsAreEnumerated(self):
        items = CONSTRAINT_ITEM.findall(_batchContractText())
        assert len(items) >= 10, (
            f"全局约束只解析出 {len(items)} 条——约束本体没入库或格式退化，"
            "「每张票都必须遵守」这件事就成了一句无从复核的话"
        )

    def test_completionCriteriaNameTheirEvidenceSources(self):
        text = _batchContractText()
        for token in (
            "tests/unit/agent/test_tool_loop_funnel_probes.py",
            "scripts/ci/experience_quality_gate.py",
        ):
            assert token in text, (
                f"整批完成判据没有点名它的取证入口 `{token}`，"
                "读者无法从判据走到可重跑的读数"
            )

    def test_constraintCriterionIsNotVacuous(self):
        """反向控制：条目检出器必须真的认得条目形态（合成输入，不看仓库现状）。"""
        sample = "1. **TDD 红绿灯**：先写必红用例。\n2. **单一事实源**：收口到一份。\n"
        assert len(CONSTRAINT_ITEM.findall(sample)) == 2
        assert CONSTRAINT_ITEM.findall("普通编号列表 1. 没有粗体标题\n") == []


class TestDefectNumberingHasProvenance:
    """票面里的 `L-xx` 断点编号必须有仓内出处索引（编号 → 票 → 出处形态）。"""

    def test_everyTicketDefectNumberIsIndexed(self):
        unindexed = _unindexedDefectNumbers(_ticketDefectNumbers(), _indexedDefectNumbers(_batchContractText()))
        assert unindexed == [], (
            "票面正文引用了索引里没有登记出处的断点编号——读者在仓内查不到它指什么:\n  "
            + "\n  ".join(unindexed)
        )

    def test_provenanceFormIsStated(self):
        text = _batchContractText()
        assert "### 断点编号 L-xx 的出处" in text, (
            "没有交代 L-xx 编号的出处形态：编号来源（深度审计）从未入库这件事"
            "必须显式写出来，否则读者会把「查不到」当成「自己找错了地方」"
        )
        assert "从未入库" in text, "出处节必须点名来源文档**从未入库**，不得含糊"

    def test_defectIndexCriterionIsNotVacuous(self):
        """反向控制：判据必须真的抓得住「票面有、索引无」的编号（合成输入）。"""
        tickets = {"L-02": {"003"}, "L-99": {"004"}}
        indexed = {"L-02": {"003"}}
        assert _unindexedDefectNumbers(tickets, indexed) == ["L-99"]
        assert _unindexedDefectNumbers(indexed, indexed) == []


# ---------------------------------------------------------------------------
# 第六组：两项「需人配合」事项的**用户裁定**必须在仓内可读
# ---------------------------------------------------------------------------
# 第五轮末，本批还剩四项「无法由实现方单方面闭环」的事项，全部登记在案。其中两项
# （008 的浏览器级 live、011 的设计契约三件套）需要用户裁决：做，还是按现状收。
# 用户在 Issue #80 给出裁定 —— **按现状承接**。
#
# 裁定落在评论里，而评论不进版本库：下一个复核者读票面，仍会看到「未闭环」四个字，
# 于是「已经裁定过、不必再做」与「没人做、待办挂着」在仓内**分不开**。这与前几轮
# 反复收口的是同一形态——写入（裁定做了）→ 读取（读者拿不到）的环断在读者这一环。
#
# 故本组判据只锁一件事：裁定本体必须在票集索引可读，且被裁定覆盖的票面必须指向它。

RULING_HEADING = "## 用户裁定（按现状承接）"
#: 裁定覆盖的两项（票号 + 事项关键词），与票面自陈一致。
RULING_ITEMS = (("008", "浏览器级 live"), ("011", "三件套"))
SPEC = PROJECT_ROOT / "docs" / "specs" / "2026-09-21-tool-experience-loop-repair.md"


def _rulingSection(text: str) -> str:
    """取裁定节正文（到下一个二级标题为止）；节不存在即返回空串。"""
    if RULING_HEADING not in text:
        return ""
    body = text.split(RULING_HEADING, 1)[1]
    cut = body.find("\n## ", 1)
    return body if cut < 0 else body[:cut]


def _rulingGaps(section: str) -> list:
    """裁定节的缺陷清单（纯函数，供反向控制复算）。"""
    gaps = []
    if not section.strip():
        return ["裁定节缺失"]
    if "按现状承接" not in section:
        gaps.append("没有写明裁定结论「按现状承接」")
    for number, topic in RULING_ITEMS:
        if number not in section or topic not in section:
            gaps.append(f"未点名被裁定项：{number} {topic}")
    return gaps


class TestUserRulingIsReadableInRepo:
    """两项需人配合事项的用户裁定必须随票集入库，否则「已裁定」与「没人做」不可分。"""

    def test_rulingSectionExists(self):
        text = _batchContractText()
        assert RULING_HEADING in text, (
            "票集索引里没有「用户裁定（按现状承接）」这一节：裁定只存在于 Issue 评论，"
            "复核者读票面仍会看到「未闭环」，无法与「待办挂着」区分"
        )

    def test_rulingNamesTheCoveredItems(self):
        gaps = _rulingGaps(_rulingSection(_batchContractText()))
        assert gaps == [], (
            "裁定节没有把被裁定项说全（结论 + 覆盖哪两张票的哪一项）:\n  "
            + "\n  ".join(gaps)
        )

    def test_rulingSaysTheseAreNoLongerOpenItems(self):
        section = _rulingSection(_batchContractText())
        assert "不再列为未闭环" in section or "退出未闭环" in section, (
            "裁定节没有交代这两项**退出未闭环清单**——「按现状承接」若只写成一句"
            "「已确认」，下一位复核者仍会把它们当成待办重开一遍"
        )
        assert "§10" in section, (
            "裁定节没有指向规格文档里记录本轮处置的那一节，读者无从看到红→绿与落点"
        )

    def test_coveredTicketsPointAtTheRuling(self):
        """写入→读取闭环：落在票面（读者第一站）的登记必须指向裁定。"""
        missing = []
        for number, _ in RULING_ITEMS:
            body = next(TICKETS.glob(f"{number}-*.md"), None)
            assert body is not None, f"{number} 票面缺失"
            if "按现状承接" not in io.open(body, encoding="utf-8").read():
                missing.append(body.name)
        assert missing == [], (
            "被裁定覆盖的票面没有指向该裁定——读者在票面上看到的还是「未闭环」，"
            "环断在读者这一环:\n  " + "\n  ".join(missing)
        )

    def test_rulingCriterionIsNotVacuous(self):
        """反向控制：判据必须真的抓得住缺失与说不全（合成输入，不看仓库现状）。"""
        assert _rulingGaps("") == ["裁定节缺失"]
        assert "按现状承接" in _rulingGaps("结论：取消该项。")[0]
        assert _rulingGaps(
            "结论：按现状承接。008 浏览器级 live 与 011 三件套，不再列为未闭环。"
        ) == []
