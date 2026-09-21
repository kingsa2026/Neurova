# -*- coding: utf-8 -*-
"""退役平铺目录的引用可达性守卫（Issue #96 收尾）。

背景（根因，不是形状）：本批把「非编号层同 basename 副本」删净、把 135 处引用
改指编号分层，但**改写面没有覆盖到全部消费方**——于是同一批删除在几处留下了
新的死链：

- `docs/01-architecture/08-project-structure.md` 的 `[ADR 0018](../adr/0018-…md)`
  在删除前解析到 `docs/adr/0018-…md`（当时存在），删除后成为硬 404；
- `docs/specs/2026-09-19-rsi-closed-loop/tickets/014-….md` 的
  `[ADR 0017](../../../adr/0017-…md)` 同理；
- `docs/INDEX.md` 自称「唯一权威入口」，第 1 节权威文档表却仍把
  `docs/memory/`、`docs/dev_progress/`、`docs/configuration/`、`docs/i18n/`
  列为领域事实源——这些目录本轮已被清空，照表找不到任何东西。

这正是修复教义第 2 条禁止的「表面消失」的反向形态：**删了副本、没有同步引用**，
报错从「两个候选」变成「零个候选」，看上去干净了，实际是把洞换了个位置。

本守卫只锁三件事，全部机器可验，且判据取自唯一事实源（`scripts/scan_docs_refs.py`
的 `trackedFiles`，不另建第二套文件清单）：

1. **活跃层不得有指向已退役平铺目录的 Markdown 链接**。退役目录由「被正文提到、
   但全仓零跟踪文件」自证，不写死名单——名单写死就会与仓库实况脱钩。
2. **`docs/INDEX.md` 第 1 节权威文档表必须全部可达**。它是文档体系的唯一导航入口，
   表里点名的目录/文件全部要在仓库里真实存在（目录按前缀判定）。
3. **反向控制**：退役检出器不得空转（必须真的检出一个已退役目录），且真实存在的
   编号分层目录不得被误判为退役。缺了这条，规则 1 会在检出器失效时空过。
"""
import io
import posixpath
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

scanner = pytest.importorskip("scripts.scan_docs_refs")

INDEX = PROJECT_ROOT / "docs" / "INDEX.md"
ARCHIVE_PREFIXES = ("docs/11-legacy/", "docs/06-bugfix/")

#: `docs/<段>/` 形态的路径引用（正文描述用反引号、链接用圆括号两种都算"提到"）
TREE_MENTION = re.compile(r"docs/([A-Za-z0-9][A-Za-z0-9_-]*)/")
LINK = re.compile(r"!?\[([^\]]*)\]\(([^)\s]+?)(?:\s+\"[^\"]*\")?\)")
CODE_SPAN = re.compile(r"`([^`\n]+)`")


def trackedFiles() -> list:
    """仓库已跟踪文件（复用扫描器，避免第二份文件清单）。"""
    return scanner.trackedFiles()


