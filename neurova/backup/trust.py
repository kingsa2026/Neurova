# -*- coding: utf-8 -*-
"""
backup 信任模型核心（P3-c，对标 QP beta.5 backup/signing）

把备份 zip 当信任边界：
- SigningKey：每实例 32 字节 HMAC key（0600、O_EXCL 原子创建、拒绝 symlink）
- sign_backup：meta 写入 signature = "hmac-sha256-v1:<hex>"，覆盖
  meta 固定字段集（signature 字段本身除外）+ 全部非 meta 条目（确定性排序、流式）
- verify_backup 三态：TRUSTED（本地签名验证通过）/ FOREIGN（签名不匹配——
  篡改或他实例备份）/ LEGACY（无签名——旧格式或外来未签名）
- resign_backup：外来备份显式信任后用本地 key 重签（绑定本地决定）

注意（诚实边界）：本模块是**核心判定层**；与 NV 备份子系统的接入
（创建/恢复流程调用 sign/verify）属上层编排，后续接线。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

SIGNATURE_SCHEME = "hmac-sha256-v1"
_META_ENTRY = "meta.json"
_SIGNATURE_KEY = "signature"

# meta 中参与签名的固定字段集（新增字段必须显式加入——防漏签漂移）
_SIGNED_META_FIELDS = ("scheme", "created_at", "backup_id")


class BackupTrustError(Exception):
    """备份信任模型操作失败"""


class TrustMode(str, Enum):
    TRUSTED = "trusted"
    FOREIGN = "foreign"
    LEGACY = "legacy"


@dataclass
class TrustVerdict:
    mode: TrustMode
    detail: str = ""


class SigningKey:
    """每实例 HMAC 签名 key（32 字节，落盘 0600）。"""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.key_bytes = self._load_or_create()

    def _load_or_create(self) -> bytes:
        if self.path.exists():
            if self.path.is_symlink():
                raise BackupTrustError(f"签名 key 路径是 symlink，拒绝: {self.path}")
            data = self.path.read_bytes()
            if len(data) < 32:
                raise BackupTrustError(f"签名 key 过短（{len(data)}B < 32B）: {self.path}")
            return data
        # O_CREAT|O_EXCL 原子创建 + 0600
        fd = os.open(
            str(self.path),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        try:
            os.write(fd, os.urandom(32))
        finally:
            os.close(fd)
        return self.path.read_bytes()

    def sign(self, data: bytes) -> str:
        return hmac.new(self.key_bytes, data, hashlib.sha256).hexdigest()


def _canonical_meta_bytes(meta: Dict) -> bytes:
    """meta 签名规范化：固定字段集、确定性 JSON（键排序）。"""
    subset = {k: meta.get(k) for k in _SIGNED_META_FIELDS if k in meta}
    return json.dumps(subset, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _compute_backup_digest(zp: Path) -> bytes:
    """备份内容指纹：meta 固定字段 + 全部非 meta 条目（确定性排序、流式）。

    帧格式与 QP 对齐语义：ENTRY\\0name\\0bytes\\0size(8B)\\0
    """
    h = hashlib.sha256()
    h.update(b"META\x00")
    with zipfile.ZipFile(zp, "r") as zf:
        meta = json.loads(zf.read(_META_ENTRY))
        h.update(_canonical_meta_bytes(meta))
        for name in sorted(zf.namelist()):
            if name == _META_ENTRY:
                continue
            payload = zf.read(name)
            h.update(b"ENTRY\x00")
            h.update(name.encode("utf-8"))
            h.update(b"\x00")
            h.update(str(len(payload)).encode("ascii"))
            h.update(b"\x00")
            h.update(payload)
    return h.digest()


def sign_backup(zip_path: Union[str, Path], key: SigningKey) -> None:
    """用本地 key 签名备份（重写 meta.json 插入 signature 字段，tmp+replace）。"""
    zp = Path(zip_path)
    digest = _compute_backup_digest(zp)
    signature = f"{SIGNATURE_SCHEME}:{key.sign(digest)}"

    with zipfile.ZipFile(zp, "r") as zf:
        entries = {n: zf.read(n) for n in zf.namelist() if n != _META_ENTRY}
        meta = json.loads(zf.read(_META_ENTRY))
    meta[_SIGNATURE_KEY] = signature

    tmp = zp.with_suffix(".zip.resign")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(entries):
            zf.writestr(name, entries[name])
        zf.writestr(_META_ENTRY, json.dumps(meta, ensure_ascii=False, indent=2))
    tmp.replace(zp)
    logger.info("备份已签名: %s (%s)", zp.name, signature[:32] + "...")


def verify_backup(zip_path: Union[str, Path], key: SigningKey) -> TrustVerdict:
    """验证备份信任三态。"""
    zp = Path(zip_path)
    try:
        with zipfile.ZipFile(zp, "r") as zf:
            if _META_ENTRY not in zf.namelist():
                return TrustVerdict(TrustMode.LEGACY, "无 meta.json")
            meta = json.loads(zf.read(_META_ENTRY))
    except (zipfile.BadZipFile, json.JSONDecodeError) as e:
        return TrustVerdict(TrustMode.FOREIGN, f"损坏的备份包: {e}")

    signature = meta.get(_SIGNATURE_KEY)
    if not signature:
        return TrustVerdict(TrustMode.LEGACY, "无签名（legacy 格式）")
    if not signature.startswith(SIGNATURE_SCHEME + ":"):
        return TrustVerdict(TrustMode.FOREIGN, f"未知签名方案: {signature[:40]}")

    expected = key.sign(_compute_backup_digest(zp))
    actual = signature.split(":", 1)[1]
    if hmac.compare_digest(expected, actual):
        return TrustVerdict(TrustMode.TRUSTED)
    return TrustVerdict(TrustMode.FOREIGN, "签名不匹配（篡改或来自其他实例）")


def resign_backup(zip_path: Union[str, Path], key: SigningKey) -> None:
    """外来备份显式信任后用本地 key 重签（绑定本地决定）。"""
    sign_backup(zip_path, key)
    logger.info("外来备份已重签绑定本地实例: %s", Path(zip_path).name)
