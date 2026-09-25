# -*- coding: utf-8 -*-
"""包内 media：内容寻址落盘、读回时的路径与摘要校验。

为什么内容寻址：同一张图在一场对话里常被引用多次（发送、重试、再贴），按名字存就会存 N 份、
撤销也数不清；按摘要存则天然去重，而且摘要本身就是完整性校验的凭据。

源侧形态按实测收敛成三类：base64 正文（截图/贴图）、源机器命名空间里的绝对路径（每日对话记的
是 /agents/<workdir>/media/xxx，本机在源目录树下确有同名文件）、file 块的裸路径。绝对路径不
直接读——只在源目录树的 media/ 子目录下按同名找，找不到就申报不可达：否则"导入"就成了任意
文件读。
"""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from neurova.core.safe_paths import UnsafePathError, resolve_within

MEDIA_DIRNAME = "media"
MAX_MEDIA_BYTES = 64 * 1024 * 1024          # 单文件上限：超了宁可申报也不静默吃进包
_DIGEST_LEN = 32

# 源里承载媒体的块型（各家长得不一样，但都是"载体"而非正文）
MEDIA_BLOCK_TYPES: Tuple[str, ...] = ("image", "file", "data")

# 魔术数用码点写死：PNG 头自带换行与控制字节，源码里不留不可见字符
_MAGIC: Tuple[Tuple[bytes, str], ...] = (
    (bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]), ".png"),
    (bytes([0xFF, 0xD8, 0xFF]), ".jpg"),
    (b"GIF8", ".gif"),
    (b"%PDF", ".pdf"),
    (b"PK" + bytes([0x03, 0x04]), ".zip"),
)


