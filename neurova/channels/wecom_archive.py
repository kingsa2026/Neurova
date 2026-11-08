# -*- coding: utf-8 -*-
"""企微会话内容存档：凭据面＋就绪读数（C7a）＋读取面与投影表（批 C7b，裁定甲案）。

方案出处：`docs/specs/2026-11-07-wecom-chat-archive-history-source-plan.md` §4-§8/§16。

**分层（甲案）**：本模块是通道层的存档单点——凭据面校验（`validateArchiveExtra`）、
就绪读数（`archiveReadiness`）、官方 C 动态库的 ctypes 薄包装（`ArchiveSdkHandle`）、
按 seq 增量拉取与归一（`pullArchiveBatch`）、投影表唯一写路径
（`ArchiveProjectionStore`，append-only）。企业源侧（connectors_chat）只拿
就绪读数与只读投影行，凭据值与路径都不过它的手。

官方接口面（方案 §16-1 实证）：`NewSdk` → `Init(sdk, corpid, secret)` →
`GetChatData(sdk, seq, limit, proxy, passwd, timeout, chatDatas)`（**从 seq+1 起**、
`limit ≤ 1000`、`≤4000 次/分钟`）→ `DecryptData(encrypt_key, encrypt_msg, msg)`
（AES 半边在 SDK 内，本仓只做 RSA 半边，见 wechat_kf_crypto.decryptArchiveRandomKey）。
解密链：`encrypt_random_key` base64 → RSA PKCS1（按 `publickey_ver` 选私钥）→
`encrypt_key` → `DecryptData` → 明文 JSON。**只给 ≤5 天窗口**：历史＝定期拉＋本地累积。

凭据落点（裁定 B＋§6.1）：配置面只放**指针**，值一律不进 `extra`（理由见 C7a docstring）。
明文进配置即拒；reason/日志不落密钥值与消息正文。
"""

from __future__ import annotations

import base64
import ctypes
import datetime as _dt
import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from neurova.core.db_migration import register_migration

#: 渠道配置 `extra` 里的三个指针字段（单一事实源：写入口校验与就绪读数共读这一份）
ARCHIVE_SDK_PATH_FIELD = "archiveSdkPath"
ARCHIVE_SECRET_ENV_FIELD = "archiveSecretEnv"
ARCHIVE_PRIVATE_KEYS_FIELD = "archivePrivateKeys"
#: 隐私白名单（批 C7c，方案 §13-1：落库前过滤，不是摄取后再删）。值是 id 列表，
#: 不是凭据——roomid 全量在存档里，白名单只决定**本系统保留哪些**。
ARCHIVE_ROOM_ALLOWLIST_FIELD = "archiveRoomAllowlist"
ARCHIVE_USER_ALLOWLIST_FIELD = "archiveUserAllowlist"

#: 原生库路径的环境注入面（与 `extra.archiveSdkPath` 二选一，extra 优先）
ARCHIVE_SDK_PATH_ENV = "NEUROVA_WECOM_ARCHIVE_SDK"

#: 官方口径：RSA 2048 位模数（方案 §16-1 解密链）
ARCHIVE_RSA_KEY_BITS = 2048

#: 明文值不得进的键：给了就拒（照抄 SQL 批 connectors_sql 的描述符自守形状）
_PLAINTEXT_FIELDS = ("archiveSecret", "archivePrivateKey", "archive_private_key")
_PEM_MARKER = "-----BEGIN"

#: POSIX 私钥权限位：owner-only（group/other 任何位都算过宽）
_OWNER_ONLY_MASK = 0o077


class ArchiveConfigError(ValueError):
    """存档凭据面配置非法：明文进配置即拒，理由不回显密钥内容。"""


@dataclass(frozen=True)
class ArchiveReadiness:
    """就绪读数：status/reason 是对外文案面，ready 是机器可判的拉取前提位。

    status ∈ degraded/error（C7a 起不产 ok：覆盖范围由席位与成员同意决定，
    代码验不到；ready=True 只表示「凭据面全就位、可以去拉」，不代表全量可达）。
    reason 一律不含密钥值、私钥内容与消息正文。
    """

    status: str
    reason: str
    ready: bool = False


