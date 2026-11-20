# -*- coding: utf-8 -*-
"""录音→纪要→Ask→任务链（B4-8）+ 有界背压转证据（B4-4）。

判据：
- 全链：转写→一次 LLM 产出纪要+判定→办事落任务（注入的任务口被调）；
- 问题类不落任务；LLM 不可用/转写空=作业诚实失败（不伪造纪要）；
- 队列有界：满时拒绝并记 input_gap 证据（计数可见），不静默丢。
"""
import asyncio
import time

import pytest

from neurova.asr import minutes as mins


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    """干净 pipeline（真单例装配会被 env 影响——这里直构，注入假依赖）。"""
    monkeypatch.setattr(mins, "_pipeline_instance", None)
    yield None
    monkeypatch.setattr(mins, "_pipeline_instance", None)


def _make(transcript="好的，明天上午十点开会讨论季度目标", llmJson=None, llmError=False):
    async def transcribeFn(audio, language="zh"):
        return {"text": transcript}

    def llmFn(prompt):
        if llmError:
            raise RuntimeError("llm down")
        if llmJson is None:
            raise RuntimeError("no llm configured")
        return llmJson

    created = []

    def createTaskFn(title, description, sourceMeta):
        created.append({"title": title, "description": description,
                        "source": dict(sourceMeta or {})})
        return {"id": "task-1", "title": title}

    return mins.RecordingMinutesPipeline(transcribeFn, llmFn, createTaskFn), created


def _waitJob(pipe, jobId, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = pipe.jobStatus(jobId)
        if job and job["status"] in (mins.JOB_DONE, mins.JOB_FAILED):
            return job
        time.sleep(0.02)
    raise AssertionError("作业超时未收敛")


class TestMinutesChain:
    def test_task_kind_creates_task(self, pipeline):
        pipe, created = _make(llmJson='{"summary":"明天十点开会","kind":"task",'
                                      '"task_title":"组织季度会议","task_description":"讨论季度目标"}')
        r = pipe.submit(b"\x00\x00" * 1600, filename="rec.wav")
        assert r["queued"] is True
        job = _waitJob(pipe, r["job_id"])
        assert job["status"] == mins.JOB_DONE
        assert job["kind"] == mins.KIND_TASK
        assert job["task_id"] == "task-1" and job["task_title"] == "组织季度会议"
        assert created and created[0]["source"]["source"] == "voice_minutes"
        assert created[0]["source"]["job_id"] == r["job_id"]

    def test_question_kind_skips_task(self, pipeline):
        pipe, created = _make(llmJson='{"summary":"问了天气","kind":"question"}')
        r = pipe.submit(b"\x00\x00" * 1600)
        job = _waitJob(pipe, r["job_id"])
        assert job["status"] == mins.JOB_DONE and job["kind"] == mins.KIND_QUESTION
        assert job["task_id"] == "" and created == []

    def test_llm_unavailable_fails_honestly(self, pipeline):
        pipe, _ = _make()  # llmFn 直接抛"no llm configured"
        r = pipe.submit(b"\x00\x00" * 1600)
        job = _waitJob(pipe, r["job_id"])
        assert job["status"] == mins.JOB_FAILED
        assert "llm" in job["error"]

    def test_llm_error_string_fails(self, pipeline):
        pipe, _ = _make(llmJson="[LLM Error] quota")
        r = pipe.submit(b"\x00\x00" * 1600)
        job = _waitJob(pipe, r["job_id"])
        assert job["status"] == mins.JOB_FAILED and "LLM Error" in job["error"]

    def test_empty_transcribe_fails(self, pipeline):
        pipe, _ = _make(transcript="  ")
        r = pipe.submit(b"\x00\x00" * 1600)
        job = _waitJob(pipe, r["job_id"])
        assert job["status"] == mins.JOB_FAILED and job["error"] == "transcribe_empty"

    def test_empty_audio_rejected(self, pipeline):
        pipe, _ = _make()
        assert pipe.submit(b"")["queued"] is False


class TestBoundedBackpressure:
    def test_queue_full_rejects_with_input_gap_evidence(self, pipeline):
        """队列满：submit 如实拒绝 + input_gap 计数可见（不静默丢）。"""
        before = mins.minutesCounters()["inputGaps"]

        async def slowTranscribe(audio, language="zh"):
            await asyncio.sleep(0.3)
            return {"text": "慢转写"}

        pipe = mins.RecordingMinutesPipeline(
            slowTranscribe, lambda p: '{"summary":"s","kind":"question"}', None, queueMax=1
        )
        # 第一条占住队列与 worker（慢转写 0.3s）
        r1 = pipe.submit(b"\x00\x00" * 1600)
        assert r1["queued"] is True
        # 队列容量 1：第二条占队尾，第三条必撞满
        pipe.submit(b"\x00\x00" * 1600)
        r3 = pipe.submit(b"\x00\x00" * 1600)
        assert r3["queued"] is False and r3["reason"] == "queue_full"
        after = mins.minutesCounters()["inputGaps"]
        assert after == before + 1, "溢出必须留下 input_gap 证据计数"
        # 等慢作业收尾，避免守护线程跨用例残留
        _waitJob(pipe, r1["job_id"], timeout=5.0)

    def test_extract_json_tolerates_fence(self):
        assert mins._extractJson('```json\n{"kind":"task"}\n```') == {"kind": "task"}
        assert mins._extractJson("前置说明 {\"kind\":\"question\"} 后缀") == {"kind": "question"}
        assert mins._extractJson("不是 JSON") is None
