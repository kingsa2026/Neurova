# -*- coding: utf-8 -*-
"""通知 SSE 流端点测试（补课 2.2：替代前端 60s 轮询）。

独立 FastAPI 挂载（create_app in-process 会挂起——一律不用），
dependency_overrides 绕过真实鉴权。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_NOTIFICATIONS_PATH", str(tmp_path / "notifications.json"))

    from neurova.api.endpoints import notifications as notif_mod
    from neurova.api.auth import get_current_user_or_default

    notif_mod.reset_notification_manager()

    app = FastAPI()
    app.include_router(notif_mod.router, prefix="/v1/notifications")
    app.dependency_overrides[get_current_user_or_default] = lambda: {
        "user_id": "u-admin",
        "role": "admin",
    }
    yield TestClient(app)
    notif_mod.reset_notification_manager()


def test_stream_emits_initial_unread_count(client):
    from neurova.api.endpoints.notifications import get_notification_manager

    get_notification_manager().add_notification(
        user_id="u-admin", title="t", message="m", notification_type="test"
    )

    # max_events=1 测试钩子：发完首帧即收尾（无限流在 TestClient 里
    # break 后 aclose 会挂在 sleep 上——见 autorun 计划 2.2 踩坑记录）
    with client.stream(
        "GET", "/v1/notifications/stream", params={"interval": 2, "max_events": 1}
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "data:" in buf:
                break
        line = [l for l in buf.split("\n") if l.startswith("data:")][0]
        payload = json.loads(line[len("data: ") :])
        assert payload["type"] == "unread"
        assert payload["count"] == 1


def test_stream_route_registered(client):
    # 端点存在性（鉴权由依赖注入保证，这里仅验证 200 而非 404）
    with client.stream(
        "GET", "/v1/notifications/stream", params={"interval": 2, "max_events": 1}
    ) as resp:
        assert resp.status_code == 200
