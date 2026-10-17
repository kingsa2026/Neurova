# -*- coding: utf-8 -*-
"""凭据落盘只留一条通道（断点①带出的根因格，用户 2026-10-17 点单甲案）。

缺陷形状：`secret_store` 里并存两套封存实现——
- 窄的一套（`encrypt_config_secrets` / `_walk_api_keys`）只认字面键名 `api_key`，
  而 `shared_config.py` 的读写**恰好走这一套**；
- 递归的一套（`sealSecrets` / `_sealWalk`）按 `CREDENTIAL_KEY_NAMES` 封，只有
  `channel_config.py` 用它。
于是本批把 `oauth.client_secret` 写进 `shared_config.json` 时，磁盘上是明文。
（活体实测抓到；本批前一版判据直接调 `sealSecrets` 验纯函数，证的不是生产那条路。）

教义第 7 条要求同功能只剩一处实现：收口到递归那套，退役窄的那套，`api_key` 并入键名集合。
"""

import ast
import json
from pathlib import Path

import pytest

from neurova.security import secret_store
from neurova.shared_config import SharedConfigManager
from neurova.tool_layers.mcp_config import validate_mcp_server_config

API_KEY_SENTINEL = "probe-api-key-PLAINTEXT-SHOULD-NOT-REACH-DISK"
CLIENT_SECRET_SENTINEL = "probe-client-secret-PLAINTEXT-SHOULD-NOT-REACH-DISK"

_SHARED_CONFIG_SOURCE = (
    # 按 __file__ 锚定，不取 CWD（活体/基线树形态下 CWD 可能已被换到临时目录）
    Path(__file__).resolve().parents[3] / "neurova" / "shared_config.py"
).read_text(encoding="utf-8")


def _calledOrLoadedNames(source):
    """取一个模块里「被调用的名字 + 被导入的名字」。

    按 AST 判代码身份，不扫源码文本——注释里提到某个退役符号不该让判据红，
    反之真调用不许因为写成 `mod.fn()` 的属性形态而漏检。
    """
    names = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.name.split(".")[0] for alias in node.names)
            names.update(alias.name for alias in node.names)
    return names


@pytest.fixture
def configPath(tmp_path):
    return str(tmp_path / "shared_config.json")


def _raw(configPath):
    with open(configPath, encoding="utf-8") as handle:
        return handle.read()


def _mcpEntryWithSecret():
    """带凭据的 MCP 记录——凭据放在 `env` 里（schema 允许的自由 str→str 字典）。

    本档证的是「按**键名**递归封存」这条通道本身，与 `oauth` 子配置无关：
    用 env 落 `client_secret` 才能与「oauth 写侧」那笔解耦，两笔各自独立成立。
    """
    return validate_mcp_server_config({
        "id": "sealed-srv",
        "transport": "http",
        "url": "https://remote.example.com/mcp",
        "env": {"client_secret": CLIENT_SECRET_SENTINEL, "REGION": "cn-north"},
    })