def retiredTrees(files: list) -> set:
    """被正文提到、但全仓零跟踪文件的 `docs/<段>/`：本批退役的平铺目录。"""
    mentioned = set()
    for path in files:
        if not path.endswith((".md", ".py", ".ts", ".json", ".yml", ".vue")):
            continue
        try:
            text = io.open(PROJECT_ROOT / path, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        mentioned.update(TREE_MENTION.findall(text))
    return {name for name in mentioned
            if not any(f.startswith(f"docs/{name}/") for f in files)}


def activeDocs(files: list) -> list:
    """活跃层文档（排除归档层，归档正文陈述的是当时结构，不就地改写）。"""
    return [f for f in files
            if f.endswith(".md") and not f.startswith(ARCHIVE_PREFIXES)]


#: 说明性文本而非路径（`文件:行号`、`bugfix-*.md`、`HARMONYOS_*.md`）
NOT_A_PATH = re.compile(r"[*<>{}]|^[^/]*:[^/]*$")


def resolves(target: str, source: str, files: list) -> bool:
    """判定权威表里的一个目标是否可达。

    三层口径，逐层放宽——收紧任一层都会误报（假阳性比漏报更坏，它会训练人
    忽略这道门禁）：

    1. 字面：按源文件所在目录与仓库根两处解析（目录按前缀判定）；
    2. 唯一同名：裸文件名在搬迁后只剩一份时算可达（`API_REFERENCE.md` →
       `docs/02-api/API_REFERENCE.md` 这类），多份并存则不算（那是第二个事实源）；
    3. 非路径文本（通配、`文件:行号`）不参与判定。
    """
    literal = target.split("#")[0].strip()
    if not literal or literal.startswith(("http://", "https://", "mailto:", "file:")):
        return True  # 非仓库内引用
    if NOT_A_PATH.search(literal):
        return True  # 说明性文本，不是路径
    if literal.startswith("/"):
        literal = literal.lstrip("/")
    for base in (posixpath.dirname(source), ""):
        rel = posixpath.normpath(posixpath.join(base, literal))
        if rel in files:
            return True
        if any(f.startswith(rel.rstrip("/") + "/") for f in files):
            return True
    basename = literal.split("/")[-1]
    if "/" not in literal:
        matches = [f for f in files if f.endswith("/" + basename)]
        return len(matches) == 1
    return False


@pytest.fixture(scope="module")
def files() -> list:
    return trackedFiles()


class TestRetiredTreeLinksAreRebased:
    """规则 1：活跃层的 Markdown 链接不得指向已退役平铺目录。"""

    def testNoActiveLinkPointsIntoRetiredTree(self, files):
        retired = retiredTrees(files)
        offenders = []
        for path in activeDocs(files):
            text = io.open(PROJECT_ROOT / path, encoding="utf-8", errors="ignore").read()
            for number, line in enumerate(text.splitlines(), 1):
                for match in LINK.finditer(line):
                    target = match.group(2).split("#")[0].strip()
                    for base in (posixpath.dirname(path), ""):
                        rel = posixpath.normpath(posixpath.join(base, target))
                        tree = rel.split("/")[1] if rel.startswith("docs/") and "/" in rel else None
                        if tree in retired:
                            offenders.append(f"{path}:{number} `{match.group(2)}` → {rel}")
                            break
        assert not offenders, (
            "活跃层仍有链接指向已退役目录（删了副本没同步引用 = 把洞换了位置）:\n  "
            + "\n  ".join(offenders)
            + "\n修法：改指编号分层里的那一份，不要删链接了事。"
        )


class TestIndexAuthorityTableResolves:
    """规则 2：`docs/INDEX.md` 第 1 节权威文档表必须全部可达。"""

    @staticmethod
    def _authorityBlock() -> str:
        assert INDEX.is_file(), "docs/INDEX.md 缺失——它是文档体系的唯一权威入口"
        text = io.open(INDEX, encoding="utf-8").read()
        start = text.find("## 1.")
        stop = text.find("## 2.", start)
        assert start != -1 and stop != -1, "INDEX.md 第 1/2 节结构变化，守卫定位失败"
        return text[start:stop]

    def testSectionOneIsFoundAndTabular(self):
        assert "| 领域 | 权威文档 |" in self._authorityBlock(), (
            "第 1 节权威文档表结构变化——表在，守卫才锁得住"
        )

    def testEveryAuthorityTargetResolves(self, files):
        broken = []
        for number, line in enumerate(self._authorityBlock().splitlines(), 1):
            if not line.startswith("|"):
                continue
            targets = [m.group(2) for m in LINK.finditer(line)]
            targets += [m.group(1).strip() for m in CODE_SPAN.finditer(line)]
            for target in targets:
                if target.startswith(("http", "#")):
                    continue
                if not resolves(target, "docs/INDEX.md", files):
                    broken.append(f"L{number} `{target}`")
        assert not broken, (
            "INDEX.md 第 1 节点名的权威目录/文件不可达（导航入口指向空气）:\n  "
            + "\n  ".join(broken)
        )


class TestRetiredDetectionDoesNotGoVacuous:
    """规则 3：反向控制——检出器要真检出，且不得误判在用的编号分层。"""

    def testDetectorActuallyFindsRetiredTrees(self, files):
        found = retiredTrees(files)
        assert found, (
            "未检出任何已退役 docs 子目录。若正文里的历史路径已被全部清理，\n"
            "本守卫的规则 1 会空转——需确认 retire 检出口径，而不是让它静默通过。"
        )

    def testLiveNumberedLayersAreNotFlaggedAsRetired(self, files):
        found = retiredTrees(files)
        for live in ("01-architecture", "02-api", "03-user-guide", "06-bugfix",
                     "09-dev-progress", "11-legacy", "architecture-model", "specs"):
            assert live not in found, (
                f"在用目录 docs/{live}/ 被误判为退役——检出器口径反了，规则 1 会误报"
            )

    def testNumberedLayersAreStillPopulated(self, files):
        docs = [f for f in files if f.startswith("docs/")]
        assert len(docs) > 200, (
            f"docs/ 仅 {len(docs)} 个跟踪文件，判据疑似失效（仓库被截断时守卫会空过）"
        )
