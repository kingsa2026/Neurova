"""ContextChannelPage 渠道共享配置落盘回归（2026-09-12 空数据页面排查）。

根因: _sharing_config 为进程内 dict，POST /enable /disable /channels 改动
仅写内存，重启回硬编码默认（enabled=True + web/mobile/api），保存不持久。

修复契约: 配置落 data/channel_sharing.json，启动自动加载，改动即时写盘，重启回读。
"""
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_chsharing_01234567")

from neurova.api.auth import get_current_user
from neurova.api.endpoints import channel_sharing as CS


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(CS, "_STORE_FILE", str(tmp_path / "channel_sharing.json"))
    CS._sharing_config.update(json.loads(json.dumps(CS._DEFAULT_CONFIG)))
    app = FastAPI()
    app.include_router(CS.router, prefix="/api/v1/channel-sharing")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u", "username": "u", "role": "admin"}
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, tmp_path
    app.dependency_overrides.clear()


class TestChannelSharingPersistence:
    def test_set_channels_written_to_disk(self, client):
        c, tmp = client
        r = c.post("/api/v1/channel-sharing/channels", json={"channels": ["feishu", "telegram"], "shared_context": True})
        assert r.status_code == 200, r.text
        f = tmp / "channel_sharing.json"
        assert f.exists()
        assert set(json.loads(f.read_text(encoding="utf-8"))["shared_channels"]) == {"feishu", "telegram"}

    def test_disable_survives_restart(self, client):
        c, tmp = client
        c.post("/api/v1/channel-sharing/disable")
        # 重启：重置内存为默认后从盘重载
        CS._sharing_config.update(json.loads(json.dumps(CS._DEFAULT_CONFIG)))
        CS._load_store()
        assert CS._sharing_config["enabled"] is False

    def test_invalid_channel_not_persisted(self, client):
        c, tmp = client
        c.post("/api/v1/channel-sharing/channels", json={"channels": ["weixin_bogus"]})
        assert not (tmp / "channel_sharing.json").exists() or "weixin_bogus" not in (tmp / "channel_sharing.json").read_text(encoding="utf-8")
