# -*- coding: utf-8 -*-
"""存量渠道归属迁移：default → 目标智能体（Issue #290 归属裁决的红灯探针）。

## 用户拍的板

「之前配置的是归属于默认 agent 的，现在可以归属到 kai 身上」

即存量 5 条（`agents.default`）的归属键要能动。此前把这条挂起是对的：
它会改写用户既有凭据的归属键，猜错方向的代价由用户承担。现在方向已给，
但**改归属键不是改一个字符串**——渠道实例表的主键是 `(agent_id, channel_type)`，
配置换了归属而实例没换，用户侧就是"迁过去反而连不上"。

## 判据（各带反向控制）

1. **移动语义**：源表不再有该渠道、目标表有；两侧都不是"复制"（复制会让
   同一个 bot 被两个 agent 各持一份连接，平台侧串台）。
2. **实例跟着换**：源实例断开并注销、目标实例注册（配置与实例必须同源）。
3. **冲突诚实失败**：目标已有同渠道 → 409，且**两边都原样**（不留半截状态：
   迁一半再报错，用户既丢了源又没拿到目标）。
4. **同身份跨 agent 拒绝**：目标表里已有同平台同身份的另一个 bot 时，409
   点名（复用既有身份冲突检测，不另起一套）。
5. **权限**：源是 `default`（无主）→ 非 admin 403；目标非属主 → 403。
6. **空可迁才是真"没有"**：无可迁内容时诚实返回 `migrated: []`，
   不拿"成功"掩盖"什么都没做"。
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_migrate_290")

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.channels.base import ChannelConfig
from neurova.channels.manager import ChannelManager

ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}

PLATFORMS = ("feishu", "dingtalk", "qq")


class _CountingAdapter:
    """记账替身：只记连接状态，不建真长连接（真凭据建连接有外部副作用）。"""

    def __init__(self, channel_type: str):
        self.channel_type = channel_type
        self.is_connected = True
        self.disconnects = 0

    def set_event_callback(self, cb):
        self.cb = cb

    async def connect(self):
        self.is_connected = True
        return True

    async def disconnect(self):
        self.disconnects += 1
        self.is_connected = False

    async def health_check(self):
        return {"ok": True}


def _agentWithOwner(agent_id: str, owner):
    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(CC, "_create_adapter", lambda channel_type, cfg: _CountingAdapter(channel_type))

    from neurova.api.endpoints import set_app_state

    set_app_state({
        "agents": {
            "default": _agentWithOwner("default", None),   # 与 api/app.py 同形：无主
            "kai": _agentWithOwner("kai", "u1"),
            "other": _agentWithOwner("other", "u2"),
        }
    })

    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)

    ChannelManager._instance = None
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, app
    app.dependency_overrides.clear()
    ChannelManager._instance = None
    set_app_state(None)


def _as(app, identity):
    app.dependency_overrides[auth_u] = lambda: dict(identity)


def _seedLegacy():
    """存量：default 下 3 个平台（形状与真实 v2 文件一致）。"""
    CC._save_configs({
        p: {"channel_type": p, "enabled": True, "app_id": f"bot-{p}",
            "app_secret": "s", "extra": {}}
        for p in PLATFORMS
    })


def _agentsOf(store, agent_id):
    return (store.get("agents") or {}).get(agent_id) or {}


# ── 1. 移动语义 ────────────────────────────────────────────────────


def test_migrationMovesChannelsFromSourceToTarget(env):
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai"})

    assert r.status_code == 200, r.text
    assert sorted(r.json()["migrated"]) == sorted(PLATFORMS)

    store = CC._load_store()
    assert _agentsOf(store, "default") == {}, "源表必须清空（移动，不是复制）"
    assert sorted(_agentsOf(store, "kai")) == sorted(PLATFORMS), "目标表未拿到存量"
    assert _agentsOf(store, "kai")["feishu"]["app_id"] == "bot-feishu", "凭据必须原样随迁"


def test_migrationDoesNotTouchOtherAgents(env):
    """反向控制：别的 agent 的同平台配置不属于本次搬迁面。"""
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)
    c.post("/api/v1/channel-configs", params={"agent_id": "other"},
           json={"channel_type": "telegram", "extra": {"bot_token": "tg"}})

    c.post("/api/v1/channel-configs/migrate-agent",
           json={"from_agent_id": "default", "to_agent_id": "kai"})

    store = CC._load_store()
    assert sorted(_agentsOf(store, "other")) == ["telegram"], "无关 agent 的配置被动了"


def test_migrationCanBeScopedToSomeChannels(env):
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai",
                     "channel_types": ["feishu", "qq"]})

    assert r.status_code == 200, r.text
    store = CC._load_store()
    assert sorted(_agentsOf(store, "kai")) == ["feishu", "qq"]
    assert sorted(_agentsOf(store, "default")) == ["dingtalk"], "未点名的渠道不该被搬走"


# ── 2. 实例跟着换 ─────────────────────────────────────────────────


def test_adaptersFollowTheConfigOwnership(env):
    """配置换了归属，实例必须在同一批动作里换 —— 否则"迁过去反而连不上"。"""
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)
    c.post("/api/v1/channel-configs/migrate-agent",
           json={"from_agent_id": "default", "to_agent_id": "kai"})

    from neurova.channels.manager import get_channel_manager

    mgr = get_channel_manager()
    assert mgr.get_adapter("feishu", agent_id="kai") is not None, "目标侧没有可用实例"
    assert mgr.get_adapter("feishu", agent_id="default") is None, "源侧旧实例仍挂着（双连接风险）"


# ── 3/4. 冲突诚实失败 ─────────────────────────────────────────────


def test_conflictLeavesBothSidesUntouched(env):
    """目标已有同渠道 → 409，且两边都原样：不留"源已删、目标没进"的半截状态。"""
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)
    c.post("/api/v1/channel-configs", params={"agent_id": "kai"},
           json={"channel_type": "feishu", "app_id": "kai-own", "app_secret": "s"})

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai"})

    assert r.status_code == 409, r.text
    assert "feishu" in r.json()["detail"], "冲突必须点名是哪条渠道"
    store = CC._load_store()
    assert sorted(_agentsOf(store, "default")) == sorted(PLATFORMS), "冲突时源表被动过"
    assert _agentsOf(store, "kai")["feishu"]["app_id"] == "kai-own", "冲突时目标表被覆盖"


def test_sameIdentityOnTargetIsRejected(env):
    """存量里已有别的 agent 占着同身份 → 409：迁过去就是同一个 bot 的双接入。

    这份坏状态**只能来自存量**（保存口的身份冲突检测会拦住新建）：换锚未搬迁
    那阵子冲突扫描只看得见空表（见 docs/06-bugfix 的 Bug B），dup 就是那时写进
    旧锚点文件的。故此处直接落盘复现存量，而不是绕开生产门造脏数据。
    """
    c, app = env
    _seedLegacy()
    _as(app, ADMIN)
    store = CC._load_store()
    store["agents"].setdefault("other", {})["feishu"] = {
        "channel_type": "feishu", "enabled": True, "app_id": "bot-feishu", "app_secret": "s", "extra": {},
    }
    CC._save_store(store)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai", "channel_types": ["feishu"]})

    assert r.status_code == 409, r.text
    store = CC._load_store()
    assert sorted(_agentsOf(store, "default")) == sorted(PLATFORMS), "被拒时源表被动过"


# ── 5. 权限 ──────────────────────────────────────────────────────


def test_nonAdminCannotMigrateOutOfDefault(env):
    """源是 default（无主 agent）→ 非 admin 不得处置（与配置门同一口径）。"""
    c, app = env
    _seedLegacy()
    _as(app, OWNER)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai"})

    assert r.status_code == 403, r.text
    assert CC._load_store()["agents"]["default"], "被拒时存量仍应在源表"


def test_nonOwnerCannotMigrateIntoSomeoneAgent(env):
    """目标非自己属主 → 403（不能把默认渠道塞进别人智能体）。"""
    c, app = env
    _seedLegacy()
    _as(app, OWNER)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "other"})

    assert r.status_code == 403, r.text


# ── 6. 空可迁 ────────────────────────────────────────────────────


def test_emptySourceReportsHonestly(env):
    """源表里没东西时诚实返回空清单，不拿成功掩盖"什么都没做"。"""
    c, app = env
    _as(app, ADMIN)

    r = c.post("/api/v1/channel-configs/migrate-agent",
               json={"from_agent_id": "default", "to_agent_id": "kai"})

    assert r.status_code == 200, r.text
    assert r.json()["migrated"] == []
