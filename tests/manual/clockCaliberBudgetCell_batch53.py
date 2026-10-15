# -*- coding: utf-8 -*-
"""live-verify（§6-230）：把市场取数总预算那格从真实墙钟改成虚拟单调钟之后，负载打不动它，而旧形态打得动。

这道改判的理由不能只写在注释里——本档给四条读数，前后各两条：

1. **空闲下的新格**：重试次数恰 3、虚拟钟推进恰 0.6（精确值，不是区间）；
2. **8 个忙线程下的同一格**：读数逐字不变 ⇒ "负载无关"从散文变成读数；
3. **旧形态复算（只留读数，不计分）**：同一场景用真实钟 + 真睡跑，报**上界还剩多少裕量**——
   真实钟下翻不翻红正取决于负载，把它做成断言就复刻了同一枚病。这才是 §6-198 那格的病灶；
4. **真生产路径**（真钟、真睡 0.2s、`HUB_FETCH_TOTAL_SECONDS=0.5`）：新虚拟钟的形状与真实行为
   **同形**（同样三次、同样越线在第三次之后），防"虚拟钟自洽而生产另一形"那种假绿；
5. 常驻守卫与本批判据复跑读数。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/clockCaliberBudgetCell_batch53.py`
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error as ue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaClockB53")
failures: list = []

SCENARIO_EACH = 0.2
SCENARIO_BUDGET = 0.5


def runScenario(virtual: bool):
    """跑一次被测路径，返回 (尝试次数, 耗时读数, 抛出的异常类型名)。

    virtual=True ⇒ 用判据那格的虚拟单调钟；False ⇒ 真实钟 + 真睡（旧形态）。
    """
    import neurova.skills.hub_client as H

    attempts: list = []
    state = {"now": 0.0}

    class VirtualTime:
        def monotonic(self):
            return state["now"]

        def sleep(self, seconds):
            state["now"] += seconds

    realTime = H.time
    if virtual:
        H.time = VirtualTime()

    def fake_urlopen(request, timeout=None):
        attempts.append(timeout)
        if virtual:
            state["now"] += SCENARIO_EACH
        else:
            time.sleep(SCENARIO_EACH)
        raise ue.URLError("simulated slow remote")

    origUrlopen, origBackoff, origTotal, origRetries = (
        H.urlopen, H._compute_backoff_seconds, H.HUB_FETCH_TOTAL_SECONDS, H._http_retries)
    H.urlopen = fake_urlopen
    H._compute_backoff_seconds = lambda attempt: 0.0
    H.HUB_FETCH_TOTAL_SECONDS = SCENARIO_BUDGET
    H._http_retries = lambda: 50
    started = time.monotonic()
    err = None
    try:
        try:
            H._http_fetch("https://hub.invalid/x")
        except Exception as exc:      # noqa: BLE001 - 要的就是"照旧抛出失败"这个形状
            err = type(exc).__name__
    finally:
        H.time = realTime
        H.urlopen, H._compute_backoff_seconds = origUrlopen, origBackoff
        H.HUB_FETCH_TOTAL_SECONDS, H._http_retries = origTotal, origRetries
    return len(attempts), (state["now"] if virtual else time.monotonic() - started), err


def loadThreads(n: int = 8):
    stop = threading.Event()

    def spin():
        x = 0
        while not stop.is_set():
            x = (x + 1) % 9973
    ts = [threading.Thread(target=spin, daemon=True) for _ in range(n)]
    for t in ts:
        t.start()
    time.sleep(0.3)               # 让线程真跑起来
    return stop, ts


def read(idx: str, desc: str, fn) -> None:
    try:
        print("[%s] PASS %s  ← %s" % (idx, desc, fn()))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def _idleVirtual() -> str:
    attempts, clockNow, err = runScenario(virtual=True)
    assert (attempts, round(clockNow, 6)) == (3, 0.6), f"读数异常：{attempts} 次 / {clockNow} / {err}"
    return "%d 次 / 虚拟钟 %.1f / 抛出 %s" % (attempts, clockNow, err)


read("1", "空闲下新格：重试恰 3 次、虚拟钟恰 0.6", _idleVirtual)

def _underLoad() -> str:
    stop, ts = loadThreads()
    try:
        attempts, clockNow, err = runScenario(virtual=True)
    finally:
        stop.set()
        for t in ts:
            t.join(timeout=2)
    assert (attempts, round(clockNow, 6)) == (3, 0.6), (
        f"加压下虚拟钟读数漂了：{attempts} 次 / {clockNow}")
    return "8 忙线程下仍 %d 次 / 虚拟钟 %.1f" % (attempts, clockNow)


read("2", "8 个忙线程下同一格逐字不变（负载无关）", _underLoad)


def observe(desc: str, fn) -> None:
    try:
        print("    OBSERVE %s：%s" % (desc, fn()))
    except Exception as exc:  # noqa: BLE001 - 观察项不记分，只留读数
        print("    OBSERVE %s：读数失败 %r" % (desc, exc))


def _oldFormUnderLoad() -> str:
    """旧形态复算（真实钟 + 真睡，断言 `elapsed < 1.5`）：报**裕量**，不报"过没过"。

    这项刻意不计分——真实钟下它翻不翻红正取决于负载，把它做成断言就复刻了同一枚病。
    要留的读数是"上界还剩多少裕量"：裕量被吃光＝这格随时在别人的机器上红。
    """
    stop, ts = loadThreads(n=10)
    try:
        attempts, elapsed, _err = runScenario(virtual=False)
    finally:
        stop.set()
        for t in ts:
            t.join(timeout=2)
    crossed = elapsed >= 1.5
    return ("10 忙线程下旧断言实测 elapsed=%.2fs（上界 1.5s，裕量 %.2fs）⇒ %s；"
            "同一场景的新格仍是精确 3 次/0.6（见第 2 项）"
            % (elapsed, 1.5 - elapsed, "**已翻红**" if crossed else "侥幸未翻红，但裕量只剩这一点点"))


observe("旧形态在负载下的上界裕量（不计分，只留读数）", _oldFormUnderLoad)


def _realClockMatchesVirtualShape() -> str:
    """真生产路径（真钟、真睡）与虚拟钟**同形**：同样三次、失败照旧抛出。"""
    attempts, elapsed, err = runScenario(virtual=False)
    assert attempts == 3, f"真实路径重试次数 {attempts} ≠ 虚拟钟那格的 3 次——判据与生产不同形"
    assert err == "URLError", f"失败没照旧抛出：{err}"
    assert 0.5 <= elapsed < 2.0, f"真实耗时读数异常：{elapsed:.2f}s"
    return "真钟 %d 次 / %.2fs / 抛出 %s（与虚拟钟同形）" % (attempts, elapsed, err)


read("4", "真生产路径与虚拟钟形状一致（防虚拟钟自洽）", _realClockMatchesVirtualShape)


def _guardsGreen() -> str:
    p = subprocess.run([sys.executable, "-m", "pytest",
                        "tests/unit/ci/test_clock_caliber_ledger.py",
                        "tests/unit/skills/test_marketFetchBudgetIsSingleSource.py",
                        "-q", "-p", "no:cacheprovider",
                        "-W", "ignore::UserWarning", "-W", "ignore::DeprecationWarning"],
                       cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                       errors="replace",
                       # 两头钉（§6-225 那族）：父端按 utf-8 解 Python 子件时，子端必须同时被钉成
                       # UTF-8 输出，否则中文被换成 U+FFFD；这条由半修等号格自动咬。
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    tail = [l for l in (p.stdout or "").splitlines() if " passed" in l or "failed" in l]
    assert p.returncode == 0 and tail, f"守卫或判据未全绿：{(tail or [p.stdout[-300:]])[-1]}"
    return tail[-1].strip("=").strip()


read("5", "常驻守卫 + 本批判据复跑", _guardsGreen)

print("\n总计：4 项计分 + 1 项读数（旧形态上界裕量），失败 %d 项 ｜ 隔离工作根=%s"
      % (len(failures), WORK_ROOT))
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)
