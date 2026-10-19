# -*- coding: utf-8 -*-
"""只降不升棘轮：`async def` 体内不得再新增"裸调阻塞子进程"的落点（§6-98）。

同一根因在两周内咬了三次（§6-93 登记 → `6c6b9cbd` 收 Studio 导出 → 本批收 neurflow
的 `video-compose` 节点与 FFmpeg 引导链）。形态很单纯：协程里直接 `subprocess.run(...)`，
语言层面即占死事件循环，而**日志零异常**——用户侧是"点了之后整个后台没反应"，
排查者按错误率去查会一条都查不到。这种故障只有钉成红/绿才拦得住。

基线口径（**本批写入前现测**，谓词见 `_scan`，扫 `neurova/` 全部 `.py`）：
**3 个文件 / 7 处**——`computer_use/camofox_supervisor.py:176/183`、
`execution_layers/__init__.py:238/314/335/395`、
`tool_executor.py:3888`。**逐文件计数**而不是全局总数：某文件站点数上升或新文件出现即红；
下降允许但本文件会红着提示"基线该收了"（偷偷比基线好＝再也没人回去核基线）。

判定形态与本仓另两枚棘轮（`test_subprocessTextEncodingRatchet` /
`test_manualScriptsEnvMutationRatchet`）一致：取 **AST 形态**而不是搜文本。

一处必须写明白的**盲区**（不写，下轮就会把这枚棘轮当成"已扫净"）：谓词只看
"`async def` 子树里直接出现 `subprocess.X(...)`"。而 `core/ffmpeg.ensure_ffmpeg()`
是 `async def` 调**同步函数** `_verify_binary()`、阻塞在那一层里——本谓词看不见它，
它由行为判据 `tests/unit/core/test_ffmpegBootstrapOffloadsTheLoop.py` 拿到
（量协程心跳推进数，不量形态）。形态守卫是地板，不是证明。
"""
from __future__ import annotations

import ast
import pathlib

from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCAN_ROOT = REPO_ROOT / "neurova"

#: 会"等结果"的形态才叫占死循环；但 Popen 也一并冻结——它后面通常紧跟
#: communicate()/wait()，且新增一发就该由作者自己说清为什么在协程里。
_BLOCKING_ATTRS = frozenset({"run", "Popen", "check_output", "check_call", "call"})

#: 冻结基线（本轮 AST 实测 3 文件 / 7 处）。只准降不准升；新文件出现即红。
#: `execution_engine/mcp_manager.py` 那一行随 §6-334 的 D 票退役收掉（整档删除 ⇒ 无 offender 可退，
#: 「单独退回 offender」那格在这一行上不成立；防它再落回来的红在
#: `test_t09_selfloop_face_ruling.py::test_mcpManagerIslandDoesNotComeBack`，那格红在文件存在上）。
BASELINE: dict[str, int] = {
    "computer_use/camofox_supervisor.py": 2,
    "execution_layers/__init__.py": 4,
    "tool_executor.py": 1,
}