def validateArchiveExtra(extra: Any) -> None:
    """配置面自守：存档凭据**值**不得进 `extra`，只许指针（路径/环境变量名）。

    非 dict 原样放过（渠道配置面由 pydantic 保证形状，此处不重复校验）；
    非存档字段不误伤——别的渠道 `extra` 里的凭据键由既有封存面负责。
    """
    if not isinstance(extra, dict):
        return
    for field in _PLAINTEXT_FIELDS:
        if str(extra.get(field) or "").strip():
            raise ArchiveConfigError(
                "渠道配置 extra 不放存档凭据明文（%s）——Secret 用 %s（环境变量名），"
                "私钥用 %s（publickey_ver → 文件路径）"
                % (field, ARCHIVE_SECRET_ENV_FIELD, ARCHIVE_PRIVATE_KEYS_FIELD))
    keyMap = extra.get(ARCHIVE_PRIVATE_KEYS_FIELD)
    if isinstance(keyMap, dict):
        for version, value in keyMap.items():
            if _PEM_MARKER in str(value):
                raise ArchiveConfigError(
                    "%s 只放私钥文件路径，不放 PEM 内容（publickey_ver=%s）"
                    % (ARCHIVE_PRIVATE_KEYS_FIELD, version))
    elif keyMap is not None and _PEM_MARKER in str(keyMap):
        raise ArchiveConfigError(
            "%s 只放私钥文件路径，不放 PEM 内容" % ARCHIVE_PRIVATE_KEYS_FIELD)
    for field_ in (ARCHIVE_ROOM_ALLOWLIST_FIELD, ARCHIVE_USER_ALLOWLIST_FIELD):
        allowlist = extra.get(field_)
        if allowlist is None:
            continue
        if not isinstance(allowlist, list) or any(
                not isinstance(item, str) for item in allowlist):
            raise ArchiveConfigError(
                "%s 必须是字符串 id 列表（roomid/userid），当前形状不合" % field_)


def archiveReadiness(extra: Optional[Mapping[str, Any]] = None) -> ArchiveReadiness:
    """按渠道配置指针判存档面就绪度：每一档各自点名缺什么/错在哪，不笼统说「未接入」。

    判定顺序＝部署依赖顺序：原生库 → Secret → 私钥映射 → 逐个私钥文件。
    前一档不成立就不必报后一档（否则一次误配吐出一屏噪声，反而看不清根因）。
    """
    config: Dict[str, Any] = dict(extra or {})
    try:
        validateArchiveExtra(config)
    except ArchiveConfigError as exc:
        return ArchiveReadiness(status="error", reason=str(exc))

    sdkPath = (str(config.get(ARCHIVE_SDK_PATH_FIELD) or "").strip()
               or os.environ.get(ARCHIVE_SDK_PATH_ENV, "").strip())
    if not sdkPath:
        return ArchiveReadiness(
            status="degraded",
            reason="会话存档原生库未配置（渠道 extra.%s 或环境变量 %s）——官方只分发 C 动态库、"
                   "无官方 Python 包，须部署侧显式给路径"
                   % (ARCHIVE_SDK_PATH_FIELD, ARCHIVE_SDK_PATH_ENV))
    library = Path(sdkPath)
    if not library.is_file():
        return ArchiveReadiness(
            status="error",
            reason="会话存档原生库文件不存在: %s（检查 extra.%s / 环境变量 %s）"
                   % (library, ARCHIVE_SDK_PATH_FIELD, ARCHIVE_SDK_PATH_ENV))
    try:
        ctypes.CDLL(str(library))
    except OSError as exc:
        return ArchiveReadiness(
            status="error",
            reason="会话存档原生库不可加载: %s（%s）——检查架构/openssl 版本是否与该库分发件匹配"
                   % (library, exc))

    secretEnv = str(config.get(ARCHIVE_SECRET_ENV_FIELD) or "").strip()
    if not secretEnv:
        return ArchiveReadiness(
            status="degraded",
            reason="会话存档专用 Secret 未配置（渠道 extra.%s 填环境变量名；Secret 取自管理端→"
                   "管理工具→聊天内容存档，不是应用 Secret）" % ARCHIVE_SECRET_ENV_FIELD)
    if not os.environ.get(secretEnv, "").strip():
        return ArchiveReadiness(
            status="degraded",
            reason="会话存档专用 Secret 环境变量 %s 未设置或为空（渠道 extra.%s）"
                   % (secretEnv, ARCHIVE_SECRET_ENV_FIELD))

    keyMap = config.get(ARCHIVE_PRIVATE_KEYS_FIELD)
    if not isinstance(keyMap, dict) or not keyMap:
        return ArchiveReadiness(
            status="degraded",
            reason="会话存档私钥未配置（渠道 extra.%s＝{publickey_ver: 私钥文件路径}；"
                   "公钥须先上传企微后台并记录版本号）" % ARCHIVE_PRIVATE_KEYS_FIELD)

    problems = []
    notes = []
    for version, rawPath in sorted(keyMap.items(), key=lambda item: str(item[0])):
        keyPath = Path(str(rawPath))
        if not keyPath.is_file():
            problems.append("私钥文件不存在（publickey_ver=%s）: %s" % (version, keyPath))
            continue
        try:
            material = keyPath.read_bytes()
        except OSError as exc:
            problems.append("私钥文件不可读（publickey_ver=%s）: %s（%s）"
                            % (version, keyPath, exc))
            continue
        keyProblem = _privateKeyProblem(material)
        if keyProblem:
            problems.append("私钥不合官方口径（publickey_ver=%s）: %s——%s"
                            % (version, keyPath, keyProblem))
            continue
        permissionProblem, permissionNote = _permissionReading(keyPath)
        if permissionProblem:
            problems.append("私钥%s（publickey_ver=%s）: %s"
                            % (permissionProblem, version, keyPath))
        elif permissionNote:
            notes.append(permissionNote)

    if problems:
        return ArchiveReadiness(status="error",
                                reason="会话存档凭据面不合口径：" + "；".join(problems))
    reason = "会话存档原生库与凭据就绪（读取面批 C7b 已实现）"
    if notes:
        reason += "；" + "；".join(dict.fromkeys(notes))
    return ArchiveReadiness(status="degraded", reason=reason, ready=True)


