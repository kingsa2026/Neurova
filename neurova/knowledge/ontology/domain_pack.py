# -*- coding: utf-8 -*-
"""领域包加载/导入（GB/T 48000.3 评估档 G5，第 9 章扩展方式的示范载体）。

领域包是**数据**（domain_packs/*.json），不是代码级种子——按扩展原则承载
领域词汇（首批："standard" 标准本体包，词汇依据征求意见稿 6.2/8 章）。
导入 = `seedMissing` 只补缺：已登记术语一行不动（写入方覆盖声明以登记者为准）；
导入计数如实返回，二次导入零写入即幂等。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

_PACKS_DIR = Path(__file__).parent / "domain_packs"


@lru_cache(maxsize=None)
def _loadPackFile(packId: str) -> Dict[str, Any]:
    path = (_PACKS_DIR / ("%s_pack.json" % packId)).resolve()
    if not path.is_file() or _PACKS_DIR.resolve() not in path.parents:
        raise ValueError("未注册领域包: %r" % packId)
    with path.open(encoding="utf-8") as handle:
        pack = json.load(handle)
    if pack.get("packId") != packId:
        raise ValueError("领域包元数据不一致: %r" % packId)
    return pack


def loadDomainPack(packId: str) -> Dict[str, Any]:
    """加载领域包（packId/namespace/basedOn/note/terms）。未注册 → ValueError。"""
    return _loadPackFile(packId)


def availablePacks() -> List[Dict[str, Any]]:
    """可用领域包清单（概要，不含 terms 全量）。"""
    packs = []
    for path in sorted(_PACKS_DIR.glob("*_pack.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
            packs.append({"packId": pack.get("packId"), "namespace": pack.get("namespace"),
                          "basedOn": pack.get("basedOn"), "note": pack.get("note"),
                          "termCount": len(pack.get("terms") or [])})
        except (json.JSONDecodeError, OSError):
            continue
    return packs


# C2 不可变锁定：已导入包的 SHA-256 注册表（进程内——首次导入登记，再导入比对）
_importChecksums: Dict[str, str] = {}


def importDomainPack(registry: Any, packId: str, tenantId: str = "default") -> int:
    """导入领域包（只补缺幂等）：返回真正补上的术语条数。未注册包 → ValueError。

    C2 不可变锁定：首次导入登记 SHA-256；再导入时比对——漂移显式拒（不静默换版）。
    """
    currentChecksum = packChecksum(packId)
    registered = _importChecksums.get(packId)
    if registered is not None and registered != currentChecksum:
        raise ValueError(
            "领域包 %r SHA-256 漂移：registered=%s current=%s（不可变锁定——"
            "新版本须显式清除旧登记后重导）" % (packId, registered[:16], currentChecksum[:16]))
    pack = loadDomainPack(packId)
    added = registry.seedMissing(pack["terms"], tenantId=tenantId)
    _importChecksums[packId] = currentChecksum
    return added


def packBytes(packId: str) -> bytes:
    """领域包原始字节（C2 工件层——校验和与不可变登记共用这一个读法）。"""
    path = (_PACKS_DIR / ("%s_pack.json" % packId)).resolve()
    if not path.is_file() or _PACKS_DIR.resolve() not in path.parents:
        raise ValueError("未注册领域包: %r" % packId)
    return path.read_bytes()


def packChecksum(packId: str) -> str:
    """领域包原始字节的 SHA-256 校验和（C2 工件级内容地址溯源）。"""
    import hashlib

    return hashlib.sha256(packBytes(packId)).hexdigest()


def packAttribution(packId: str) -> Dict[str, Any]:
    """领域包归属卡（C2）：license/upstream/version/termCount/SHA-256。"""
    pack = loadDomainPack(packId)
    return {
        "packId": packId,
        "namespace": pack.get("namespace", ""),
        "basedOn": pack.get("basedOn", ""),
        "note": pack.get("note", ""),
        "termCount": len(pack.get("terms") or []),
        "sha256": packChecksum(packId),
        "license": pack.get("license", ""),
        "upstream": pack.get("upstream", ""),
        "version": pack.get("version", "v1"),
    }


def verifyPackIntegrity(packId: str, registeredChecksum: str = "") -> Dict[str, Any]:
    """完整性校验：当前 SHA-256 vs 调用方传入的注册哈希（漂移显式报）。

    哈希不能存在 pack 文件自身（自引用不可能）——registeredChecksum 由
    调用方（导入端点/审批面/外部清单）传入注册时记录的值。"""
    current = packChecksum(packId)
    if not registeredChecksum:
        return {"packId": packId, "status": "unverified", "sha256": current,
                "detail": "无注册哈希可比对（首次导入时由调用方登记）"}
    if current != registeredChecksum:
        return {"packId": packId, "status": "drift", "sha256": current,
                "detail": "SHA-256 漂移：registered=%s current=%s（版本漂移显式报，不静默换版）"
                          % (registeredChecksum[:16], current[:16]),
                "registered": registeredChecksum}
    return {"packId": packId, "status": "ok", "sha256": current}
