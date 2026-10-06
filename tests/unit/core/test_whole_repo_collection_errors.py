# -*- coding: utf-8 -*-
"""全仓收集零错误守卫：一份文件在收集期报错，`pytest tests/` 就一条用例都不跑

`tests/benchmarks/test_multi_agent_coordination.py` 自 2026-09-21 起在模块顶层
`from neurova.agents.seen_boundary import ...`——该模块本仓不存在（`coordination_api.py:34-35`
记着这批端点连同依赖已退役）。后果不是"那一份文件不跑"，而是 pytest 的默认行为
**Interrupted: 1 error during collection**：整仓 21289 条一条都不执行。
`docs/specs/2026-09-20-knowledge-foundation-design.md:534` 当时给的绕行是
`--ignore=tests/benchmarks`——绕行不是修，忽略面还会随文件数增长。

为什么不进 `scripts/ci/protected_tests.txt`：本守卫要真跑一次全仓 `--collect-only`
（实测约 60s），而 CI 的 unit job 是按子集清单起一次 pytest，加进来就是把 60s 直接
加到 CI 上。CI 时长口径归用户定，这里默认不占；本地/目录级跑仍会执行它。
成本另按"一次收集、多条断言"收：模块级夹具只起一次子进程。

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
        timeout=COLLECT_TIMEOUT,
    )
    return proc.returncode, proc.stdout + proc.stderr


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


@pytest.mark.timeout(120)
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
