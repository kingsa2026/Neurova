# -*- coding: utf-8 -*-
"""live-verify（Issue #290 / Bug B）：渠道配置换锚后存量搬迁的真链路自证。

## 判据（不以单测全绿代替）

1. 真端点 `GET /api/v1/channel-configs?agent_id=default` 读到搬回来的存量
   （取证报告 §2.3 在旧锚点实测到的 5 个平台）；
2. 真启动装配 `bootstrap_channel_adapters` 的 `registered` == 5
   —— 改前该读数是 `{registered: 0, connected: 0, skipped: 0, failed: 0}`，
   全零看起来"一切正常"，这正是本 bug 被拖了 6 天没人定位到落点的原因；
3. 两侧都在时点名旧落点，不静默。

## 隔离

数据根走唯一注入口 `NEUROVA_DATA_DIR`（`_liveVerifyIsolation.isolatedDataRoot()`），
旧锚点落在伪仓库根下 —— 全程不碰本机真实 `data/` 与真实 `neurova/data/`。
适配器工厂换成记账替身：真凭据建真长连接有外部副作用（取证报告 §4 已点名）。

跑法：`python tests/manual/channel_landing_anchor_290.py`
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaChannel290")

PLATFORMS = ("dingtalk", "feishu", "qq", "wechat", "wecom")
LEGACY_RELATIVE = ("neurova", "data", "channel_configs.json")


def _legacyStore() -> str:
    agents = {
        platform: {
            "channel_type": platform,
            "enabled": True,
            "app_id": "bot-%s" % platform,
            "app_secret": "s",
            "extra": {"bot_token": "tok"} if platform == "wechat" else {},
        }
        for platform in PLATFORMS
    }
    return json.dumps({"version": 2, "agents": {"default": agents}}, ensure_ascii=False)


class _CountingAdapter:
    """装配替身：只记账，不建真长连接。"""

    def __init__(self, channel_type: str):
        self.channel_type = channel_type
        self.is_connected = False

    def set_event_callback(self, callback):
        self.callback = callback

    async def connect(self) -> bool:
        self.is_connected = True
        return True

    async def disconnect(self) -> None:
        self.is_connected = False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    fake_repo = WORK_ROOT / "repo"
    legacy = fake_repo.joinpath(*LEGACY_RELATIVE)
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(_legacyStore(), encoding="utf-8")

    from neurova.core import data_root

    data_root.repoRoot = lambda: fake_repo

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import channel_config as cc
    from neurova.channels.manager import ChannelManager

    app = FastAPI()
    app.include_router(cc.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "u", "username": "u", "role": "admin",
    }

    print("[1] 落点读数:", cc._configFile())
    print("[1] 数据根:", WORK_ROOT)
    assert str(WORK_ROOT) in str(cc._configFile()), "落点没走注入的数据根"
    with TestClient(app) as client:
        rows = client.get("/api/v1/channel-configs", params={"agent_id": "default"}).json()
    print("[1] GET 行数:", len(rows), sorted(r["channel_type"] for r in rows))
    assert len(rows) == len(PLATFORMS), "真端点没读到搬回来的存量"
    assert not legacy.exists(), "旧物应已搬走，不该留两份"

    print()
    print("[2] 启动装配（真 bootstrap，工厂换记账替身）")
    originalFactory = cc._create_adapter
    cc._create_adapter = lambda channel_type, config: _CountingAdapter(channel_type)
    ChannelManager._instance = None
    try:
        stats = asyncio.run(cc.bootstrap_channel_adapters())
    finally:
        cc._create_adapter = originalFactory
        ChannelManager._instance = None
    print("[2] stats:", stats)
    assert stats["registered"] == len(PLATFORMS), "启动装配没按存量重建"
    assert stats["registered"] + stats["skipped"] == len(PLATFORMS)

    print()
    print("[3] 两侧都在：不静默（新落点胜出 + 点名旧落点）")
    legacy.write_text(_legacyStore(), encoding="utf-8")
    data_root.nameConflictOnce.cache_clear()
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture(level=logging.WARNING)
    logging.getLogger("neurova.core.data_root").addHandler(handler)
    try:
        cc._load_store()
    finally:
        logging.getLogger("neurova.core.data_root").removeHandler(handler)

    named = [m for m in captured if str(legacy) in m]
    print("[3] 点名原文:", named)
    assert named, "两侧同时存在必须点名旧落点路径，不许静默"
    assert legacy.exists(), "冲突路径上不该搬走旧物（交人工核对）"

    print()
    print("LIVE-VERIFY PASSED / Issue #290 Bug B")


if __name__ == "__main__":
    main()
