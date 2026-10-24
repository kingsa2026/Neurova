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
import concurrent.futures
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


def activeDocs(files: list, extraExcludes: tuple = ()) -> list:
    """活跃层文档（排除归档层，归档正文陈述的是当时结构，不就地改写）。

    `extraExcludes` 让规则 1b/1c 再排掉一次性审计快照（见 `SNAPSHOT_PREFIXES`）。
    """
    return [f for f in files
            if f.endswith(".md") and not f.startswith(ARCHIVE_PREFIXES + extraExcludes)]


#: 说明性文本而非路径（`文件:行号`、`bugfix-*.md`、`HARMONYOS_*.md`）
NOT_A_PATH = re.compile(r"[*<>{}]|^[^/]*:[^/]*$")

#: 规则 1b/1c 的**扫描面排除**：一次性审计快照。
#:
#: `audit-reports/` 是审计产物，正文里的 `docs/<旧目录>/<文件>` 是**当时的读数证据**
#: （那一屏写着 `git log -S` 与命令输出）。就地改指，等于替证据换掉它当时指向的东西——
#: 判据在这里要求"改指"，恰好把证据改成了不会失败的样子。与 `ARCHIVE_PREFIXES`
#: （`docs/11-legacy/`、`docs/06-bugfix/`）同一口径：陈述当时结构的正文不就地改写。
#: 规则 1（可点击链接）不适用本排除——链接点不动就是死链，与快照无关。
SNAPSHOT_PREFIXES = ("audit-reports/",)


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


#: 规则 1b 的读盘分片数。这一条要读**每一份活跃层文档**（上千档）：`--cov` 插桩下
#: 单线程实测把整档推到 10s 量级，而它只是读盘 + 正则。分片只为把读盘并行起来，
#: 判据一行不改；取小值——同场还有别的档在跑，不为这一条占满 runner。
SCAN_SHARDS = 8


def _rebasableOffendersInText(path: str, text: str, files: list, retired: set) -> list:
    """逐文件判定（分片扫描与反空转格共用同一份口径）。"""
    fileSet = set(files)
    out = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in SPECIFIC_REF.finditer(line):
            target, tree = match.group(1), match.group(2)
            if tree not in retired or "<" in target or "*" in target:
                continue
            if target in fileSet:
                continue
            suffix = "/" + target.split("/", 2)[-1]
            matches = [f for f in files if f.endswith(suffix)]
            if len(matches) == 1:
                out.append(f"{path}:{number} `{target}` → {matches[0]}")
    return out


