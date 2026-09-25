# -*- coding: utf-8 -*-
"""导航/纪律索引不得手抄「仓库条目数」（第二份定义）。

## 根因（与 `.cnb.yml` 头部手抄条数同一形态）

`docs/0-index/README.md` 是 `docs/` 的唯一入口，`AGENTS.md` 是纪律的唯一事实源。
两者都在正文里**逐字写下全仓内容的条数**：

    — 21 个架构决策记录（memory/recall/skill/market/sandbox 等）
    — 47 个修复记录（Agent/LLM/Memory/Skill/UI 等各领域，按文件名）
    — 模块设计（19 篇，含 chat_page/execution_engine/knowledge_base 等）
    — 代码评审（3 篇）
    — 历史/过时文档 30 篇（…）
    被全仓 90+ 处编号引用 / 全仓 97 处引用的唯一事实源

这些数字与仓库实况之间**没有任何机器判据**，于是它们各自漂移、且互相矛盾。
实测（2026-09-25，`main`）：

    ADR 00*.md           自述 21   实际 21     一致
    bugfix-*.md          自述 47   实际 37     漂移 10
    module_designs       自述 19   实际 21     漂移 2
    code_reviews         自述 3    实际 4      漂移 1
    11-legacy *.md       自述 30   实际 30     一致
    「修复教义第 N 条」   AGENTS.md 自述 90+ / 0-index 自述 97 / 实际 60

`90+` 与 `97` 是**同一事实的两份手抄**，同一时刻给出两个数——正是教义第 6 条
点名的那类断点。读者按这些数字去索引里找条目，找不全也看不出少了什么，
而平台不会为此报任何错。

## 修法（沿用 `tests/unit/ci/test_cnb_pipeline_header_count` 的口径）

条数的单一事实源**是目录本身**（`ls docs/06-bugfix/bugfix-*.md | wc -l` 一类），
索引只描述结构与口径，不再写具体数字。这不是「把错的数改成对的数」——
改对了的数字下一次增删文档又会漂移，且依然无人复核。

## 本守卫钉三件事

- **A 索引不手抄条目数**：`docs/0-index/README.md` 与 `AGENTS.md` 不得出现
  「N 个 <条目标签>」「目录条目（N 篇）」「历史/过时文档 N 篇」「被 N 处引用」；
- **B 判据不空转**：索引必须仍然**点名**这些目录（删了数字不等于删了条目），
  否则「不写数字」会退化成「读者无处可查」；
- **C 反向锁**：往副本里注入一个手抄数字 → 必须判红。缺了这条，A 只是
  「当前这份文件恰好没写数字」的快照。

范围（教义第 5 条：命中点逐条点名，不静默留白）：本守卫只裁**导航/纪律事实源**
两处。根 `README.md` 的「846 个测试文件」「42 个 Vitest 文件」等与 `docs/INDEX.md`
的历史盘点数字属同一根因的其它命中点，登记在残留台账，不在本单扩范围。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: 导航/纪律事实源——本条契约的两个落点。
INDEX_DOC = PROJECT_ROOT / "docs" / "0-index" / "README.md"
DISCIPLINE_DOC = PROJECT_ROOT / "AGENTS.md"

#: 手抄「仓库条目数」的四种句式（历史原文形态，属同一根因）。
COUNT_OF_ENTRIES = re.compile(r"\d+\s*个\s*(?:架构决策记录|修复记录|测试记录|模块设计)")
COUNT_OF_DOCS_IN_DIR = re.compile(r"（\s*\d+\s*篇")
COUNT_OF_LEGACY_DOCS = re.compile(r"历史/过时文档\s*\d+\s*篇")
COUNT_OF_CITATIONS = re.compile(r"(?:全仓|被)\s*\d+\+?\s*处(?:编号)?引用")

HAND_COPIED_PATTERNS = (
    COUNT_OF_ENTRIES,
    COUNT_OF_DOCS_IN_DIR,
    COUNT_OF_LEGACY_DOCS,
    COUNT_OF_CITATIONS,
)

#: B 判据：索引必须仍然点名的目录（条目本身不得被顺手删掉）。
REQUIRED_ENTRIES = (
    "adr/README.md",
    "../06-bugfix/",
    "module_designs/",
    "code_reviews/",
)


def handCopiedCounts(text: str) -> list[str]:
    """文本里**写死条目数**的片段（空列表＝已收口到单一事实源）。"""
    found: list[str] = []
    for line in text.splitlines():
        for pattern in HAND_COPIED_PATTERNS:
            found.extend(m.group(0).strip() for m in pattern.finditer(line))
    return found


class TestIndexDoesNotHandCopyCounts:
    """条数的单一事实源是目录本身，索引不得保留第二份手抄。"""

    def test_index_has_no_hand_copied_count(self):
        """`docs/0-index/README.md` 不得手抄条目数（本条是主判据）。"""
        text = io.open(INDEX_DOC, encoding="utf-8").read()
        offenders = handCopiedCounts(text)
        assert not offenders, (
            f"文档总索引仍在手抄条目数: {offenders}\n"
            "这些数字与目录实况之间没有任何机器判据，已实测漂移三处"
            "（修复记录 47→37、模块设计 19→21、代码评审 3→4）。\n"
            "修法：删掉数字，只描述结构与口径——现读数用目录本身给出，"
            "例如 `ls docs/06-bugfix/bugfix-*.md | wc -l`。"
        )

    def test_discipline_doc_has_no_hand_copied_count(self):
        """`AGENTS.md` 不得手抄引用处数（`90+` 与索引里的 `97` 同源却互相矛盾）。"""
        text = io.open(DISCIPLINE_DOC, encoding="utf-8").read()
        offenders = handCopiedCounts(text)
        assert not offenders, (
            f"纪律事实源仍在手抄引用处数: {offenders}\n"
            "它与 `docs/0-index/README.md` 的 `97 处` 是同一事实的两份手抄，"
            "同一时刻给出两个数（实测实际引用 60 处）。\n"
            "修法：删掉数字，保留可执行的那半句（改条款编号前先 grep 引用方），"
            "需要读数时现场复算。"
        )

    def test_index_still_names_the_directories(self):
        """B 判据：删数字不得连带删条目，否则读者无处可查。"""
        text = io.open(INDEX_DOC, encoding="utf-8").read()
        missing = [entry for entry in REQUIRED_ENTRIES if entry not in text]
        assert not missing, (
            f"文档总索引不再点名这些目录: {missing}\n"
            "修「手抄数字」时把条目本身也删掉，等于把洞换了个位置"
            "（读者从「数字不准」变成「找不到入口」）。"
        )

    def test_discriminating_power(self, tmp_path, monkeypatch):
        """C 反向锁：把手抄数字注入回去 → 必须判红。

        没有这一条，上面两条只是「当前这份文件恰好没写数字」的快照——
        本守卫的全部价值是拦住「下次增删文档时顺手再抄一个数」的回头路。
        """
        module = __import__(__name__, fromlist=["handCopiedCounts"])
        assert module.handCopiedCounts("— 21 个架构决策记录（x）") == ["21 个架构决策记录"]
        assert module.handCopiedCounts("— 模块设计（19 篇，含 x）") == ["（19 篇"]
        assert module.handCopiedCounts("历史/过时文档 30 篇（x）") == ["历史/过时文档 30 篇"]
        assert module.handCopiedCounts("被全仓 97 处引用的唯一事实源") == ["全仓 97 处引用"]

        drifted = tmp_path / "README.md"
        original = io.open(INDEX_DOC, encoding="utf-8").read()
        drifted.write_text(
            original.replace("— 模块设计（", "— 模块设计（21 篇，含 ", 1),
            encoding="utf-8",
        )
        monkeypatch.setattr(module, "INDEX_DOC", drifted)
        assert module.handCopiedCounts(io.open(drifted, encoding="utf-8").read())
        import pytest
        with pytest.raises(AssertionError, match="手抄条目数"):
            module.TestIndexDoesNotHandCopyCounts().test_index_has_no_hand_copied_count()