class MediaSink:
    """把源里的媒体载体按内容寻址写进包的 media/，返回可放进 content_blocks 的引用。"""

    def __init__(self, out_dir: Path, *, name_hint: str = "",
                 store: Optional[Path] = None) -> None:
        self.out_dir = Path(out_dir)
        self.name_hint = name_hint
        self.store = Path(store) if store else Path(out_dir)
        self.total_bytes = 0

    def resolve(self, block: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """源媒体块 → 包内引用；取不到字节返回 None，由上层申报条数。"""
        payload = resolve_payload(block, self.store)
        if payload is None:
            return None
        data, name = payload
        return self.put(data, name=name)

    def put(self, data: bytes, *, name: str = "") -> Optional[Dict[str, Any]]:
        """同名字节只落一份：摘要即文件名。"""
        if not data or len(data) > MAX_MEDIA_BYTES:
            return None
        digest = hashlib.sha256(data).hexdigest()[:_DIGEST_LEN]
        original = name or self.name_hint
        if not Path(original).suffix:
            original = f"{Path(original).stem or 'media'}{_sniff(data) or ''}"
        rel = f"{MEDIA_DIRNAME}/{digest}{Path(original).suffix.lower()}"
        target = self.out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
            self.total_bytes += len(data)
        return {"media": rel, "digest": digest, "bytes": len(data),
                "name": Path(original).name,
                "mime": mimetypes.guess_type(original)[0] or "application/octet-stream"}


def resolve_payload(source: Any, store: Path) -> Optional[Tuple[bytes, str]]:
    """源里的 media 载体（块或裸路径）→ (字节, 原名)。解不出返回 None 交给申报。"""
    if isinstance(source, dict):
        return _from_block(source, store)
    return _from_path(str(source or ""), store)


def verify_media(root: Path) -> List[str]:
    """包读回时的三道检查：引用在包内、文件在、摘要与声明相符。"""
    root = Path(root)
    errors: List[str] = []
    for lineno, row in _iter_rows(root / "transcripts.jsonl"):
        for block in row.get("content_blocks") or []:
            if not isinstance(block, dict) or not block.get("media"):
                continue
            errors.extend(_check_ref(root, str(block["media"]), block, lineno))
    return errors


def _check_ref(root: Path, rel: str, block: Dict[str, Any], lineno: int) -> List[str]:
    try:
        target = resolve_within(root, rel)
    except UnsafePathError as exc:
        return [f"transcripts.jsonl:{lineno} media 引用越出包外: {rel!r}（{exc}）"]
    parts = rel.split("/")
    if len(parts) != 2 or parts[0] != MEDIA_DIRNAME:
        return [f"transcripts.jsonl:{lineno} media 引用命名不符内容寻址约定: {rel!r}"
                f"（必须是 {MEDIA_DIRNAME}/<digest>.<ext>，落盘只取基名，子目录会被拍平）"]
    declared = str(block.get("digest") or "")
    if not declared:
        return [f"transcripts.jsonl:{lineno} media 引用摘要必须声明: {rel!r}"
                f"（无摘要就无法证明引用与字节是一对）"]
    if Path(rel).name != f"{declared}{Path(rel).suffix.lower()}":
        return [f"transcripts.jsonl:{lineno} media 引用命名不符内容寻址约定: {rel!r}"
                f"（文件名应为 {declared}<原后缀>）"]
    if not target.is_file():
        return [f"transcripts.jsonl:{lineno} media 缺文件: {rel!r}"]
    data = target.read_bytes()
    actual = hashlib.sha256(data).hexdigest()[:_DIGEST_LEN]
    if declared and declared != actual:
        return [f"transcripts.jsonl:{lineno} media 摘要不符: {rel!r}"
                f"（声明 {declared}，实际 {actual}）"]
    if len(data) > MAX_MEDIA_BYTES:
        return [f"transcripts.jsonl:{lineno} media 超单文件上限: {rel!r}"]
    return []


def _sniff(data: bytes) -> Optional[str]:
    """没带文件名的字节也得定类型：按魔术数定后缀，判不出就留空。"""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    return None


def _iter_rows(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    if not path.exists():
        return
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            yield lineno, parsed


def _from_block(block: Dict[str, Any], store: Path) -> Optional[Tuple[bytes, str]]:
    source = block.get("source")
    name = str(block.get("name") or block.get("filename") or "")
    if isinstance(source, dict):
        if str(source.get("type") or "") == "base64":
            return _decode_base64(source.get("data"), name)
        return _from_uri(str(source.get("url") or ""), store, name or _name_of_url(source.get("url")))
    if isinstance(source, str) and source.split(":", 1)[0].lower() in ("data", "file"):
        # 有的平台把 URI 直接放在 source/url 字段里（opencode 的 file 块是 data:）。# http 不在这里取：导入过程不联网拉外部内容。
        return _from_uri(source, store, name)
    if source is None and isinstance(block.get("data"), str):
        # 也有的把 base64 正文直接挂在块上（配 mimeType/media_type 说明类型），不套一层 source
        return _decode_base64(block["data"], name or _name_of_mime(block))
    return _from_path(str(source or ""), store, name)


def _name_of_mime(block: Dict[str, Any]) -> str:
    """块只声明了 MIME 时按它补一个后缀，让包内文件名与 mime 字段都定得下来。"""
    mime = str(block.get("mimeType") or block.get("media_type") or "")
    ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ""
    return f"media{ext}" if ext else ""


def _from_uri(uri: str, store: Path, fallback_name: str) -> Optional[Tuple[bytes, str]]:
    text = uri.strip()
    if text.startswith("data:"):
        _, _, payload = text.partition(",")
        return _decode_base64(payload, fallback_name)
    if text.startswith("file://"):
        text = text[len("file://"):]
    return _from_path(text, store, fallback_name)


def _decode_base64(data: Any, name: str) -> Optional[Tuple[bytes, str]]:
    try:
        raw = base64.b64decode(str(data or ""), validate=True)
    except Exception:                              # noqa: BLE001 - 解不出即视为不可得
        return None
    if not raw or len(raw) > MAX_MEDIA_BYTES:
        return None
    return raw, str(name or "")


def _from_path(raw: str, store: Path, name_hint: str = "") -> Optional[Tuple[bytes, str]]:
    name = Path(str(raw or "").replace("\\", "/")).name or Path(name_hint).name
    if not name or name.startswith("."):
        return None
    for media_dir in _media_dirs(store):
        try:
            candidate = resolve_within(media_dir, name)
        except UnsafePathError:
            continue
        if not candidate.is_file():
            continue
        if candidate.stat().st_size > MAX_MEDIA_BYTES:
            return None
        return candidate.read_bytes(), name
    return None


def _media_dirs(store: Path) -> List[Path]:
    """源目录树上层的 media/——只认这一处，不做全盘按名搜。"""
    store = Path(store)
    return [parent / MEDIA_DIRNAME for parent in store.parents if parent.is_dir()]


def _name_of_url(value: Any) -> str:
    return Path(str(value or "").split("?")[0]).name
