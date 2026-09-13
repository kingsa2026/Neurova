# -*- coding: utf-8 -*-
"""AIGC 统一 runtime facade（批次0，三栈收敛单源）。

背景（根因）：AIGC 曾有三套并行客户栈——
1. ``protocols.py``：QwenPaw 实测协议矩阵（REST /generation/* 在用，真实端点）；
2. ``text_to_image.py`` 等六件 BaseGenerator 实现：文档已判定打的是**虚构端点**，
   从未真实产出（本批次随修删除）；
3. 渠道层（telegram/qqbot/wechat/wechat_ai/feishu）：因包零导出恒 ImportError。

本模块为唯一入口：
- ``resolve_generation_creds`` / ``persist_media``：自 ``api/endpoints/generation.py``
  搬移（端点改薄包装，安全测试 patch 面不变；凭据解析与产物落盘口径单源）；
- ``ProtocolGenerator``：按 GeneratorType 分发到 protocols 实测矩阵，产物即刻
  本地化，返回渠道三 mixin 读取的 ``GenerationResult.success/urls/error_message``
  契约（urls=服务端本地路径，渠道 ``_download_url`` 带本地分支）；
- ``LegacyBytesAdapter``：wechat_ai/feishu_ai 旧工厂契约 ``generate(**kwargs)->bytes``；
- keyframe_to_video / video_to_video 无实测协议：**诚实报错**（缓后台账登记），
  不假成功。
"""
from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.llm.generators import protocols as protocols
from neurova.llm.generators.base import GenerationConfig, GenerationResult, GeneratorType
from neurova.llm.generators.protocols import ProtocolCredentials

logger = get_logger(__name__)

# P1-8 同源：仓库根绝对路径（端点 generation.py 引用本常量，杜绝两处漂移）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATION_OUTPUT_DIR = PROJECT_ROOT / "data" / "generations"

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_WAN_BASE = "https://dashscope.aliyuncs.com/api/v1"

_VIDEO_TYPES = ("text_to_video", "image_to_video")
_IMAGE_TYPES = ("text_to_image", "image_to_image")
_UNSUPPORTED_TYPES = ("keyframe_to_video", "video_to_video")


class GenerationCredsError(ValueError):
    """生成凭据不可得。HTTP 层映射 400；facade 层转 GenerationResult 错误。"""


# P0-1（审计 2026-09-11）：task_id 参与落盘文件名，仅保留安全字符，
# 路径穿越一律打平（自端点上移至单源层，端点 re-export 保持测试 patch 面）。
_SAFE_TASK_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def safe_task_name(task_id: str) -> str:
    cleaned = _SAFE_TASK_NAME_RE.sub("_", str(task_id or "")).strip("_")[:80]
    return cleaned or "task"


# 落盘文件扩展名白名单（防经 ext 注入路径分隔符）
_SAFE_EXT_RE = re.compile(r"[^A-Za-z0-9]")


# 产物静态挂载前缀（与 api/app.py StaticFiles 挂载同源语义）
FILES_URL_PREFIX = "/api/v1/generation/files"


def local_url_for(path: str) -> str:
    """本地产物文件 → 可访问的静态 URL（批次2：单源，端点与恢复循环共用）。"""
    return f"{FILES_URL_PREFIX}/{Path(path).name}"


# ── 凭据解析（自端点搬移，语义不变：显式凭据 > provider_id > 协议匹配服务商）──


def resolve_generation_creds(
    protocol_hint: str,
    model: Optional[str],
    provider_id: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    default_base: str,
) -> ProtocolCredentials:
    """凭据解析（B2-b）：显式凭据 > provider_id 配置 > 协议匹配服务商。"""
    if api_key and base_url:
        return ProtocolCredentials(api_key=api_key, base_url=base_url,
                                   model=model or "", protocol=protocol_hint or "")

    from neurova.llm.provider_manager import get_provider_manager

    manager = get_provider_manager()
    provider = manager.get_provider(provider_id) if provider_id else None
    if provider is None and not provider_id:
        # 按协议启发在启用服务商里找：base_url host 匹配
        for p in manager.list_providers(enabled_only=True):
            host = (getattr(p, "base_url", "") or "").lower()
            if ("dashscope" in host and "dashscope" in (protocol_hint or "").lower()) or (
                "volces.com" in host and ("ark" in (protocol_hint or "").lower() or "seedance" in (protocol_hint or "").lower() or "volcengine" in (protocol_hint or "").lower())
            ) or ("googleapis.com" in host and "veo" in (protocol_hint or "").lower()):
                provider = p
                break
    if provider is not None:
        try:
            from neurova.llm.providers.secret_store import decrypt_api_key

            key = decrypt_api_key(getattr(provider, "api_key", "") or "")
        except Exception:
            key = getattr(provider, "api_key", "") or ""
        if key:
            return ProtocolCredentials(
                api_key=key,
                base_url=base_url or getattr(provider, "base_url", "") or default_base,
                model=model or getattr(provider, "default_model", "") or "",
                protocol=protocol_hint or "",
            )
    # 显式 base_url 无 key（自托管网关可无鉴权）
    if base_url:
        return ProtocolCredentials(api_key="", base_url=base_url, model=model or "",
                                   protocol=protocol_hint or "")
    raise GenerationCredsError(
        "缺少生成凭据：请传 api_key+base_url，或 provider_id，或先在模型页配置并启用对应服务商（填 API Key）",
    )


