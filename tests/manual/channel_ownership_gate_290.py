# -*- coding: utf-8 -*-
"""live-verify（Issue #290 追问）：归属门 + 存量归属迁移的真链路自证。

## 判据（不以单测全绿代替）

1. 真 HTTP 链路（TestClient 起真 app 的渠道路由）上，非管理员对 `default`
   视图的读/写/删/测试全 403；管理员全通；
2. 属主自己的 agent 照常可配（门不是"只有管理员能用"）；
3. 迁移端点在真链路上把 `default` 的存量搬到目标 agent：
   - 响应 `migrated` 清单与源表清空、目标表接住**同一份凭据**；
   - **实例跟着换**（`manager.get_adapter` 在目标侧有、源侧无）——这条是
     "迁过去反而连不上"的判据；
   - 冲突时两边原样（不留半截状态）。

## 隔离

数据根走唯一注入口 `NEUROVA_DATA_DIR`（`_liveVerifyIsolation.isolatedDataRoot()`）；
适配器工厂换成记账替身（真凭据建真的平台长连接有外部副作用，取证报告 §4 已点名）。

跑法：`python tests/manual/channel_ownership_gate_290.py`
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaChannelOwnership290")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.auth import get_current_user as auth_u  # noqa: E402
from neurova.api.endpoints import channel_config as cc  # noqa: E402
from neurova.api.endpoints import set_app_state  # noqa: E402
from neurova.channels.manager import ChannelManager  # noqa: E402

PLATFORMS = ("dingtalk", "feishu", "qq")
ADMIN = {"user_id": "root", "username": "root", "role": "admin"}
OWNER = {"user_id": "u1", "username": "u1", "role": "user"}
STRANGER = {"user_id": "u2", "username": "u2", "role": "user"}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


class _CountingAdapter:
    """装配替身：只记账，不建真长连接。"""

    def __init__(self, channel_type: str):
        self.channel_type = channel_type
        self.is_connected = False

    def set_event_callback(self, cb):
        self.cb = cb

    async def connect(self):
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False

    async def health_check(self):
        return {"ok": True}


def _agentWithOwner(agent_id: str, owner):
    return SimpleNamespace(
        agent_id=agent_id,
        config=SimpleNamespace(owner_user_id=owner, agent_id=agent_id),
    )


def _seedLegacy() -> None:
    cc._save_configs({
        p: {"channel_type": p, "enabled": True, "app_id": f"bot-{p}",
            "app_secret": f"sec-{p}", "extra": {}}
        for p in PLATFORMS
    })


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")
    cc._create_adapter = lambda channel_type, cfg: _CountingAdapter(channel_type)

    set_app_state({
        "agents": {
            "default": _agentWithOwner("default", None),
            "kai": _agentWithOwner("kai", "u1"),
        }
    })

    app = FastAPI()
    app.include_router(cc.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)

    ChannelManager._instance = None
    _seedLegacy()

    with TestClient(app, raise_server_exceptions=False) as c:
        # ── [1] 非管理员对 default 一律 403 ──────────────────────────────
        app.dependency_overrides[auth_u] = lambda: dict(STRANGER)
        codes = {
            "读列表": c.get("/api/v1/channel-configs", params={"agent_id": "default"}).status_code,
            "写配置": c.post("/api/v1/channel-configs", params={"agent_id": "default"},
                             json={"channel_type": "telegram", "extra": {"bot_token": "t"}}).status_code,
            "删配置": c.delete("/api/v1/channel-configs/feishu", params={"agent_id": "default"}).status_code,
            "测试连接": c.post("/api/v1/channel-configs/feishu/test", params={"agent_id": "default"},
                               json={"channel_type": "feishu", "app_id": "bot-feishu"}).status_code,
        }
        check("[1] 非管理员对 default 视图全 403", set(codes.values()) == {403}, str(codes))

        # ── [2] 属主对自己的 agent 照常可用（门不是"只有管理员能用"）──
        app.dependency_overrides[auth_u] = lambda: dict(OWNER)
        r = c.post("/api/v1/channel-configs", params={"agent_id": "kai"},
                   json={"channel_type": "telegram", "extra": {"bot_token": "tg-kai"}})
        check("[2] 属主可配自己的 agent", r.status_code == 200, str(r.status_code))

        # ── [3] 管理员对 default 全通 ───────────────────────────────────
        app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
        r = c.get("/api/v1/channel-configs", params={"agent_id": "default"})
        rows_default_before = sorted(x["channel_type"] for x in r.json())
        check("[3] 管理员可读 default", r.status_code == 200 and rows_default_before == sorted(PLATFORMS),
              str(rows_default_before))

        # ── [3.5] 候选源读面（Issue #326 第 1、2 条）────────────────────
        # 用户口径：迁移前先选源、再选既有渠道。这条读面就是把「有哪些可选」
        # 交给用户的那一步 —— 它与迁移门**同一判据**，故此处按两个身份各验一遍。
        r = c.get("/api/v1/channel-configs/migration-sources", params={"to_agent_id": "kai"})
        admin_sources = {x["agent_id"]: x["channels"] for x in (r.json().get("sources") or [])}
        check("[3.5] 管理员可见候选源，渠道清单随候选带回（稳定排序）",
              r.status_code == 200
              and admin_sources.get("default") == sorted(PLATFORMS)
              and "kai" not in admin_sources,
              str(admin_sources))

        app.dependency_overrides[auth_u] = lambda: dict(STRANGER)
        r = c.get("/api/v1/channel-configs/migration-sources", params={"to_agent_id": "kai"})
        stranger_sources = {x["agent_id"] for x in (r.json().get("sources") or [])}
        check("[3.6] 候选面与迁移门同口径：非属主看不见无主/他人的源",
              r.status_code == 200 and "default" not in stranger_sources,
              str(stranger_sources))
        app.dependency_overrides[auth_u] = lambda: dict(ADMIN)

        # ── [4] 迁移：目标表接住同一份凭据、源表清空 ────────────────────
        r = c.post("/api/v1/channel-configs/migrate-agent",
                   json={"from_agent_id": "default", "to_agent_id": "kai"})
        body = r.json()
        check("[4] 迁移端点 200 且清单完整",
              r.status_code == 200 and sorted(body.get("migrated", [])) == sorted(PLATFORMS), str(body))

        store = cc._load_store()
        src_after = sorted((store.get("agents") or {}).get("default") or {})
        dst_after = (store.get("agents") or {}).get("kai") or {}
        check("[5] 源表清空（移动语义，不是复制）", src_after == [], str(src_after))
        check("[6] 目标表拿到存量且凭据原样",
              all(dst_after.get(p, {}).get("app_id") == f"bot-{p}" for p in PLATFORMS),
              str(sorted(dst_after)))

        # ── [7] 实例跟着换（"迁过去反而连不上"的判据）───────────────────
        from neurova.channels.manager import get_channel_manager

        mgr = get_channel_manager()
        dst_instances = [p for p in PLATFORMS if mgr.get_adapter(p, agent_id="kai") is not None]
        src_instances = [p for p in PLATFORMS if mgr.get_adapter(p, agent_id="default") is not None]
        check("[7] 实例随配置换归属", dst_instances == list(PLATFORMS) and src_instances == [],
              f"目标 {dst_instances} / 源 {src_instances}")

        # ── [8] 冲突时两边原样（不留半截状态）──────────────────────────
        # 造"目标已有同渠道"：把 feishu 加回源表，而目标侧早已有它。
        store8 = cc._load_store()
        store8["agents"].setdefault("default", {})["feishu"] = {
            "channel_type": "feishu", "enabled": True, "app_id": "bot-feishu-2",
            "app_secret": "s", "extra": {},
        }
        cc._save_store(store8)
        r2 = c.post("/api/v1/channel-configs/migrate-agent",
                    json={"from_agent_id": "default", "to_agent_id": "kai",
                          "channel_types": ["feishu"]})
        store2 = cc._load_store()
        src2 = (store2.get("agents") or {}).get("default") or {}
        dst2 = (store2.get("agents") or {}).get("kai") or {}
        check("[8] 冲突 409 且两边原样",
              r2.status_code == 409 and "feishu" in r2.json().get("detail", "")
              and src2.get("feishu", {}).get("app_id") == "bot-feishu-2"
              and dst2.get("feishu", {}).get("app_id") == "bot-feishu",
              f"{r2.status_code} / {r2.json().get('detail', '')[:70]}")

        # ── [9] 按 channel_types 收窄：弹层勾选在真链路上的判据（Issue #326）──
        # 前端弹层提交的就是 (源, 目标, 选中渠道) 三元组；此处验它只动被点名的
        # 那几条，其余留在源表（否则「勾选」只是 UI 上的装饰）。
        store9 = cc._load_store()
        store9["agents"].setdefault("default", {}).update({
            p: {"channel_type": p, "enabled": True, "app_id": f"pick-{p}",
                "app_secret": "s", "extra": {}}
            for p in ("feishu", "dingtalk")
        })
        store9["agents"].setdefault("other", {})
        cc._save_store(store9)
        r3 = c.post("/api/v1/channel-configs/migrate-agent",
                    json={"from_agent_id": "default", "to_agent_id": "other",
                          "channel_types": ["feishu"]})
        store3 = cc._load_store()
        moved3 = sorted((store3.get("agents") or {}).get("other") or {})
        left3 = sorted((store3.get("agents") or {}).get("default") or {})
        check("[9] 只迁被点名的渠道，未勾的留在源表",
              r3.status_code == 200 and r3.json().get("migrated") == ["feishu"]
              and moved3 == ["feishu"] and left3 == ["dingtalk"],
              f"{r3.status_code} / moved={moved3} / left={left3}")

    ChannelManager._instance = None
    set_app_state(None)

    print()
    if failures:
        print("LIVE-VERIFY FAILED / Issue #290 归属门与迁移：" + "；".join(failures))
        return 1
    print("LIVE-VERIFY PASSED / Issue #290 归属门与存量迁移")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
