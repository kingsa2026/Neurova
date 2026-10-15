# -*- coding: utf-8 -*-
"""源码里不得再有非法转义序列（§6-177 批 22 · 全仓棘轮，零容忍）。

复核实状（本批现量，`git ls-files -z '*.py'` ⇒ 3340 个文件逐个 `compile()` 并捕获警告）：
- **非法转义 11 处**：生产 3（`neurova/cognitive_layers/memory_layer/muscle_memory.py:624`、
  `neurova/context/eviction_ledger_db.py:22` 与 `:807`）、脚本 2（`scripts/desktop/package_installer_zip.py:83`
  与 `:199`）、判据 6（`tests/unit/test_ci_npc_config_guard.py:45/:442/:563/:1007`、
  `tests/unit/ci/test_npc_pipeline_time_budget.py:340`、
  `tests/unit/llm/test_ledgerTerminalVocabularySingleSource.py:85`）。
- **语法坏的档 0 处**——所以"跳过编译失败的文件"这条兜底一旦存在就是纯逃逸口，本档把它钉成必报。

为什么值得常驻：这 11 处全是 docstring 里"写给人看的反斜杠"（正则字符类里的反斜杠 w、Windows 路径的
Bin 目录段、Schema 锚点里的转义点）。Python 目前对未知转义**按字面保留**，所以文本没坏、只有 `SyntaxWarning`——
这正是它危险的地方：今天不改变行为，语言侧把它升级为错误的那天，全仓 import 一起断，
而且断在**别人的文档注释**上。同时它们已经在污染每次跑测的 warnings 摘要
（`test_voiceEngineBridgeRetired` 那档就替别人报了 4 条转义点警告）。

口径决定：**零容忍，不留存量表**。11 处全是加一个 `r` 前缀的行内改动、不改字符串值（等值由
本批的活体自证逐文件核过），留一份"允许非法转义的文件清单"就是第二个事实源，且那份清单只会被
顺手加长。体量下限按**测量值取整做地板**而不是等值断言（见 `_MIN_SCANNED`），这样收窄扫描面会红，
而仓库自然增减文件不会。

一处自指形态必须防：判据要抓的就是"源码里的反斜杠"，样本若写成本文件里的普通字符串，
本档自己就成了第 12 处命中（"本文件不得出现 X"的源码包含检查把自己那句断言算进去＝恒红那一形）。
故合成样本一律由 `chr(92)` 现拼，本文件通篇不出现裸反斜杠。

口径边界（不是缺陷，如实写）：扫描取的是**工作树**读数——并发会话在途的半截文件若带非法转义，
本机这条会红而 CI（扫提交态）不会。这与其他全仓源码扫描守卫同形，不做"只扫已提交内容"的收窄：
那样会把别人未提交的坏写法读成绿。
"""

from tests import ast_scan  # noqa: E402
import pathlib
import warnings

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
BACKSLASH = chr(92)
#: 2026-10-13 实测 3340 个跟踪的 .py 文件。这是**地板**不是等值：扫到不足 3000 说明口径被
#: 收窄（只扫某个目录、或把 git 读数换成了 rglob 后被 __pycache__ 之类挤掉），那正是这条棘轮
#: 失效的形态；仓库自然增减几十个文件不会撞到它。
_MIN_SCANNED = 3000


def _trackedSources() -> list:
    """扫描集合＝git 跟踪的 `*.py`（不用 rglob：那会把 __pycache__ 与未跟踪垃圾算进来，
    也会漏掉 .gitignore 外但已跟踪的档，两个方向都能造假绿）。取数走 `ast_scan` 单点。"""
    return ast_scan.trackedPyPaths()


def _escapeWarnings(rel: str, src: str) -> list:
    """单个文件的读数：非法转义列表；编译不通过时**点名**而不是跳过。"""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(src, rel, "exec")
        except SyntaxError as exc:
            return [f"语法坏（不是被跳过）：{exc.msg} @line {exc.lineno}"]
    return [str(w.message) for w in caught if "escape sequence" in str(w.message)]


def _scan(relPaths) -> dict:
    results = {}
    for rel in relPaths:
        path = REPO / rel
        if not path.is_file():
            results[rel] = ["文件在 ls-files 读数里却不存在（HEAD 与磁盘不一致，别当绿）"]
            continue
        results[rel] = _escapeWarnings(rel, path.read_text(encoding="utf-8", errors="replace"))
    return results


@pytest.fixture(scope="module")
def trackedScan() -> dict:
    return _scan(_trackedSources())


class TestTheRatchetIsGreen:
    def testNoIllegalEscapeSequenceAnywhere(self, trackedScan):
        offenders = sorted(
            f"{rel}:{entry}" for rel, hits in trackedScan.items() for entry in hits)
        assert offenders == [], (
            f"非法转义序列 {len(offenders)} 处（今天是警告，升级为错误即全仓 import 断）：" + "\n    ".join(offenders))

    def testScanCoversTheThreePoolsItClaimsTo(self, trackedScan):
        """排除型断言在功能缺失时会自动成立——所以这里证明"扫得到"而不是只证明"没命中"。"""
        perPool = {}
        for rel in trackedScan:
            top = rel.split("/", 1)[0]
            perPool[top] = perPool.get(top, 0) + 1
        assert len(trackedScan) >= _MIN_SCANNED, (
            f"只扫到 {len(trackedScan)} 个文件，低于地板 {_MIN_SCANNED}——扫描面被收窄了，"
            "这条棘轮就不再是全仓棘轮")
        for pool in ("neurova", "scripts", "tests"):
            assert perPool.get(pool, 0) > 0, f"扫描面不含 {pool}/，那半区无人守（读数：{sorted(perPool)[:8]}）"


class TestTheDetectorItself:
    def testIllegalEscapeIsActuallyCaught(self):
        """自证：合成样本必须被抓。反证是"扫描器永远返回空列表"这种假绿形态。"""
        sample = 'value = "路径 ' + BACKSLASH + 'wave 里的反斜杠"\n'
        hits = _escapeWarnings("<inline>", sample)
        assert len(hits) == 1, f"合法样本没抓到（判据是空的）：{hits!r}"
        assert BACKSLASH + "w" in hits[0], f"抓到的不是那一条：{hits}"

    def testRawStringIsAccepted(self):
        """加 r 前缀是本批的修法，判据必须认它——否则绿灯那一步会被自己的判据否掉。"""
        sample = 'value = r"路径 ' + BACKSLASH + 'wave 里的反斜杠"\n'
        assert _escapeWarnings("<inline>", sample) == []

    def testBrokenFileIsNamedNotSkipped(self):
        """编译失败的兜底不能是"悄悄不算"，否则少扫一个文件就少一片命中。"""
        hits = _escapeWarnings("<inline>", "def broken( ):\n")
        assert any("语法坏" in h for h in hits), f"坏文件被吞掉了：{hits!r}"

    def testTheRepoWasNotAlreadyCleanWhenThisFileWasWritten(self):
        """钉住本批的来路：修法（加 r 前缀）确实把一条命中消掉了，而不是判据看不见它。"""
        dirty = 'text = """文档里写 ' + BACKSLASH + 'w 是正则字符类"""\n'
        clean = 'text = r"""文档里写 ' + BACKSLASH + 'w 是正则字符类"""\n'
        assert len(_escapeWarnings("<inline>", dirty)) == 1
        assert _escapeWarnings("<inline>", clean) == []
        assert dirty != clean, "两个样本必须不同形，否则这条格什么都没证"
