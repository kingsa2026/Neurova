# -*- coding: utf-8 -*-
"""进程治理单源：超时矩阵、进程组回收、重试总预算、失败诚实分类。

C3 卡（参照系 ac 追平计划批三）四件套：
- TIMEOUT_MATRIX：握手/请求/取消/退出宽限的超时单源（acp_client 从此取值）；
- terminateProcessGroup：进程组/树级回收，治理子进程孵化孙进程的孤儿问题；
- RetryBudget：重试总预算（超预算即 fail，不只数次数）；
- classifyFailure：失败原因诚实分类（OOM 明确标注资源耗尽，不掩盖）。
"""
import os
import re
import subprocess
import sys
from typing import Callable, Dict, Optional

# ---------- 超时矩阵（单源） ----------

#: ACP 生命周期超时单源。取值依据：
#: - handshake=30.0：initialize 握手是首轮 request，与 request 同源；正常握手
#:   远小于该值，宽裕值只为容纳慢启动 CLI 的首次冷启动，不兼容版本会快速失败。
#: - request=30.0：沿用 acp_client 历史默认（_DEFAULT_REQUEST_TIMEOUT 原值）。
#: - cancel=5.0：取消是协作语义，与退出宽限同级短等待，超时即按失败收口。
#: - terminate_grace=5.0：terminate 先宽限后强杀的宽限期，沿用历史默认
#:   （_TERMINATE_WAIT_S 原值）。
TIMEOUT_MATRIX: Dict[str, float] = {
    "handshake": 30.0,
    "request": 30.0,
    "cancel": 5.0,
    "terminate_grace": 5.0,
}

# ---------- 进程组回收 ----------

#: kill_impl(pid, force)：force=True 强杀（Windows taskkill /T /F、
#: POSIX killpg SIGKILL）；force=False 温和信号（POSIX killpg SIGTERM，
#: Windows 无组级温和信号、不会以 force=False 调用）。
GroupKill = Callable[[int, bool], None]

_PLATFORM_MODE = "taskkill" if sys.platform == "win32" else "killpg"


