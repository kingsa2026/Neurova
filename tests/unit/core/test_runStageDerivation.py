# -*- coding: utf-8 -*-
"""运行阶段由事实反推（D-2 / N-2）。

立项理由（本仓可核实）：`agent_runs.status` 是**被写出来的字段**，读面直接投它；
写完与事实相反时读面照旧相信它。§6-421 活体抓到过同形故障：任务仍在跑，run 被
扫成 `failed/process_died`。本批把「是否还在跑／是否等人」做成纯函数，字段只留
写者意图；读面用同一函数，事实与字段打架时以事实为准。

事实来源只有两列：`heartbeat_at` 与 `lease_expires_at`（WAL 里既有、写侧每轮都写）。
判据分两支：
- 字段说 running 但租约已过期 ⇒ `stalled`（执行体不再心跳）；
- 字段说 failed/process_died 但**心跳晚于 finished_at** ⇒ `running`
  （终态落下之后仍有执行体在续租，终态是误判）。
- 边界裁定（2026-11-03 批 E）：心跳==finished_at、租约==now 都算**未漂移**——
  反推只咬严格晚于/严格早于，相等侧没有"终态之后仍在续租／租约已失效"的证据。
"""
from __future__ import annotations

from neurova.core.agent_run_store import deriveRunStage


def _row(status, lease=0.0, heartbeat=0.0, finished=0.0, error_type=""):
    return {
        "status": status,
        "lease_expires_at": lease,
        "heartbeat_at": heartbeat,
        "finished_at": finished,
        "error_type": error_type,
    }


def test_terminalStatusesMapOneToOne():
    assert deriveRunStage(_row("completed"), now=1000) == "done"
    assert deriveRunStage(_row("failed"), now=1000) == "failed"
    assert deriveRunStage(_row("cancelled"), now=1000) == "cancelled"


def test_parkedMeansWaitingForHuman():
    assert deriveRunStage(_row("parked"), now=1000) == "waiting_human"


def test_liveLeaseMeansRunning():
    assert deriveRunStage(_row("running", lease=1100, heartbeat=990), now=1000) == "running"


def test_expiredLeaseContradictsRunningStatus():
    """字段说 running，但事实（租约过期）说执行体已不在——读面取事实。"""
    assert deriveRunStage(_row("running", lease=900, heartbeat=880), now=1000) == "stalled"


def test_terminalClaimContradictedByLaterHeartbeat():
    """§6-421 同形：run 被扫成 failed/process_died，但心跳晚于终态 ⇒ 仍在跑。"""
    row = _row("failed", lease=1100, heartbeat=1005, finished=1000,
               error_type="process_died")
    assert deriveRunStage(row, now=1010) == "running"


def test_terminalClaimWithoutLaterHeartbeatStaysFailed():
    row = _row("failed", lease=990, heartbeat=970, finished=1000,
               error_type="process_died")
    assert deriveRunStage(row, now=1010) == "failed"


def test_realFailureWithFreshHeartbeatIsNotResurrected():
    """只有 `process_died` 这条误判路径才反推；真错误（chat_error 等）不翻案。"""
    row = _row("failed", lease=1100, heartbeat=1005, finished=1000,
               error_type="chat_error")
    assert deriveRunStage(row, now=1010) == "failed"


def test_unknownStatusDoesNotInventAWord():
    assert deriveRunStage(_row("weird"), now=1000) == "unknown"


def test_queuedStatusProjectsQueued():
    """queued 是存储状态之一，读面必须原样投出——丢了这一格，排队中的轮次会被
    读面谎报成 unknown，面板阶段列从此缺一类。"""
    assert deriveRunStage(_row("queued"), now=1000) == "queued"


def test_heartbeatEqualToFinishedAtIsNotDrift():
    """边界裁定：心跳==finished_at 是"终态与心跳同刻落下"，没有"终态之后仍在续租"
    的证据 ⇒ 按未漂移处理，终态保持。反推只咬严格晚于（store 里是 `>`）。"""
    row = _row("failed", lease=1100, heartbeat=1000, finished=1000,
               error_type="process_died")
    assert deriveRunStage(row, now=1010) == "failed"


def test_leaseExactlyAtNowIsStillAlive():
    """边界裁定：租约到点那一刻仍算活着——"过期"必须是严格早于 now（store 里是
    `<`），否则租约临界点上的正常轮次会被读面判成 stalled。"""
    assert deriveRunStage(_row("running", lease=1000, heartbeat=990), now=1000) == "running"


def test_consoleRunsReadFaceProjectsTheDerivedStage():
    """读面必须投 stage 且取数走同一函数——否则前端只能继续信写出来的 status。"""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3] / "neurova/api/endpoints/console.py").read_text(
        encoding="utf-8")
    start = source.index('@router.get("/chat/runs")')
    rest = source[start:]
    end = rest.find("@router.", 1)
    body = rest[:end] if end != -1 else rest
    assert '"stage"' in body, "runs 读面没有投 stage"
    assert "deriveRunStage" in body, "runs 读面的 stage 不是由 deriveRunStage 算的"
