# -*- coding: utf-8 -*-
"""录音 → 纪要 → Ask 判定 → 任务链（对照报告 B4-8）+ 有界背压转证据（B4-4）。

四步闭环（Linger 会议链路的本仓落法）：
1. **录音完成**：调用方（HTTP 上传/渠道收音）把音频字节交进来；
2. **秒级快速纪要**：批式转写（VoiceEngine/ASRManager 链，与渠道预检同源）
   得全文，再**一次** LLM 调用同时产出「简短纪要」与「问题/办事」判定
   （Ask 一次调用，不拆两轮）；
3. **判定**：question → 纪要即答案素材，任务面不动作；task → 带标题/描述；
4. **办事转任务**：经调用方注入的任务创建口落到任务看板（Tasks API），
   元数据带回溯源（job id / 来源=语音纪要链）。

背压（B4-4 有界背压转证据）：纪要是秒级重活（转写 + LLM），进程内处理队列
**有界**——队列满时**显式记 ``input_gap`` 证据**（审计单源留痕 + 计数进
/audio/status 读面）并向调用方如实拒绝（HTTP 429 形态由端点给），不静默丢、
不无界积压。

依赖全部由调用方注入（转写口/LLM 口/任务口），本模块不关心引擎与分层——
与 ``benchmark.suite_eval`` 的"LLM 通道由调用方注入"同一纪律。
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "RecordingMinutesPipeline",
    "getMinutesPipeline",
    "resetMinutesPipeline",
    "minutesCounters",
]

#: 处理队列上限（有界背压：满即拒 + 记 input_gap 证据，不静默丢）
QUEUE_MAX = 8

#: 送 LLM 的转写文本上限（纪要不需要全文无限长）
_TRANSCRIPT_PROMPT_MAX = 6000

#: 任务看板缺省名（无看板时自动创建；按名幂等）
DEFAULT_MINUTES_BOARD = "语音纪要"

#: 审计动作标识（input_gap 证据在审计单源里的 action）
AUDIT_INPUT_GAP_ACTION = "voice.minutes_input_gap"

#: job 状态词汇
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"

#: 判定词汇（Ask 一次调用的两出口）
KIND_QUESTION = "question"
KIND_TASK = "task"


@dataclass
class MinutesJob:
    """一条录音纪要作业的状态快照。"""

    job_id: str
    status: str = JOB_QUEUED
    filename: str = ""
    transcript: str = ""
    summary: str = ""
    kind: str = ""
    task_id: str = ""
    task_title: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    _audio: bytes = b""

    def toDict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "filename": self.filename,
            "transcript": self.transcript,
            "summary": self.summary,
            "kind": self.kind,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


#: 进程内计数（观测面）：submitted/done/failed/inputGaps
_counters: Dict[str, int] = {
    "submitted": 0,
    "done": 0,
    "failed": 0,
    "inputGaps": 0,
}
_countersLock = threading.Lock()


def _bump(name: str) -> None:
    with _countersLock:
        _counters[name] = _counters.get(name, 0) + 1


def minutesCounters() -> Dict[str, int]:
    """纪要链计数快照（/audio/status 读面消费；含 input_gap 证据读数）。"""
    with _countersLock:
        return dict(_counters)


def _recordInputGap(reason: str) -> None:
    """背压溢出证据：审计单源留痕 + 计数（诚实暴露，不静默丢）。"""
    _bump("inputGaps")
    logger.warning("录音纪要队列已满（%s），拒绝新作业并记 input_gap 证据", reason)
    try:
        from neurova.core.identity_context import get_request_user_id
        from neurova.security.audit_logger import (
            AuditEventType,
            AuditSeverity,
            log_audit,
        )

        log_audit(
            AuditEventType.SECURITY_EVENT,
            AuditSeverity.LOW,
            user_id=str(get_request_user_id() or ""),
            action=AUDIT_INPUT_GAP_ACTION,
            details={"reason": reason, "queue_max": QUEUE_MAX},
            resource_type="voice_minutes",
        )
    except Exception as exc:  # noqa: BLE001 - 审计失败不影响拒绝本身
        logger.error("input_gap 审计留痕失败：%s", exc)


class RecordingMinutesPipeline:
    """录音纪要链：有界队列 + 单 worker；依赖（转写/LLM/任务）全部注入。

    - ``transcribeFn``：``async (audio_bytes, language=...) -> {"text": ...}``
      （即 voice_ingress.getAsrTranscriber 的产物口径）；
    - ``llmFn``：``(prompt: str) -> str``（同步；agent 候选 llm_client 链，
      不可用时传 None——作业诚实失败，不伪造纪要）；
    - ``createTaskFn``：``(title, description, sourceMeta) -> dict``
      （任务看板创建口；返回含 id）。
    """

    def __init__(
        self,
        transcribeFn: Callable[..., Any],
        llmFn: Optional[Callable[[str], str]],
        createTaskFn: Optional[Callable[..., Dict[str, Any]]],
        queueMax: int = QUEUE_MAX,
    ):
        self._transcribeFn = transcribeFn
        self._llmFn = llmFn
        self._createTaskFn = createTaskFn
        self._jobs: Dict[str, MinutesJob] = {}
        self._jobsLock = threading.Lock()
        self._queue: "queue.Queue[MinutesJob]" = queue.Queue(maxsize=max(1, int(queueMax)))
        self._worker: Optional[threading.Thread] = None
        self._workerLock = threading.Lock()

    # ── 提交侧（调用方线程/事件循环）────────────────────────────────

    def submit(self, audioBytes: bytes, filename: str = "") -> Dict[str, Any]:
        """入队一条录音纪要作业；队列满时记 input_gap 证据并如实拒绝。"""
        if not audioBytes:
            return {"queued": False, "reason": "empty_audio"}
        job = MinutesJob(
            job_id=f"mins-{uuid.uuid4().hex[:12]}",
            filename=str(filename or ""),
            _audio=audioBytes,
        )
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            _recordInputGap(f"job={job.job_id}")
            return {"queued": False, "reason": "queue_full", "queue_max": QUEUE_MAX}
        with self._jobsLock:
            self._jobs[job.job_id] = job
        _bump("submitted")
        self._ensureWorker()
        return {"queued": True, "job_id": job.job_id}

    def jobStatus(self, jobId: str) -> Optional[Dict[str, Any]]:
        with self._jobsLock:
            job = self._jobs.get(jobId)
            return job.toDict() if job else None

    # ── worker（独立线程：转写与 LLM 都是秒级重活，不占调用方循环）────

    def _ensureWorker(self) -> None:
        with self._workerLock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._runWorker, name="voice-minutes-worker", daemon=True
            )
            self._worker.start()

    def _runWorker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self._process(job)
            except Exception as exc:  # noqa: BLE001 - 单作业失败不拖垮 worker
                logger.error("录音纪要作业异常 job=%s：%s", job.job_id, exc)
                self._finish(job, JOB_FAILED, error=str(exc)[:300])

    # ── 四步链（转写 → 纪要+判定 → 任务）────────────────────────────

    def _process(self, job: MinutesJob) -> None:
        self._setStatus(job, JOB_RUNNING)

        # 1) 转写：异步引擎在 worker 线程里起临时事件循环跑完
        try:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(
                    self._transcribeFn(job._audio, language="zh")
                )
            finally:
                loop.close()
        except Exception as exc:  # noqa: BLE001 - 转写失败=作业失败（诚实上报）
            self._finish(job, JOB_FAILED, error=f"transcribe_failed: {exc}"[:300])
            _bump("failed")
            return
        transcript = ""
        if isinstance(result, dict):
            transcript = (result.get("text") or "").strip()
        if not transcript:
            self._finish(job, JOB_FAILED, error="transcribe_empty")
            _bump("failed")
            return
        with self._jobsLock:
            job.transcript = transcript

        # 2)+3) Ask 一次调用：纪要 + 问题/办事判定（LLM 不可用=诚实失败）
        verdict = self._askLLM(job, transcript)
        if verdict is None:
            return  # _askLLM 内已置失败态
        summary = str(verdict.get("summary") or "").strip()
        kind = str(verdict.get("kind") or "").strip().lower()
        with self._jobsLock:
            job.summary = summary
            job.kind = kind

        # 4) 办事转任务（question 不落任务面）
        if kind == KIND_TASK:
            title = str(verdict.get("task_title") or summary or "语音纪要任务").strip()[:200]
            description = str(verdict.get("task_description") or summary or "").strip()[:2000]
            if self._createTaskFn is not None:
                try:
                    task = self._createTaskFn(
                        title,
                        description,
                        {"source": "voice_minutes", "job_id": job.job_id,
                         "board_name": DEFAULT_MINUTES_BOARD},
                    )
                    with self._jobsLock:
                        job.task_id = str((task or {}).get("id") or "")
                        job.task_title = title
                except Exception as exc:  # noqa: BLE001 - 任务落点失败如实标注
                    logger.error("纪要转任务失败 job=%s：%s", job.job_id, exc)
                    self._finish(job, JOB_FAILED, error=f"task_create_failed: {exc}"[:300])
                    _bump("failed")
                    return

        self._finish(job, JOB_DONE)
        _bump("done")
        logger.info(
            "录音纪要完成 job=%s kind=%s task=%s len=%s",
            job.job_id, job.kind, job.task_id, len(transcript),
        )

    def _askLLM(self, job: MinutesJob, transcript: str) -> Optional[Dict[str, Any]]:
        """Ask 一次调用：同一轮产出纪要与判定；不可用/解析失败=作业失败。"""
        if self._llmFn is None:
            self._finish(job, JOB_FAILED, error="llm_unavailable")
            _bump("failed")
            return None
        prompt = (
            "你是会议/录音纪要助手。对下面的录音转写文本，一次完成两件事：\n"
            "1. 生成不超过 120 字的简短纪要（summary）；\n"
            "2. 判定这段话的性质：只是在问问题/要信息（kind=\"question\"），"
            "还是需要实际去做一件事（kind=\"task\"）。\n"
            "若判定为 task，再给 task_title（20 字内）与 task_description（一段话）。\n"
            '只输出一个 JSON 对象：{"summary":"...","kind":"question|task",'
            '"task_title":"...","task_description":"..."}。\n\n'
            f"录音转写文本：\n{transcript[:_TRANSCRIPT_PROMPT_MAX]}"
        )
        try:
            raw = self._llmFn(prompt)
        except Exception as exc:  # noqa: BLE001 - LLM 调用失败=作业失败
            self._finish(job, JOB_FAILED, error=f"llm_call_failed: {exc}"[:300])
            _bump("failed")
            return None
        content = str(raw or "").strip()
        if content.startswith("[LLM Error]"):
            self._finish(job, JOB_FAILED, error=content[:300])
            _bump("failed")
            return None
        verdict = _extractJson(content)
        if not isinstance(verdict, dict) or not str(verdict.get("kind") or "").strip():
            self._finish(job, JOB_FAILED, error="llm_verdict_unparsable")
            _bump("failed")
            return None
        return verdict

    # ── 状态写入 ────────────────────────────────────────────────────

    def _finish(self, job: MinutesJob, status: str, **fields: Any) -> None:
        with self._jobsLock:
            job.status = status
            for key, value in fields.items():
                setattr(job, key, value)
            job.finished_at = time.time()

    def _setStatus(self, job: MinutesJob, status: str) -> None:
        with self._jobsLock:
            job.status = status


def _extractJson(text: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出里取第一个 JSON 对象（容忍 ```json 围栏与前后废话）。"""
    t = str(text or "").strip()
    if not t:
        return None
    start = t.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except (ValueError, TypeError):
                    return None
    return None