def rebasableOffenders(files: list, excludes: tuple = ()) -> list:
    """规则 1b 的判定全体：分成 `SCAN_SHARDS` 片读盘，各片只 append 自己的命中。"""
    retired = retiredTrees(files)
    scanFiles = [f for f in files
                 if (f.endswith(".md") or f.endswith((".json", ".dot", ".dsl")))
                 and not f.startswith(ARCHIVE_PREFIXES + excludes)]
    buckets: list = [[] for _ in range(SCAN_SHARDS)]

    def scanSlice(index: int) -> None:
        for path in scanFiles[index::SCAN_SHARDS]:
            try:
                text = io.open(PROJECT_ROOT / path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            buckets[index].extend(_rebasableOffendersInText(path, text, files, retired))

    with concurrent.futures.ThreadPoolExecutor(max_workers=SCAN_SHARDS) as pool:
        list(pool.map(scanSlice, range(SCAN_SHARDS)))
    return [item for bucket in buckets for item in bucket]


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


#: 点名到具体文件（带扩展名、无 `<>`/`*` 占位）的退役目录引用
SPECIFIC_REF = re.compile(r"(docs/([A-Za-z0-9][\w\-]*)/[^\s`|()]*\.[A-Za-z0-9]{1,6})")

#: 源码里的**路径拼接**形态：`"docs" / "<退役目录>" / "<文件名>"`。
#: 它不会出现在任何 Markdown 正文里，只在代码里被拼成真实路径——口径漏了它，
#: 改指就只能靠人工记得，删副本留下的洞照样会从门禁下溜过去。
JOIN_REF = re.compile(r"""["']docs["']\s*/\s*["']([A-Za-z0-9_-]+)["']\s*/\s*["']([^"']+)["']""")


class TestNamedRetiredFilesAreRebased:
    """规则 1b：点名到**具体文件**的退役目录引用，若目标在编号分层唯一可解，必须改指。

    与规则 1 的区别：规则 1 管 Markdown 链接（可点击），本条管正文里的行内路径
    （`docs/dev_progress/x.md` 这类）。它们不会渲染成链接，但同样把人指向已删目录，
    且同样只需一次改名即可到位——属于同批删除漏改的同一根因。

    只锁「编号分层有唯一同名」的那部分：目标确实还在，改指是确定动作。
    占位符（`YYYY-MM-DD-<dev-name>.md`）是流程模板、不是引用，不参与判定；
    已彻底不存在且无唯一命中的历史文件名保持登记状态，不在此处扩范围。
    """

    def testSpecificTargetsWithUniqueRebaseAreFixed(self, files):
        offenders = rebasableOffenders(files, SNAPSHOT_PREFIXES)
        assert not offenders, (
            "点名的退役目录文件在编号分层唯一可解，却没改指（同批删除漏改的同一根因）:\n  "
            + "\n  ".join(offenders)
        )

    def testTheDetectorStillSeesAPlantableRebase(self, files):
        """反空转：分片扫描后，探测器必须仍能从**合成的一份**里点名出可改指项。

        上一格断言"没有 offending"——把扫描面整个关掉也能绿。这一格把一份必然命中的
        合成材料喂给同一个判定函数，钉住"判定真在跑"。退役目录与"目录下唯一同名文档"
        都取自仓内事实，不另造第二套路径源。
        """
        retired = sorted(retiredTrees(files))
        assert retired, "退役目录检不出来——反空转格失去根据"
        tree = next(t for t in retired if any(f.endswith(".md") for f in files))
        # 规则 1b 的改指前提是 `endswith("/" + 文件名)` 命中一份：仓根的 `AGENTS.md`
        # 不带目录段，拿它构造会把"认不认 `docs/<tree>/<leaf>`"和"有没有目录前缀"混成一件事。
        byName: dict = {}
        for path in files:
            if path.endswith(".md") and "/" in path:
                byName.setdefault(path.rsplit("/", 1)[-1], []).append(path)
        leafName = next((name for name, paths in byName.items() if len(paths) == 1), None)
        assert leafName, "仓库里没有目录下唯一同名的 md——反空转格失去构造前提"
        hits = _rebasableOffendersInText(
            "probe.md", f"见 `docs/{tree}/{leafName}`\n", files, retired)
        assert hits, f"合成材料里的 `docs/{tree}/{leafName}` 没被点名——探测器失效"


class TestSourcePathJoinRefsAreRebased:
    """规则 1c：源码里拼出来的退役目录路径，唯一可解时必须改指。

    前两条规则只看得见 Markdown（链接 + 正文行内路径）。`docs/adr/` 整目录删除后，
    本批新增用例里的 `REPO_ROOT / "docs" / "adr" / "0016-….md"` 正是拼接形态：
    正文里没有它的影子，规则 1/1b 都放行，于是 CI 上 py3.11/py3.12 双跑同时红在
    `FileNotFoundError`。同一根因（改指面没有覆盖全部消费方），只是消费方换成了代码。
    """

    SOURCE_SUFFIXES = (".py", ".ts", ".js", ".vue", ".json")

    def testJoinRefsWithUniqueRebaseAreFixed(self, files):
        retired = retiredTrees(files)
        fileSet = set(files)
        offenders = []
        for path in files:
            if (not path.endswith(self.SOURCE_SUFFIXES) or path.startswith(ARCHIVE_PREFIXES)
                    or path.startswith(SNAPSHOT_PREFIXES)):
                continue
            text = io.open(PROJECT_ROOT / path, encoding="utf-8", errors="ignore").read()
            for number, line in enumerate(text.splitlines(), 1):
                for match in JOIN_REF.finditer(line):
                    tree, leaf = match.group(1), match.group(2)
                    if tree not in retired or "<" in leaf or "*" in leaf:
                        continue
                    if "." not in leaf:
                        continue
                    target = f"docs/{tree}/{leaf}"
                    if target in fileSet:
                        continue
                    matches = [f for f in files if f.endswith("/" + leaf)]
                    if len(matches) == 1:
                        offenders.append(f"{path}:{number} `{target}` → {matches[0]}")
        assert not offenders, (
            "源码里拼出的退役目录路径在编号分层唯一可解，却没改指"
            "（同批删除漏改的同一根因，只在代码里出现，Markdown 口径看不见）:\n  "
            + "\n  ".join(offenders)
        )


class TestGlobRefsIntoRetiredTreesAreRebased:
    """规则 1b′：通配形态（`docs/adr/0019-*.md`）在唯一可解时同样必须改指。

    通配不是占位符：占位符描述**将来**会产生什么文件名（`YYYY-MM-DD-<dev>.md`），
    通配描述**现在已存在**的那一份（`0019-*.md` 指的就是那份唯一的 ADR）。前者
    不参与判定，后者一旦命中唯一候选就与普通引用同性质——删副本没同步改指。
    只在唯一可解时判红：多候选说明它真的是一族文件，不给假阳性留口子。
    """

    def testGlobRefsWithUniqueCandidateAreRebased(self, files):
        retired = retiredTrees(files)
        offenders = []
        for path in activeDocs(files):
            text = io.open(PROJECT_ROOT / path, encoding="utf-8", errors="ignore").read()
            for number, line in enumerate(text.splitlines(), 1):
                for match in SPECIFIC_REF.finditer(line):
                    target, tree = match.group(1), match.group(2)
                    if tree not in retired or "*" not in target or "<" in target:
                        continue
                    leaf = target.split("/", 2)[-1]
                    prefix = leaf.split("*")[0].rstrip("-. _")
                    if not prefix:
                        continue
                    matches = [f for f in files
                               if f.startswith("docs/") and f.split("/")[-1].startswith(prefix)]
                    if len(matches) == 1:
                        offenders.append(f"{path}:{number} `{target}` → {matches[0]}")
        assert not offenders, (
            "通配引用指向已退役目录且唯一可解，却没改指"
            "（通配说的是'现在已存在的那一份'，不是占位符）:\n  "
            + "\n  ".join(offenders)
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
