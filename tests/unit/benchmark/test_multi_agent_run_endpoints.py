# -*- coding: utf-8 -*-
"""R3：multi_agent 评测跑批生产入口（API 触发 → 报告落盘可读回）。

红→绿契约（docs/04-plans/2026-11-21-recursive-self-evolution-plan.md §1.4/§1.7-A3/§6-R3）：
- POST /v1/benchmark/multi-agent/run：admin 权限门；body 可选 task/suite 子集
  （缺省=全部注册任务）、modes（solo/swarm，缺省 solo）；后台线程执行
  runAllWithReport，POST 立即返回 run 标识与 running 态；
- GET /v1/benchmark/multi-agent/runs/{run_id}：执行状态可查询（running→completed），
  终态含报告落盘路径与结果摘要；报告文件真实落盘 <数据根>/benchmark/multi_agent/
  且可经 loadReport 读回；
- 鉴权：无凭据 401、非 admin 403，跑批入口（消耗真实 LLM 预算）不对普通用户开放。

测试纪律：swarm 全链（真 SwarmManager）不在单测跑——本文件只用 solo 模式验证
管线，agent 用 MagicMock 桩；数据根用 tmp 注入，不写仓库 data/。
"""

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.benchmark.multi_agent import BenchmarkTask, clearTasks, registerTask
from neurova.benchmark.multi_agent.report import loadReport

RUN_URL = "/api/v1/benchmark/multi-agent/run"


def _make_client(role: str = "admin") -> TestClient:
    """挂 benchmark 路由的测试客户端；admin 场景覆写身份门（沿 S1-1E 同款）。"""
    from neurova.api.auth import get_current_user as _gcu
    from neurova.api.endpoints import benchmark as benchmark_api

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": role, "neuser_id": "tuser",
    }
    return TestClient(app)


def _make_client_no_auth() -> TestClient:
    """不覆写身份门：真实 get_current_user 对无凭据请求必须 401。"""
    from neurova.api.endpoints import benchmark as benchmark_api

    app = FastAPI()
    app.include_router(benchmark_api.router, prefix="/api/v1/benchmark")
    return TestClient(app)


def _stubAgent(delaySeconds: float = 0.0):
    """solo 桩 agent：返回合规正文；delaySeconds>0 用于观察 running 中间态。"""
    agent = MagicMock()
    agent.config.name = "R3评测假Agent"

    async def _chat(prompt, *args, **kwargs):
        if delaySeconds:
            await asyncio.sleep(delaySeconds)
        return {"text": "合规报告正文", "usage": {"total_tokens": 42}}

    agent.chat = AsyncMock(side_effect=_chat)
    return agent


@pytest.fixture
def seededTasks():
    """三个最小任务：两个 t1_sim + 一个自定义 suite（suites 子集选择用）。"""
    clearTasks()
    registerTask(BenchmarkTask(
        task_id="t1-r3-alpha", suite="t1_sim", prompt="alpha",
        check=lambda outcome: (True, 100.0, {}),
    ))
    registerTask(BenchmarkTask(
        task_id="t1-r3-beta", suite="t1_sim", prompt="beta",
        check=lambda outcome: (True, 80.0, {}),
    ))
    registerTask(BenchmarkTask(
        task_id="r3-iso-gamma", suite="r3_iso", prompt="gamma",
        check=lambda outcome: (True, 100.0, {}),
    ))
    yield
    clearTasks()


def _pollTerminal(client: TestClient, runId: str, deadlineSeconds: float = 15.0) -> dict:
    """轮询 run 至终态（沿既有后台线程+轮询范式）。"""
    deadline = time.time() + deadlineSeconds
    body = None
    while time.time() < deadline:
        resp = client.get(f"/api/v1/benchmark/multi-agent/runs/{runId}")
        assert resp.status_code == 200, resp.text
        body = resp.json()["data"]
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"run {runId} 未在 {deadlineSeconds}s 内到达终态: {body}")


