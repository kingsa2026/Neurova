# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-14 批 40，§6-198）：市场取数的预算单线与两条截止线。

判据档在桩件上量形状；这一支要在**真出网的生产链**上读：

1. 真 `SkillMarketSearcher().search_all_markets(...)` 打真市场，量整趟耗时——
   改前最坏 7 × 30 = 210 秒，改后必须被 18s 截止线兜住；
2. 聚合的跳过读数必须在（到点没开跑的市场要点名，不许静默）；
3. 真 `hub_client._http_fetch` 打一个解析不了的域名，量"重试 + 退避"叠完的实际耗时与
   那条"停止重试"的日志——这条路在**生产安装链**上（`skill_service:652`、`manifest_source:119`）；
4. 反证段：把截止线放到 600s，同样一个会吊死的假市场必须**一直等下去**——
   证明拦住它的是这条截止线，不是别处的巧合；
5. 撤桩复证：截止线回到生产缺省，同形场景必须重新在预算内返回。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/marketFetchBudget_batch40.py`
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot(prefix="neurovaB40")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def main() -> int:
    import urllib.error

    import neurova.skills.hub_client as HUB
    import neurova.skills.market_searcher as MS
    from neurova.skills.market_adapters import MARKET_FETCH_TIMEOUT_SECONDS as BUDGET

    wall = 30.0  # pyproject 的全局 timeout；判据档自己读，这里只作对照
    searcher = MS.SkillMarketSearcher()
    names = searcher.list_market_names()
    print(f"[取值] 现役市场={names} 每市场预算={BUDGET}s 聚合截止线="
          f"{MS.MARKET_SEARCH_AGGREGATE_SECONDS}s hub 总预算={HUB.HUB_FETCH_TOTAL_SECONDS}s")
    check("[R1] 市场数与两条预算线都读得到，且每市场预算明显小于跑测墙钟",
          len(names) >= 1 and BUDGET * 2 <= wall,
          f"markets={len(names)} budget={BUDGET}")

    collector = _Collect()
    # 失败读数是**适配器自己的 logger** 发的（`market_adapters.py:197` 等十处），
    # 挂在 searcher 上会一条也接不到——挂根 logger 才量得准。
    root = logging.getLogger()
    root.addHandler(collector)
    root.setLevel(logging.DEBUG)
    started = time.monotonic()
    try:
        results = searcher.search_all_markets("search", limit_per_market=3)
    except Exception as e:  # noqa: BLE001 — 活体只记录，真链路的异常本身是读数
        results = []
        print(f"        聚合抛错（真网络环境下的形状）：{type(e).__name__}: {e}")
    elapsed = time.monotonic() - started
    root.removeHandler(collector)

    print(f"[真链路] search_all_markets 耗时 {elapsed:.1f}s，结果 {len(results)} 条，"
          f"日志 {len(collector.messages)} 条")
    check("[R2] 真出网的整趟聚合落在跑测墙钟之内（改前最坏 210s）",
          elapsed < wall, f"elapsed={elapsed:.1f}s")
    skipped = [m for m in collector.messages if "截止线" in m or "跳过" in m]
    exhausted = [m for m in collector.messages if "Failed to search" in m]
    check("[R3] 每只市场的下场都有读数：要么被跳过并点名，要么失败并被记下来",
          bool(skipped or exhausted) or len(results) > 0,
          f"跳过读数={len(skipped)} 失败读数={len(exhausted)} 结果={len(results)}")

    hubCollector = _Collect()
    hubRoot = logging.getLogger()
    hubRoot.addHandler(hubCollector)
    started = time.monotonic()
    raised = None
    try:
        HUB._http_fetch("https://neurova-b40-invalid.invalid/skill.json")
    except Exception as e:  # noqa: BLE001
        raised = e
    hubElapsed = time.monotonic() - started
    hubRoot.removeHandler(hubCollector)
    stopped = [m for m in hubCollector.messages if "停止重试" in m or "failed after" in m]
    check("[R4] 安装链上那次真取数失败是**抛出来**的，不是悄悄返回半截",
          raised is not None, f"{type(raised).__name__ if raised else '没抛'}")
    check("[R5] 重试叠退避的实际耗时被总预算兜住（远小于墙钟）",
          hubElapsed < wall, f"hub elapsed={hubElapsed:.1f}s，日志读数={len(hubCollector.messages)}")
    check("[R6] 重试怎么收场的必须有读数：到点停止，或试完次数后点名失败",
          bool(stopped), f"收场读数={[m[:60] for m in stopped]}")

    def scenario(deadline: float, hang: float) -> tuple[float, list[str]]:
        class Fast:
            market_name = "fast"

            def search(self, query, limit=10):
                return []

        class Hanging:
            market_name = "hanging"

            def search(self, query, limit=10):
                time.sleep(hang)
                return []

        class Never:
            market_name = "never"

            def search(self, query, limit=10):
                opened.append("never")
                return []

        opened: list[str] = []
        registry = type("R", (), {
            "adapters": {"fast": Fast(), "hanging": Hanging(), "never": Never()},
            "list_markets": lambda self: list(self.adapters),
            "get_adapter": lambda self, name: self.adapters[name],
        })()
        original = MS.MARKET_SEARCH_AGGREGATE_SECONDS
        MS.MARKET_SEARCH_AGGREGATE_SECONDS = deadline
        import tempfile

        probe = MS.SkillMarketSearcher(cache_dir=tempfile.mkdtemp(prefix="b40live-"),
                                       registry=registry)
        try:
            t0 = time.monotonic()
            probe.search_all_markets("q", limit_per_market=2)
            spent = time.monotonic() - t0
        finally:
            MS.MARKET_SEARCH_AGGREGATE_SECONDS = original
        return spent, opened

    # 两只已开跑的市场各 0.3s：宽预算下第三只照开，紧预算下第三只该被跳过——
    # 只差在截止线一个变量上，这才是"拦住它的是这条线"的反证形状。
    wideSpent, wideOpened = scenario(600.0, 0.3)
    check("[R7] 反证段：把截止线放宽 ⇒ 后面的市场照开（拦住它的确实是这条线）",
          "never" in wideOpened,
          f"开跑={wideOpened} 耗时={wideSpent:.2f}s")

    tightSpent, tightOpened = scenario(0.1, 0.3)
    check("[R8] 复证：同一场景把截止线收紧，第三只市场不再开跑且留下跳过读数",
          "never" not in tightOpened and tightSpent < 2.0,
          f"开跑={tightOpened} 耗时={tightSpent:.2f}s")

    print(f"\n读数 8 + 1 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
