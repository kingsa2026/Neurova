# -*- coding: utf-8 -*-
"""代码执行沙箱后端契约（Issue #68 收口 · 「补一个真的代码执行沙箱后端」）。

## 根因（把报错恢复原状就会复现）

`SandboxPage.vue` 是路由表内的真实页面，它描述的能力是**代码执行沙箱**：
列表卡片展示 `image` / `steps_count`，执行区提交 `{command, language}`，
新建弹窗提交 `{name, image, timeout}`，`/commit` 与 `DELETE /{id}` 无 body。

而后端 `neurova/api/endpoints/sandbox.py` 实现的是**思维沙箱**：`/start` 要
`agent_id`/`topic`（前端载荷因此必 422），执行面是 `POST /{id}/step` 收
`{input, context}`（前端发的 `/execute` 从未注册过路由 ⇒ 必 404），
`/commit` 要结论 body（前端不传 ⇒ 必 422）。

于是「同一件事有两套值域、两套命名、两套语义」——前端页面点下去三个动作全失败。
本套件钉死**唯一的沙箱值域**：一套形态 + 一套 status 枚举 + 一套路由契约，
两种能力（思维沙箱 = `null` session 的限定能力面；代码执行 = 真 session 承载）。

## 分层判据

1. **形态层**：`sandbox` 字段是前端 `Sandbox` 接口的字段来源，`status` 取值必须
   落在有限枚举里（前端 tag 三色映射只认它们）。
2. **路由层**：前端 6 个调用逐条命中真装配后路由表（走 `tests/route_table.py`
   的唯一遍历口径，不静态重建路由语义）。
3. **执行层**：`execute` 真的跑代码（不是返回占位串），语言必须真被解释器认。
4. **诚实层**：Docker 不可用时**不得静默降级成裸跑**——必须自报 `backend`
   与 `enforced`，`backend=docker` 时不可用要显式报错（教义第 1/2 条）。
5. **生命周期层**：`DELETE` 真删、`/{id}` 真 404、`timeout` 真生效。
"""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import sandbox as sandbox_api_module
from neurova.api.endpoints.sandbox import router

BASE = "/api/v1/sandbox"

ALLOWED_STATUS = {"running", "paused", "stopped", "failed", "timeout", "committed"}
SANDBOX_FIELDS = {"id", "name", "status", "image", "steps_count", "created_at", "language"}
MIN_TIMEOUT_SECONDS = 60


@pytest.fixture(autouse=True)
def _isolate_store():
    """每个用例一份干净的内存态 + 独立工作目录（不触碰真实 data/）。"""
    sandbox_api_module.reset_execution_sandboxes()
    yield
    sandbox_api_module.reset_execution_sandboxes()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router, prefix=BASE)
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u1",
        "neuser_id": "neu",
        "role": "admin",
    }
    yield TestClient(app)


class TestSessionShapeMatchesFrontendContract:
    """形态层：`Sandbox` 接口字段与 status 值域是唯一一份（前端 tag 映射只认这些）。"""

    def test_create_accepts_the_frontend_payload(self, client):
        """前端 `{name, image, timeout}` 必被接受——原先要求 agent_id/topic ⇒ 必 422。"""
        resp = client.post(f"{BASE}/start", json={"name": "ce", "image": "python:3.11-slim", "timeout": 300})
        assert resp.status_code == 200, f"前端新建载荷被拒（422）：{resp.text}"

    def test_create_returns_the_frontend_field_set(self, client):
        data = client.post(f"{BASE}/start", json={"name": "ce", "image": "python:3.11-slim"}).json()["data"]
        missing = SANDBOX_FIELDS - set(data)
        assert not missing, f"响应缺前端 Sandbox 接口字段 {missing}：卡片会渲染成 undefined"

    def test_status_is_a_closed_enum(self, client):
        data = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]
        assert data["status"] in ALLOWED_STATUS, (
            f"status={data['status']!r} 不在有限枚举 {sorted(ALLOWED_STATUS)} 内——"
            "前端 tag 三色映射（running/paused/其他）是有限值域契约。"
        )

    def test_default_image_is_declared_not_guessed(self, client):
        data = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]
        assert data["image"], "默认镜像必须显式落库——前端卡片直接展示它"

    def test_list_envelope_matches_the_page_unpacking(self, client):
        client.post(f"{BASE}/start", json={"name": "ce"})
        body = client.get(BASE).json()
        assert body["data"]["total"] == 1
        assert len(body["data"]["sandboxes"]) == 1, "列表信封形状是页面 v-for 的取数口径"

    def test_steps_count_advances_after_execute(self, client):
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        client.post(f"{BASE}/{sid}/execute", json={"command": "print(1)", "language": "python"})
        data = client.get(f"{BASE}/{sid}").json()["data"]
        assert data["steps_count"] == 1, "执行后卡片步骤数必须真的涨——否则读数与事实脱节"