def wecomArchiveReadiness(agentId: str = "default") -> ArchiveReadiness:
    """活渠道配置 → 就绪读数（企业源侧唯一消费点，凭据值与路径都不过它的手）。

    读的是渠道管理器里**已装配实例**的配置，不另读一份配置文件——存档凭据面
    与 corpid/app_secret 同源同处（甲案：不新造第二套凭据存储）。
    """
    from neurova.channels.manager import get_channel_manager

    agent = str(agentId or "default")
    adapter = get_channel_manager().get_adapter("wecom", agent_id=agent)
    if adapter is None:
        return ArchiveReadiness(
            status="degraded",
            reason="企微通道未装配（agent=%s）——会话存档凭据面在渠道配置里，先装配企微通道" % agent)
    return archiveReadiness(adapter.config.extra or {})


def _privateKeyProblem(material: bytes) -> str:
    """私钥内容判据：可解析 → RSA → 2048 位。失败原因点名，**内容一律不回显**。"""
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    try:
        key = serialization.load_pem_private_key(material, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        return "不是可解析的未加密 PEM 私钥（内容不在此回显）"
    if not isinstance(key, rsa.RSAPrivateKey):
        return "不是 RSA 私钥（官方口径 RSA %d 位）" % ARCHIVE_RSA_KEY_BITS
    if key.key_size != ARCHIVE_RSA_KEY_BITS:
        return "RSA 位数 %d，官方口径 %d 位" % (key.key_size, ARCHIVE_RSA_KEY_BITS)
    return ""


def _permissionReading(keyPath: Path) -> Tuple[str, str]:
    """权限位判据：POSIX 真咬 owner-only；Windows 无 POSIX 权限位则如实点名。

    Windows 上 `st_mode` 的 group/other 位不反映 NTFS ACL，按它判「通过」是假通过
    （教义第 2 条禁表面抹除）——故不判，改为把责任如实交回部署侧。
    """
    if os.name != "posix":
        return "", ("Windows 无 POSIX 权限位，私钥文件访问控制须由部署侧 NTFS ACL 保证"
                    "（本系统不假装校验通过）")
    mode = keyPath.stat().st_mode
    if mode & _OWNER_ONLY_MASK:
        return "权限位过宽（%o）：须 owner-only（chmod 600）" % (mode & 0o777), ""
    return "", ""


# ══ 批 C7b：读取面（ctypes 薄包装＋按 seq 增量拉＋归一）与投影表 ══

#: 投影库路径的环境注入面（单一事实源：通道层写入口与 connectors_chat 只读拉取共读）
CHANNEL_ARCHIVE_DB_ENV = "NEUROVA_CHANNEL_ARCHIVE_DB"

#: 官方口径（方案 §16-1）：GetChatData 单次 limit ≤ 1000、速率 ≤ 4000 次/分钟。
#: 本仓单轮批量的自我节流（registry 的 20×200=4000 行/轮）是另一回事，两个数不混。
ARCHIVE_BATCH_LIMIT_MAX = 1000
ARCHIVE_API_RATE_LIMIT_PER_MINUTE = 4000

#: 经典存档面的 msgtype 是字符串枚举（§5：与专区面 0–28 数字枚举不同源，不合并）；
#: 未知类型不猜——原样落投影＋计数，health 点名。
_KNOWN_MSGTYPES = ("text", "image", "voice", "video", "file", "mixed")
_MEDIA_MSGTYPES = ("image", "voice", "video", "file", "mixed")

_ARCHIVE_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_archive_messages (
    seq INTEGER NOT NULL,
    msgid TEXT NOT NULL,
    publickey_ver TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT 'send',
    msgtype TEXT NOT NULL DEFAULT '',
    from_id TEXT NOT NULL DEFAULT '',
    tolist TEXT NOT NULL DEFAULT '[]',
    roomid TEXT NOT NULL DEFAULT '',
    msgtime_ms INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '',
    media_ref TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (seq)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_archive_msgid
    ON channel_archive_messages(msgid);
CREATE INDEX IF NOT EXISTS idx_archive_send_seq
    ON channel_archive_messages(action, seq);
CREATE TABLE IF NOT EXISTS channel_archive_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT ''
);
"""

#: 消费面共用查询：按 seq 扫描（**不按 action 过滤**——recall/switch 行也要被
#: 游标推进过，否则它们永远留在扫描窗内、水位卡死；send 过滤在消费侧 Python 做，
#: 与捕获面「坏行跳过但游标推进过它」同规）。connectors_chat 的 ro 短连接与
#: 本模块写侧共用同一条 SQL（不抄两份）。
SEND_ROWS_SQL = (
    "SELECT seq, msgid, action, msgtype, from_id, tolist, roomid, msgtime_ms,"
    " text, media_ref FROM channel_archive_messages WHERE seq > ?"
    " ORDER BY seq LIMIT ?"
)

register_migration(1, _ARCHIVE_SCHEMA, domain="channel_archive")


class ArchiveSdkError(RuntimeError):
    """官方 C 动态库调用失败（加载缺导出/句柄失败/接口非零返回/JSON 形状不合）。"""


def _nowIso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _requireExports(lib: ctypes.CDLL, names: Sequence[str]) -> None:
    missing = []
    for name in names:
        if not hasattr(lib, name):
            missing.append(name)
    if missing:
        raise ArchiveSdkError(
            "会话存档原生库缺少导出函数: %s——库分发件版本与官方接口面不符"
            % ", ".join(missing))


def _parseChatDataPayload(payload: bytes) -> List[Dict[str, Any]]:
    """GetChatData 返回体 → chatdata 行列表；errcode 非零显式抛（带 errmsg 不带密文）。"""
    try:
        parsed = json.loads((payload or b"").decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArchiveSdkError("GetChatData 返回体不是合法 JSON（长度 %d）"
                              % len(payload or b"")) from exc
    if not isinstance(parsed, dict):
        raise ArchiveSdkError("GetChatData 返回体形状不合（顶层不是对象）")
    errcode = parsed.get("errcode")
    if errcode not in (0, None):
        raise ArchiveSdkError("GetChatData errcode=%s errmsg=%s"
                              % (errcode, parsed.get("errmsg") or ""))
    rows = parsed.get("chatdata")
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ArchiveSdkError("GetChatData 返回体形状不合（chatdata 不是数组）")
    return rows


class ArchiveSdkHandle:
    """官方 C 动态库的 ctypes 薄包装（本仓独立实现；库是功能依赖，按其许可使用）。

    接口面按方案 §16-1：NewSdk/Init/GetChatData/DecryptData＋同一接口族的
    资源管理半边 FreeChatData/DestroySdk。代理参数（proxy/passwd）留接口位，
    部署侧需要时由调用方传，本仓不新增配置字段。
    """

    _EXPORTS = ("NewSdk", "Init", "GetChatData", "DecryptData",
                "FreeChatData", "DestroySdk")

    def __init__(self, libraryPath: str, corpid: str, secret: str) -> None:
        lib = ctypes.CDLL(str(libraryPath))
        _requireExports(lib, self._EXPORTS)
        lib.NewSdk.argtypes = []
        lib.NewSdk.restype = ctypes.c_void_p
        lib.Init.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        lib.Init.restype = ctypes.c_int
        lib.GetChatData.argtypes = [
            ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_uint,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        lib.GetChatData.restype = ctypes.c_int
        lib.FreeChatData.argtypes = [ctypes.c_char_p]
        lib.FreeChatData.restype = None
        lib.DecryptData.argtypes = [
            ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_char_p),
        ]
        lib.DecryptData.restype = ctypes.c_int
        lib.DestroySdk.argtypes = [ctypes.c_void_p]
        lib.DestroySdk.restype = None

        handle = lib.NewSdk()
        if not handle:
            raise ArchiveSdkError("NewSdk() 返回空句柄——检查库分发件与运行架构是否匹配")
        self._lib = lib
        self._handle = ctypes.c_void_p(handle)
        ret = lib.Init(self._handle, str(corpid or "").encode("utf-8"),
                       str(secret or "").encode("utf-8"))
        if ret != 0:
            self.close()
            raise ArchiveSdkError(
                "Init 失败 ret=%d——检查 corpid 与聊天内容存档专用 Secret"
                "（不是应用 Secret）" % ret)

    def getChatData(self, seq: int, limit: int, timeout: int = 10) -> List[Dict[str, Any]]:
        """按水位拉一批密文行（官方从 seq+1 起）；limit 由 pullArchiveBatch 钳制。"""
        out = ctypes.c_char_p()
        ret = self._lib.GetChatData(
            self._handle, ctypes.c_ulonglong(int(seq)), ctypes.c_uint(int(limit)),
            b"", b"", ctypes.c_uint(int(timeout)), ctypes.byref(out))
        if ret != 0:
            raise ArchiveSdkError("GetChatData 失败 ret=%d——检查出口 IP 白名单/网络" % ret)
        try:
            return _parseChatDataPayload(out.value or b"")
        finally:
            self._lib.FreeChatData(out)

    def decryptData(self, encryptKey: bytes, encryptMsg: bytes) -> bytes:
        """AES 半边在 SDK 内：密钥＋密文进、明文 JSON 出。失败显式抛。"""
        out = ctypes.c_char_p()
        ret = self._lib.DecryptData(
            encryptKey, len(encryptKey or b""),
            encryptMsg, len(encryptMsg or b""),
            ctypes.byref(out))
        if ret != 0:
            raise ArchiveSdkError("DecryptData 失败 ret=%d" % ret)
        return bytes(out.value or b"")

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            self._lib.DestroySdk(handle)
            self._handle = ctypes.c_void_p(0)


@dataclass
class ArchivePullResult:
    """单批拉取结果：归一行集＋水位（跳过行也计入）＋处置计数（health 点名用）。"""

    rows: List[Dict[str, Any]]
    nextSeq: int
    hasMore: bool
    counts: Dict[str, int] = field(default_factory=dict)


def _archiveRowFromPlain(seq: int, msgid: str, plain: Dict[str, Any]) -> Dict[str, Any]:
    """明文消息 → 投影行（append-only 的诚实存档；recall/switch 也落，消费面过滤）。"""
    msgtype = str(plain.get("msgtype") or "")
    body = plain.get(msgtype) if isinstance(plain.get(msgtype), dict) else {}
    text = ""
    mediaRef = ""
    if msgtype == "text":
        text = str(body.get("content") or "")
    elif msgtype in _MEDIA_MSGTYPES:
        if msgtype == "mixed":
            items = body.get("content") if isinstance(body.get("content"), list) else []
            for item in items:
                if not isinstance(item, dict):
                    continue
                itemBody = item.get(item.get("msgtype")) \
                    if isinstance(item.get(item.get("msgtype")), dict) else {}
                sdkFileId = str(itemBody.get("sdkfileid") or "")
                if not mediaRef and sdkFileId:
                    mediaRef = sdkFileId
        else:
            mediaRef = str(body.get("sdkfileid") or "")
    tolist = plain.get("tolist")
    return {
        "seq": int(seq),
        "msgid": str(msgid or ""),
        "publickey_ver": str(plain.get("publickey_ver") or ""),
        "action": str(plain.get("action") or "send"),
        "msgtype": msgtype,
        "from_id": str(plain.get("from") or ""),
        "tolist": json.dumps(tolist, ensure_ascii=False) if isinstance(tolist, list) else "[]",
        "roomid": str(plain.get("roomid") or ""),
        "msgtime_ms": int(plain.get("msgtime") or 0),
        "text": text,
        "media_ref": mediaRef,
    }


def pullArchiveBatch(sdk: Any, seq: int, limit: int,
                     keyMap: Mapping[str, bytes],
                     timeout: int = 10) -> ArchivePullResult:
    """按水位拉一批：GetChatData（seq 原样进，官方从 seq+1 起）→ RSA → DecryptData → 归一。

    - `seq` **原样**交给 SDK（自增一即双重推进 bug）；`nextSeq` 取本轮**见过的最大 seq**
      （未知 key_ver 的跳过行也计入——否则会被无限重拉）；
    - `publickey_ver` 未知 → 该条跳过并计数（方案 §3 前置表），不猜不抛；
    - RSA/解密/JSON 失败 → 显式抛，整批失败（§5：不静默落密文；§5/registry 同规：
      拉取失败不落半行，水位推进属 appendBatch 事务）；
    - `hasMore`＝满页探测（返回行数 ≥ limit 即可能还有）。
    """
    from neurova.channels.wechat_kf_crypto import decryptArchiveRandomKey

    boundedLimit = min(max(1, int(limit)), ARCHIVE_BATCH_LIMIT_MAX)
    rawRows = sdk.getChatData(int(seq), boundedLimit, timeout=timeout)
    rows: List[Dict[str, Any]] = []
    counts = {"pulled": 0, "skipped_unknown_key_ver": 0, "recall": 0,
              "switch": 0, "unknown_msgtype": 0}
    seenSeqs: List[int] = [int(seq)]
    for item in rawRows:
        if not isinstance(item, dict):
            raise ArchiveSdkError("GetChatData 返回行形状不合（元素不是对象）")
        rowSeq = int(item.get("seq") or 0)
        seenSeqs.append(rowSeq)
        counts["pulled"] += 1
        version = str(item.get("publickey_ver") or "")
        pem = keyMap.get(version)
        if pem is None:
            counts["skipped_unknown_key_ver"] += 1
            continue
        encryptKey = decryptArchiveRandomKey(
            str(item.get("encrypt_random_key") or ""), pem)
        try:
            encryptMsg = base64.b64decode(str(item.get("encrypt_chat_msg") or ""),
                                          validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ArchiveSdkError(
                "encrypt_chat_msg 不是合法 base64（seq=%d，内容不回显）" % rowSeq) from exc
        plainBytes = sdk.decryptData(encryptKey, encryptMsg)
        try:
            plain = json.loads(plainBytes.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ArchiveSdkError(
                "DecryptData 出的不是合法 JSON（seq=%d，内容不回显）" % rowSeq) from exc
        if not isinstance(plain, dict):
            raise ArchiveSdkError("明文消息形状不合（顶层不是对象，seq=%d）" % rowSeq)
        row = _archiveRowFromPlain(rowSeq, str(item.get("msgid") or ""), plain)
        row["publickey_ver"] = version
        if row["action"] == "recall":
            counts["recall"] += 1
        elif row["action"] == "switch":
            counts["switch"] += 1
        if row["msgtype"] not in _KNOWN_MSGTYPES:
            counts["unknown_msgtype"] += 1
        rows.append(row)
    return ArchivePullResult(
        rows=rows,
        nextSeq=max(seenSeqs) if seenSeqs else int(seq),
        hasMore=len(rawRows) >= boundedLimit,
        counts=counts,
    )


def msgtimeMillisToIso(msgtimeMs: int) -> str:
    """存档面 `msgtime` 毫秒 → ISO8601 带时区（与捕获面 timestamp.isoformat() 同形）。

    ⚠ 专区面 `send_time` 是**秒**——两面单位不同，归一不共用一个除数（方案 §5）。
    0＝未知，如实空串（不落 epoch 假时间）。
    """
    if not msgtimeMs:
        return ""
    return _dt.datetime.fromtimestamp(int(msgtimeMs) / 1000,
                                      tz=_dt.timezone.utc).isoformat()


class ArchiveProjectionStore:
    """`channel_archive_messages` 投影表唯一写路径（append-only；水印事务推进）。

    - 落行与推水印**同一事务**：拉取失败不落半行（§5），水印只在成功后推进；
    - 幂等：seq 主键＋msgid 唯一索引，INSERT OR IGNORE——重放同批 written=0；
    - 多线程访问走 RLock（AGENTS §3），WAL 常开；
    - 水印存 `channel_archive_state`（键 `watermark_seq`）：未知 key_ver 跳过行的
      seq 也在水印里，投影表 max(seq) 会因跳行滞后、不能当水印用。
    """

    def __init__(self, dbPath: Any) -> None:
        from neurova.core.db_migration import migrate as applyMigrations

        self._lock = threading.RLock()
        self.path = Path(dbPath)
        if self.path.parent and str(self.path.parent):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False,
                                     timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        applyMigrations(self._conn, domain="channel_archive")

    def appendBatch(self, rows: List[Dict[str, Any]], nextSeq: int,
                    fetchedAt: Optional[str] = None) -> int:
        """单事务落一批＋推水印；返回实际新写入行数（重放幂等时为 0）。"""
        stamped = fetchedAt or _nowIso()
        with self._lock:
            cur = self._conn.cursor()
            try:
                written = 0
                for row in rows:
                    cur.execute(
                        "INSERT OR IGNORE INTO channel_archive_messages ("
                        " seq, msgid, publickey_ver, action, msgtype, from_id,"
                        " tolist, roomid, msgtime_ms, text, media_ref, fetched_at"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (int(row["seq"]), str(row.get("msgid") or ""),
                         str(row.get("publickey_ver") or ""),
                         str(row.get("action") or "send"),
                         str(row.get("msgtype") or ""),
                         str(row.get("from_id") or ""),
                         str(row.get("tolist") or "[]"),
                         str(row.get("roomid") or ""),
                         int(row.get("msgtime_ms") or 0),
                         str(row.get("text") or ""),
                         str(row.get("media_ref") or ""), stamped))
                    written += max(0, cur.rowcount)
                cur.execute(
                    "INSERT INTO channel_archive_state (key, value, updated_at)"
                    " VALUES ('watermark_seq', ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET"
                    " value = MAX(value, excluded.value), updated_at = excluded.updated_at",
                    (str(int(nextSeq)), stamped))
                self._conn.commit()
                return written
            except Exception:
                self._conn.rollback()
                raise

    def watermark(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM channel_archive_state WHERE key = 'watermark_seq'"
            ).fetchone()
        return int(row[0]) if row else 0

    def querySendRows(self, sinceSeq: int, limit: int) -> Tuple[List[Dict[str, Any]], int, bool]:
        """写侧便捷读（测试/worker 读数用）；企业源消费面走自己的 mode=ro 短连接，
        共用同一条 SEND_ROWS_SQL。按 seq 扫描、send 过滤在 Python 侧做（游标推进
        过全部扫描行，含 recall/switch）；返回 (行, lastSeq, hasMore)，limit+1 探测。"""
        with self._lock:
            fetched = self._conn.execute(
                SEND_ROWS_SQL, (int(sinceSeq), int(limit) + 1)).fetchall()
        hasMore = len(fetched) > int(limit)
        scanned = fetched[: int(limit)]
        lastSeq = max((int(r[0]) for r in scanned), default=int(sinceSeq))
        sends = [self._rowFromDbRow(r) for r in scanned if r[2] == "send"]
        return sends, lastSeq, hasMore

    @staticmethod
    def _rowFromDbRow(dbRow: tuple) -> Dict[str, Any]:
        keys = ("seq", "msgid", "action", "msgtype", "from_id", "tolist", "roomid",
                "msgtime_ms", "text", "media_ref")
        return dict(zip(keys, dbRow))

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ══ 批 C7c：落库前白名单过滤＋常驻增量拉取（worker）══

#: 常驻拉取节拍（秒）：默认 5 分钟，须**远小于**官方 5 天窗口（方案 §8——
#: 停拉超过 5 天那段历史永久取不回，节拍与水位落后读数共同防静默丢历史）。
ARCHIVE_WORKER_DEFAULT_INTERVAL_SECONDS = 300
ARCHIVE_WORKER_INTERVAL_ENV = "NEUROVA_WECOM_ARCHIVE_INTERVAL_SECONDS"
#: 常驻开关 env（方案 §8：通道层定时任务默认关、env 门控）
ARCHIVE_WORKER_ENV = "NEUROVA_WECOM_ARCHIVE_WORKER"
#: 每轮最大批数×批大小＝单轮自我节流上限（对齐 registry 的 20×200=4000 行/轮口径；
#: 与官方 4000 次/分钟速率限制不是一回事，方案 §8）
ARCHIVE_WORKER_BATCHES_PER_CYCLE = 20
ARCHIVE_WORKER_BATCH_LIMIT = 200
#: 官方硬窗口（天）：水位落后超过它＝那段历史永久取不回（方案 §3/§8/§16-1）
ARCHIVE_WINDOW_DAYS = 5


def applyArchiveAllowlist(rows: List[Dict[str, Any]],
                          roomAllowlist: Sequence[str],
                          userAllowlist: Sequence[str]) -> Tuple[List[Dict[str, Any]], int]:
    """隐私白名单**落库前**过滤（方案 §13-1：不是摄取后再删）。

    - `archiveRoomAllowlist` 非空 → 群聊行只保留 roomid 在名单内的；
    - `archiveUserAllowlist` 非空 → 行的参与者（from/tolist）须与名单有交集；
    - 两者都给＝同时满足（AND）；都空＝不过滤（白名单是隐私缓解手段，
      不是功能开关——没有名单时如实全量落投影，靠部署侧配置约束范围）。
    返回 (保留行, 过滤掉的数量)——过滤数进 health/读数，不许静默丢。
    """
    rooms = {str(r) for r in (roomAllowlist or [])}
    users = {str(u) for u in (userAllowlist or [])}
    if not rooms and not users:
        return list(rows), 0
    kept: List[Dict[str, Any]] = []
    filtered = 0
    for row in rows:
        if rooms and (not row.get("roomid") or row["roomid"] not in rooms):
            filtered += 1
            continue
        if users:
            try:
                tolist = json.loads(row.get("tolist") or "[]")
            except (TypeError, ValueError):
                tolist = []
            participants = {str(row.get("from_id") or "")} | {str(t) for t in tolist}
            if not (participants & users):
                filtered += 1
                continue
        kept.append(row)
    return kept, filtered


def _archiveWorkerContexts(agentId: str) -> List[Dict[str, Any]]:
    """装配好的企微渠道 → 存档拉取上下文（凭据在此解引用，不过企业源的手）。"""
    from neurova.channels.manager import get_channel_manager

    contexts: List[Dict[str, Any]] = []
    adapter = get_channel_manager().get_adapter("wecom", agent_id=str(agentId or "default"))
    if adapter is None:
        return contexts
    extra = adapter.config.extra or {}
    reading = archiveReadiness(extra)
    if not reading.ready:
        contexts.append({"agentId": str(agentId or "default"), "ready": False,
                         "reason": reading.reason})
        return contexts
    secretEnv = str(extra.get(ARCHIVE_SECRET_ENV_FIELD) or "").strip()
    keyMap: Dict[str, bytes] = {}
    for version, rawPath in (extra.get(ARCHIVE_PRIVATE_KEYS_FIELD) or {}).items():
        keyMap[str(version)] = Path(str(rawPath)).read_bytes()
    contexts.append({
        "agentId": str(agentId or "default"),
        "ready": True,
        "sdkPath": (str(extra.get(ARCHIVE_SDK_PATH_FIELD) or "").strip()
                    or os.environ.get(ARCHIVE_SDK_PATH_ENV, "").strip()),
        "corpid": str(extra.get("corpid") or extra.get("app_id") or ""),
        "secret": os.environ.get(secretEnv, ""),
        "keyMap": keyMap,
        "roomAllowlist": list(extra.get(ARCHIVE_ROOM_ALLOWLIST_FIELD) or []),
        "userAllowlist": list(extra.get(ARCHIVE_USER_ALLOWLIST_FIELD) or []),
    })
    return contexts


def runArchiveWorkerCycle(agentId: str = "default", *,
                          sdkFactory: Any = None,
                          storeFactory: Any = None,
                          batchesPerCycle: int = ARCHIVE_WORKER_BATCHES_PER_CYCLE,
                          batchLimit: int = ARCHIVE_WORKER_BATCH_LIMIT) -> Dict[str, Any]:
    """常驻拉取的单轮：凭据就绪则从**已存水位**增量拉到当前水位，落库前过白名单。

    - **backfill 默认开（方案 §8 更正后语义）**：水位初始 0＝首轮即从 seq=0 拉到
      当前水位——5 天窗口下不拉就永久丢，不存在「要不要回溯」的开关可关；
    - 单轮批量上限＝batchesPerCycle×batchLimit（自我节流，与官方速率上限两回事）；
    - 每批「拉取→过滤→落库＋推水印」事务收口，任一批失败整轮抛出（下轮从水位续拉）；
    - sdkFactory/storeFactory 是测试注入口（假 SDK／临时库），生产缺省走真件。
    """
    from neurova.core.data_root import callerPath

    contexts = _archiveWorkerContexts(agentId)
    if not contexts:
        return {"status": "skipped", "reason": "企微通道未装配（agent=%s）" % agentId}
    context = contexts[0]
    if not context.get("ready"):
        return {"status": "skipped", "reason": str(context.get("reason") or "")}
    dbPath = callerPath(os.environ.get(CHANNEL_ARCHIVE_DB_ENV), "channel_archive.db")
    store = storeFactory(dbPath) if storeFactory else ArchiveProjectionStore(dbPath)
    sdk = None
    try:
        if sdkFactory is not None:
            sdk = sdkFactory()
        else:
            secret = str(context.get("secret") or "")
            sdk = ArchiveSdkHandle(str(context["sdkPath"]),
                                   str(context.get("corpid") or ""), secret)
        watermark = store.watermark()
        writtenTotal = 0
        counts: Dict[str, int] = {}
        filteredTotal = 0
        for _ in range(max(1, int(batchesPerCycle))):
            result = pullArchiveBatch(sdk, watermark, batchLimit, context["keyMap"])
            kept, filtered = applyArchiveAllowlist(
                result.rows,
                context.get("roomAllowlist") or [],
                context.get("userAllowlist") or [])
            filteredTotal += filtered
            for name, value in result.counts.items():
                counts[name] = counts.get(name, 0) + value
            store.appendBatch(kept, result.nextSeq)
            writtenTotal += len(kept)
            watermark = result.nextSeq
            if not result.hasMore:
                break
        return {"status": "ok", "written": writtenTotal, "filtered": filteredTotal,
                "watermark": int(watermark), "counts": counts}
    finally:
        if sdk is not None and hasattr(sdk, "close"):
            sdk.close()
        store.close()


async def runArchiveWorkerLoop(intervalSeconds: Optional[float] = None,
                               stopEvent: Any = None) -> None:
    """常驻轮询环：周期跑 runArchiveWorkerCycle（ctypes 阻塞调用进线程池）。

    单轮失败下轮再试（对齐 ingest_bridge.runIngestWorker 的容错口径）；
    间隔取 `NEUROVA_WECOM_ARCHIVE_INTERVAL_SECONDS`，缺省 300s。"""
    import asyncio

    from neurova.core.logger import get_logger

    logger = get_logger(__name__)
    rawInterval = (intervalSeconds
                   or os.environ.get(ARCHIVE_WORKER_INTERVAL_ENV)
                   or ARCHIVE_WORKER_DEFAULT_INTERVAL_SECONDS)
    interval = max(5.0, float(rawInterval))
    while True:
        if stopEvent is not None and stopEvent.is_set():
            return
        try:
            outcome = await asyncio.to_thread(runArchiveWorkerCycle)
            if outcome.get("status") != "ok":
                logger.info("会话存档拉取轮跳过: %s", outcome.get("reason") or "")
            else:
                logger.info("会话存档拉取轮完成: written=%s watermark=%s",
                            outcome.get("written"), outcome.get("watermark"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单轮失败下轮再试，不打死进程
            logger.warning("会话存档拉取单轮失败: %s", exc)
        try:
            if stopEvent is not None:
                await asyncio.wait_for(stopEvent.wait(), timeout=interval)
            else:
                await asyncio.sleep(interval)
        except asyncio.TimeoutError:
            continue


def watermarkLagDays(updatedAtIso: str) -> Optional[int]:
    """水位落后天数（now − updated_at 向下取整）；无时间戳返回 None。"""
    if not updatedAtIso:
        return None
    try:
        stamp = _dt.datetime.fromisoformat(str(updatedAtIso))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return int((_dt.datetime.now(_dt.timezone.utc) - stamp).total_seconds() // 86400)


def watermarkLagReading(updatedAtIso: str) -> str:
    """水位落后读数（方案 §8：health 须能报「水位落后多久」，否则静默丢历史）。

    落后 ≥ 官方 5 天窗口 → 点名「落后的历史已不可取回」；窗口内 → 只报天数。
    """
    lag = watermarkLagDays(updatedAtIso)
    if lag is None:
        return ""
    if lag >= ARCHIVE_WINDOW_DAYS:
        return "水位落后 %d 天——已超过官方 %d 天窗口，落后的历史**不可取回**" % (
            lag, ARCHIVE_WINDOW_DAYS)
    if lag >= 1:
        return "水位落后 %d 天" % lag
    return ""