def _blockingCallsInAsync(source: str) -> list[int]:
    """返回 `async def` 子树里直接调用 `subprocess.<阻塞族>(...)` 的行号。

    含 `async def` 内嵌的 `def`——那种嵌套体一旦被同协程直接调用，照样占循环。
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits: list[int] = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)]:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name)
                    and f.value.id == "subprocess" and f.attr in _BLOCKING_ATTRS):
                hits.append(node.lineno)
    return hits


def _scan(directory: pathlib.Path) -> dict[str, int]:
    """逐文件统计 `async def` 体内裸调阻塞子进程的落点数。

    取数走 `tests/ast_scan` 的共享解析预算（`sourceRefsUnder` + 文本预筛），
    不私有 `rglob + ast.parse`——后者把判据成本绑在代码总量上
    （`tests/unit/test_ci_ast_scan_budget_guard.py` 判红的正是这处）。
    预筛词取 `subprocess`，是判据的**充分条件**：谓词只认
    `subprocess.<阻塞族>(...)`，连 `subprocess` 字样都没出现的文件不可能命中。
    """
    perFile: dict[str, int] = {}
    for ref in ast_scan.sourceRefsUnder(directory, ".py", ast_scan.textHints("subprocess")):
        hits = _blockingCallsInAsync(ref.code)
        if hits:
            # `as_posix()` 不是风格问题：基线里的键要能在 Linux CI 上同样命中，
            # 而 `str(relative_to(...))` 在 Windows 上给的是反斜杠（本判据首跑即被
            # 自己的 baseline 格抓到：4 个键里只有 `tool_executor.py` 那个不含目录的对了）。
            perFile[ref.path.relative_to(directory).as_posix()] = len(hits)
    return perFile


def test_baselineMatchesMeasuredCount():
    """基线与现测必须逐文件相等——否则要么真有人动了，要么扫描根/谓词被改坏。"""
    measured = _scan(SCAN_ROOT)
    assert len(measured) > 0, "扫描面为空＝谓词或扫描根坏了，这条守卫会假绿"
    assert measured == BASELINE, (
        f"现测与基线不符（{len(measured)} 文件 / {sum(measured.values())} 处）。\n"
        f"  新增/上升：{( {k: v for k, v in measured.items() if v > BASELINE.get(k, 0)} )}\n"
        f"  下降/消失：{( {k: v for k, v in BASELINE.items() if measured.get(k, 0) < v} )}\n"
        "上升即红（本判据的全部目的）；下降是好事，但要显式把基线收掉，"
        "别留一份比现实差的基线给下一轮。")


def test_ratchetDoesNotRise():
    """逐文件只降不升——把这条单列出来，是为了让"新文件出现"报出文件名而不是只报总数差。"""
    measured = _scan(SCAN_ROOT)
    rose = {k: (BASELINE.get(k, 0), v) for k, v in measured.items() if v > BASELINE.get(k, 0)}
    assert not rose, (
        "`async def` 里又长出裸调阻塞子进程的落点（基线值→现值）："
        f"{rose}\n后果：那几十秒内同进程所有请求与回调排队，日志零异常。"
        "改法：把阻塞段收进一个同步函数，调用侧 `await asyncio.to_thread(...)`"
        "（本仓已有三处成型形态：`aigc_studio/services.py` 的 `_ffmpegExportStage`、"
        "`neurflow/drama_nodes.py` 的 `_concatLocalClips`、`core/ffmpeg.py` 的 `_verify_binary`）。")


def test_asyncBodyReallyIsTheCountedShape():
    """注入探针：谓词咬得住"协程里裸调"，也不会误伤"同步函数里调"。"""
    asyncShape = (
        "import subprocess\n"
        "async def handler():\n"
        "    return subprocess.run(['x'], check=False)\n"
    )
    assert _blockingCallsInAsync(asyncShape) == [3], "协程内那一发必须被抓到"

    syncShape = (
        "import subprocess\n"
        "def helper():\n"
        "    return subprocess.run(['x'], check=False)\n"
    )
    assert _blockingCallsInAsync(syncShape) == [], (
        "同步函数不是本判据的射程（它由调用侧决定在不在循环里）——误伤会让下一轮把守卫放宽")

    nestedShape = (
        "import subprocess\n"
        "async def outer():\n"
        "    def inner():\n"
        "        return subprocess.Popen(['x'])\n"
        "    return inner\n"
    )
    assert _blockingCallsInAsync(nestedShape) == [4], "协程内嵌套 def 里那一发同样要抓"


def test_scanRootActuallyCoversTheTree():
    """防"扫了个空却报绿"：扫描根必须真覆盖到生产树里那些文件。"""
    files = ast_scan.filesUnder(SCAN_ROOT, ".py")
    assert len(files) > 200, f"扫描根 {SCAN_ROOT} 只覆盖 {len(files)} 个文件——路径层级写错了"
    for rel in BASELINE:
        assert (SCAN_ROOT / rel).is_file(), f"基线里的 {rel} 不在扫描面内"
