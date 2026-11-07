# -*- coding: utf-8 -*-
"""批 C7a：企微会话内容存档凭据面与就绪读数（2026-11-08 裁定甲案＋A/B/C/D 按推荐）。

方案出处：`docs/specs/2026-11-07-wecom-chat-archive-history-source-plan.md` §6.1/§7/§11/§16。

## 判据（全部红在行为断言上，不红在 import）

新模块**不在本档 import**——缺席时整档仍照常收集，每条判据各自红在它咬的那个行为上：

- **写边界**（`POST /api/v1/channel-configs`，真 HTTP 栈）：明文 Secret / PEM 私钥进 `extra`
  即 400，且拒绝理由不回显密钥内容；指针型配置（路径/环境变量名/版本→路径映射）照常 200。
- **读边界**（`ChatChannelAdapter.health()`，企业源侧唯一消费点）：历史缺口读数必须来自
  通道层同一份判断——原生库未配置/文件不存在/不可加载、Secret env 未设/为空、
  私钥映射缺失/文件不存在/位数不对/内容不是私钥，各档各自点名；凭据齐了也仍 degraded
  并点名读取面属 C7b 未实现（C7a 不含拉取逻辑，报 ok 就是冒充全量可达）。
- **权限位**：POSIX 下 group/other 可读即拒；Windows 无 POSIX 权限位则如实点名 NTFS ACL，
  不假装校验通过（教义第 2 条禁表面抹除）。两档都 skipif 对侧平台，故另加一条结构反证
  钉住「实装里两档都在」，防只写一档靠 skip 蒙过。
- **单源退役**：官方只分发 C 动态库、无官方 Python 包（§16-1）⇒ 仓内 `WeWorkFinanceSdk`
  模块名不对应任何可安装件、那次 `importlib` 探测恒 ImportError＝假判据，须退役；
  企业源适配器不得自己碰 ctypes/凭据字段名（甲案：零凭据）。

夹具＝真 `ChannelConfig`＋真 `WeComAdapter`（构造期零 I/O）＋真 RSA 私钥文件＋按生产 DDL
自建捕获面库；动态加载器是 OS 边界，用**手写哨兵**替并记录被调路径（证明分支真被走到），
不用 mock 冒充业务对象。
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import channel_config as CC
from neurova.channels.base import ChannelConfig
from neurova.channels.channel_ingress_queue import _SCHEMA as INGRESS_SCHEMA
from neurova.channels.manager import get_channel_manager
from neurova.channels.wecom import WeComAdapter
from neurova.knowledge.enterprise.connectors_chat import ChatChannelAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CHANNELS = PROJECT_ROOT / "neurova" / "channels"
CONNECTORS_CHAT = PROJECT_ROOT / "neurova" / "knowledge" / "enterprise" / "connectors_chat.py"
ARCHIVE_MODULE = CHANNELS / "wecom_archive.py"

ADMIN = {"user_id": "u", "username": "u", "role": "admin"}
SDK_FIELD = "archiveSdkPath"
SECRET_ENV_FIELD = "archiveSecretEnv"
KEYS_FIELD = "archivePrivateKeys"
SDK_PATH_ENV = "NEUROVA_WECOM_ARCHIVE_SDK"
SECRET_ENV_NAME = "NEUROVA_UNIT_ARCHIVE_SECRET"
SECRET_VALUE = "archive-secret-DO-NOT-LEAK-42"
PEM_MARKER = "-----BEGIN"


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsaKeys(tmp_path_factory):
    """真 RSA 私钥文件：2048 位（官方口径）与 1024 位（反证位数判据真咬）。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    root = tmp_path_factory.mktemp("archive-keys")
    out = {}
    for bits in (2048, 1024):
        key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
        path = root / ("rsa-%d.pem" % bits)
        path.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
        out[bits] = path
    return out