class TestExecuteIsARealExecution:
    """执行层：`execute` 真跑代码，不是返回占位串。"""

    def _run(self, client, code: str, language: str = "python") -> dict:
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/execute", json={"command": code, "language": language})
        assert resp.status_code == 200, f"/execute 未命中真路由：{resp.status_code} {resp.text}"
        return resp.json()["data"]

    def test_python_stdout_is_really_captured(self, client):
        data = self._run(client, "print('neurova-probe-42')")
        assert "neurova-probe-42" in (data.get("output") or data.get("stdout") or ""), (
            "输出里没有探针串——执行面没有真跑解释器。"
        )

    def test_exit_code_is_reported(self, client):
        ok = self._run(client, "pass")
        bad = self._run(client, "raise SystemExit(3)")
        assert ok["exit_code"] == 0
        assert bad["exit_code"] != 0, "非零退出码必须如实上报，不得抹平成成功"

    def test_stderr_is_reported_separately(self, client):
        data = self._run(client, "import sys; sys.stderr.write('boom\\n')")
        assert "boom" in (data.get("stderr") or ""), "stderr 未与 stdout 分流——排障者看不到错误"

    def test_unknown_language_is_rejected_explicitly(self, client):
        """不认识的语言必须显式 4xx——不许当成 python 跑（诚实报错优于静默改语义）。"""
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/execute", json={"command": "x", "language": "brainfuck"})
        assert resp.status_code in (400, 422), f"未支持语言被放行：{resp.status_code} {resp.text}"

    def test_empty_command_is_rejected(self, client):
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/execute", json={"command": "", "language": "python"})
        assert resp.status_code == 422, "空命令必须 422——不得跑出一次「成功」的空执行"

    def test_timeout_is_enforced(self, client):
        """按 session 的 timeout 掐断（请求级 timeout 可覆盖，不早不晚）。"""
        sid = client.post(
            f"{BASE}/start", json={"name": "ce", "timeout": MIN_TIMEOUT_SECONDS}
        ).json()["data"]["id"]
        started = time.time()
        resp = client.post(
            f"{BASE}/{sid}/execute",
            json={"command": "import time; time.sleep(120)", "timeout": 2},
        )
        elapsed = time.time() - started
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["exit_code"] != 0, "长任务必须被超时掐断，不得放行到 120 秒"
        assert elapsed < 30, f"掐断动作用了 {elapsed:.1f}s —— 超时没有真生效"
        assert data.get("timed_out") is True, "超时必须可判定（timed_out: true）"

    def test_shell_language_really_runs_the_script(self, client):
        """shell 语言必须真跑脚本 —— 不能因为语言分派写错就跑成别的语言（或报语法错）。"""
        data = self._run(client, "echo shell-live-probe", language="shell")
        assert data["exit_code"] == 0, f"shell 脚本没跑成：{data['stderr']!r}"
        assert "shell-live-probe" in (data.get("stdout") or ""), (
            "shell 输出里没有探针串——语言分派把源码交给了解释器以外的东西。"
        )

    def test_javascript_language_really_runs(self, client):
        """javascript 语言必须真跑 node —— 缺解释器时要显式报错，不得静默换语言。"""
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/execute", json={"command": "console.log('js-probe')", "language": "javascript"})
        if resp.status_code == 503:
            assert "node" in resp.text.lower(), "缺 node 时的拒绝理由没点名解释器"
            return
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["exit_code"] == 0, f"js 没跑成：{data['stderr']!r}"
        assert "js-probe" in (data.get("stdout") or "")

    def test_timeout_must_stay_in_range(self, client):
        """timeout 超出 [MIN, MAX] 必须 422 —— 前端控件约束由后端同域兜住。"""
        resp = client.post(f"{BASE}/start", json={"name": "ce", "timeout": 10})
        assert resp.status_code == 422, "timeout 低于下界被接受——前端控件不是唯一防线"
        resp = client.post(f"{BASE}/start", json={"name": "ce", "timeout": 99999})
        assert resp.status_code == 422, "timeout 高于上界被接受"


