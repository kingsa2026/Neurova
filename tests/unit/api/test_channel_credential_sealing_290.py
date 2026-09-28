# -*- coding: utf-8 -*-
"""渠道凭据落盘加密（Issue #290 未闭环项⑤：`app_secret` 明文落盘的旧账）。

## 缺陷（本仓早已登记，见 `docs/空数据页面与保存落盘排查_2026-09-12.md` §D）

`channel_config.py` 的保存路径注释写着「不保存明文密钥到文件」，实际把
`ChannelConfigRequest` 原样 `safe_model_dump` 后写盘——**注释与行为相反**：

    app_secret / client_secret / bot_token / secret_key / access_token / password …
    全部以明文落在 `channel_configs.json`。

换锚救济（本单第一批）把这份明文一起搬到新落点，等于把旧账从一份文件挪到另一份。
用户侧的直接后果：任何拿到该文件的人（备份、云同步、误传的附件）都握有平台凭据，
而界面上的「密码」字段与掩码只掩住了展示面。

## 修法（教义第 1 条：在产生非法状态的上游修）

落盘的唯一写入口是 `_save_store()`，唯一读入口是 `_load_store()`。在这两处加
「凭据字段加密落盘 / 读回解密」，业务链路（装配、冲突检测、扫码回填）**照旧拿明文**
——加密只改变磁盘上的表示，不改内存契约，也就不会在消费端造第二份语义。

加密原语不新造：复用 `neurova/security/secret_store.py`（`enc:v1:` Fernet，
密钥链 env → keyring → `data/.secret_key`），与 `shared_config.py` 的 api_key
同源同格式；明文旧文件读侧原样透传，下一次保存自动迁移为密文（幂等）。

## 判据（各带反向控制）

1. 顶层 `app_secret` 落盘不是明文，且读回来仍是原文（业务可用）；
2. `extra` 里的凭据（`bot_token` 等）同样不落明文，读回原文；
3. **反向控制**：装配链路必须拿到真凭据（防「加密了但忘了解密」这种把功能打死的修法）；
4. 存量明文文件下一次保存即迁移为密文（老用户不需要手工操作）；
5. 重复保存不叠前缀（幂等）；
6. 配置文件损坏时**点名**告警，不静默当「没有配置」——空表与读不到必须在日志里可区分。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.security import secret_store

PROJECT_ROOT = Path(__file__).resolve().parents[3]

ADMIN = {"user_id": "u", "username": "u", "role": "admin"}

APP_SECRET = "REAL-SECRET-42"
BOT_TOKEN = "TOKEN-42"
ENC_PREFIX = "enc:v1:"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """隔离：落点走唯一注入口 `NEUROVA_DATA_DIR`，密钥链走 env（不碰真实 .secret_key）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEUROVA_SECRET_KEY", "unit-test-key-for-channel-secrets")
    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    monkeypatch.setattr(CC, "_create_adapter", lambda *a, **k: None)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, tmp_path
    app.dependency_overrides.clear()


def _storeFile(tmp_path):
    return tmp_path / "channel_configs.json"


def _postFeishu(client, agent_id="216fb777"):
    return client.post(
        "/api/v1/channel-configs",
        params={"agent_id": agent_id},
        json={
            "channel_type": "feishu",
            "app_id": "cli_x",
            "app_secret": APP_SECRET,
            "extra": {"bot_token": BOT_TOKEN, "bot_prefix": "@bot"},
        },
    )


class TestSecretsAreNotPlainOnDisk:
    """判据 1/2：落盘不得出现凭据原文；读回必须是原文（业务仍可用）。"""

    def test_topLevelSecretIsSealedOnDisk(self, api):
        client, tmp_path = api
        assert _postFeishu(client).status_code == 200

        raw = _storeFile(tmp_path).read_text(encoding="utf-8")

        assert APP_SECRET not in raw, (
            "app_secret 以明文落盘 —— 注释写着「不保存明文密钥到文件」，"
            "而任何拿到该文件的人都握有平台凭据"
        )
        assert ENC_PREFIX in raw, "落盘未见密文标记，说明凭据没经加密通道"
        stored = json.loads(raw)["agents"]["216fb777"]["feishu"]
        assert stored["app_secret"] != APP_SECRET

    def test_extraCredentialsAreSealedOnDisk(self, api):
        client, tmp_path = api
        assert _postFeishu(client).status_code == 200

        raw = _storeFile(tmp_path).read_text(encoding="utf-8")

        assert BOT_TOKEN not in raw, (
            "extra 里的 bot_token 明文落盘 —— 同一根因的第二批命中点"
            "（app_secret 只是这一族凭据里最先被点名的那个）"
        )
        stored = json.loads(raw)["agents"]["216fb777"]["feishu"]["extra"]
        assert stored["bot_token"] != BOT_TOKEN
        assert stored["bot_prefix"] == "@bot", "非凭据字段不该被改写"

    def test_secretsReadBackAsPlainText(self, api):
        """写进去的凭据读回来必须还是原文——加密只改磁盘表示，不改内存契约。"""
        client, tmp_path = api
        assert _postFeishu(client).status_code == 200

        store = CC._load_store()
        cfg = store["agents"]["216fb777"]["feishu"]

        assert cfg["app_secret"] == APP_SECRET, "读回的不是真凭据，适配器将拿密文去登录"
        assert cfg["extra"]["bot_token"] == BOT_TOKEN


