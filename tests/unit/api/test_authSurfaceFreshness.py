# -*- coding: utf-8 -*-
"""`API_REFERENCE.md` 公开面机器段的新鲜度守卫（§6-399 裁定 A）。

背景：附录里那张**手写**的「无需认证」名单实测系统性错误（60 个模块里 55 个至少有一条路由
需认证，同一份文件里 `settings` 还留在"无需认证"行）。裁定 B 先停用，本档守的是 A 的产物：
**机器段由生成器产出、守卫逐字比对**，手改或代码漂移都会红。

四件事，每件都配反向控制或正向自证：

1. **可写回**：`applyBlock(当前文档) == 当前文档`——重跑 `--write` 不产生 diff；
2. **负向控制**：往机器段里塞一行陈旧内容 ⇒ `applyBlock` 必须把它拉回真值；
3. **读数自洽**：机器段汇总的"需认证 + 公开 == 路由总数"，且公开清单条数 == 公开数；
   再加两条下界（路由 > 500、公开 > 0）防止"两侧都空也能自洽"的空转；
4. **B 的止血不许回潮**：文档里不得再出现「无需认证」那张名单行；口径 caveat 必须在段内
   （handler 体内自验那一类未覆盖，不能因为生成了清单就把它读成全覆盖）。
"""
from __future__ import annotations

import functools
import importlib
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOC = PROJECT_ROOT / "docs" / "02-api" / "API_REFERENCE.md"


def _generator():
    """生成器模块。缺失即红——不许 importorskip 把它变成静默跳过。"""
    return importlib.import_module("scripts.generate_api_auth_surface")


@functools.lru_cache(maxsize=1)
def _app():
    from neurova.api.app import create_app
    return create_app()


def _docText() -> str:
    return DOC.read_bytes().decode("utf-8")


def _blockText(text: str) -> str:
    mod = _generator()
    begin = text.index(mod.BLOCK_BEGIN)
    end = text.index(mod.BLOCK_END) + len(mod.BLOCK_END)
    return text[begin:end]


class TestTheMachineBlockIsFresh:
    def testWriterIsIdempotentOnTheShippedDocument(self):
        mod = _generator()
        original = _docText()
        assert mod.applyBlock(original, app=_app()) == original, (
            "机器段与路由表脱节：先跑 `python scripts/generate_api_auth_surface.py --write`")

    def testNegativeControlRestoresADriftedBlock(self):
        mod = _generator()
        original = _docText()
        drifted = original.replace(
            mod.BLOCK_END, "- `GET /api/v1/not-a-real-route`\n" + mod.BLOCK_END)
        assert drifted != original, "注入漂移失败"

        restored = mod.applyBlock(drifted, app=_app())

        assert "not-a-real-route" not in restored
        assert restored == original

    def testTheBlockIsPresentExactlyOnce(self):
        text = _docText()
        mod = _generator()
        assert text.count(mod.BLOCK_BEGIN) == 1
        assert text.count(mod.BLOCK_END) == 1


class TestTheReadingsAreConsistent:
    def testGuardedPlusOpenEqualsTotalAndThePublicListIsComplete(self):
        block = _blockText(_docText())
        summary = re.search(r"路由 (\d+) 条（含方法展开）——需认证 \*\*(\d+)\*\*、公开 \*\*(\d+)\*\*", block)
        assert summary, "汇总行不见了或格式变了：%s" % block[:200]
        total, guarded, openCount = map(int, summary.groups())
        # 公开清单里可能有 `/api/v1` 之外的前缀（`/acp/...` 这类），别按前缀过滤——
        # 只认"段内的列表项"，否则会把真实存在的公开路由漏数（本档第一版就这样假红）。
        publicList = [line for line in block.splitlines() if line.startswith("- `")]

        assert guarded + openCount == total, (guarded, openCount, total)
        assert len(publicList) == openCount, (
            "公开清单条数(%d)与汇总里的公开数(%d)不一致：列一半比不列更坏" % (
                len(publicList), openCount))
        assert total > 500 and openCount > 0, (
            "读数下界不成立（%d/%d）——两侧都空时上面的自洽也是成立的，必须防这枚空转"
            % (total, openCount))

    def testTheCaveatAboutHandlerInternalAuthIsDeclared(self):
        block = _blockText(_docText())
        assert "handler 体内自验" in block, (
            "口径里的未覆盖类别被删了：生成物会被读成「身份门全覆盖」")
        assert "404/405 不算门" in block
        assert "候选集" in block, "清单的措辞退回「无凭证可打」了——那正是 C 抽样证明会骗人的说法"

    def testTheSamplingNoteIsAttached(self):
        """C 的抽样结论挂在机器段后面：2 条 handler 内自验被点到名，读者知道清单不是证明。"""
        text = _docText()
        assert "抽样复核（裁定 C" in text
        assert "/api/v1/auth/me" in text


class TestTheStopGapDoesNotRegress:
    def testTheHandWrittenNoAuthListIsGone(self):
        text = _docText()
        assert "| **无需认证**" not in text, (
            "手写「无需认证」名单又出现了——它已被实测证伪（§6-399），改由机器段承担")
