# -*- coding: utf-8 -*-
"""CORE-09：Webhook 有效签名的重放必须被原子去重，不得重复触发工作流。

根因：`verify_request()` 只做 HMAC + 时间戳时效（300s 窗口），窗口内同一份
已签名请求可被无限重放，每次都会派发一次工作流。修法：在验签/限流之后、
派发之前，用「签名覆盖物」（trigger_id + 规范化时间戳 + payload）派生重放键，
落 SQLite 原子领取（INSERT OR IGNORE）；重放显式 409 REPLAY_DETECTED。
派发抛异常时释放领取，允许发送方对失败投递做合法重试。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from neurova.core.trigger_rate_limiter import TriggerRateLimiter
from neurova.core.webhook_security import (
    compute_signature,
    compute_signed_payload_signature,
)


@pytest.fixture()
def replayDb(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield tmp_path / "data" / "webhook_replay.db"


def _trigger(secret_encrypted: str | None = "enc") -> SimpleNamespace:
    return SimpleNamespace(
        id="trg_replay",
        workflow_id="wf_replay",
        enabled=True,
        type=SimpleNamespace(value="webhook"),
        secret_encrypted=secret_encrypted,
        rate_limit_per_minute=None,
    )


def _deps(run_calls: list, workflow=SimpleNamespace(id="wf_replay")):
    limiter = TriggerRateLimiter(None)

    async def run_workflow(wf, inputs):
        run_calls.append(inputs)
        if getattr(run_workflow, "fail_next", False):
            run_workflow.fail_next = False
            raise RuntimeError("dispatch boom")
        return SimpleNamespace(id=f"exec_{len(run_calls)}", status=SimpleNamespace(value="completed"))

    return {
        "load_trigger": lambda _tid: _trigger(),
        "load_published_workflow": lambda _ref: workflow,
        "decrypt_secret": lambda _enc: "raw-secret",
        "run_workflow": run_workflow,
        "rate_limiter_for": lambda _tr: limiter,
    }


def _signed(payload: bytes, ts: int | None = None):
    stamp = str(int(time.time()) if ts is None else ts)
    return stamp, compute_signed_payload_signature(stamp, payload, "raw-secret")


@pytest.mark.asyncio
async def testLegacySignatureWithoutTimestampIsRejected(replayDb):
    from neurova.collaboration.neurflow.webhook_ingress import (
        IngressRejected,
        handle_webhook_ingress,
    )

    calls: list = []
    deps = _deps(calls)
    payload = b'{"payload":{"legacy":true}}'
    legacySig = compute_signature(payload, "raw-secret")

    with pytest.raises(IngressRejected) as exc:
        await handle_webhook_ingress("trg_replay", payload, legacySig, deps=deps)
    assert exc.value.status_code == 401
    assert exc.value.reason == "INVALID_SIGNATURE"
    assert calls == [], "旧签名不得绕过时间戳与重放守卫再次派发"


@pytest.mark.asyncio
async def testDuplicateSignedDeliveryTriggersOnce(replayDb):
    from neurova.collaboration.neurflow.webhook_ingress import (
        IngressRejected,
        handle_webhook_ingress,
    )

    calls: list = []
    deps = _deps(calls)
    payload = b'{"payload":{"order":42}}'
    ts, sig = _signed(payload)

    first = await handle_webhook_ingress("trg_replay", payload, sig, deps=deps, timestamp_header=ts)
    assert first["code"] == 0
    assert len(calls) == 1

    with pytest.raises(IngressRejected) as exc:
        await handle_webhook_ingress("trg_replay", payload, sig, deps=deps, timestamp_header=ts)
    assert exc.value.status_code == 409
    assert exc.value.reason == "REPLAY_DETECTED"
    assert len(calls) == 1, "重放请求又派发了一次工作流"


@pytest.mark.asyncio
async def testDistinctTimestampIsNewDeliveryNotReplay(replayDb):
    """同一 payload 以新时间戳重新签名＝新投递，不得误判为重放。"""
    from neurova.collaboration.neurflow.webhook_ingress import handle_webhook_ingress

    calls: list = []
    deps = _deps(calls)
    payload = b'{"payload":{"n":1}}'
    now = int(time.time())
    ts1, sig1 = _signed(payload, now - 10)
    ts2, sig2 = _signed(payload, now)

    await handle_webhook_ingress("trg_replay", payload, sig1, deps=deps, timestamp_header=ts1)
    await handle_webhook_ingress("trg_replay", payload, sig2, deps=deps, timestamp_header=ts2)
    assert len(calls) == 2


@pytest.mark.asyncio
async def testFailedDispatchReleasesClaimForLegitimateRetry(replayDb):
    """派发失败不吞领取：同一签名重试必须能再执行（发送方重试语义）。"""
    from neurova.collaboration.neurflow.webhook_ingress import handle_webhook_ingress

    calls: list = []
    deps = _deps(calls)
    deps["run_workflow"].fail_next = True
    payload = b'{"payload":{"retry":true}}'
    ts, sig = _signed(payload)

    with pytest.raises(RuntimeError):
        await handle_webhook_ingress("trg_replay", payload, sig, deps=deps, timestamp_header=ts)

    result = await handle_webhook_ingress("trg_replay", payload, sig, deps=deps, timestamp_header=ts)
    assert result["code"] == 0
    assert len(calls) == 2


def testConcurrentClaimsOnlyOneWins(replayDb):
    """真 SQLite + 真线程并发：同一重放键的原子领取只能有一个成功。"""
    import threading

    from neurova.core.webhook_replay import claimReplayKey

    barrier = threading.Barrier(8)
    results: list = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        ok = claimReplayKey("trg_replay", "f" * 64, now_s=time.time())
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sum(1 for ok in results if ok) == 1, f"并发领取结果：{results}"