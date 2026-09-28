# -*- coding: utf-8 -*-
"""live-verify（Issue #290 未闭环项⑤）：渠道凭据封存落盘的真链路自证。

## 判据（不以单测全绿代替）

1. 真端点 `POST /channel-configs` 写入带凭据的配置后，**磁盘上**不出现凭据原文；
2. 真 `GET /channel-configs` 与真 `_load_store()` 读回来仍**是原文**
   —— 加密只改磁盘表示，业务链路照旧拿明文（否则适配器拿密文去登录）；
3. 真启动装配 `bootstrap_channel_adapters` 拿到的凭据是原文（同一事实的第三面）；
4. 存量**明文**配置文件下一次保存即迁移为密文，且读回仍是原文（老用户零操作）。

## 隔离

数据根走唯一注入口 `NEUROVA_DATA_DIR`（`_liveVerifyIsolation.isolatedDataRoot()`），
密钥链走 env `NEUROVA_SECRET_KEY`（不碰真实 `data/.secret_key`、不碰 keyring）。
适配器工厂换成记账替身：真凭据建真长连接有外部副作用（取证报告 §4 已点名）。

跑法：`python tests/manual/channel_credential_sealing_290.py`
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaChannelSecret290")
os.environ.setdefault("NEUROVA_SECRET_KEY", "live-verify-key-for-issue-290")
os.environ.setdefault("NEUROVA_AGENT_WORKSPACES_DIR", str(WORK_ROOT / "ws"))
os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "live-verify-jwt-secret-for-290")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.auth import get_current_user as authUser  # noqa: E402
from neurova.api.endpoints import channel_config as cc  # noqa: E402

APP_SECRET = "LIVE-SECRET-290-abc"
BOT_TOKEN = "LIVE-TOKEN-290-xyz"
AGENT = "216fb777"


class _RecordingAdapter:
    """装配替身：只记账，不建真长连接。"""

    channel_type = "feishu"

    def __init__(self):
        self.is_connected = False
        self._cb = None

    def set_event_callback(self, cb):
        self._cb = cb

    async def connect(self):
        self.is_connected = True
        return True

    async def disconnect(self):
        self.is_connected = False


def _seedPlaintextStore(target: Path) -> None:
    """存量明文配置（换锚旧账的形态）。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({
            "version": 2,
            "agents": {"default": {"telegram": {
                "channel_type": "telegram", "enabled": True,
                "extra": {"bot_token": "LEGACY-PLAINTEXT-290"},
            }}},
        }),
        encoding="utf-8",
    )


def main() -> int:
    target = WORK_ROOT / "channel_configs.json"
    _seedPlaintextStore(target)

    app = FastAPI()
    app.include_router(cc.router, prefix="/api/v1")
    app.dependency_overrides[authUser] = lambda: {"user_id": "u", "username": "u", "role": "admin"}
    cc._create_adapter = lambda *a, **k: _RecordingAdapter()

    failures = []
    with TestClient(app) as client:
        resp = client.post(
            f"/api/v1/channel-configs?agent_id={AGENT}",
            json={
                "channel_type": "feishu", "app_id": "cli_x", "app_secret": APP_SECRET,
                "extra": {"bot_token": BOT_TOKEN, "bot_prefix": "@bot"},
            },
        )
        print(f"[1] POST 落盘: {resp.status_code}")
        if resp.status_code != 200:
            failures.append(f"POST 失败: {resp.text}")

        raw = target.read_text(encoding="utf-8")
        for label, secret in (("app_secret", APP_SECRET), ("extra.bot_token", BOT_TOKEN),
                              ("存量 telegram.bot_token", "LEGACY-PLAINTEXT-290")):
            sealed = secret not in raw
            print(f"[2] 磁盘上 {label} 是否已封存: {sealed}")
            if not sealed:
                failures.append(f"{label} 仍以明文落盘")

        store = cc._load_store()
        back = store["agents"][AGENT]["feishu"]
        legacy = store["agents"]["default"]["telegram"]["extra"]["bot_token"]
        ok_top = back["app_secret"] == APP_SECRET
        ok_extra = back["extra"]["bot_token"] == BOT_TOKEN
        ok_legacy = legacy == "LEGACY-PLAINTEXT-290"
        print(f"[3] 读回 app_secret 是否原文: {ok_top}")
        print(f"[4] 读回 extra.bot_token 是否原文: {ok_extra}")
        print(f"[5] 读回存量明文是否原文: {ok_legacy}")
        for label, good in (("app_secret", ok_top), ("extra.bot_token", ok_extra),
                            ("存量 bot_token", ok_legacy)):
            if not good:
                failures.append(f"读回的 {label} 不是原文（适配器将拿密文登录）")

        rows = client.get(f"/api/v1/channel-configs?agent_id={AGENT}").json()
        print(f"[6] GET 行数: {len(rows)} {sorted(r['channel_type'] for r in rows)}")

    seen = []

    def capture(channel_type, config):
        seen.append((channel_type, config))
        return _RecordingAdapter()

    cc._create_adapter = capture
    stats = asyncio.run(cc.bootstrap_channel_adapters())
    print(f"[7] 装配 stats: {stats} ｜ 造出的渠道: {[t for t, _ in seen]}")
    feishu = [cfg for channel_type, cfg in seen if channel_type == "feishu"]
    if not feishu:
        failures.append("装配链没按落盘配置为本轮保存的渠道造适配器")
    else:
        good = feishu[0].app_secret == APP_SECRET and feishu[0].extra.get("bot_token") == BOT_TOKEN
        print(f"[8] 装配拿到的凭据是否原文: {good}")
        if not good:
            failures.append("装配链路拿到的是密文——读侧没解回来")

    if failures:
        print("\nLIVE-VERIFY FAILED / Issue #290 ⑤")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nLIVE-VERIFY PASSED / Issue #290 ⑤")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