# ── 产物落盘（自端点搬移；SSRF 出网校验随迁）──────────────────────────────


async def persist_bytes(
    data: bytes,
    ext: str,
    task_id: str,
    index: int = 0,
    out_dir: Optional[str] = None,
) -> str:
    """原始字节直接落盘产物目录（批次4：画布 voice-over/TTS 节点等内存产物用）。"""
    root = Path(out_dir) if out_dir else GENERATION_OUTPUT_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_task_name(task_id)}_{index}.{_SAFE_EXT_RE.sub('', str(ext or 'bin'))}"
    path.write_bytes(data)
    return str(path)


async def persist_media(
    url_or_data: str,
    kind: str,
    task_id: str,
    index: int,
    out_dir: Optional[str] = None,
) -> str:
    """结果 URL 临时有效 → 立即下载本地化（data/generations/）。

    out_dir=None 时落到模块级 GENERATION_OUTPUT_DIR；端点包装层传入自身模块全局
    （tests/api/test_generation_security.py 的 monkeypatch 契约保持）。
    """
    import aiohttp
    import base64 as _b64

    root = Path(out_dir) if out_dir else GENERATION_OUTPUT_DIR
    out_dir_path = root
    out_dir_path.mkdir(parents=True, exist_ok=True)
    # P0-1：task_id 参与文件名拼接，安全化后才允许落盘
    safe_name = safe_task_name(task_id)
    if url_or_data.startswith("data:"):
        header, _, payload = url_or_data.partition(",")
        ext = "png" if "image" in header else ("mp4" if "video" in header else "bin")
        path = out_dir_path / f"{safe_name}_{index}.{ext}"
        path.write_bytes(_b64.b64decode(payload))
        return str(path)
    # P1-7：产物 URL 来自 provider 响应（base_url 可被调用方指定为自建端点），
    # 下载前必须过全局出网校验，防 SSRF 打内网/云元数据。
    from neurova.security.governance import check_outbound_url

    check_outbound_url(url_or_data)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.get(url_or_data) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"产物下载失败 HTTP {resp.status}")
            content_type = resp.headers.get("content-type", "")
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                   "video/mp4": "mp4"}.get(content_type.split(";")[0], "bin")
            path = out_dir_path / f"{safe_name}_{index}.{ext}"
            path.write_bytes(await resp.read())
    return str(path)


# ── ProtocolGenerator：渠道/画布单入口 ─────────────────────────────────────


def _type_value(t: Any) -> str:
    return t.value if isinstance(t, GeneratorType) else str(getattr(t, "value", t) or "")


