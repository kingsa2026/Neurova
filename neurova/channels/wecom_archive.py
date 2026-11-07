# -*- coding: utf-8 -*-
"""企微会话内容存档：凭据面与就绪读数（批 C7a，2026-11-08 裁定甲案）。

方案出处：`docs/specs/2026-11-07-wecom-chat-archive-history-source-plan.md` §6.1/§7/§16。

**本模块不含任何拉取逻辑**（读取面属 C7b）：只负责「配置面只放指针」的校验，
以及一份诚实的就绪读数——渠道配置写入口与聊天企业源 `health()` 共用同一判断，
不在两处各写一份（教义第 6/7 条）。

官方核查结论（方案 §16-1）：会话内容存档只分发 **C 动态库**（linux x86/arm、windows），
**没有官方 Python 包**；`GetChatData` 从 `seq+1` 起、`limit ≤ 1000`、`≤4000 次/分钟`，
且只给 **≤5 天**窗口。据此：

- 库路径由部署侧显式给（`extra.archiveSdkPath` 或 `NEUROVA_WECOM_ARCHIVE_SDK`），
  本模块**不猜文件名**——未经一次真实部署核实的名字不写进代码当默认值；
- 探测走 `ctypes` 加载（标准库，零新增 pip 件，不引第三方 Python 包装）；
- 凭据齐了也仍 `degraded` 并点名读取面未实现——报 `ok` 就是冒充全量可达。

凭据落点（裁定 B＋§6.1）：配置面只放**指针**，值一律不进 `extra`。理由是
`GET /channel-configs/{type}` 把 `extra` 原样回读，且新增封存键名要同步
`secret_store.CREDENTIAL_KEY_NAMES`＋前端密码字段表＋11 语言文案。故 Secret 走
环境变量名指针、私钥走「`publickey_ver` → 文件路径」映射；明文进配置即拒。
"""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

#: 渠道配置 `extra` 里的三个指针字段（单一事实源：写入口校验与就绪读数共读这一份）
ARCHIVE_SDK_PATH_FIELD = "archiveSdkPath"
ARCHIVE_SECRET_ENV_FIELD = "archiveSecretEnv"
ARCHIVE_PRIVATE_KEYS_FIELD = "archivePrivateKeys"

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
    """就绪读数：只有 status 与 reason 两个字段，两者都有生产消费方。

    status ∈ ok/degraded/error；C7a 不产 ok（读取面未实现，报 ok 即冒充全量可达）。
    reason 一律不含密钥值、私钥内容与消息正文。
    """

    status: str
    reason: str


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
    reason = "会话存档原生库与凭据就位，读取面属批 C7b 未实现"
    if notes:
        reason += "；" + "；".join(dict.fromkeys(notes))
    return ArchiveReadiness(status="degraded", reason=reason)


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