class TestMultiAgentRunLifecycle:
    def test_post_run_running_to_completed_with_report_on_disk(
        self, tmp_path, monkeypatch, seededTasks
    ):
        """红灯主判据：POST 触发 → running → completed，报告真实落盘可读回。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        agent = _stubAgent(delaySeconds=0.5)
        client = _make_client()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            resp = client.post(RUN_URL, json={"task_ids": ["t1-r3-alpha", "t1-r3-beta"]})
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            runId = data["run_id"]
            assert runId, "POST 必须立即返回 run 标识"
            # 缺省模式 = solo（R3 契约）
            assert data["modes"] == ["solo"]
            assert data["status"] == "running"

            # 立即查询：agent 有延时，后台线程尚未收尾 → 仍为 running
            first = client.get(f"/api/v1/benchmark/multi-agent/runs/{runId}")
            assert first.status_code == 200, first.text
            assert first.json()["data"]["status"] == "running"

            body = _pollTerminal(client, runId)

        assert body["status"] == "completed", body
        assert body["error"] is None
        # 结果摘要（分模式聚合）与报告落盘路径
        assert body["report_id"] and body["report_path"], body
        assert body["summary"]["metrics"]["solo"]["task_count"] == 2

        # 报告文件真实落盘（tmp 数据根）且可读回——R3 验收核心
        assert Path(body["report_path"]).exists(), body["report_path"]
        assert str(tmp_path) in body["report_path"], "报告必须落在注入的 tmp 数据根"
        saved = loadReport(body["report_id"])
        assert saved is not None, "报告须可经 loadReport 读回"
        assert {t["task_id"] for t in saved["tasks"]} == {"t1-r3-alpha", "t1-r3-beta"}
        assert saved["metrics"]["solo"]["passed_count"] == 2

    def test_suites_subset_runs_only_matching_tasks(self, tmp_path, monkeypatch, seededTasks):
        """suites 子集：只跑该 suite 下的注册任务。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        client = _make_client()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_stubAgent()):
            resp = client.post(RUN_URL, json={"suites": ["r3_iso"]})
            assert resp.status_code == 200, resp.text
            runId = resp.json()["data"]["run_id"]
            body = _pollTerminal(client, runId)

        assert body["status"] == "completed", body
        assert body["summary"]["metrics"]["solo"]["task_count"] == 1
        saved = loadReport(body["report_id"])
        assert saved is not None
        assert [t["task_id"] for t in saved["tasks"]] == ["r3-iso-gamma"]

    def test_unknown_task_id_recorded_honestly(self, tmp_path, monkeypatch, seededTasks):
        """未注册任务 id：如实记 task_not_registered 失败事实，不伪造通过。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
        client = _make_client()
        with patch("neurova.api.endpoints.get_agent_instance", return_value=_stubAgent()):
            resp = client.post(RUN_URL, json={"task_ids": ["no-such-task"]})
            assert resp.status_code == 200, resp.text
            body = _pollTerminal(client, resp.json()["data"]["run_id"])

        assert body["status"] == "completed"
        saved = loadReport(body["report_id"])
        assert saved["tasks"][0]["error"] == "task_not_registered"
        assert saved["tasks"][0]["passed"] is False

    def test_invalid_mode_422(self, seededTasks):
        """modes 非法值：契约校验 422，不静默落库。"""
        client = _make_client()
        resp = client.post(RUN_URL, json={"modes": ["bogus"]})
        assert resp.status_code == 422

    def test_get_unknown_run_404(self, seededTasks):
        client = _make_client()
        resp = client.get("/api/v1/benchmark/multi-agent/runs/no-such-run")
        assert resp.status_code == 404


class TestMultiAgentRunAuth:
    def test_non_admin_forbidden_403(self, seededTasks):
        """普通用户（role=user）：403，跑批入口不对普通用户开放。"""
        client = _make_client(role="user")
        resp = client.post(RUN_URL, json={"task_ids": ["t1-r3-alpha"]})
        assert resp.status_code == 403
        resp2 = client.get("/api/v1/benchmark/multi-agent/runs/whatever")
        assert resp2.status_code == 403

    def test_missing_credentials_unauthorized_401(self, seededTasks):
        """无凭据：401（真实身份门，不覆写）。"""
        client = _make_client_no_auth()
        resp = client.post(RUN_URL, json={"task_ids": ["t1-r3-alpha"]})
        assert resp.status_code == 401
        resp2 = client.get("/api/v1/benchmark/multi-agent/runs/whatever")
        assert resp2.status_code == 401