class TestBackendHONESTY:
    """诚实层：后端选择必须自报，Docker 不可用时不得静默裸跑。"""

    def test_execute_reports_backend_and_enforcement(self, client):
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        data = client.post(f"{BASE}/{sid}/execute", json={"command": "print(1)"}).json()["data"]
        assert data.get("backend"), "必须自报实际执行后端——否则「隔离了没有」无从审计"
        assert isinstance(data.get("enforced"), bool), "必须自报是否真隔离（enforced: bool）"

    def test_docker_unavailable_is_an_explicit_error_not_a_silent_downgrade(self, client, monkeypatch):
        """请求 docker 后端而 Docker 不可用 → 明确报错（不是悄悄换成裸跑还回 200 成功）。

        降级必须显形：要么建 session 就拒绝，要么执行时 5xx 并点名 Docker；
        两者都不做、却回 200 且自报 enforced=True 才是要禁的静默降级。
        """
        monkeypatch.setattr(sandbox_api_module, "dockerAvailable", lambda: False)
        created = client.post(f"{BASE}/start", json={"name": "ce", "backend": "docker"})
        if created.status_code >= 400:
            assert "docker" in created.text.lower(), "拒绝理由没点名 Docker"
            return
        sid = created.json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/execute", json={"command": "print(1)"})
        assert resp.status_code >= 400, "Docker 不可用却执行成功 —— 静默降级成了裸跑"
        assert "docker" in resp.text.lower(), "拒绝理由没点名 Docker"

    def test_unsupported_image_is_rejected_not_ignored(self, client):
        """镜像白名单外的 image 必须显式拒绝——不许收下却按别的镜像跑。"""
        resp = client.post(f"{BASE}/start", json={"name": "ce", "image": "evil:latest"})
        assert resp.status_code in (400, 422), (
            f"白名单外镜像被接受：{resp.status_code}——用户以为跑在自己选的镜像里。"
        )


class TestLifecycle:
    """生命周期层：删除真删、取不到真 404、commit 无 body 也能落。"""

    def test_delete_removes_the_session(self, client):
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        assert client.delete(f"{BASE}/{sid}").status_code == 200
        assert client.get(f"{BASE}/{sid}").status_code == 404

    def test_unknown_id_is_404(self, client):
        assert client.get(f"{BASE}/nope").status_code == 404
        assert client.post(f"{BASE}/nope/execute", json={"command": "print(1)"}).status_code == 404

    def test_commit_without_body_is_accepted(self, client):
        """前端 `commitSandbox(id)` 不带 body —— 原实现强制结论 body ⇒ 必 422。"""
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        resp = client.post(f"{BASE}/{sid}/commit")
        assert resp.status_code == 200, f"无 body 提交被拒：{resp.status_code} {resp.text}"

    def test_commit_freezes_further_execution(self, client):
        sid = client.post(f"{BASE}/start", json={"name": "ce"}).json()["data"]["id"]
        client.post(f"{BASE}/{sid}/execute", json={"command": "print(1)"})
        assert client.post(f"{BASE}/{sid}/commit").status_code == 200
        again = client.post(f"{BASE}/{sid}/execute", json={"command": "print(2)"})
        assert again.status_code == 400, "已提交的沙箱仍可执行——生命周期没有终点"


class TestThoughtSandboxCapabilityIsNotLost:
    """思维沙箱是同一值域下的**限定能力面**（`null` session），不是第二套沙箱。"""

    def test_thought_capability_lives_on_the_null_session(self, client):
        resp = client.post(f"{BASE}/start", json={"agent_id": "a1", "topic": "复盘的路径选择"})
        assert resp.status_code == 200, f"思维沙箱面不可达：{resp.status_code} {resp.text}"
        data = resp.json()["data"]
        assert data["id"] == "null", "思维沙箱的 session 是保留 id `null`（无容器承载）"
        assert data["status"] in ALLOWED_STATUS

    def test_step_runs_on_the_thought_session(self, client):
        resp = client.post(f"{BASE}/null/step", json={"input": "先验证假设"})
        assert resp.status_code == 200, f"思维步进不可达：{resp.status_code} {resp.text}"

    def test_thought_session_cannot_be_deleted(self, client):
        assert client.delete(f"{BASE}/null").status_code == 400, (
            "`null` 是保留 session，删除它等于把思维沙箱面从值域里摘掉"
        )

    def test_thought_session_does_not_serve_code_execution(self, client):
        resp = client.post(f"{BASE}/null/execute", json={"command": "print(1)"})
        assert resp.status_code == 400, "思维 session 无容器承载，不得冒充代码执行面"
