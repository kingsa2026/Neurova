# -*- coding: utf-8 -*-
"""渠道配置落点：存量搬迁 + 活锚点守卫（Issue #290 取证报告 Bug B）。

## 根因（2026-09-28 取证，A/B 双锚点跑真代码实测）

`721ef038`（"剩余数据落点全量收口到数据根"）把本模块的配置锚点从
包内 `<仓库>/neurova/data` 换到数据根 `<仓库>/data`，**没有带存量搬迁**：

    旧：CONFIG_DIR = Path(__file__).parent.parent.parent / "data"   → neurova/data/
    新：CONFIG_DIR = get_data_root()                                 → <仓库根>/data/

旧锚点那份带着真实凭据的配置从此**再无人读**——`_load_store()` 在新锚点找不到
文件即走 `if not CONFIG_FILE.exists(): return {"version": 2, "agents": {}}`，
**静默返回空表**：不报错、不告警、不日志。用户侧是"所有渠道配置全没了"：
页面全未启用、重启后一个适配器都不连接（装配读到空 store，日志
`registered: 0` 看起来一切正常）、跨 agent 身份冲突检测（`_identity_conflict_owner`
只扫 `_load_store()` 的结果）同时失明，双长连接串台不再被 409 拦住。

## 为什么既有守卫没拦住

`tests/unit/core/test_data_root_no_cwd_landing.py` 的判据是**源码字形**
（"生产代码里不得出现第二份根"）——它把本模块从红扫到绿，却对"绿了以后原来的
数据还在不在"零判据。渠道配置类测试又**全部** monkeypatch 落点
（`monkeypatch.setattr(cc, "CONFIG_FILE", ...)`），于是锚点本身从未被断言过，
落点换没换、换完有没有搬，没有任何一条判据咬合。

## 判据（各带反向控制）

1. **活锚点**：落点必须由数据根**调用时**推导（`NEUROVA_DATA_DIR` 注入即生效），
   且本模块不得自己反推第二份根；
2. **搬迁**：旧锚点有存量、新锚点空缺 → 读到真实平台数，且旧锚点不再存在；
3. **不覆盖**：新锚点已有文件时旧物绝不覆盖（旧物只作空缺时的救济）；
4. **冲突点名**：两侧都在时不静默 —— 新锚点内容胜出，且日志点出旧落点路径。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

from neurova.api.endpoints import channel_config as cc
from neurova.channels.manager import ChannelManager
from neurova.core import data_root
from neurova.core.data_root import get_data_root

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 旧锚点（相对仓库根）—— 即换锚前的 `Path(__file__).parent.parent.parent / "data"`。
LEGACY_PARTS = ("neurova", "data", "channel_configs.json")

#: 取证报告 §2.3 在旧锚点实测到的平台集合。
PLATFORMS = ("dingtalk", "feishu", "qq", "wechat", "wecom")


def _legacyStore() -> str:
    """旧锚点的一份存量（形状与真实文件一致：v2 + default agent 下 5 个平台）。"""
    agents = {
        platform: {
            "channel_type": platform,
            "enabled": True,
            "app_id": "bot-%s" % platform,
            "app_secret": "s",
            "extra": {"bot_token": "t"} if platform == "wechat" else {},
        }
        for platform in PLATFORMS
    }
    return json.dumps({"version": 2, "agents": {"default": agents}}, ensure_ascii=False)


class TestLandingFollowsTheInjectionPoint:
    """判据 1：落点由数据根推导，且**调用时**解析（注入才对延迟装配生效）。"""

    def test_landingIsUnderDataRoot(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "dataRoot"))

        assert cc._configFile() == tmp_path / "dataRoot" / "channel_configs.json"

    def test_lateInjectionIsHonored(self, tmp_path, monkeypatch):
        """反向控制：先解析一次，再换注入值 —— 必须跟着换。

        模块级常量做不到这一点（导入期就定死了），而落点会随部署漂移——
        这正是"靠 monkeypatch 常量隔离"的测试形态盖住锚点真相的入口。
        """
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "first"))
        assert cc._configFile() == tmp_path / "first" / "channel_configs.json"

        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "second"))
        assert cc._configFile() == tmp_path / "second" / "channel_configs.json"

    def test_moduleDoesNotDeriveASecondRoot(self):
        source = Path(cc.__file__).read_text(encoding="utf-8")

        assert "parents[" not in source, "本模块又按层数反推了一份数据根"

    def test_defaultLandingIsTheRepoDataRoot(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_DATA_DIR", raising=False)

        assert cc._configFile() == get_data_root() / "channel_configs.json"


@pytest.fixture()
def landing(tmp_path, monkeypatch):
    """双锚点：旧锚点在伪仓库根下，新锚点在临时数据根下（都不碰真实目录）。"""
    legacy_root = tmp_path / "repo"
    legacy = legacy_root.joinpath(*LEGACY_PARTS)
    legacy.parent.mkdir(parents=True)
    target_root = tmp_path / "dataRoot"

    monkeypatch.setattr(data_root, "repoRoot", lambda: legacy_root)
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(target_root))
    return legacy, target_root


class TestLegacyStoreIsRelocated:
    """判据 2/3/4：换锚未搬迁的存量必须被收养，且不覆盖、不静默。"""

    def test_legacyStoreIsRelocatedOnRead(self, landing):
        legacy, target_root = landing
        legacy.write_text(_legacyStore(), encoding="utf-8")

        store = cc._load_store()

        assert set(store["agents"]["default"]) == set(PLATFORMS), (
            "旧锚点的存量没被搬进数据根 —— 用户侧就是'配置全没了'"
        )
        assert (target_root / "channel_configs.json").exists(), "新锚点未出现该文件"
        assert not legacy.exists(), "旧锚点文件应已搬走，不该留两份"

    def test_relocationIsIdempotentAndNeverOverwrites(self, landing):
        legacy, target_root = landing
        legacy.write_text(_legacyStore(), encoding="utf-8")
        cc._load_store()

        target = target_root / "channel_configs.json"
        target.write_text(
            json.dumps({"version": 2, "agents": {"a1": {"feishu": {"channel_type": "feishu", "enabled": True}}}}),
            encoding="utf-8",
        )
        # 旧物再次出现（备份回滚 / 旧版本再写了一次）：新锚点已是事实源，不得被盖回
        legacy.write_text(_legacyStore(), encoding="utf-8")

        store = cc._load_store()

        assert set(store["agents"]) == {"a1"}, "新锚点已有的内容被旧物覆盖了"
        assert set(json.loads(target.read_text(encoding="utf-8"))["agents"]) == {"a1"}

    def test_conflictIsNamedNotSilent(self, landing, caplog):
        legacy, target_root = landing
        target = target_root / "channel_configs.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"version": 2, "agents": {"a1": {"feishu": {"channel_type": "feishu", "enabled": True}}}}),
            encoding="utf-8",
        )
        legacy.write_text(_legacyStore(), encoding="utf-8")
        data_root.nameConflictOnce.cache_clear()

        with caplog.at_level(logging.WARNING, logger="neurova.core.data_root"):
            store = cc._load_store()

        assert set(store["agents"]) == {"a1"}, "两侧都在时新锚点内容必须原样胜出"
        assert legacy.exists(), "冲突的旧物应由人核对后处置，不在冲突路径上搬走"
        assert any(str(legacy) in record.getMessage() for record in caplog.records), (
            "两侧同时存在必须点名旧落点路径，不许静默"
        )


class _CountingAdapter:
    """装配替身：只记账，不建真长连接（取证报告 §4 点名真连接有外部副作用）。"""

    def __init__(self, channel_type: str):
        self.channel_type = channel_type
        self.is_connected = False
        self.connect_calls = 0

    def set_event_callback(self, callback):
        self.callback = callback

    async def connect(self) -> bool:
        self.connect_calls += 1
        self.is_connected = True
        return True

    async def disconnect(self) -> None:
        self.is_connected = False


class TestBootstrapSeesRelocatedStore:
    """live-verify：启动装配必须按搬回来的存量重建适配器。

    改前实测：`bootstrap_channel_adapters` 读到空表 → 日志
    `渠道启动装配完成: {registered: 0, connected: 0, skipped: 0, failed: 0}`
    —— 全零看起来"一切正常"，这正是本 bug 被拖了 6 天没人定位到落点的原因。
    """

    def test_bootstrapRegistersRelocatedPlatforms(self, landing, monkeypatch):
        legacy, _ = landing
        legacy.write_text(_legacyStore(), encoding="utf-8")
        monkeypatch.setattr(cc, "_create_adapter", lambda channel_type, config: _CountingAdapter(channel_type))
        ChannelManager._instance = None
        try:
            stats = asyncio.run(cc.bootstrap_channel_adapters())
        finally:
            ChannelManager._instance = None

        assert stats["registered"] == len(PLATFORMS), "启动装配没按搬回来的存量重建适配器"
        assert stats["registered"] + stats["skipped"] == len(PLATFORMS)
        assert stats["failed"] == 0
        assert stats["connected"] == len(PLATFORMS)


class TestGuardIsProtected:
    """守卫必须真进 CI 受保护子集——"绿"要和"跑过"是同一件事。"""

    def test_listedInProtectedSubset(self):
        listed = (PROJECT_ROOT / "scripts" / "ci" / "protected_tests.txt").read_text(encoding="utf-8")

        assert "tests/unit/api/test_channel_config_landing_anchor.py" in listed, \
            "本守卫不在受保护子集里，CI 不会跑它"
