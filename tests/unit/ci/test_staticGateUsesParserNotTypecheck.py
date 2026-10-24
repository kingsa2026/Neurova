# -*- coding: utf-8 -*-
r"""未定义名门禁只该问「这个名字在**本文件**里有没有绑定」，不该问「它能不能被求值」。

成因（CI 现场读数，2026-10-23 `cnb-8a0-1k5kcrpsh-001`）：
`scripts/ci_static_gate.py` 把 pyflakes 的 `UndefinedName` 收成全仓闸门，判据是
「名字在它出现的地方查无绑定」。这条判据对**运行期**是对的，对**注解**是错的：

- `from __future__ import annotations` 的模块里，注解不求值（PEP 563），只被工具读；
- `if TYPE_CHECKING:` 块内的导入，运行期不绑定，但按设计正是注解该引用的地方；
- 局部导入（`from x import Y` 写在函数体内，用来断循环导入）在**模块级**注解里同样合法。

三种形状都**不说谎**：名字真存在于被 import 的模块。过去这道闸门把它们一起判红，于是只剩
两条出路——要么把能求值但会拉循环的导入提到模块级（改坏生产），要么删掉注解（丢解析器能用的
事实）。两条都是把报错挪走（教义第 1、2 条）。所以第三态修在闸门这一侧：同一条 pyflakes 读数
要再过一道「这个名字在文件里以某种方式被 import 过吗」的复核。

反向也被钉住：真·未定义（拼错的名字、忘写的形参）**必须**仍然红。判据用 pyflakes 自己的入口，
不另写 AST 扫描——那才是第二个事实源（教义第 6 条）。
"""
from __future__ import annotations

from pathlib import Path

from scripts.ci_static_gate import collectUndefinedNames

#: 真仓根：本档最后一格要在真目录上跑，不在小样例上自证（`tests/` 的唯一根）。
REPO_ROOT = Path(__file__).resolve().parents[3]


def _readings(source: str) -> list:
    """走闸门自己的取数口，返回 `(行, 列, 名字)` 清单（不碰文件系统）。"""
    return collectUndefinedNames(source, filename="probe.py")


class TestAnnotationOnlyShapesAreNotReported:
    """三种「运行期不绑定、但名字确实存在」的形状：过去 6 处红里占 3 种。"""

    def testForwardReferencedNameImportedUnderTypeCheckingIsAccepted(self):
        source = (
            "from __future__ import annotations\n"
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from somewhere import McpCaller\n"
            "def f(x: McpCaller | None = None):\n"
            "    return x\n"
        )
        assert _readings(source) == []

    def testForwardReferencedNameImportedInsideFunctionIsAccepted(self):
        source = (
            "from __future__ import annotations\n"
            "def f(x: McpCaller | None = None):\n"
            "    from somewhere import McpCaller\n"
            "    return McpCaller if x is None else x\n"
        )
        assert _readings(source) == []

    def testLocalImportUsedOnlyInAnnotationIsAccepted(self):
        """被注解点名、但函数体里真的用到了那个局部导入——这不是「删了才绿」的躺平格。"""
        source = (
            "def build():\n"
            "    return None\n"
            "def f():\n"
            "    from somewhere import ChannelMessage\n"
            "    msg: ChannelMessage = build()\n"
            "    return msg\n"
        )
        assert _readings(source) == []


class TestRealUndefinedNamesStillTurnRed:
    """反绕过：这道闸门的存在意义是拦真缺陷，放宽注解不许顺带放过拼错的名字。"""

    def testTypoIsStillReported(self):
        readings = _readings("def f():\n    return undefinedThing\n")
        assert [n for _line, _col, n in readings] == ["undefinedThing"], readings

    def testMisspelledParameterIsStillReported(self):
        """形参写错正是 tool_executor 那格 `file_path` 的真形态——不许被注解回退吃掉。"""
        readings = _readings(
            "import logging\n"
            "logger = logging.getLogger(__name__)\n"
            "def f(params):\n"
            "    logger.warning('x: %s', file_path)\n"
            "    return params\n"
        )
        assert [n for _line, _col, n in readings] == ["file_path"], readings

    def testSameNameImportedElsewhereDoesNotWhitelistARealTypo(self):
        """只有「这个名字在文件里被 import 过」才复核——不是「整个文件出现过」就放行。"""
        readings = _readings(
            "from somewhere import okName\n"
            "def f():\n"
            "    return okName + otherThing\n"
        )
        assert [n for _line, _col, n in readings] == ["otherThing"], readings


class TestWholeTreeReadsClean:
    """全仓读数：这道闸门跑在**真目录**上，不许只在小样例上绿。

    修复前实测 6 处（同一份清单，CI `cnb-8a0a-1k5kcrpsh-001` 与本地逐行一致）：
    `tool_executor.py` 的 `file_path`、`channels.py` 的 `ChannelMessage`、
    `mcp_server_api.py` 的 `McpCaller`、`knowledge_facts.py` 两处 `Tuple`、
    `provider_compat.py` 的 `Any`。前三种形状各有一条小样例钉住，这一格钉的是
    「闸门在真仓上跑完是空的」——小样例绿而全仓红，就是没过闸门。
    """

    def testNeurovaTreeReportsNoUndefinedNames(self):
        from scripts.ci_static_gate import scanUndefinedNamesUnder

        readings = scanUndefinedNamesUnder(str(REPO_ROOT / "neurova"))
        assert readings == [], "仍有未定义名称：\n" + "\n".join(readings)
