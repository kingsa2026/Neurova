"""trace 端点族接真实记录器 + TrajectoryRecorder 根因回归（2026-09-12 台账清剿 P2）。

根因链：
1. chat_pipeline 用**字符串** event_type 调 record_event，而持久化
   TrajectoryEvent.to_dict 读 `self.event_type.value` → AttributeError 被
   save_trace 的 except 吞掉，但 `open(path,'w')` 已把文件截断成 0 字节
   （实测 trajectories/ 1525 文件中 1168 个 0 字节——76.6% 生产轨迹为空）。
2. /v1/trace 端点族的进程内 TraceManager 全仓零写入方恒空，与真实记录器
   TrajectoryRecorder 是完全脱钩的平行假数据源（与已修 reflection_manager 同型）。

修复契约：
- record_event 入口 str→TrajectoryEventType 归一（非法值落 INFO），save_trace
  先序列化再 tmp+replace 原子写（异常绝不截断旧文件）；
- trace.py 数据源换 TrajectoryRecorder，响应形状对齐前端 trace.ts
  （列表 {id,status,duration_ms,steps_count,started_at}、stats
  {total,avg_duration_ms,success_rate,avg_steps}、详情
  +tool_calls/llm_calls/breakdown/events）；新增 FE 调用但后端缺失的
  /{id}/export；删除零消费方的孤儿 /{id}/events。
"""
import json
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_trace_0123456789")

from neurova.api.deps import get_current_user
from neurova.api.endpoints import trace as TRACE
from neurova.core import trace_recorder as TR


@pytest.fixture()
def recorder(tmp_path, monkeypatch):
    """隔离 TrajectoryRecorder 单例到 tmp 存储目录。"""
    saved_inst, saved_init = TR.TrajectoryRecorder._instance, TR.TrajectoryRecorder._initialized
    TR.TrajectoryRecorder._instance = None
    TR.TrajectoryRecorder._initialized = False
    rec = TR.get_trajectory_recorder()
    rec._storage_dir = tmp_path / "trajectories"
    rec._storage_dir.mkdir(parents=True, exist_ok=True)
    rec._saved_traces = []
    yield rec
    TR.TrajectoryRecorder._instance = saved_inst
    TR.TrajectoryRecorder._initialized = saved_init


@pytest.fixture()
def client(recorder):
    app = FastAPI()
    app.include_router(TRACE.router, prefix="/api/v1/trace")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1", "username": "u1", "role": "user",
    }
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _seed_completed(recorder):
    """一条含字符串 event_type + 工具/LLM 事件的完整轨迹（复现生产调用方式）。"""
    tid = recorder.start_trace(session_id="s-1", agent_id="a1", user_id="u1")
    recorder.record_event(tid, "user_input", {"user_input": "hello"})  # 字符串！
    span = recorder.start_span(tid, operation_name="tool", operation_type="tool_call")
    recorder.record_event(tid, "tool_call_end", {"tool_name": "web_search", "execution_time": 120.0, "success": True})
    recorder.end_span(span)
    recorder.record_event(tid, "llm_call_end", {"model": "gpt-4o", "input_tokens": 10, "output_tokens": 20, "duration_ms": 500.0})
    recorder.record_event(tid, "output_end", {"reply_length": 7})
    path = recorder.save_trace(tid)
    return tid, path


class TestRootCause:
    def test_string_event_type_coerced_and_file_valid(self, recorder):
        tid, path = _seed_completed(recorder)
        assert path and os.path.getsize(path) > 0, "轨迹文件仍被截断为 0 字节"
        data = json.load(open(path, encoding="utf-8"))
        events = data["spans"][data["root_span"]]["events"]
        assert any(e["event_type"] == "user_input" for e in events)

    def test_bad_event_type_falls_back_info_not_crash(self, recorder):
        tid = recorder.start_trace(session_id="s2", agent_id="a1", user_id="u1")
        recorder.record_event(tid, "totally-bogus-type", {})
        path = recorder.save_trace(tid)
        data = json.load(open(path, encoding="utf-8"))
        ev = data["spans"][data["root_span"]]["events"]
        assert ev and ev[-1]["event_type"] == "info"


class TestEndpointWiring:
    def test_list_returns_frontend_shape(self, client, recorder):
        tid, _ = _seed_completed(recorder)
        r = client.get("/api/v1/trace", params={"agent_id": "a1"})
        assert r.status_code == 200, r.text
        items = r.json()
        assert isinstance(items, list) and len(items) == 1
        it = items[0]
        assert it["id"] == tid
        assert "duration_ms" in it and "status" in it and "steps_count" in it
        assert isinstance(it["started_at"], str)

    def test_detail_has_tool_llm_breakdown(self, client, recorder):
        tid, _ = _seed_completed(recorder)
        d = client.get(f"/api/v1/trace/{tid}").json()
        assert [t["tool"] for t in d["tool_calls"]] == ["web_search"]
        assert d["tool_calls"][0]["duration_ms"] == 120.0
        assert d["llm_calls"][0]["model"] == "gpt-4o"
        assert d["llm_calls"][0]["tokens_in"] == 10
        assert d["events"], "详情缺事件时间轴"
        assert {"type", "timestamp"} <= set(d["events"][0])
        assert d["breakdown"]["tool_ms"] == 120.0 and d["breakdown"]["llm_ms"] == 500.0

    def test_stats_aggregates(self, client, recorder):
        _seed_completed(recorder)
        s = client.get("/api/v1/trace/stats", params={"agent_id": "a1"}).json()
        assert s["total"] == 1
        assert s["avg_duration_ms"] >= 0
        assert 0 <= s["success_rate"] <= 1

    def test_export_attachment(self, client, recorder):
        tid, _ = _seed_completed(recorder)
        r = client.get(f"/api/v1/trace/{tid}/export")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        assert json.loads(r.text)["trace_id"] == tid

    def test_missing_trace_404_and_events_route_gone(self, client, recorder):
        assert client.get("/api/v1/trace/no-such").status_code == 404
        assert client.get("/api/v1/trace/whatever/events").status_code == 404
