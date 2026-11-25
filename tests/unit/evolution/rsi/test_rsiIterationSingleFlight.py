"""EVO-01：RSI 迭代必须单飞——并发回合不得同时驱动同一编排器的轮次。

审计证据（2026-11-25）：`post_chat_pipeline` 可并发 `to_thread(run_iteration)`，
多个回合同时进入迭代主体，竞争轮次、提案、快照与世代状态（重复迭代、状态覆盖）。

判据（红 → 绿）：
- 第一线程进入迭代主体（反馈收集阻塞点）后，第二调用**不得**进入主体，
  必须返回 `skipped=True / reason=iteration_in_progress` 的结构化读数；
- 同一次并发下编排器只完成一轮（`_iteration_count` 只加一）；
- 第一轮结束后锁释放，下一轮照常可跑。
"""

from __future__ import annotations

import threading

import pytest


def test_concurrentRunIterationIsSingleFlight(rsi_probe_factory, monkeypatch):
    probe = rsi_probe_factory(rsi_phase=0)
    orch = probe.orchestrator
    entered = threading.Event()
    release = threading.Event()
    originalCollect = orch.collect_feedback_signals

    def slowCollect():
        entered.set()
        assert release.wait(10), "测试等待释放超时（迭代主体未进入）"
        return originalCollect()

    monkeypatch.setattr(orch, "collect_feedback_signals", slowCollect)
    results = {}
    errors = []

    def runFirst():
        try:
            results["first"] = orch.run_iteration()
        except Exception as exc:  # noqa: BLE001 - 线程异常带回主线程断言
            errors.append(exc)

    worker = threading.Thread(target=runFirst, name="rsi-first")
    worker.start()
    try:
        assert entered.wait(10), "第一线程未进入迭代主体"
        second = orch.run_iteration()
    finally:
        release.set()
        worker.join(60)
    assert not errors, f"第一轮线程异常: {errors}"
    assert second.get("skipped") is True, f"并发第二轮必须被单飞拦下: {second}"
    assert second.get("reason") == "iteration_in_progress"
    assert second.get("applied_count") == 0
    assert results["first"].get("skipped") is not True, "第一轮必须真实完成"
    assert orch._iteration_count == 1, "并发下只允许一轮迭代落账"


def test_singleFlightReleasesAfterRound(rsi_probe_factory):
    probe = rsi_probe_factory(rsi_phase=0)
    orch = probe.orchestrator

    first = orch.run_iteration()
    second = orch.run_iteration()

    assert first.get("skipped") is not True
    assert second.get("skipped") is not True, "上一轮结束后锁必须释放，下一轮照常执行"
    assert orch._iteration_count == 2