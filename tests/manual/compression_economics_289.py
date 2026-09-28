# -*- coding: utf-8 -*-
"""live-verify（Issue #289 · 002）：压缩经济性判据的两个形态在真链路上都成立。

形态一 · 判定为「不动作 + 原因」：开关开、无上一轮实测 ⇒ 判据挡下这一刀，
         读数里 `action=insufficient_data`，且**确实没有发生**有损折叠。
形态二 · 「安全线让位强制压」：占用撞窗口硬顶 ⇒ 判据让位、照压，
         `action=safety_line_yield`，比例 < 1.0。

两条都走真 `UnifiedContextInjector`（生产装配点）与真 `compress_envelope`，
不手工喂阈值、不碰私有字段。

跑法：`PYTHONPATH=. python tests/manual/compression_economics_289.py`
"""

from __future__ import annotations

from types import SimpleNamespace

from neurova.context.compression_economics import CompressionAction
from neurova.context.envelope import build_envelope, compress_envelope
from neurova.context.injector import UnifiedContextInjector
from neurova.context.models import TokenBudget
from neurova.context.token_estimator import isRulerCalibrated

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

isolatedDataRoot()

HISTORY = [{"role": "user", "content": "历史消息" * 400} for _ in range(6)]
OVER_BUDGET_INPUT = "问" * 2000


def _injector(**kwargs):
    return UnifiedContextInjector(
        memory_manager=SimpleNamespace(),
        token_budget=TokenBudget(max_total=1000),
        enable_cache=False,
        **kwargs,
    )


def main() -> int:
    failures = []

    print(f"[0] 尺子校准档：{isRulerCalibrated()}（判定类动作允许生效的唯一前置）")
    if not isRulerCalibrated():
        failures.append("尺子未校准")

    # ── 形态一：不动作 + 原因 ────────────────────────────────────────────
    held = _injector(compression_economics=True, window_ceiling=50000)
    r1 = held.build_context(
        system_prompt="BASE", memories=[], conversation_history=HISTORY, user_input=OVER_BUDGET_INPUT
    )
    readout1 = r1.stats["compression_economics"]
    print(
        "[1] 不动作形态：action={action} deferred={deferred} profit={profit} cost={cost} "
        "compression_ratio={ratio}".format(
            action=readout1["action"],
            deferred=readout1["deferred_reason"],
            profit=readout1["profit"],
            cost=readout1["cost"],
            ratio=r1.compression_ratio,
        )
    )
    if readout1["action"] != CompressionAction.INSUFFICIENT_DATA.value:
        failures.append(f"形态一原因不是 insufficient_data：{readout1['action']}")
    if r1.compression_ratio != 1.0:
        failures.append(f"形态一竟然发生了折叠：ratio={r1.compression_ratio}")

    # ── 形态二：安全线让位强制压 ────────────────────────────────────────
    forced = _injector(compression_economics=True, window_ceiling=1000)
    r2 = forced.build_context(
        system_prompt="BASE", memories=[], conversation_history=HISTORY, user_input=OVER_BUDGET_INPUT
    )
    readout2 = r2.stats["compression_economics"]
    print(
        "[2] 让位形态：action={action} compression_ratio={ratio} deferred={deferred}".format(
            action=readout2["action"], ratio=r2.compression_ratio, deferred=readout2["deferred_reason"]
        )
    )
    if readout2["action"] != CompressionAction.SAFETY_LINE_YIELD.value:
        failures.append(f"形态二原因不是 safety_line_yield：{readout2['action']}")
    if not r2.compression_ratio < 1.0:
        failures.append(f"形态二未强制压：ratio={r2.compression_ratio}")

    # ── 跨趟反馈：上一轮实测必须能回读 ─────────────────────────────────
    r3 = forced.build_context(
        system_prompt="BASE", memories=[], conversation_history=HISTORY, user_input=OVER_BUDGET_INPUT
    )
    prior = r3.stats["compression_economics"]["prior_ratio"]
    print(f"[3] 跨趟反馈：第二轮 prior_ratio={prior}（回读读数={forced.readCompressionFeedback()}）")
    if prior != forced.readCompressionFeedback() or prior is None:
        failures.append("跨趟反馈未接上")

    # ── 弃封出账（真信封 / 真 compress_envelope）──────────────────────
    envelope = build_envelope({"memories": "\n".join(["记忆行" + "细节" * 20] * 50)})
    report = {}
    out = compress_envelope(envelope, budget_tokens=1, report=report)
    print(f"[4] 弃封出账：envelope_after={out!r} report={report}")
    if report.get("reason") != CompressionAction.ENVELOPE_DISCARDED.value:
        failures.append(f"弃封未出账：{report}")

    # ── 开关关：判据只观测不出门（该压的照压）────────────────────────
    off = _injector(window_ceiling=50000)
    r4 = off.build_context(
        system_prompt="BASE", memories=[], conversation_history=HISTORY, user_input=OVER_BUDGET_INPUT
    )
    readout4 = r4.stats["compression_economics"]
    print(
        f"[5] 默认关：enabled={readout4['enabled']} action={readout4['action']} "
        f"compression_ratio={r4.compression_ratio}（判据本会挡下这一刀）"
    )
    if readout4["enabled"] is not False:
        failures.append("默认关未生效")
    if not r4.compression_ratio < 1.0:
        failures.append("默认关改变了现网行为")

    if failures:
        print("\nLIVE-VERIFY FAILED：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nLIVE-VERIFY PASSED / Issue #289 · 002（两形态 + 跨趟反馈 + 弃封出账 + 默认关）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
