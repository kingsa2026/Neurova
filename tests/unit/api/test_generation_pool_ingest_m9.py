# -*- coding: utf-8 -*-
"""M9（多模态追平批一）：生成完成回执经 add_context 单源咽喉写入活水池。

接线点（调查结论：生成 REST 端点本无会话上下文，故在端点成功回执/
任务收口成功处接线，会话归属经请求可选字段显式携带）：
1. /generation/image 成功 → 产物入池（metadata 带 session_id/turn/task_id）；
2. /generation/video 收口成功（/video/status 轮询 settle）→ 产物入池；
3. 无会话归属（未传 agent_id / 无已登记池）→ 诚实跳过，不写错池。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import generation as generation_ep
from neurova.context.pool_models import ContextSource
from neurova.context_pool import ContextPool
from neurova.context_pool_registry import get_registry
from neurova.llm.generators import task_ledger as ledger_mod
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.llm.generators.task_ledger import GenerationTaskLedger


@pytest.fixture()
def tmp_ledger(tmp_path, monkeypatch):
    led = GenerationTaskLedger(path=str(tmp_path / "tasks.json"))
    monkeypatch.setattr(ledger_mod, "_ledger", led)
    yield led
    monkeypatch.setattr(ledger_mod, "_ledger", None)


@pytest.fixture()
def pool():
    """登记 (tuser, agent-1) 归属的池——编排器构造池即 adopt 的同款单源入口。"""
    p = ContextPool(user_id="tuser", agent_id="agent-1", session_id=None)
    get_registry().adopt(p)
    yield p
    get_registry().reset()


@pytest.fixture()
def client(tmp_ledger, tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(generation_ep.router, prefix="/api/v1/generation")
    from neurova.api.deps import get_current_user as _gcu_deps

    app.dependency_overrides[_gcu_deps] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    monkeypatch.setattr(generation_ep, "_GENERATION_OUTPUT_DIR", str(tmp_path))
    with TestClient(app) as c:
        yield c


def _stub_image_pipeline(monkeypatch, tmp_path):
    def fake_resolve(protocol_hint, model, provider_id, api_key, base_url, default_base):
        return ProtocolCredentials(api_key="k", base_url=base_url or "https://x",
                                   model=model or "m", protocol=protocol_hint)

    async def fake_generate_image(creds, prompt, **kw):
        return {"images": ["http://cdn/a.png"], "task_id": None, "raw": {}}

    async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
        p = tmp_path / f"art_{index}.png"
        p.write_bytes(b"PNG")
        return str(p)

    from neurova.llm.generators import runtime as gen_runtime
    from neurova.llm.generators import protocols as proto_mod
    monkeypatch.setattr(gen_runtime, "resolve_generation_creds", fake_resolve)
    monkeypatch.setattr(proto_mod, "generate_image", fake_generate_image)
    monkeypatch.setattr(gen_runtime, "persist_media", fake_persist)


class TestImageGenerationIngestsPool:
    def test_image_success_writes_generation_entry(
        self, client, monkeypatch, tmp_ledger, pool, tmp_path,
    ):
        _stub_image_pipeline(monkeypatch, tmp_path)
        resp = client.post("/api/v1/generation/image", json={
            "prompt": "一只赛博朋克猫", "api_key": "k", "base_url": "https://x/v1",
            "session_id": "sess-9", "agent_id": "agent-1", "turn": 5,
        })
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["data"]["task_id"]
        entries = pool.query(source=ContextSource.GENERATION)
        assert len(entries) == 1, "生成回执必须入池（改前恒不写池）"
        md = entries[0].metadata
        assert md["task_id"] == task_id
        assert md["session_id"] == "sess-9"
        assert md["turn"] == 5
        assert md["kind"] == "image"
        assert "赛博朋克" in entries[0].content

    def test_ingested_entry_recalled_by_draw(
        self, client, monkeypatch, tmp_ledger, pool, tmp_path,
    ):
        _stub_image_pipeline(monkeypatch, tmp_path)
        resp = client.post("/api/v1/generation/image", json={
            "prompt": "一只赛博朋克猫", "api_key": "k", "base_url": "https://x/v1",
            "agent_id": "agent-1",
        })
        assert resp.status_code == 200
        hits = pool.draw(need="生成 赛博朋克 猫")
        assert any(getattr(h, "source", None) == ContextSource.GENERATION for h in hits), \
            "入池生成物必须能被 draw 语义通道召回"

    def test_without_agent_context_skips_pool(
        self, client, monkeypatch, tmp_ledger, pool, tmp_path,
    ):
        _stub_image_pipeline(monkeypatch, tmp_path)
        resp = client.post("/api/v1/generation/image", json={
            "prompt": "p", "api_key": "k", "base_url": "https://x/v1",
        })
        assert resp.status_code == 200
        # 未传 agent_id → 取不到归属池 → 不写（不把生成物写进错误的池）
        assert pool.query(source=ContextSource.GENERATION) == []


class TestVideoSettleIngestsPool:
    def test_video_settle_success_writes_pool(
        self, client, monkeypatch, tmp_ledger, pool,
    ):
        from neurova.llm.generators import protocols as proto_mod
        from neurova.llm.generators import recovery as recovery_mod
        from neurova.llm.generators.task_ledger import TaskRecord

        rec = tmp_ledger.add(TaskRecord(
            kind="video", protocol="wan", model="wan2.7-t2v",
            base_url="https://x", status="submitted", remote_task_id="r-1",
            owner_user_id="tuser", session_id="sess-9", agent_id="agent-1", turn=2,
        ))

        async def fake_poll(creds, task_id, poll_url=""):
            return {"status": "succeeded", "video_url": "https://cdn/out.mp4", "raw": {}}

        async def fake_persist(url_or_data, kind, task_id, index, out_dir=None):
            p = tmp_ledger._path.parent / f"{task_id}_0.mp4"
            p.write_bytes(b"MP4")
            return str(p)

        monkeypatch.setattr(proto_mod, "poll_video", fake_poll)
        monkeypatch.setattr(recovery_mod, "persist_media", fake_persist)

        resp = client.get(f"/api/v1/generation/video/status/{rec.task_id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "succeeded"
        entries = pool.query(source=ContextSource.GENERATION)
        assert len(entries) == 1, "视频收口成功必须入池"
        md = entries[0].metadata
        assert md["task_id"] == rec.task_id
        assert md["session_id"] == "sess-9"
        assert md["turn"] == 2
        assert md["kind"] == "video"
