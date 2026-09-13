"""
安全压缩包解包 —— 阻断 Zip Slip / Tar Slip (安全审计 L3)

背景:
    多处 ``zipfile.extractall()`` / ``tarfile.extractall()`` 未校验成员路径。
    恶意压缩包用 ``../../etc/cron.d/x`` 这类成员名可在解包时向目标目录外
    写文件（Zip Slip / Tar Slip），skill 市场/远程安装场景可直接演化为
    任意文件写入 / RCE。

设计:
    解包前逐个成员校验，任一成员越界即整体拒绝（fail-closed）：
      - 拒绝绝对路径
      - 拒绝含 ``..`` 的路径
      - 拒绝符号链接/硬链接（tar）——链接可指向目录外
      - 解析后的最终路径必须落在目标目录内

用法::

    from neurova.security.safe_archive import safe_extract_zip, safe_extract_tar

    safe_extract_zip(zip_path, target_dir)
    safe_extract_tar(tar_path, target_dir)          # 自动识别 gz/bz2/xz
"""

from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path
from typing import Union

__all__ = ["UnsafeArchiveError", "safe_extract_zip", "safe_extract_tar"]


class UnsafeArchiveError(ValueError):
    """压缩包含不安全成员，已拒绝解包。"""


def _resolve_within(base: Path, name: str) -> Path:
    """把成员名解析到 base 内，越界则抛 UnsafeArchiveError。"""
    if not name or name in (".", "./"):
        raise UnsafeArchiveError("非法成员名")
    # 绝对路径 / 盘符 / UNC 直接拒绝
    if os.path.isabs(name) or name.startswith(("/", "\\")) or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchiveError(f"压缩包含绝对路径成员: {name}")
    # 归一化后必须仍在 base 内（显式拦 ..）
    norm = os.path.normpath(name)
    if norm == ".." or norm.startswith(".." + os.sep) or f"..{os.sep}" in norm or norm.startswith(".."):
        raise UnsafeArchiveError(f"压缩包含路径穿越成员: {name}")
    target = (base / norm).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise UnsafeArchiveError(f"成员越出目标目录: {name}")
    return target


def safe_extract_zip(source: Union[str, bytes, Path, "zipfile.ZipFile"], target_dir: Union[str, Path]) -> Path:
    """安全解包 ZIP，校验每个成员路径后落盘。

    source 可以是路径、字节内容或已打开的 ZipFile。
    """
    base = Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    own = False
    if isinstance(source, zipfile.ZipFile):
        zf = source
    elif isinstance(source, (bytes, bytearray)):
        zf = zipfile.ZipFile(io.BytesIO(source), "r")
        own = True
    else:
        zf = zipfile.ZipFile(source, "r")
        own = True
    try:
        for info in zf.infolist():
            _resolve_within(base, info.filename)
        zf.extractall(base)
    finally:
        if own:
            zf.close()
    return base


def safe_extract_tar(source: Union[str, Path, tarfile.TarFile], target_dir: Union[str, Path], mode: str = "r:*") -> Path:
    """安全解包 TAR（自动识别 gz/bz2/xz），校验成员路径与链接类型。

    source 可以是路径或已打开的 TarFile。
    """
    base = Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    own = False
    if isinstance(source, tarfile.TarFile):
        tf = source
    elif hasattr(source, "read"):
        # 文件类对象（io.BytesIO 等）
        tf = tarfile.open(fileobj=source, mode=mode)  # type: ignore[arg-type]
        own = True
    else:
        tf = tarfile.open(source, mode=mode)
        own = True
    try:
        members = tf.getmembers()
        for member in members:
            if member.issym() or member.islnk():
                raise UnsafeArchiveError(f"压缩包含链接成员: {member.name}")
            _resolve_within(base, member.name)
        # Python 3.12+ 支持 filter='data'；旧版本已在上面显式校验
        try:
            tf.extractall(base, filter="data")
        except TypeError:
            tf.extractall(base)
    finally:
        if own:
            tf.close()
    return base