def _defaultGroupKill(pid: int, force: bool) -> None:
    """平台默认组级击杀原语：Windows taskkill 树杀；POSIX killpg 信号。"""
    if sys.platform == "win32":
        # /T 连树一起杀（覆盖子进程孵化的孙进程），/F 强制终止。
        # 输出为系统本地编码（中文系统 GBK），按字节收再容错解码，
        # 判定只看 returncode，不因输出解码差异误判失败。
        completed = subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        if completed.returncode != 0:
            detail = (
                (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
            ).strip()
            raise OSError(f"taskkill /T /F 失败 (pid={pid}): {detail}")
        return
    import signal

    from neurova.security.process_reaper import signalGroup

    sig = signal.SIGKILL if force else signal.SIGTERM
    signalGroup(os.getpgid(pid), sig)


def _fallbackKill(proc) -> None:
    """兜底单进程强杀（fail-closed：进程必须死）。

    进程已死的竞态（ProcessLookupError）视为目标达成；kill 后短等收尸，
    收尸超时不算失败（退出码由调用方观测点收口）。其余异常诚实上抛。
    """
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        pass


def terminateProcessGroup(
    proc,
    grace_s: float,
    *,
    kill_impl: Optional[GroupKill] = None,
) -> Dict[str, object]:
    """进程组/树级回收：先宽限后强杀，任何路径失败兜底 proc.kill()。

    Windows 走 ``taskkill /T /F``（按父子树杀，孙进程一并回收）；POSIX 走
    ``killpg(SIGTERM)`` + grace 等待 + ``killpg(SIGKILL)``。注意：POSIX 下
    若子进程与调用方同进程组，killpg 会误伤自身——生产侧 spawn 时必须
    ``start_new_session=True`` 让子进程自立门户。

    返回 ``{"mode": "taskkill|killpg|fallback", "graceful": bool}``：
    graceful=True 表示未经强制击杀即退出（含进来时已退出的空操作）。
    """
    killer = kill_impl or _defaultGroupKill
    grace = max(0.0, float(grace_s))
    try:
        if proc.poll() is not None:
            return {"mode": _PLATFORM_MODE, "graceful": True}
        if sys.platform == "win32":
            # Windows：taskkill /T /F 直接树强杀（无组级温和信号可投）
            killer(proc.pid, True)
            strong_mode = "taskkill"
        else:
            # POSIX：先 SIGTERM 宽限，超时升级 SIGKILL
            killer(proc.pid, False)
            try:
                proc.wait(timeout=grace)
                return {"mode": "killpg", "graceful": True}
            except subprocess.TimeoutExpired:
                pass
            killer(proc.pid, True)
            strong_mode = "killpg"
    except Exception:
        # 组级路径任何失败：兜底单进程强杀，进程必须死
        _fallbackKill(proc)
        return {"mode": "fallback", "graceful": False}
    # 强杀后收尸确认；仍未退出再兜底一刀（仍失败则异常上抛，诚实暴露）
    try:
        proc.wait(timeout=grace if sys.platform == "win32" else 2.0)
    except subprocess.TimeoutExpired:
        _fallbackKill(proc)
        return {"mode": "fallback", "graceful": False}
    return {"mode": strong_mode, "graceful": False}


# ---------- 重试总预算 ----------


class RetryBudget:
    """重试总预算：次数与总耗时双闸，任一耗尽即 fail（不只数次数）。

    典型用法：每次尝试前问 :meth:`canAttempt`；失败后 :meth:`recordFailure`
    记账本次耗时。成功路径不记账（次数与预算都不动）。
    """

    def __init__(self, max_attempts: int, total_budget_s: float) -> None:
        self._max_attempts = max(1, int(max_attempts))
        self._total_budget_s = max(0.0, float(total_budget_s))
        self._attempts_used = 0
        self._spent_s = 0.0
        self._exhausted_reason: Optional[str] = None

    def canAttempt(self) -> bool:
        """还能否发起下一次尝试；耗尽时记下诚实原因。"""
        if self._attempts_used >= self._max_attempts:
            self._exhausted_reason = (
                f"重试次数用尽（{self._attempts_used}/{self._max_attempts}）"
            )
            return False
        if self._spent_s >= self._total_budget_s:
            self._exhausted_reason = (
                f"重试总预算耗尽（已耗 {self._spent_s:.3f}s / 预算 "
                f"{self._total_budget_s:.3f}s，次数仅用 "
                f"{self._attempts_used}/{self._max_attempts}）"
            )
            return False
        return True

    def recordFailure(self, cost_s: float) -> None:
        """记一次失败尝试及其耗时（成功路径不调用本方法）。"""
        self._attempts_used += 1
        self._spent_s += max(0.0, float(cost_s))

    @property
    def attemptsUsed(self) -> int:
        return self._attempts_used

    @property
    def remainingBudgetS(self) -> float:
        return max(0.0, self._total_budget_s - self._spent_s)

    def exhaustedReason(self) -> Optional[str]:
        """最近一次判定耗尽的原因；未耗尽为 None。"""
        return self._exhausted_reason


# ---------- 失败诚实分类 ----------

#: OOM 识别模式：英文按词边界匹配（防 room/doom 误伤），中文直接子串。
_OOM_RE = re.compile(
    r"out of memory|\boom\b|cannot allocate|allocation fail|std::bad_alloc"
    r"|enomem|memoryerror|内存不足|内存耗尽|无法分配内存",
    re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(r"timeout|timed out|超时", re.IGNORECASE)
_CRASH_RE = re.compile(
    r"exited \(code=|exit code|crashed|segfault|segmentation fault"
    r"|aborted|core dumped|崩溃",
    re.IGNORECASE,
)


#: honest_reason 内嵌原始证据的截断上限（分类匹配用全文，证据只留头部）
_EVIDENCE_LIMIT = 500


def classifyFailure(text: str) -> Dict[str, str]:
    """失败原因诚实分类：OOM 类明确标注资源耗尽，不掩盖原始证据。

    返回 ``{"kind": "oom|timeout|crash|unknown", "honest_reason": str}``；
    honest_reason 始终保留原始证据（unknown 时即原文不加工，其余截断留头）。
    """
    raw = str(text or "")
    if _OOM_RE.search(raw):
        return {
            "kind": "oom",
            "honest_reason": (
                f"外部代理内存资源耗尽（OOM），失败按资源耗尽如实标注；"
                f"原始证据: {raw[:_EVIDENCE_LIMIT]}"
            ),
        }
    if _TIMEOUT_RE.search(raw):
        return {
            "kind": "timeout",
            "honest_reason": f"外部代理响应超时；原始证据: {raw[:_EVIDENCE_LIMIT]}",
        }
    if _CRASH_RE.search(raw):
        return {
            "kind": "crash",
            "honest_reason": f"外部代理进程崩溃退出；原始证据: {raw[:_EVIDENCE_LIMIT]}",
        }
    return {"kind": "unknown", "honest_reason": raw}
