# -*- coding: utf-8 -*-
"""活跃层引用可达性守卫（Issue #96 收尾·第三轮 / Ref: #68）。

背景（根因，不是形状）：文档目录重排 `fd7ea92c`+`5f94b93d` 把文档 `git mv` 进编号
分层，之后另一批次 `3b5d7e80` 又把旧路径还原回来；两次搬家都**没有同批改指引用方**。
`663faa5d`（第三方痕迹清除波）退役 43 篇文档时同样只删文件、不动引用。

前序两轮收口只覆盖了两类形态：

- `test_legacy_ref_ledger_guard.py`：`docs/11-legacy/` 归档层的悬空引用（登记台账）；
- `test_docs_retired_tree_refs_guard.py`：活跃层指向**退役目录**（`docs/<旧目录>/`）的链接。

两者都拦不住**第三类形态**：活跃层里指向**不存在的具体文件**的引用——目标既不属
「归档层」，也不属「退役目录」，于是活跃层里 20 余处死链一路无人拦。这正是修复
教义第 2 条禁止的抹除式修复的反向形态：改了目录、没改引用，洞只是换了个地方。

判据只写一份（`scripts/scan_docs_refs.py` 的 `activeLayerDangling`），本守卫只做
「重算 + 比对 + 负向控制」，不在别处复制一套解析规则。

口径边界（写死在扫描器里，此处置信）：
- 归档层（`docs/05-reports/`、`docs/06-bugfix/`、`docs/09-dev-progress/`、`docs/11-legacy/`）
  不就地改写：它们陈述的是**当时**的代码结构与路径，改成今天的形态反而让历史失真；
- 随仓库分发的第三方文档（`embedding/`、`models/`）不属本仓文档体系。

因此本守卫锁三件事：

1. **活跃层零悬空引用**（硬零，不是棘轮）：新增一处即红，不留「登记了事」的余地。
2. **修法不是删链接**：被改名/退役的目标必须改指真实可达的权威文档，或改成
   显式文本交代去处；不得把链接删成空白（由 §负向控制与既有抹除棘轮共同兜底）。
3. **反向控制**：注入一处悬空引用必须被抓到；合法形态（外链、行内代码里的示例
   语法、围栏代码块）不得误报——假阳性比漏报更坏，它会训练人忽略这道门禁。
"""
import io
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

scanner = pytest.importorskip("scripts.scan_docs_refs")


class TestActiveLayerHasNoDanglingRef:
    """活跃层的每一处引用都必须真实可达。"""

    def test_scanner_exposes_active_layer_scan(self):
        """判据必须由扫描器提供——守卫不另写一套解析。"""
        assert hasattr(scanner, "activeLayerDangling"), (
            "扫描器未提供 activeLayerDangling()：活跃层可达性判据缺位，"
            "本守卫会退化成一条空规则。"
        )
        assert hasattr(scanner, "activeLayerDocuments"), (
            "扫描器未提供 activeLayerDocuments()：活跃层范围必须单源定义。"
        )

    def test_active_scope_is_not_vacuous(self):
        """反向控制：范围不得缩成空集（那样下面的零断言会空转通过）。"""
        documents = scanner.activeLayerDocuments()
        assert len(documents) > 200, (
            f"活跃层只扫到 {len(documents)} 篇文档，范围疑似失效。"
        )

    def test_no_dangling_reference_in_active_layer(self):
        entries = scanner.activeLayerDangling()
        rendered = "\n  ".join(
            f"{e['file']}:{e['line']} [{e['label']}]({e['ref']})（{e['verdict']}）"
            for e in entries[:20]
        )
        assert not entries, (
            f"活跃层存在 {len(entries)} 处悬空引用——搬家/退役改了目录没改引用，"
            "洞换了地方。\n修法：改指真实可达的权威文档，或改成显式文本交代去处；\n"
            "不得删链接了事，也不得留成登记状态（活跃层是当下可读面）。\n  " + rendered
        )


class TestScannerActuallyDetectsDangling:
    """负向控制：检出器不得空转，也不得误报合法形态。"""

    def test_injected_dangling_link_is_detected(self, tmp_path):
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# 样例\n\n见 [已搬家文档](../01-architecture/这条路径并不存在_zzz.md)。\n",
            encoding="utf-8",
        )
        found = scanner.scanDocumentLinks(sample, scanner.indexByBasename(scanner.trackedFiles()))
        assert found, "注入的悬空引用未被检出——本守卫的核心目标失效"
        assert found[0]["ref"].endswith("这条路径并不存在_zzz.md")

    def test_injected_html_ref_is_detected(self, tmp_path):
        sample = tmp_path / "sample.md"
        sample.write_text(
            '# 样例\n\n<img src="./并不存在的品牌图_zzz.png" alt="logo">\n',
            encoding="utf-8",
        )
        found = scanner.scanDocumentLinks(sample, scanner.indexByBasename(scanner.trackedFiles()))
        assert found, "注入的悬空 HTML src 未被检出——只扫 Markdown 链接会留盲区"

    def test_external_and_inline_code_forms_are_not_false_positives(self, tmp_path):
        """外链、围栏代码块、行内代码里的示例语法都不是仓库内引用。"""
        sample = tmp_path / "sample.md"
        sample.write_text(
            "# 样例\n\n"
            "外链 [官网](https://example.com/x.md) 不是引用。\n"
            "锚点 [小节](#section) 不是引用。\n"
            "围栏示例：\n\n```markdown\n[示例](并不存在的文件_zzz.md)\n```\n\n"
            "行内示例：GFM 表格与 `![alt](src)` 写法说明。\n",
            encoding="utf-8",
        )
        found = scanner.scanDocumentLinks(sample, scanner.indexByBasename(scanner.trackedFiles()))
        assert not found, f"合法形态被误报为悬空引用: {found}"


class TestFixIsNotLinkRemoval:
    """修法纪律：活跃层的目标必须改指真实文件，或以显式文本交代去处。"""

    def test_every_dangling_target_would_be_reachable(self):
        """每条悬空引用的「引用原文」都在当前文件树里找不到——这就是判定本身的自证。"""
        entries = scanner.activeLayerDangling()
        for entry in entries:
            literal = entry["ref"].lstrip("/").split("#")[0].strip()
            assert literal, f"空目标应以显式文本呈现，不得留成 `[]()`: {entry}"

    def test_ledger_registers_this_round(self):
        """本轮根因、边界与残留必须登记进台账——不许静默遗留（教义第 5 条）。"""
        ledger = PROJECT_ROOT / "docs" / "06-bugfix" / "历史悬空引用登记台账_2026-09-21.md"
        assert ledger.is_file(), "登记台账缺失"
        text = io.open(ledger, encoding="utf-8").read()
        for keyword in ("活跃层", "activeLayerDangling"):
            assert keyword in text, (
                f"台账未登记本轮范围与判据（缺「{keyword}」）——"
                "修完不等于不必登记，读者要能查到边界与判据在哪。"
            )