class ProtocolGenerator:
    """GeneratorType → protocols 实测协议矩阵的统一分发器。

    成功时 ``GenerationResult.urls`` 为服务端本地产物路径（渠道 ``_download_url``
    本地分支读取）；``metadata.remote_urls`` 保留原始 URL 供追溯。
    失败时 success=False + error 原文（诚实报错，不假成功）。
    """

    def __init__(self, generator_id: str = "",
                 generator_type: GeneratorType = GeneratorType.TEXT_TO_IMAGE,
                 **kwargs):
        self.generator_type = generator_type
        self.generator_id = generator_id or _type_value(generator_type)
        self._config = kwargs

    async def generate(self, config: GenerationConfig) -> GenerationResult:
        t = _type_value(config.type)
        start = time.monotonic()
        if t in _IMAGE_TYPES:
            result = await self._generate_image(t, config)
        elif t in _VIDEO_TYPES:
            result = await self._generate_video(t, config)
        else:
            result = GenerationResult(success=False, error=(
                f"{t}：无实测协议支撑（首尾帧需百炼临时上传、视频生视频需专协议，"
                "登记缓后台账），见 docs/Neurova_PRINTFILM_火宝短剧_AIGC对标研究_2026-09-13.md"
            ))
        result.duration = time.monotonic() - start
        return result

    async def _generate_image(self, t: str, config: GenerationConfig) -> GenerationResult:
        model = (config.model or config.model_id or "").strip()
        n = max(1, int(config.num_outputs or 1))
        size = f"{max(1, int(config.width or 1024))}x{max(1, int(config.height or 1024))}"
        refs = [config.image_url] if (t == "image_to_image" and config.image_url) else []
        protocol = protocols.resolve_image_protocol("", model, "")
        try:
            creds = resolve_generation_creds(
                protocol.value, model, None, None, None, DEFAULT_OPENAI_BASE)
        except GenerationCredsError as e:
            return GenerationResult(success=False, error=str(e))
        try:
            result = await protocols.generate_image(
                creds, config.prompt, size=size, n=n, ref_images=refs)
        except Exception as e:  # noqa: BLE001 — 诚实回传错误原文
            logger.warning("facade 图像生成失败: %s", e)
            return GenerationResult(success=False, error=f"图像生成失败: {str(e)[:300]}")

        remote = [u for u in (result.get("images") or []) if u]
        if not remote:
            return GenerationResult(success=False, error="图像生成未返回产物")
        task_id = uuid.uuid4().hex[:16]
        urls: List[str] = []
        locals_: List[str] = []
        for i, item in enumerate(remote):
            try:
                path = await persist_media(item, "image", task_id, i)
                locals_.append(path)
                urls.append(path)
            except Exception as e:  # noqa: BLE001 — 单产物落盘失败保留远端 URL（可能已过期）
                logger.warning("产物本地化失败（%s）: %s", item[:120], e)
                if str(item).startswith("http"):
                    urls.append(item)
        if not urls:
            return GenerationResult(success=False, error="产物本地化全部失败")
        return GenerationResult(
            success=True,
            output_path=locals_[0] if locals_ else "",
            urls=urls,
            metadata={
                "task_id": task_id,
                "remote_urls": remote,
                "protocol": protocol.value,
                "model": creds.model,
            },
        )

    async def _generate_video(self, t: str, config: GenerationConfig) -> GenerationResult:
        model = (config.model or config.model_id or "").strip()
        refs = [config.image_url] if (t == "image_to_video" and config.image_url) else []
        protocol = protocols.resolve_video_protocol("", model, "")
        try:
            creds = resolve_generation_creds(
                protocol.value, model, None, None, None, DEFAULT_WAN_BASE)
        except GenerationCredsError as e:
            return GenerationResult(success=False, error=str(e))
        duration = int(config.duration or 5)
        resolution = str((config.extra_params or {}).get("resolution") or "1080p")
        max_wait = float((config.extra_params or {}).get("max_wait", 900))
        try:
            result = await protocols.generate_video_wait(
                creds, config.prompt, duration=duration, resolution=resolution,
                ref_images=refs, max_wait=max_wait)
        except Exception as e:  # noqa: BLE001 — 诚实回传
            logger.warning("facade 视频生成失败: %s", e)
            return GenerationResult(success=False, error=f"视频生成失败: {str(e)[:300]}")

        if result.get("status") != "succeeded":
            return GenerationResult(
                success=False,
                error=f"视频任务失败: {str(result.get('error') or result.get('raw') or '')[:300]}",
            )
        video_url = result.get("video_url") or ""
        if not video_url:
            return GenerationResult(success=False, error="视频任务成功但未返回产物 URL")
        task_id = uuid.uuid4().hex[:16]
        try:
            path = await persist_media(video_url, "video", task_id, 0)
            urls = [path]
            output_path = path
        except Exception as e:  # noqa: BLE001 — 下载失败仍回成功+远端 URL（可能已过期）
            logger.warning("视频产物本地化失败: %s", e)
            urls = [video_url]
            output_path = ""
        return GenerationResult(
            success=True,
            output_path=output_path,
            urls=urls,
            metadata={
                "task_id": task_id,
                "remote_urls": [video_url],
                "protocol": protocol.value,
                "model": creds.model,
            },
        )