class TestSealingGoesThroughRealManager:
    """判据一律走真 `SharedConfigManager`（写侧生产入口），不直接调封存函数。"""

    def test_llmApiKeyIsNotPlaintextOnDisk(self, configPath):
        manager = SharedConfigManager(configPath)
        assert manager.add_llm_provider({"id": "p1", "name": "P1", "api_key": API_KEY_SENTINEL})
        assert API_KEY_SENTINEL not in _raw(configPath)

    def test_llmApiKeyReadsBackInPlaintext(self, configPath):
        SharedConfigManager(configPath).add_llm_provider(
            {"id": "p1", "name": "P1", "api_key": API_KEY_SENTINEL}
        )
        reloaded = SharedConfigManager(configPath).list_llm_providers()
        assert next(p for p in reloaded if p["id"] == "p1")["api_key"] == API_KEY_SENTINEL

    def test_clientSecretInsideServerEnvIsNotPlaintextOnDisk(self, configPath):
        manager = SharedConfigManager(configPath)
        assert manager.add_mcp_server(_mcpEntryWithSecret())
        assert CLIENT_SECRET_SENTINEL not in _raw(configPath)

    def test_clientSecretInsideServerEnvReadsBackInPlaintext(self, configPath):
        SharedConfigManager(configPath).add_mcp_server(_mcpEntryWithSecret())
        entry = SharedConfigManager(configPath).get_mcp_server("sealed-srv")
        assert entry["env"]["client_secret"] == CLIENT_SECRET_SENTINEL

    def test_nonCredentialKeysStayReadableAsPlaintext(self, configPath):
        # 反向控制（与 test_channel_credential_sealing_290 同族）：收口不得把
        # id/url/enabled 与非凭据键一并加密——那会破坏重复检测与掩码回读
        SharedConfigManager(configPath).add_mcp_server(_mcpEntryWithSecret())
        raw = _raw(configPath)
        assert "sealed-srv" in raw and "https://remote.example.com/mcp" in raw
        assert "cn-north" in raw

    def test_preExistingPlaintextValuesStillReadable(self, configPath):
        # 存量兼容：历史上窄通道没管住的键是明文落盘的，收口后必须照读
        with open(configPath, "w", encoding="utf-8") as handle:
            json.dump({
                "llm_providers": [{"id": "legacy", "api_key": API_KEY_SENTINEL}],
                "mcp_servers": [_mcpEntryWithSecret()],
                "last_updated": "2026-01-01T00:00:00",
            }, handle, ensure_ascii=False)
        manager = SharedConfigManager(configPath)
        assert manager.list_llm_providers()[0]["api_key"] == API_KEY_SENTINEL
        assert manager.get_mcp_server("sealed-srv")["env"]["client_secret"] == CLIENT_SECRET_SENTINEL

    def test_preExistingCipherValuesStillReadable(self, configPath):
        # 存量兼容：窄通道早已封过的 api_key（enc:v1: 形态）在新通道下必须照解
        sealed = secret_store.encrypt_secret(API_KEY_SENTINEL)
        assert sealed.startswith(secret_store._ENC_PREFIX)
        with open(configPath, "w", encoding="utf-8") as handle:
            json.dump({"llm_providers": [{"id": "old", "api_key": sealed}]}, handle)
        assert SharedConfigManager(configPath).list_llm_providers()[0]["api_key"] == API_KEY_SENTINEL


class TestSingleChannelShape:
    """退役形态判据：按 AST 判代码身份，不钉文档措辞。"""

    NARROW_SYMBOLS = ("encrypt_config_secrets", "decrypt_config_secrets", "_walk_api_keys")

    def test_narrowChannelSymbolsRetired(self):
        for name in self.NARROW_SYMBOLS:
            assert not hasattr(secret_store, name), f"窄通道符号 {name} 仍在世＝两套并存未闭环"

    def test_sharedConfigNoLongerReferencesNarrowChannel(self):
        source = _SHARED_CONFIG_SOURCE
        referenced = {
            name for name in _calledOrLoadedNames(source) if name in self.NARROW_SYMBOLS
        }
        assert not referenced, f"shared_config 仍引用窄通道：{sorted(referenced)}"

    def test_recursiveChannelIsTheOnlySealerUsedBySharedConfig(self):
        used = _calledOrLoadedNames(_SHARED_CONFIG_SOURCE)
        missing = {"sealSecrets", "unsealSecrets"} - used
        assert not missing, f"收口未接上递归通道，缺：{sorted(missing)}"

    def testApiKeyBelongsToCredentialKeySet(self):
        assert "api_key" in secret_store.CREDENTIAL_KEY_NAMES

    def test_oauthClientSecretNameIsAlreadyInCredentialKeySet(self):
        # 正向钉：新落点的键名本就在集合里，收口才谈得上覆盖它
        assert "client_secret" in secret_store.CREDENTIAL_KEY_NAMES
