# -*- coding: utf-8 -*-
"""全仓收集零错误守卫：一份文件在收集期报错，`pytest tests/` 就一条用例都不跑

`tests/benchmarks/test_multi_agent_coordination.py` 自 2026-09-21 起在模块顶层
`from neurova.agents.seen_boundary import ...`——该模块本仓不存在（`coordination_api.py:34-35`
记着这批端点连同依赖已退役）。后果不是"那一份文件不跑"，而是 pytest 的默认行为
**Interrupted: 1 error during collection**：整仓 21289 条一条都不执行。
`docs/specs/2026-09-20-knowledge-foundation-design.md:534` 当时给的绕行是
`--ignore=tests/benchmarks`——绕行不是修，忽略面还会随文件数增长。

为什么不进 `scripts/ci/protected_tests.txt`：本守卫要真跑一次全仓 `--collect-only`
（2026-10-08 逐文件单跑实测 **63.63s**、21690 条、零收集错误），而 CI 的 unit job 是按
子集清单起一次 pytest，加进来就是把 60s+ 直接加到 CI 上。CI 时长口径归用户定，
这里默认不占；本地/目录级跑仍会执行它。
成本另按"一次收集、多条断言"收：模块级夹具只起一次子进程。

**本文件曾经一条主断言都没跑过**（2026-10-08 查出）：`_collect` 用 `text=True`
而不显式给 `encoding`，父进程按本机 locale（cp936）解子进程的 UTF-8 字节，
全仓那一发把 `proc.stdout` 静默解成了 `None` ⇒ `proc.stdout + proc.stderr`
抛 TypeError ⇒ 两条主断言全部 **ERROR at setup**，唯一真跑起来的是最便宜的反证。
"守卫在跑"和"守卫有效"是两件事，所以本文件现在先跑一条运行性前置判据。

判据防"假绿"两条：① 收集条数下限（路径写错或整体被 skip 也会"零错误"）；
② 反证——真造一份带死导入的文件必须被点名，证明守卫咬得住。
"""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
#: 全仓 --collect-only 实测 ~60s；给 420s 余量（本机跑测有并发时更慢），
#: 全局 30s timeout 会直接把本守卫杀成 Timeout kill，必须按仓内成例单独放宽。
COLLECT_TIMEOUT = 420
#: 实测 21289 条；下限只拦"其实没收到东西"，不为钉死条数。
COLLECTED_FLOOR = 15000


def _collect(targets: list):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "--collect-only", "-q",
         "--continue-on-collection-errors", "-p", "no:cacheprovider"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        # 两侧都要钉死：子进程按什么写、父进程就得按什么解。不显式给 encoding 时
        # 父进程按 locale（本机 cp936）去解子进程的 UTF-8 字节——实测两种坏法都出现过：
        # 全仓收集那一发 `proc.stdout` 被**静默置成 None**（同调用改回 bytes 模式即拿到
        # 1.65MB 正常输出），于是 `proc.stdout + proc.stderr` 抛 TypeError，
        # 本守卫的两条主断言**从来没运行过**（实测 2 ERROR at setup，
        # 而文件里唯一真跑起来的是最便宜的那条反证）。
        # 这与 `scripts/ci/pip_audit_gate.py` 那次红同根因，是仓内第 2 格命中。
        encoding="utf-8",
        errors="replace",
        timeout=COLLECT_TIMEOUT,
    )
    return proc.returncode, proc.stdout + proc.stderr


#: 本格与下面那格都走 `_collect`（子墙 `COLLECT_TIMEOUT`）：父墙低于子墙时先到点的
#: 是父墙，Windows 侧即整场终止。同档另两格早已按 `COLLECT_TIMEOUT + 60` 声明，
#: 这里补齐剩下的两格（§6-402 批 K）。
@pytest.mark.timeout(COLLECT_TIMEOUT + 60)
def test_collectDecodesChildOutputExplicitly():
    """守卫必须真在跑：子进程输出含非 ASCII 时，捕获结果不许被静默换成 None。

    这是本文件自己的**运行性前置**——`test_wholeRepoCollection*` 两条断言读的
    就是 `_collect` 的返回值；它一旦抛 TypeError 或返回空，"零错误"就成了没人在看的绿。

    走法：让子进程去取一个**路径含中文**的目标，pytest 会把这条路径原样打进它自己的
    stdout（`ERROR: file or directory not found: …`）。不用"模块顶层 print"做证据——
    收集期 print 被子 pytest 的捕获层吞掉，与编码口径无关也会缺席，那样这条判据就
    分不出"解码坏了"和"根本没打出来"。子进程写侧同时钉成 UTF-8，两侧都可控。
    """
    import os

    saved = os.environ.get("PYTHONIOENCODING")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    try:
        rc, out = _collect(["tests/中文路径探针_不存在.py"])
        assert isinstance(out, str), f"捕获被静默丢弃（out={out!r}），主断言因此从未运行"
        assert "中文路径探针" in out, (
            f"子进程的非 ASCII 输出没有原样回到父进程——解码口径不可信：\n{out[-400:]!r}"
        )
    finally:
        if saved is None:
            os.environ.pop("PYTHONIOENCODING", None)
        else:
            os.environ["PYTHONIOENCODING"] = saved


@pytest.fixture(scope="module")
def wholeRepoCollection():
    """全仓收集跑一次，供多条断言共用（避免每次断言再付 60s）。"""
    return _collect(["tests/"])


@pytest.mark.timeout(COLLECT_TIMEOUT + 60)
def test_wholeRepoCollectionHasNoErrors(wholeRepoCollection):
    """`pytest tests/` 必须收得起来——收集期错误会让整仓零执行。"""
    rc, out = wholeRepoCollection
    errorLines = [ln for ln in out.splitlines() if "ERROR collecting" in ln]
    assert not errorLines, (
        "全仓收集存在错误，`pytest tests/` 会 Interrupted 且不跑任何用例：\n%s\n%s"
        % ("\n".join(errorLines), out[-1200:])
    )
    assert rc == 0, f"收集返回码非 0 却没有 ERROR collecting 行，判据需补形态：\n{out[-1200:]}"


@pytest.mark.timeout(COLLECT_TIMEOUT + 60)
def test_wholeRepoCollectionCountIsReal(wholeRepoCollection):
    """反假绿：条目数必须落在真实量级，否则"零错误"可能只是没收到东西。"""
    rc, out = wholeRepoCollection
    marker = " tests collected"
    line = next((ln for ln in out.splitlines() if marker in ln), "")
    count = int("".join(ch for ch in line.split(marker)[0] if ch.isdigit()) or 0)
    assert count >= COLLECTED_FLOOR, f"收集条数异常低（{count} < {COLLECTED_FLOOR}）：{line!r}"


@pytest.mark.timeout(COLLECT_TIMEOUT + 60)
def test_reverseProofDetectsADeadModuleImport():
    """守卫非空转：模块顶层死导入必须被收集期点名到文件。"""
    probe = PROJECT_ROOT / "tests" / "unit" / "test_deadImportProbe.py"
    assert not probe.exists(), "上一次反证残留会污染收集基线"
    try:
        probe.write_text(
            "from neurova.thisModuleDoesNotExist import anything\n\n"
            "def test_probe():\n    assert True\n",
            encoding="utf-8",
        )
        rc, out = _collect(["tests/unit/test_deadImportProbe.py"])
        assert "ERROR collecting" in out, f"死导入未被收集期点名（守卫空转）：\n{out[-600:]}"
        assert "test_deadImportProbe.py" in out, f"报错没点名肇事文件：\n{out[-600:]}"
    finally:
        probe.unlink(missing_ok=True)