# ── LegacyBytesAdapter：wechat_ai/feishu_ai 旧工厂契约 ─────────────────────


class LegacyBytesAdapter:
    """``async generate(**kwargs) -> bytes | None``。

    wechat_ai.py / feishu_ai.py 旧代码按想象契约写：kwargs 传 prompt/width/...
    并期待产物 bytes。此适配器把 kwargs 规整进 GenerationConfig（含 wechat 的
    ``image=<bytes>`` 入参 → 落临时文件转 data URL 参考图），走 ProtocolGenerator，
    读本地产物 bytes 返回；失败返回 None（旧代码 ``if not data`` 分支诚实兜底）。
    """

    def __init__(self, generator_type: GeneratorType):
        self.generator_type = generator_type
        self._inner = ProtocolGenerator(generator_type=generator_type)

    async def generate(self, **kwargs: Any) -> Optional[bytes]:
        ref_image_bytes = kwargs.pop("image", None)
        num_images = kwargs.pop("num_images", None)
        image_path = str(kwargs.pop("image_path", "") or kwargs.pop("image_url", "") or "")
        if ref_image_bytes and not image_path:
            image_path = self._materialize_bytes(ref_image_bytes)
        try:
            cfg = GenerationConfig(
                type=self.generator_type,
                prompt=str(kwargs.pop("prompt", "") or ""),
                negative_prompt=str(kwargs.pop("negative_prompt", "") or ""),
                width=int(kwargs.pop("width", 1024) or 1024),
                height=int(kwargs.pop("height", 1024) or 1024),
                model=str(kwargs.pop("model", "") or ""),
                duration=float(kwargs.pop("duration", 5) or 5),
                fps=int(kwargs.pop("fps", 30) or 30),
                strength=float(kwargs.pop("strength", 0.75) or 0.75),
                num_outputs=int(num_images or kwargs.pop("num_outputs", 1) or 1),
                image_url=image_path,
                extra_params=dict(kwargs),
            )
        except (TypeError, ValueError) as e:
            logger.error("legacy AIGC 参数非法: %s", e)
            return None
        result = await self._inner.generate(cfg)
        if not result.success:
            logger.error("legacy AIGC 生成失败(%s): %s", self.generator_type.value, result.error)
            return None
        # urls 首项为本地路径（facade 契约）；远端 URL 回退时下载
        first = (result.urls or [""])[0]
        if first and not first.startswith(("http://", "https://")):
            try:
                return Path(first).read_bytes()
            except OSError as e:
                logger.error("读取产物失败(%s): %s", first, e)
                return None
        try:
            persisted = await persist_media(first, "image", str(result.metadata.get("task_id") or uuid.uuid4().hex[:16]), 0)
            return Path(persisted).read_bytes()
        except Exception as e:  # noqa: BLE001
            logger.error("legacy AIGC 产物获取失败: %s", e)
            return None

    def _materialize_bytes(self, data: Any) -> str:
        """wechat i2i 传裸 bytes → 落输入目录供 media_to_data_url 读取。"""
        try:
            in_dir = GENERATION_OUTPUT_DIR / "inputs"
            in_dir.mkdir(parents=True, exist_ok=True)
            path = in_dir / f"ref_{uuid.uuid4().hex[:12]}.png"
            path.write_bytes(bytes(data))
            return str(path)
        except OSError as e:
            logger.error("参考图 bytes 落盘失败: %s", e)
            return ""


_get_image_adapter: Optional[LegacyBytesAdapter] = None
_get_video_adapter: Optional[LegacyBytesAdapter] = None


def get_image_generator() -> LegacyBytesAdapter:
    """旧工厂兼容：文生图 bytes 适配器。"""
    global _get_image_adapter
    if _get_image_adapter is None:
        _get_image_adapter = LegacyBytesAdapter(GeneratorType.TEXT_TO_IMAGE)
    return _get_image_adapter


def get_video_generator() -> LegacyBytesAdapter:
    """旧工厂兼容：文生视频 bytes 适配器。"""
    global _get_video_adapter
    if _get_video_adapter is None:
        _get_video_adapter = LegacyBytesAdapter(GeneratorType.TEXT_TO_VIDEO)
    return _get_video_adapter


def reset_legacy_adapters() -> None:
    """测试用：重置单例。"""
    global _get_image_adapter, _get_video_adapter
    _get_image_adapter = None
    _get_video_adapter = None
