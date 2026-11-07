# -*- coding: utf-8 -*-
"""live-verify（批 C7a，2026-11-08 裁定甲案）：企微会话存档凭据面与就绪读数的真链路自证。

## 判据（不以单测全绿代替）

1. **写入口拒明文**：真 `POST /api/v1/channel-configs` 带 `extra.archiveSecret`（明文 Secret）
   与带 PEM 内容的 `extra.archivePrivateKeys` 均 **400**，拒绝理由不回显密钥值，
   且**磁盘上的 `channel_configs.json` 一个字节都没为这条请求改变**；
2. **指针配置落得下去**：同一端点收 `archiveSdkPath / archiveSecretEnv / archivePrivateKeys`
   三指针 → 200；真 `GET /api/v1/channel-configs/wecom` 回显 `extra` 里只有指针，
   没有密钥值也没有 PEM；
3. **读数经真消费链**：企业源 `chat` 描述符提交后，`GET /api/v1/knowledge/enterprise/sources/{id}/health`
   的 reason 来自通道层存档面——缺库时点名字段与注入面，库路径指向不存在的文件时如实
   `error`，文件在但不可加载（文本假件）时如实 `error` 并点名架构/依赖库匹配方向，
   三件全配（**真能加载的**原生库件＋env Secret＋真 RSA 2048 私钥文件）时仍 `degraded`
   并点名读取面属批 C7b 未实现，**不报 ok**（报 ok 就是冒充全量可达）；
4. **存量明文在读边界也被拦**：绕开写入口、直接把明文塞进盘上配置文件再装配，
   health 必须 `error` 且 reason 不含该明文值。

## 隔离与替身边界

数据根走 `isolatedDataRoot()` 单点，密钥链走 env（不碰真实 `data/`）。
**只有「适配器工厂」与「建长连接」这一处被替身接管**：C7a 不碰任何平台凭据、不建长连接，
真连企微有外部副作用；工厂仍返回**真 `WeComAdapter`**（配置身份是真的），只跳过 `connect()`。
其余（HTTP 端点、配置落盘与封存、渠道管理器、企业源注册表、适配器工厂、health 链）全是真件。

跑法：`python tests/manual/wecomArchiveFaceC7a_live.py`
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaWecomArchiveC7a")
# 进程 env 的改写**全部收在 main() 内**（`tests/manual/` 顶层改 env 有常驻棘轮：
# 顶层那一条会在 import 期执行、把变量带进整个跑测进程）。数据根那一步必须
# 在 import neurova 之前生效，故留在顶层的是 `isolatedDataRoot()` 单点调用本身。

#: 库件假面：`SDK_LIB_STUB`＝在但不可加载；`REAL_LIB`＝真能加载的件（系统 C 库/kernel32）。
#: C7a 的就绪判据只到「能不能加载」——用真件验这一条，验不到「是不是存档库」
#: （后者要真 SDK 分发件，属 C7b 的真部署面，此处不冒充）。
SDK_LIB_STUB = WORK_ROOT / "stub-archive-sdk.so"
SECRET_ENV = "NEUROVA_LIVE_C7A_ARCHIVE_SECRET"
SECRET_VALUE = "live-c7a-archive-secret-DO-NOT-LEAK"
PLAINTEXT_PROBE = "live-plaintext-secret-PROBE-42"
EVIDENCE: list = []


def say(title: str, reading) -> None:
    line = "%s :: %s" % (title, reading)
    EVIDENCE.append(line)
    print(line)


def check(label: str, condition: bool, detail: str = "") -> None:
    say(("PASS " if condition else "FAIL ") + label, detail)
    if not condition:
        raise AssertionError("%s 不符合判据：%s" % (label, detail))


def _loadableLibrary() -> str:
    """挑一个本机真能 CDLL 加载的件，用来验「可加载」那一档（不是假装有存档库）。"""
    import ctypes

    candidates = []
    windir = os.environ.get("WINDIR")
    if windir:
        candidates.append(str(Path(windir) / "System32" / "kernel32.dll"))
    candidates += ["/usr/lib/x86_64-linux-gnu/libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6",
                   "/usr/lib/libc.dylib", "/usr/lib/libc.dylib"]
    for c in candidates:
        if not Path(c).is_file():
            continue
        try:
            ctypes.CDLL(c)
        except OSError:
            continue
        return c
    raise AssertionError("本机找不到任何可加载的原生库件：'可加载' 这一档无法活体取证")


def main() -> int:
    # 密钥链与代理面：必须在 import 任何 neurova 模块之前落定（AGENTS.md §0 两件事）
    os.environ.setdefault("NEUROVA_SECRET_KEY", "live-verify-key-for-c7a-0123456789abcdef")
    os.environ.setdefault("NEUROVA_JWT_SECRET", "live-verify-jwt-for-c7a-0123456789abcdef-xyz")
    for _p in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        os.environ.pop(_p, None)
    REAL_LIB = _loadableLibrary()
    say("取用的可加载原生库件", REAL_LIB)
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user as authUser
    from neurova.api.auth import get_current_user_or_service as authOrService
    from neurova.api.endpoints import channel_config as cc
    from neurova.channels.base import ChannelConfig
    from neurova.channels.channel_ingress_queue import CHANNEL_INGRESS_DB_ENV
    from neurova.channels.manager import get_channel_manager
    from neurova.channels.wecom import WeComAdapter
    from neurova.core.data_root import get_data_root
    from neurova.knowledge.foundation import get_knowledge_fact_store
    from neurova.knowledge.ontology.term_registry import OntologyTermRegistry

    # ── 存档面素材：假库件 + 真 RSA 2048 私钥文件（owner-only） ──
    SDK_LIB_STUB.write_text("not a real library, live-verify stub", encoding="utf-8")
    keyDir = WORK_ROOT / "archive-keys"
    keyDir.mkdir(exist_ok=True)
    keyPath = keyDir / "priv_2048.pem"
    keyPath.write_bytes(rsa.generate_private_key(public_exponent=65537, key_size=2048)
                        .private_bytes(
                            encoding=serialization.Encoding.PEM,
                            format=serialization.PrivateFormat.PKCS8,
                            encryption_algorithm=serialization.NoEncryption()))
    if os.name == "posix":
        keyPath.chmod(0o600)
    os.environ[SECRET_ENV] = SECRET_VALUE

    pointers = {"corpid": "ww_live_corpid",
                "archiveSdkPath": REAL_LIB,
                "archiveSecretEnv": SECRET_ENV,
                "archivePrivateKeys": {"1": str(keyPath)}}

    # 捕获面 DB：按生产 DDL 在隔离数据根建库（health 先判它存在）
    from neurova.channels.channel_ingress_queue import _SCHEMA as INGRESS_SCHEMA
    ingressDb = get_data_root() / "channel_ingress.db"
    conn = sqlite3.connect(str(ingressDb))
    conn.executescript(INGRESS_SCHEMA)
    conn.commit()
    conn.close()
    os.environ[CHANNEL_INGRESS_DB_ENV] = str(ingressDb)

    # 谓词单点注册（真术语表，走生产注册器）
    factStore = get_knowledge_fact_store()
    OntologyTermRegistry(factStore).register("says", "relation", label="说过")

    app = create_app()
    admin = {"user_id": "live-c7a-admin", "role": "admin", "username": "live"}
    app.dependency_overrides[authUser] = lambda: dict(admin)
    app.dependency_overrides[authOrService] = lambda: dict(admin)
    # 唯一替身：工厂仍构真适配器，只跳过建长连接（C7a 不碰平台凭据）
    cc._create_adapter = lambda channel_type, config: (
        WeComAdapter(config) if channel_type == "wecom" else None)

    storeFile = cc._configFile()
    manager = get_channel_manager()

    def postWecom(extra, enabled=True):
        return client.post("/api/v1/channel-configs", params={"agent_id": "default"},
                           json={"channel_type": "wecom", "enabled": enabled,
                                 "app_id": "ww_live_corpid",
                                 "app_secret": "live-app-secret", "extra": extra})

    def unregister():
        manager.unregister_adapter("wecom", agent_id="default")

    with TestClient(app) as client:
        # ── 判据 1：写入口拒明文，且盘上零改变 ──
        base = postWecom(dict(pointers))
        check("指针配置可写入（POST 200）", base.status_code == 200,
              "HTTP %s %s" % (base.status_code, base.text[:180]))
        onDiskBefore = storeFile.read_bytes()

        r1 = postWecom(dict(pointers, archiveSecret=PLAINTEXT_PROBE))
        check("明文 Secret 写入口 400", r1.status_code == 400,
              "HTTP %s %s" % (r1.status_code, r1.text[:200]))
        check("400 理由不回显明文值", PLAINTEXT_PROBE not in r1.text, r1.text[:200])

        r2 = postWecom(dict(pointers, archivePrivateKeys={"1": str(keyPath.read_text("utf-8"))}))
        check("PEM 内容进私钥映射写入口 400", r2.status_code == 400,
              "HTTP %s %s" % (r2.status_code, r2.text[:200]))
        check("400 理由不回显 PEM", "-----BEGIN" not in r2.text, r2.text[:200])

        r3 = postWecom(dict(pointers, archivePrivateKey=PLAINTEXT_PROBE))
        check("明文私钥别名字段同样 400", r3.status_code == 400,
              "HTTP %s %s" % (r3.status_code, r3.text[:200]))
        check("被拒请求未改动盘上配置", storeFile.read_bytes() == onDiskBefore,
              "落盘字节比对")

        # ── 判据 2：GET 回显只含指针 ──
        echoed = client.get("/api/v1/channel-configs/wecom", params={"agent_id": "default"})
        echoExtra = echoed.json().get("extra") or {}
        check("GET 回显含三指针",
              {"archiveSdkPath", "archiveSecretEnv", "archivePrivateKeys"} <= set(echoExtra),
              json.dumps(sorted(echoExtra), ensure_ascii=False))
        check("GET 回显不含密钥值", SECRET_VALUE not in echoed.text
              and PLAINTEXT_PROBE not in echoed.text, echoed.text[:200])

        # ── 判据 3：health 读数经真消费链（企业源端点 → 通道层存档面） ──
        descriptor = {"sourceType": "chat", "vendor": "wecom", "agentId": "default",
                      "columns": ["msg_id", "chat_id", "chat_type", "sender", "sent_at", "text"],
                      "subject": {"template": "chat:{chat_id}:msg:{msg_id}"},
                      "predicate": {"termId": "says"},
                      "object": {"kind": "column", "column": "text"},
                      "qualifiers": {}}
        submitted = client.post("/api/v1/knowledge/enterprise/sources",
                                json={"source_id": "live_wecom_chat",
                                      "descriptor": descriptor, "enabled": True})
        check("chat 企业源描述符提交通过编译期校验", submitted.status_code == 200,
              "HTTP %s %s" % (submitted.status_code, submitted.text[:200]))

        def health():
            resp = client.get("/api/v1/knowledge/enterprise/sources/live_wecom_chat/health")
            assert resp.status_code == 200, resp.text[:200]
            return resp.json()["data"]

        unregister()
        h = health()
        say("通道未装配档", "%s | %s" % (h["status"], h["reason"]))
        check("未装配档如实 degraded", h["status"] == "degraded", h["reason"])

        manager.register_adapter(WeComAdapter(ChannelConfig(
            channel_type="wecom", enabled=True, app_id="ww_live_corpid",
            app_secret="live-app-secret", extra={"corpid": "ww_live_corpid"})),
            agent_id="default")
        h = health()
        say("原生库未配置档", "%s | %s" % (h["status"], h["reason"]))
        check("缺库档点名配置字段与环境变量注入面",
              h["status"] == "degraded" and "archiveSdkPath" in h["reason"]
              and "NEUROVA_WECOM_ARCHIVE_SDK" in h["reason"], h["reason"])

        manager.unregister_adapter("wecom", agent_id="default")
        ghost = str(WORK_ROOT / "no-such-sdk.so")
        ghostResp = postWecom(dict(pointers, archiveSdkPath=ghost))
        check("库路径指向不存在的文件仍可写入（配置面不预知部署）",
              ghostResp.status_code == 200, ghostResp.text[:160])
        h = health()
        say("库文件不在档", "%s | %s" % (h["status"], h["reason"]))
        check("库文件不在＝如实 error 并点名路径",
              h["status"] == "error" and ghost in h["reason"], h["reason"])

        manager.unregister_adapter("wecom", agent_id="default")
        stubResp = postWecom(dict(pointers, archiveSdkPath=str(SDK_LIB_STUB)))
        check("在但不可加载的库件仍可写入（加载判定属运行期）",
              stubResp.status_code == 200, stubResp.text[:160])
        h = health()
        say("库件不可加载档", "%s | %s" % (h["status"], h["reason"]))
        check("不可加载＝如实 error 并点名匹配排查方向",
              h["status"] == "error" and "不可加载" in h["reason"]
              and str(SDK_LIB_STUB) in h["reason"], h["reason"])

        ok = postWecom(dict(pointers))
        check("三指针全配可写入", ok.status_code == 200, ok.text[:160])
        h = health()
        say("凭据齐备档（读取面属 C7b）", "%s | %s" % (h["status"], h["reason"]))
        check("凭据齐备仍 degraded 且点名读取面未实现",
              h["status"] == "degraded" and ("C7b" in h["reason"] or "未实现" in h["reason"]),
              h["reason"])
        check("齐备档仍说明只到既有捕获面", "既有捕获面" in h["reason"], h["reason"])
        check("reason 不含密钥值/PEM", SECRET_VALUE not in h["reason"]
              and "-----BEGIN" not in h["reason"], h["reason"][:200])

        # ── 判据 4：存量明文（绕开写入口）在读边界被拦 ──
        raw = json.loads(storeFile.read_bytes().decode("utf-8"))
        raw["agents"]["default"]["wecom"]["extra"]["archiveSecret"] = PLAINTEXT_PROBE
        storeFile.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        leaked = cc._load_store()["agents"]["default"]["wecom"].get("extra") or {}
        unregister()
        manager.register_adapter(WeComAdapter(ChannelConfig(
            channel_type="wecom", enabled=True, app_id="ww_live_corpid",
            app_secret="live-app-secret", extra=leaked)), agent_id="default")
        h = health()
        say("存量明文读边界档", "%s | %s" % (h["status"], h["reason"]))
        check("读边界把存量明文判为 error", h["status"] == "error", h["reason"])
        check("error 理由不回显明文值", PLAINTEXT_PROBE not in h["reason"], h["reason"])
        check("error 理由指回指针字段", "archiveSecretEnv" in h["reason"], h["reason"])

        unregister()
        app.dependency_overrides.clear()

    print("\n===== 证据行数 %d =====" % len(EVIDENCE))
    print("临时数据根：%s" % WORK_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
