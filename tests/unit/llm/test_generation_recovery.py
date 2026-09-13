# -*- coding: utf-8 -*-
"""批次2：生成任务收口轮询 + 重启恢复 + /tasks 历史数据源契约。

锁定：
1. settle_video_record 与端点/恢复循环共用同一实现（成功下载本地化、失败落错误、
   running 保持）；
2. recovery_tick 扫账本未决任务逐条收口（单条异常不中断整轮）；
3. GET /generation/tasks 返回 url 可访问产物 + kind 过滤 + source 字段。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.llm.generators import recovery as rec_mod
from neurova.llm.generators import runtime as gen_runtime
from neurova.llm.generators.task_ledger import (
    GenerationTaskLedger, TaskRecord,
)


@pytest.fixture()
def ledger(tmp_path):
    led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    yield led


def _mk_video(led):
    return led.add(TaskRecord(
        kind="video", provider_id="p1", protocol="wan", model="wan3.0-t2v",
        base_url="https://dashscope/api/v1", status="submitted",
        remote_task_id="rt-1", poll_url="https://x/tasks/rt-1", prompt="p",
        owner_user_id="u1",
    ))


class TestSettleVideoRecord:
    def test_succeeded_persists_local_and_ledger(self, ledger, tmp_path, monkeypatch):
        rec = _mk_video(ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "http://cdn/v.mp4", "raw": {}}

        async def fake_persist(url, kind, task_id, index, out_dir=None):
            p = tmp_path / f"{task_id}_{index}.mp4"
            p.write_bytes(b"MP4")
            return str(p)

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fake_poll)
        monkeypatch.setattr(rec_mod, "persist_media", fake_persist)
        monkeypatch.setattr(rec_mod, "resolve_generation_creds",
                            lambda *a, **k: gen_runtime.ProtocolCredentials(
                                api_key="k", base_url="b", model="m", protocol="p"))

        out = __import__("asyncio").run(rec_mod.settle_video_record(rec, ledger=ledger))
        assert out["status"] == "succeeded"
        assert out["url"].startswith("/api/v1/generation/files/")
        fresh = ledger.get(rec.task_id)
        assert fresh.status == "succeeded" and fresh.local_path

    def test_running_keeps_unfinished(self, ledger, monkeypatch):
        rec = _mk_video(ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "running", "raw": {}}

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fake_poll)
        out = __import__("asyncio").run(rec_mod.settle_video_record(rec, ledger=ledger))
        assert out["status"] == "running"
        assert ledger.get(rec.task_id).status == "running"
        assert rec.task_id in [r.task_id for r in ledger.unfinished()]

    def test_failed_records_error_verbatim(self, ledger, monkeypatch):
        rec = _mk_video(ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "failed", "error": "内容审核不通过", "raw": {}}

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fake_poll)
        out = __import__("asyncio").run(rec_mod.settle_video_record(rec, ledger=ledger))
        assert out["status"] == "failed"
        assert "审核" in ledger.get(rec.task_id).error
        assert ledger.unfinished() == []

    def test_poll_exception_becomes_failed(self, ledger, monkeypatch):
        rec = _mk_video(ledger)

        async def boom(creds, task_id, poll_url=""):
            raise RuntimeError("网络中断")

        monkeypatch.setattr(rec_mod.protocols, "poll_video", boom)
        out = __import__("asyncio").run(rec_mod.settle_video_record(rec, ledger=ledger))
        assert out["status"] == "failed"
        assert "网络中断" in ledger.get(rec.task_id).error


class TestRecoveryTick:
    def test_tick_settles_unfinished_and_survives_errors(self, ledger, tmp_path, monkeypatch):
        r1 = _mk_video(ledger)
        _mk_video(ledger)

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "running", "raw": {}}

        monkeypatch.setattr(rec_mod.protocols, "poll_video", fake_poll)
        n = __import__("asyncio").run(rec_mod.recovery_tick(ledger=ledger))
        assert n == 2

        # 单条抛异常不中断整轮
        async def boom(creds, task_id, poll_url=""):
            raise RuntimeError("x")

        monkeypatch.setattr(rec_mod.protocols, "poll_video", boom)
        n2 = __import__("asyncio").run(rec_mod.recovery_tick(ledger=ledger))
        assert n2 == 2  # 两条都被尝试处理
        # 轮询异常被诚实收口为 failed（错误原文入账本），不静默滞留、不炸循环
        assert all(r.status == "failed" and r.error for r in ledger.list())
        assert ledger.unfinished() == []

    def test_finished_records_not_picked(self, ledger, monkeypatch):
        rec = _mk_video(ledger)
        ledger.update(rec.task_id, status="succeeded", local_path="/x/y.mp4")
        called = []

        async def spy(creds, task_id, poll_url=""):
            called.append(task_id)
            return {"status": "running"}

        monkeypatch.setattr(rec_mod.protocols, "poll_video", spy)
        __import__("asyncio").run(rec_mod.recovery_tick(ledger=ledger))
        assert called == []


class TestTasksEndpointShape:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        from neurova.api.endpoints import generation as gen_ep
        from neurova.api.deps import get_current_user as _gcu

        app = FastAPI()
        app.include_router(gen_ep.router, prefix="/api/v1/generation")
        app.dependency_overrides[_gcu] = lambda: {
            "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
        }
        led = GenerationTaskLedger(path=str(tmp_path / "t.json"))
        monkeypatch.setattr("neurova.llm.generators.task_ledger._ledger", led)
        yield TestClient(app)
        monkeypatch.setattr("neurova.llm.generators.task_ledger._ledger", None)

    def test_tasks_url_and_kind_filter(self, client, tmp_path):
        from neurova.llm.generators.task_ledger import get_generation_task_ledger

        art = tmp_path / "img_0.png"
        art.write_bytes(b"P")
        get_generation_task_ledger().add(TaskRecord(
            kind="image", status="succeeded", local_path=str(art),
            prompt="猫", owner_user_id="tuser", source="rest",
        ))
        get_generation_task_ledger().add(TaskRecord(
            kind="audio", status="succeeded", local_path=str(art),
            prompt="hi", owner_user_id="tuser", source="channel",
        ))

        resp = client.get("/api/v1/generation/tasks")
        assert resp.status_code == 200
        tasks = resp.json()["data"]["tasks"]
        assert len(tasks) == 2
        img = next(t for t in tasks if t["kind"] == "image")
        assert img["url"] == f"/api/v1/generation/files/{art.name}"
        assert img["source"] == "rest"

        resp2 = client.get("/api/v1/generation/tasks", params={"kind": "audio"})
        tasks2 = resp2.json()["data"]["tasks"]
        assert [t["kind"] for t in tasks2] == ["audio"]
        assert tasks2[0]["source"] == "channel"
