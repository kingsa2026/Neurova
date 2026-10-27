# -*- coding: utf-8 -*-
"""台账的机器区必须只由**被扫描目录的内容**决定。

根因（CI 构建 `cnb-1f0-1k5uonjt2-003` 实读，7 red）：台账记的是「哪份文档的哪一行
引用了哪个路径」，而生成物入库后与`docs/11-legacy/` 的现行行号早已不是一回事 ——
归档层文档被后续批次改过分节，台账里的行号停在生成那一刻。于是每一格都成了
「行号对不对」的判据：删掉一个文件、某处 `pytest.skip` 换一行，都能把台账整片
重排，而**被引用的路径一条没变**。

判据的落点因此不在「台账对不对」，而在**生成器的输入面**：行号是扫描时那一份
文件的属性，不是路径的属性。断言：

- 同一份被扫描内容 → 无论正文在别处怎么变（此处**只**改行号所在的源文档），生成结果逐字节相同；
- 反向控制：引用**变化**时生成结果必须变 —— 否则前一条会退化成「生成器恒返回空」。

同时钉住修法所在：`_entry` 提供 `contentDigest`、台账渲染走它，不再写行号。
"""
import shutil
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

scanner = pytest.importorskip("scripts.scan_docs_refs")

LEGACY = PROJECT_ROOT / "docs" / "11-legacy"
# 台账里条数最多的载体：改写它的分节最能把行号整片推走
CARRIER = LEGACY / "test-debt-skip-list.md"


def _scan(directory: Path) -> list:
    return scanner.scanDirectory(directory)


def testLedgerIsInvariantToLineNumbersInScannedDocs(tmp_path):
    """被扫描文档的行号整体平移 → 机器区逐字节不变。"""
    work = tmp_path / "11-legacy"
    shutil.copytree(LEGACY, work)

    before = _scan(work)
    target = work / CARRIER.name
    original = target.read_text(encoding="utf-8")
    # 在文首插入一节，把它下面每一行都推走；引用本身一个字都没动
    target.write_text("## 行号平移练习\n\n" + original, encoding="utf-8")
    after = _scan(work)

    assert len(before) == len(after), (
        "只有行号变了，台账条目数却变了：%d → %d" % (len(before), len(after))
    )
    assert scanner.renderTable(before) == scanner.renderTable(after), (
        "同一份引用集合、只把源文档的行号平移，机器区却变了——\n"
        "说明台账把「扫描那一刻的行号」当成了路径的属性，"
        "任何编辑归档层正文都会把整张表重排一次。"
    )
    assert scanner.renderSummary(before) == scanner.renderSummary(after)


def testLedgerStillMovesWhenAReferenceActuallyChanges(tmp_path):
    """反向控制：引用真的变了，机器区必须跟着变（否则上一格恒真）。"""
    work = tmp_path / "11-legacy"
    shutil.copytree(LEGACY, work)

    before = _scan(work)
    target = work / CARRIER.name
    target.write_text(
        target.read_text(encoding="utf-8") + "\n`neurova/__definitely_absent__.py`\n",
        encoding="utf-8",
    )
    after = _scan(work)

    assert scanner.renderSummary(before) != scanner.renderSummary(after), (
        "新增一处悬空引用后机器区一动不动——生成器对引用集合不敏感，"
        "前一条判据会退化成恒真。"
    )


def testEntriesCarryContentDigestNotTheScannerLineNumber():
    """条目带 `contentDigest` 作锚点，且锚点随文档内容而非行号走。"""
    entries = _scan(LEGACY)
    assert entries, "扫描器在归档层零命中——本判据会空转，先修扫描器"
    missing = [e for e in entries if not e.get("contentDigest")]
    assert not missing, (
        "有 %d 条悬空引用没有内容锚点：%r。台账的定位必须由内容决定，"
        "由行号决定就会随任意一次正文编辑整片漂移。" % (len(missing), missing[:3])
    )
    anchors = {e["contentDigest"] for e in entries}
    assert all(len(a) >= 8 for a in anchors), "锚点过短，不足以定位"

    # 同一文档里不同的行不得共用同一个锚点（否则同一行重复引用会被吞掉）
    perDocument = {}
    for entry in entries:
        perDocument.setdefault(entry["file"], set()).add(entry["contentDigest"])
    shrinking = {
        path: (len(anchorsOf), sum(1 for e in entries if e["file"] == path))
        for path, anchorsOf in perDocument.items()
        if len(anchorsOf) < sum(1 for e in entries if e["file"] == path)
    }
    assert not shrinking, f"同一文档内锚点撞号（定位不到唯一一行）：{shrinking}"