class TestAdaptersStillGetRealCredentials:
    """判据 3（反向控制）：装配链路必须拿到真凭据，不是密文。"""

    def test_bootstrapSeesPlainCredentials(self, api, monkeypatch):
        import asyncio

        client, _ = api
        assert _postFeishu(client).status_code == 200

        seen = []

        class _RecordingAdapter:
            """装配替身：只记账，不建真长连接（避免测试外呼）。"""

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

        def capture(channel_type, config):
            seen.append((channel_type, config))
            return _RecordingAdapter()

        monkeypatch.setattr(CC, "_create_adapter", capture)
        stats = asyncio.run(CC.bootstrap_channel_adapters())

        assert seen, "装配链没有按落盘配置造适配器"
        _, cfg = seen[0]
        assert cfg.app_secret == APP_SECRET, "适配器拿到的是密文 —— 加密通道读侧没解回来"
        assert cfg.extra.get("bot_token") == BOT_TOKEN
        assert stats["registered"] == 1


class TestLegacyPlaintextStoreMigrates:
    """判据 4/5：存量明文文件下一次保存即迁移；重复保存不叠前缀。"""

    def test_plaintextFileIsSealedOnNextSave(self, api):
        client, tmp_path = api
        store = {
            "version": 2,
            "agents": {"default": {"telegram": {
                "channel_type": "telegram", "enabled": True,
                "app_id": "", "app_secret": "",
                "extra": {"bot_token": "legacy-token-7"},
            }}},
        }
        _storeFile(tmp_path).write_text(json.dumps(store), encoding="utf-8")

        assert CC._load_store()["agents"]["default"]["telegram"]["extra"]["bot_token"] == "legacy-token-7"
        assert client.post(
            "/api/v1/channel-configs", params={"agent_id": "216fb777"},
            json={"channel_type": "feishu", "app_id": "cli_x", "app_secret": APP_SECRET},
        ).status_code == 200

        raw = _storeFile(tmp_path).read_text(encoding="utf-8")

        assert "legacy-token-7" not in raw, "存量明文凭据未在下一次保存时迁移为密文"
        assert CC._load_store()["agents"]["default"]["telegram"]["extra"]["bot_token"] == "legacy-token-7"

    def test_repeatedSaveDoesNotStackPrefixes(self, api):
        client, tmp_path = api
        assert _postFeishu(client).status_code == 200
        assert _postFeishu(client).status_code == 200

        raw = _storeFile(tmp_path).read_text(encoding="utf-8")

        assert raw.count(ENC_PREFIX + ENC_PREFIX) == 0, "重复保存把已加密的值再加密了一层"
        assert CC._load_store()["agents"]["216fb777"]["feishu"]["app_secret"] == APP_SECRET


class TestCorruptStoreIsNamedNotSilent:
    """判据 6：空表与「读不到」必须在日志里可区分（教义第 2 条：不静默）。"""

    def test_corruptFileIsNamedInLog(self, api, caplog):
        _, tmp_path = api
        _storeFile(tmp_path).write_text("{ this is not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="neurova.api.endpoints.channel_config"):
            store = CC._load_store()

        assert store["agents"] == {}
        assert any(
            str(_storeFile(tmp_path)) in record.getMessage() for record in caplog.records
        ), "配置文件损坏被静默当成「没有配置」——用户看不到任何线索"

class TestSealSetMatchesTheOtherLanguageFace:
    """判据 7（单一事实源）：前后端两张「凭据字段」表必须逐名咬合。

    前端 `channelFields.ts` 的 `type: 'password'` 管「渲染成密码框」，
    后端 `CREDENTIAL_KEY_NAMES` 管「落盘要封」。两边各改各的就会漏：
    前端新加一个密码字段而落盘集合没收 → 那个字段的明文照旧躺进磁盘，
    而界面上它明明是个密码框（用户以为它被保护了）。
    """

    FIELDS_TS = PROJECT_ROOT / "NeurUI" / "src" / "config" / "channelFields.ts"
    PASSWORD_ENTRY = re.compile(r"\{[^{}]*type:\s*'password'[^{}]*\}", re.S)
    KEY_OF = re.compile(r"key:\s*'([^']+)'")

    def _frontendPasswordKeys(self) -> set:
        text = self.FIELDS_TS.read_text(encoding="utf-8")
        keys = set()
        for entry in self.PASSWORD_ENTRY.findall(text):
            match = self.KEY_OF.search(entry)
            if match:
                keys.add(match.group(1))
        return keys

    def test_everyFrontendPasswordFieldIsSealed(self):
        frontend = self._frontendPasswordKeys()

        assert frontend, "没从 channelFields.ts 读出任何密码字段——解析口径失效，判据等于没跑"
        missing = sorted(frontend - set(secret_store.CREDENTIAL_KEY_NAMES))
        assert not missing, (
            f"前端声明为密码字段但落盘不封存：{missing}\n"
            "两面对同一件事给不同答案，用户以为它被保护而磁盘上是明文。"
        )

    def test_nonCredentialKeysAreNotSweptIn(self):
        """反向控制：身份/路径/开关类键名不得混进封存集合。"""
        intruders = sorted(
            {"app_id", "agent_id", "homeserver_url", "bot_prefix", "use_stream", "media_directory"}
            & set(secret_store.CREDENTIAL_KEY_NAMES)
        )

        assert not intruders, (
            f"非凭据键被收进封存集合：{intruders}——把集合塞满会让判据看起来更\u201c绿\u201d，"
            "实际把身份字段也加密，冲突检测与掩码回读会当场坏掉。"
        )
