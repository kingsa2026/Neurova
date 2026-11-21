# -*- coding: utf-8 -*-
"""B4 深化：排队 run 管理面 REST（/v1/swarm-queue）契约测试。

真 create_app（ENDPOINT_MODULES 注册表挂载）+ 真 JWT；队列经 SwarmManager
单例播种（真管理面方法，非 mock 冒充）。队列管理是运维面：admin 门。
"""
import time

import pytest
from fastapi.testclient import TestClient

from tests.auth_headers import bearerHeaders

BASE = "/api/v1/swarm-queue"


@pytest.fixture(scope="module")
def client():
    from neurova.api.app import create_app

    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def adminHeaders():
    return bearerHeaders("b4q-admin", role="admin")


def userHeaders():
    return bearerHeaders("b4q-user", role="user")


def _seedQueuedRun(sid="api-q-1", priority="normal"):
    """经 SwarmManager 真管理面播种一条排队 run。"""
    from neurova.agent.swarm import get_swarm_manager, reset_swarm_manager
    from neurova.agent.swarm_support import SubAgentRun

    reset_swarm_manager()
    swarm = get_swarm_manager()
    run = SubAgentRun(subagent_id=sid, depth=1, agent_id="agent-a", agent_name="A",
                      task="排队任务", origin="chat", status="pending")
    with swarm._lock:
        swarm._runs[sid] = run
    swarm._registerRunQueue(run)
    if priority != "normal":
        swarm.setRunQueuePriority(sid, priority)
    return swarm


def test_queue_requires_auth(client):
    assert client.get(BASE).status_code == 401
    assert client.get(BASE, headers=userHeaders()).status_code == 403


def test_queue_snapshot_lists_position(client):
    _seedQueuedRun("api-q-snap", priority="high")
    resp = client.get(BASE, headers=adminHeaders())
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    entry = next(e for e in data["queue"] if e["subagent_id"] == "api-q-snap")
    assert entry["position"] >= 1
    assert entry["priority"] == "high"
    assert entry["task"] == "排队任务"


def test_queue_patch_priority(client):
    _seedQueuedRun("api-q-pri")
    resp = client.patch(f"{BASE}/api-q-pri/priority",
                        json={"priority": "urgent"}, headers=adminHeaders())
    assert resp.status_code == 200
    assert resp.json()["position"] == 1
    assert resp.json()["priority"] == "urgent"


def test_queue_delete_cancels_run(client):
    swarm = _seedQueuedRun("api-q-cancel")
    resp = client.delete(f"{BASE}/api-q-cancel", headers=adminHeaders())
    assert resp.status_code == 200
    assert resp.json()["subagent_id"] == "api-q-cancel"
    assert swarm.status("api-q-cancel")["status"] == "failed", "队列取消落诚实终态"


def test_queue_post_task_edit(client):
    _seedQueuedRun("api-q-edit")
    resp = client.post(f"{BASE}/api-q-edit/task",
                       json={"task": "改后的任务书"}, headers=adminHeaders())
    assert resp.status_code == 200
    assert resp.json()["mode"] == "requeued"


def test_queue_ops_on_unknown_run_404(client):
    assert client.patch(f"{BASE}/no-such/priority", json={"priority": "high"},
                        headers=adminHeaders()).status_code == 404
    assert client.delete(f"{BASE}/no-such", headers=adminHeaders()).status_code == 404