# ── 进程级单例（DCL + RLock，仓规）────────────────────────────────────

_pipeline_instance: Optional[RecordingMinutesPipeline] = None
_pipeline_lock = threading.RLock()


def _buildPipeline() -> RecordingMinutesPipeline:
    """装配：转写口=voice_ingress 单源；LLM 口=agent 候选链；任务口=Tasks API。"""
    from neurova.channels.voice_ingress import getAsrTranscriber

    transcribeFn = getAsrTranscriber()

    llmFn: Optional[Callable[[str], str]] = None
    try:
        from neurova.api.endpoints.benchmark import _rag_llm_fn

        llmFn = _rag_llm_fn("")  # 空串 → 内部回落 defaultAgentId
    except Exception as exc:  # noqa: BLE001 - LLM 口缺席时作业诚实失败
        logger.warning("纪要链 LLM 通道装配失败（作业将报 llm_unavailable）：%s", exc)

    from neurova.api.endpoints import tasks_api

    createTaskFn = tasks_api.createTaskFromVoiceMinutes
    return RecordingMinutesPipeline(transcribeFn, llmFn, createTaskFn)


def getMinutesPipeline() -> RecordingMinutesPipeline:
    global _pipeline_instance
    if _pipeline_instance is not None:
        return _pipeline_instance
    with _pipeline_lock:
        if _pipeline_instance is None:
            _pipeline_instance = _buildPipeline()
        return _pipeline_instance


def resetMinutesPipeline() -> None:
    """重置单例（测试专用）。"""
    global _pipeline_instance
    with _pipeline_lock:
        _pipeline_instance = None