@pytest.fixture()
def loadableSdk(tmp_path, monkeypatch):
    """把动态加载器换成记录路径的手写哨兵：证明「按配置路径去加载」这一分支真被走到。

    替的是 OS 边界（`ctypes.CDLL`），不是业务对象；哨兵恒真不了——它只记路径。
    """
    import ctypes

    libFile = tmp_path / "libwecomarchive.so"
    libFile.write_bytes(b"\x7fELF-placeholder")
    loaded = []

    class _LoadedLibrary:
        def __init__(self, path):
            self.path = path

    def _fakeCDLL(path, *args, **kwargs):
        loaded.append(str(path))
        return _LoadedLibrary(str(path))

    monkeypatch.setattr(ctypes, "CDLL", _fakeCDLL)
    return libFile, loaded


@pytest.fixture()
def api(tmp_path, monkeypatch):
    """渠道配置写入口的真 HTTP 栈（落点与密钥链都走唯一注入口，不碰真实数据根）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NEUROVA_SECRET_KEY", "unit-test-key-for-archive-face")
    app = FastAPI()
    app.include_router(CC.router, prefix="/api/v1")
    app.dependency_overrides[auth_u] = lambda: dict(ADMIN)
    monkeypatch.setattr(CC, "_create_adapter", lambda *a, **k: None)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _postWecom(client, extra):
    return client.post(
        "/api/v1/channel-configs",
        params={"agent_id": "default"},
        json={"channel_type": "wecom", "app_id": "ww_unit_corp",
              "app_secret": "unit-app-secret", "extra": extra},
    )


def _healthWith(tmp_path, extra, *, vendor="wecom", installChannel=True):
    """读边界：真渠道配置 → 真企业源适配器 → health()（捕获面库按生产 DDL 自建）。"""
    db = tmp_path / "channel_ingress.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(INGRESS_SCHEMA)
        conn.commit()
    finally:
        conn.close()

    manager = get_channel_manager()
    manager.unregister_adapter("wecom", agent_id="default")
    if installChannel and vendor == "wecom":
        manager.register_adapter(WeComAdapter(ChannelConfig(
            channel_type="wecom", enabled=True, app_id="ww_unit_corp",
            app_secret="unit-app-secret", extra=dict(extra),
        )), agent_id="default")
    loop = asyncio.new_event_loop()
    try:
        adapter = ChatChannelAdapter(
            {"sourceType": "chat", "vendor": vendor, "ingressDb": str(db),
             "agentId": "default"}, "unit_chat", "default")
        return loop.run_until_complete(adapter.health())
    finally:
        loop.close()
        manager.unregister_adapter("wecom", agent_id="default")


def _configured(libFile, keyPath, **overrides):
    extra = {SDK_FIELD: str(libFile), SECRET_ENV_FIELD: SECRET_ENV_NAME,
             KEYS_FIELD: {"1": str(keyPath)}}
    extra.update(overrides)
    return extra


# ---------------------------------------------------------------------------
# 判据 1：恒假探测退役＋凭据面单点在通道层（结构反证，不 import 新模块）
# ---------------------------------------------------------------------------


class TestSingleSourceAndBogusProbeRetired:
    def test_connectorsChatNoLongerProbesAFictionalPythonModule(self):
        src = CONNECTORS_CHAT.read_text(encoding="utf-8")
        assert "WeWorkFinanceSdk" not in src, (
            "官方只分发 C 动态库、无官方 Python 包（方案 §16-1）——这个模块名不对应任何"
            "可安装件，探测恒 ImportError 属假判据，须退役")
        assert "import_module" not in src, "SDK 探测不得再走 importlib（企业源侧零凭据零探测）"

    def test_connectorsChatDoesNotTouchNativeLoaderOrCredentialFields(self):
        """反向控制：今天该绿——企业源侧本来就不该有这些东西，改完也不许长出来。"""
        src = CONNECTORS_CHAT.read_text(encoding="utf-8")
        assert "ctypes" not in src, "原生库加载归通道层，企业源适配器不碰"
        assert SECRET_ENV_FIELD not in src, "凭据字段名不得在企业源侧出现（甲案：零凭据）"
        assert KEYS_FIELD not in src, "私钥映射不得在企业源侧出现（甲案：零凭据）"

    def test_connectorsChatConsumesTheChannelLayerArchiveFace(self):
        src = CONNECTORS_CHAT.read_text(encoding="utf-8")
        assert "wecom_archive" in src, (
            "历史缺口读数必须改接通道层单点，不在适配器里另写一份判断（教义第 6/7 条）")

    def test_archiveFaceIsDeclaredInTheChannelLayer(self):
        assert ARCHIVE_MODULE.is_file(), "存档凭据面须落通道层（甲案），不落企业源侧"
        src = ARCHIVE_MODULE.read_text(encoding="utf-8")
        for needle in (SDK_FIELD, SECRET_ENV_FIELD, KEYS_FIELD, SDK_PATH_ENV, "2048"):
            assert needle in src, "通道层单点须声明 %r（字段名/注入面/官方位数口径）" % needle


# ---------------------------------------------------------------------------
# 判据 2：明文进配置即拒——系统边界（写入口）就拒，不等读取面才炸
# ---------------------------------------------------------------------------


class TestPlaintextRejectedAtWriteBoundary:
    def test_pemInsidePrivateKeyMapIsRejectedWith400(self, api, rsaKeys):
        pem = rsaKeys[2048].read_text(encoding="utf-8")
        resp = _postWecom(api, {KEYS_FIELD: {"1": pem}})
        assert resp.status_code == 400, (
            "明文私钥必须在渠道配置写入口就拒（系统边界）；实得 %s: %s"
            % (resp.status_code, resp.text[:200]))
        assert PEM_MARKER not in resp.text, "拒绝理由不得回显私钥内容"

    def test_plaintextArchiveSecretFieldIsRejectedWith400(self, api):
        resp = _postWecom(api, {"archiveSecret": SECRET_VALUE})
        assert resp.status_code == 400
        assert SECRET_VALUE not in resp.text, "拒绝理由不得回显密钥值"

    def test_plaintextPrivateKeyFieldIsRejectedWith400(self, api):
        resp = _postWecom(api, {"archivePrivateKey": PEM_MARKER + " RSA PRIVATE KEY-----\nabc"})
        assert resp.status_code == 400
        assert "abc" not in resp.text

    def test_pointerOnlyConfigIsAccepted(self, api, rsaKeys, loadableSdk):
        """反向控制：指针型配置是合法形状，不得误拒（今天该绿）。"""
        libFile, _loaded = loadableSdk
        resp = _postWecom(api, _configured(libFile, rsaKeys[2048]))
        assert resp.status_code == 200, "指针型配置被误拒：%s" % resp.text[:200]

    def test_nonWecomExtraIsNotSweptIntoArchiveValidation(self, api):
        """反向控制：别的渠道 extra 里的凭据键不被存档判据误伤（今天该绿）。"""
        resp = _postWecom(api, {"bot_token": "x", "share_session_in_group": True})
        assert resp.status_code == 200, "非存档字段被误拒：%s" % resp.text[:200]


# ---------------------------------------------------------------------------
# 判据 3：就绪读数各档点名——全部经 health() 这条真消费链
# ---------------------------------------------------------------------------


class TestReadinessStatesThroughHealth:
    def test_unconfiguredSdkNamesWhereToConfigure(self, tmp_path, monkeypatch):
        monkeypatch.delenv(SDK_PATH_ENV, raising=False)
        health = _healthWith(tmp_path, {"corpid": "ww_unit_corp"})
        assert health.status == "degraded"
        assert SDK_FIELD in health.reason, "缺哪一项须点名去哪配，不笼统说「未接入」"
        assert SDK_PATH_ENV in health.reason

    def test_envInjectedSdkPathIsHonored(self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, loaded = loadableSdk
        monkeypatch.setenv(SDK_PATH_ENV, str(libFile))
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        extra = _configured(libFile, rsaKeys[2048])
        del extra[SDK_FIELD]  # 只靠 env 注入
        health = _healthWith(tmp_path, extra)
        assert loaded == [str(libFile)], "env 注入的库路径必须真被拿去加载（分支真被走到）"
        assert health.status == "degraded", health.reason

    def test_missingSdkFileIsErrorAndNamesPath(self, tmp_path):
        ghost = tmp_path / "no-such-library.so"
        health = _healthWith(tmp_path, {SDK_FIELD: str(ghost)})
        assert health.status == "error", "路径给了但文件不在＝配置错，须如实 error"
        assert str(ghost) in health.reason
        assert "不存在" in health.reason, (
            "文件不在与加载失败是两种根因：把前者说成「检查架构/openssl」会把人引向错方向")

    def test_unloadableSdkFileIsErrorNotSilentPass(self, tmp_path):
        notALibrary = tmp_path / "broken.so"
        notALibrary.write_text("this is not a dynamic library", encoding="utf-8")
        health = _healthWith(tmp_path, {SDK_FIELD: str(notALibrary)})
        assert health.status == "error", "加载失败必须如实 error，不得静默当已装"
        assert str(notALibrary) in health.reason
        assert "不可加载" in health.reason

    def test_unsetSecretEnvNamesFieldAndEnvName(self, tmp_path, monkeypatch, loadableSdk):
        libFile, _loaded = loadableSdk
        monkeypatch.delenv(SECRET_ENV_NAME, raising=False)
        health = _healthWith(tmp_path, {SDK_FIELD: str(libFile),
                                       SECRET_ENV_FIELD: SECRET_ENV_NAME})
        assert health.status == "degraded"
        assert SECRET_ENV_FIELD in health.reason
        assert SECRET_ENV_NAME in health.reason

    def test_emptySecretEnvIsSameAsUnset(self, tmp_path, monkeypatch, loadableSdk):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, "")
        health = _healthWith(tmp_path, {SDK_FIELD: str(libFile),
                                       SECRET_ENV_FIELD: SECRET_ENV_NAME})
        assert health.status == "degraded", "空值不是凭据，不得报成就位"
        assert SECRET_ENV_NAME in health.reason

    def test_missingPrivateKeyMapNamesField(self, tmp_path, monkeypatch, loadableSdk):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        health = _healthWith(tmp_path, {SDK_FIELD: str(libFile),
                                       SECRET_ENV_FIELD: SECRET_ENV_NAME})
        assert health.status == "degraded"
        assert KEYS_FIELD in health.reason

    def test_missingPrivateKeyFileIsError(self, tmp_path, monkeypatch, loadableSdk):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        ghost = tmp_path / "no-such-key.pem"
        health = _healthWith(tmp_path, _configured(libFile, ghost))
        assert health.status == "error"
        assert str(ghost) in health.reason

    def test_wrongKeySizeIsErrorAndNamesOfficialBits(self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        health = _healthWith(tmp_path, _configured(libFile, rsaKeys[1024]))
        assert health.status == "error", "1024 位不是官方口径，不得放行"
        assert "2048" in health.reason

    def test_notAPrivateKeyFileIsErrorWithoutEchoingContent(self, tmp_path, monkeypatch, loadableSdk):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        junk = tmp_path / "junk.pem"
        junk.write_text("SENSITIVE-JUNK-CONTENT-42", encoding="utf-8")
        health = _healthWith(tmp_path, _configured(libFile, junk))
        assert health.status == "error"
        assert "SENSITIVE-JUNK-CONTENT-42" not in health.reason

    def test_plaintextAlreadyInLiveConfigIsErrorAtReadBoundary(self, tmp_path):
        """存量配置里的明文（C7a 之前落的／手工改盘的）在读边界也要如实 error。"""
        health = _healthWith(tmp_path, {"archiveSecret": SECRET_VALUE})
        assert health.status == "error", (
            "写入口拒得住不代表盘上存量干净：读边界须复用同一判据再判一次")
        assert SECRET_ENV_FIELD in health.reason, "须点名该改成哪个指针字段"
        assert SECRET_VALUE not in health.reason

    def test_fullyConfiguredFaceStillNamesReaderAsUnimplemented(
            self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        health = _healthWith(tmp_path, _configured(libFile, rsaKeys[2048]))
        assert loaded == [str(libFile)]
        assert health.status == "degraded", (
            "C7a 不含拉取逻辑：凭据齐了也不得报 ok（读取面属 C7b），否则就是冒充全量可达")
        assert "C7b" in health.reason or "未实现" in health.reason
        assert "既有捕获面" in health.reason

    def test_unassembledWecomChannelIsNamedHonestly(self, tmp_path):
        health = _healthWith(tmp_path, {}, installChannel=False)
        assert health.status == "degraded"
        assert "企微" in health.reason or "wecom" in health.reason
        assert "未装配" in health.reason or "未配置" in health.reason

    def test_reasonNeverCarriesSecretValueOrKeyMaterial(
            self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        """反向控制：今天该绿——任何一档的输出面都不许出现密钥值/PEM 头。"""
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        for keyPath in (rsaKeys[2048], rsaKeys[1024]):
            health = _healthWith(tmp_path, _configured(libFile, keyPath))
            assert SECRET_VALUE not in health.reason
            assert PEM_MARKER not in health.reason, "reason 不得含 PEM 头（私钥内容一律不进输出面）"


# ---------------------------------------------------------------------------
# 判据 4：权限位——POSIX 真咬，Windows 如实点名不假通过
# ---------------------------------------------------------------------------


class TestPrivateKeyPermissions:
    @pytest.mark.skipif(os.name != "posix", reason="POSIX 权限位只在 posix 有意义")
    def test_groupReadableKeyIsRejectedOnPosix(self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        key = rsaKeys[2048]
        key.chmod(0o644)
        try:
            health = _healthWith(tmp_path, _configured(libFile, key))
            assert health.status == "error", "组/其他可读的私钥不得放行"
            assert "权限" in health.reason
        finally:
            key.chmod(0o600)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX 权限位只在 posix 有意义")
    def test_ownerOnlyKeyPassesPermissionGateOnPosix(self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        key = rsaKeys[2048]
        key.chmod(0o600)
        health = _healthWith(tmp_path, _configured(libFile, key))
        assert health.status == "degraded", health.reason
        assert "权限" not in health.reason

    @pytest.mark.skipif(os.name != "nt", reason="Windows 无 POSIX 权限位，走另一档")
    def test_windowsNamesAclInsteadOfPretendingPass(self, tmp_path, monkeypatch, loadableSdk, rsaKeys):
        libFile, _loaded = loadableSdk
        monkeypatch.setenv(SECRET_ENV_NAME, SECRET_VALUE)
        health = _healthWith(tmp_path, _configured(libFile, rsaKeys[2048]))
        assert "NTFS" in health.reason or "ACL" in health.reason, (
            "Windows 上 st_mode 权限位无意义：必须如实点名访问控制由部署侧 ACL 保证，"
            "不假装校验通过（教义第 2 条禁表面抹除）")

    def test_permissionGateHasBothPlatformBranches(self):
        """反向控制：两档都得在实装里，不许只写一档然后靠 skipif 蒙过。"""
        assert ARCHIVE_MODULE.is_file(), "存档凭据面模块缺席"
        src = ARCHIVE_MODULE.read_text(encoding="utf-8")
        assert "0o077" in src, "POSIX owner-only 判据要在实装里"
        assert "NTFS" in src or "ACL" in src, "Windows 诚实文案要在实装里"


# ---------------------------------------------------------------------------
# 判据 5：vendor 隔离（反向控制，今天该绿）
# ---------------------------------------------------------------------------


class TestVendorIsolation:
    def test_wechatVendorNeverConsultsWecomArchiveFace(self, tmp_path):
        health = _healthWith(tmp_path, {SDK_FIELD: str(tmp_path / "absent.so")},
                             vendor="wechat", installChannel=False)
        assert health.status == "degraded", "微信侧不受企微存档配置错牵连"
        assert "历史" in health.reason
        assert SDK_FIELD not in health.reason