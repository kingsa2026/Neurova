# -*- coding: utf-8 -*-
"""
备份编排层（遗留②，P3-c trust 核心的流程接线）

- create_backup(sources)：目录集打包 → sign_backup → 签名 zip
- restore_backup(zip, apply_fn, trust=False)：verify 信任门 →
  TRUSTED/显式信任的 LEGACY 才执行 apply_fn（payload 与
  CheckpointService.restore_snapshot 同形：session_json/kb_files）
- import_backup(zip, trust=False)：外来/legacy 备份导入即本地重签
  （绑定本地决定，QP 语义）

诚实边界：编排层只负责"包+信任+内容交付"，写回动作（会话/文件落盘）
由调用方经 apply_fn 注入；回滚复用 CheckpointService.restore_with_rollback。
"""

from __future__ import annotations

import datetime
import json
import secrets
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from neurova.backup.trust import (
    SigningKey,
    TrustMode,
    resign_backup,
    sign_backup,
    verify_backup,
)
from neurova.core.logger import get_logger

logger = get_logger(__name__)


class TrustRequiredError(Exception):
    """备份信任校验未通过（FOREIGN 或未显式信任的 LEGACY）"""


class BackupOrchestrator:
    """备份编排（create/restore/import，信任门内建）。"""

    def __init__(self, key: SigningKey, work_dir: Union[str, Path] = "data/backups"):
        self.key = key
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # ── create ──

    def create_backup(self, sources: Dict[str, Path]) -> Path:
        """把目录集打包为签名备份。

        Args:
            sources: {逻辑前缀: 目录路径}——目录内文件按
                `<前缀>/<相对路径>` 进包（会话/知识库等分开挂载）

        Returns:
            产物 zip 路径
        """
        backup_id = f"nvbak-{datetime.datetime.now().strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(3)}"
        meta = {
            "scheme": "hmac-sha256-v1",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "backup_id": backup_id,
        }
        out = self.work_dir / f"{backup_id}.zip"

        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for prefix, directory in sorted(sources.items()):
                d = Path(directory)
                if not d.exists():
                    logger.warning("备份源目录不存在，跳过: %s", d)
                    continue
                for f in sorted(d.rglob("*")):
                    if not f.is_file():
                        continue
                    rel = f.relative_to(d).as_posix()
                    zf.writestr(f"{prefix}/{rel}", f.read_bytes())
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        sign_backup(out, self.key)
        logger.info("备份创建完成: %s", out.name)
        return out

    # ── restore ──

    def restore_backup(
        self,
        zip_path: Union[str, Path],
        apply_fn: Callable[[Dict[str, Any]], Any],
        key: Optional[SigningKey] = None,
        trust: bool = False,
    ) -> Dict[str, Any]:
        """信任门 + 内容交付。

        verify 结果：
        - TRUSTED → 交付内容给 apply_fn
        - LEGACY → 仅在 trust=True（用户显式信任旧格式）时放行
        - FOREIGN → 一律 TrustRequiredError（篡改/他实例，不可用 trust 覆盖）

        Returns:
            {"mode": ..., "files": {path: content}, "meta": {...}}
        """
        zp = Path(zip_path)
        verdict = verify_backup(zp, key or self.key)
        if verdict.mode == TrustMode.FOREIGN:
            raise TrustRequiredError(
                f"备份信任校验失败（FOREIGN，{verdict.detail}）——拒绝恢复"
            )
        if verdict.mode == TrustMode.LEGACY and not trust:
            raise TrustRequiredError(
                "备份无签名（legacy）——需显式 trust=True 才可恢复"
            )

        with zipfile.ZipFile(zp, "r") as zf:
            meta = json.loads(zf.read("meta.json"))
            files: Dict[str, str] = {}
            for name in zf.namelist():
                if name == "meta.json":
                    continue
                files[name] = zf.read(name).decode("utf-8", "replace")

        payload = {"mode": verdict.mode, "files": files, "meta": meta}
        logger.info(
            "备份恢复交付: %s (mode=%s, %d files)", zp.name, verdict.mode.value, len(files)
        )
        apply_fn(payload)
        return payload

    # ── import ──

    def import_backup(
        self,
        zip_path: Union[str, Path],
        trust: bool = False,
    ) -> Path:
        """导入外来备份：复制进工作目录并本地重签（绑定本地决定）。

        LEGACY（无签名）需 trust=True；FOREIGN（签名校验失败=篡改）一律拒绝。
        """
        zp = Path(zip_path)
        verdict = verify_backup(zp, self.key)
        # FOREIGN = 他实例签名或篡改：导入需显式 trust=True（用户承担；
        # 导入即本地重签，绑定本地决定）。restore 路径 FOREIGN 仍无条件拒绝。
        if verdict.mode == TrustMode.FOREIGN and not trust:
            raise TrustRequiredError(
                f"导入备份签名校验失败（FOREIGN，{verdict.detail}）——"
                "需显式 trust=True（确认为其他实例的正常备份）"
            )
        if verdict.mode == TrustMode.LEGACY and not trust:
            raise TrustRequiredError(
                "导入备份无签名（legacy）——需显式 trust=True"
            )

        imported = self.work_dir / f"imported-{secrets.token_hex(4)}-{zp.name}"
        import shutil

        shutil.copy2(zp, imported)
        resign_backup(imported, self.key)
        logger.info("备份导入完成: %s", imported.name)
        return imported
