# -*- coding: utf-8 -*-
"""AIGC 统一 runtime facade（批次0，三栈收敛单源）。

背景（根因）：AIGC 曾有三套并行客户栈——
1. ``protocols.py``：真实端点）
2. ``text_to_image.py`` 等六件 BaseGenerator 实现：文档已判定打的是**虚构端点**，
   从未真实产出（本批次随修删除）；
3. 渠道层（telegram/qqbot/wechat/wechat_ai/feishu）：因包零导出恒 ImportError。

本模块为唯一入口：
- ``resolve_generation_creds`` / ``persist_media``：自 ``api/endpoints/generation.py``
  搬移（端点改薄包装，安全测试 patch 面不变；凭据解析与产物落盘口径单源）；
- ``ProtocolGenerator``：按 GeneratorType 分发到 protocols 实测矩阵，产物即刻
  本地化，返回渠道 mixin 读取的 ``GenerationResult.success/urls/error_message``
  契约（urls=服务端本地路径，渠道 ``_download_url`` 带本地分支）；
- keyframe_to_video / video_to_video：M2 起走 wan/seedance2/veo 实测协议
  （源视频 video_url + 首尾帧 imageUrl/endImageUrl，契约按桩锁定官方待核）。

旧 ``LegacyBytesAdapter``（wechat_ai/feishu_ai 旧工厂契约 ``generate(**kwargs)->bytes``）
已随那两个死码文件于 2026-11-14 退役。
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger
from neurova.llm.generators import protocols as protocols
from neurova.llm.generators.base import GenerationConfig, GenerationResult, GeneratorType
from neurova.llm.generators.protocols import ProtocolCredentials
from neurova.core.data_root import get_data_root

logger = get_logger(__name__)

# P1-8 同源：仓库根绝对路径（端点 generation.py 引用本常量，杜绝两处漂移）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATION_OUTPUT_DIR = get_data_root() / "generations"

# 产物下载体积上限（256MB）：生成媒体（图/短视频/音频）的宽松上界，防异常
# 回包把内存吃穿；safe_fetch 超限诚实报错，不静默截断。
_MAX_MEDIA_DOWNLOAD_BYTES = 256 * 1024 * 1024

DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_WAN_BASE = "https://dashscope.aliyuncs.com/api/v1"

# L5：keyframe_to_video 转真实通道（Seedance first_frame+last_frame 先画后动）；
# M2：video_to_video 落地 wan/seedance2/veo 三家（源视频 + 首尾帧 imageUrl/
# endImageUrl，契约按桩锁定官方待核）——facade 按用户传入模型/协议分派，
# 未指定默认 dashscope-wan 先验证。
_VIDEO_TYPES = ("text_to_video", "image_to_video", "keyframe_to_video", "video_to_video")
_IMAGE_TYPES = ("text_to_image", "image_to_image")


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
            ) or ("googleapis.com" in host and "veo" in (protocol_hint or "").lower()) or (
                # agnes 视频：协议标签 agnes ↔ host agnes（auto 路由无 provider_id 时）
                "agnes" in host and "agnes" in (protocol_hint or "").lower()
            ) or (
                # sora 视频：OpenAI 官方 /videos 端点（auto 路由无 provider_id 时）
                "sora" in (protocol_hint or "").lower() and "openai" in host
            ) or (
                # openai_compat：Agnes/自托管等 host 无法穷举——协议为 openai_compat 时
                # 取任一含 openai/agnes 的已启用服务商兜底（前端正常已透传 provider_id）
                "openai_compat" in (protocol_hint or "").lower() and ("openai" in host or "agnes" in host)
            ):
                provider = p
                break
    if provider is not None:
        try:
            from neurova.llm.providers.secret_store_clean import decrypt_api_key

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


def derive_generation_protocol(
    kind: str,
    model: str = "",
    provider_id: Optional[str] = None,
    protocol_label: str = "",
    base_url: str = "",
) -> Tuple[str, str]:
    """自适应推导单源：返回 (生效 provider_id, 协议标签)。

    2026-09-15 推导顺序根因修：REST 端点原在凭据解析前推导协议，入参
    base_url 恒空（前端服务商经 provider_id 上报、不传 base_url）→
    OpenAI/Sora、火山具名模型全落默认支（视频→WAN、图像→OPENAI_COMPAT）
    请求发错端点。本函数按 provider base_url 参与推导（与 Studio
    _hint_for_provider 同语义，升级为共享单源）：
    1. 显式协议标签最优先（不覆盖）；
    2. provider_id → 其 base_url；pid 缺省按模型反查含该模型的启用服务商
       （反查值回填 pid——auto/手填之外的 API 消费方同享）；
    3. 其余走 resolve_*_protocol 的 模型名+base 兜底探测 → 默认支。
    """
    fn = (protocols.resolve_image_protocol if kind == "image"
          else protocols.resolve_video_protocol if kind == "video"
          else protocols.resolve_music_protocol)
    pid = str(provider_id or "")
    base = str(base_url or "")
    if not base and not protocol_label:
        manager = None
        try:
            from neurova.llm.provider_manager import get_provider_manager

            manager = get_provider_manager()
        except Exception:  # noqa: BLE001 — 服务商栈不可用时退回矩阵默认语义
            manager = None
        if manager is not None:
            provider = manager.get_provider(pid) if pid else None
            if provider is None and model:
                for p in manager.list_providers(enabled_only=True):
                    if any(
                        getattr(m, "id", "") == model or getattr(m, "name", "") == model
                        for m in (getattr(p, "models", None) or [])
                    ):
                        provider = p
                        break
            if provider is not None:
                pid = str(getattr(provider, "id", "") or pid)
                base = str(getattr(provider, "base_url", "") or "")
    return pid, fn(protocol_label or "", model or "", base).value


# ── 产物落盘（自端点搬移；SSRF 出网校验随迁）──────────────────────────────


async def persist_bytes(
    data: bytes,
    ext: str,
    task_id: str,
    index: int = 0,
    out_dir: Optional[str] = None,
    owner_user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    kind: str = "browser",
) -> str:
    """原始字节直接落盘产物目录（批次4：画布 voice-over/TTS 节点等内存产物用）。

    ``owner_user_id`` 非空时（浏览器 pdf/下载两条链）落盘后在生成任务账本登记
    产物属主——serve 端（``generation.py`` /files）按账本反查 owner 做归属校验，
    他人读取即 403；不传（默认 None）保持既有行为不变、不登记（存量产物仍按
    "登录即可读"向后兼容），既有调用方零破坏。
    """
    root = Path(out_dir) if out_dir else GENERATION_OUTPUT_DIR
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{safe_task_name(task_id)}_{index}.{_SAFE_EXT_RE.sub('', str(ext or 'bin'))}"
    path.write_bytes(data)
    if owner_user_id is not None:
        from neurova.llm.generators.task_ledger import (
            TASK_SUCCEEDED,
            TaskRecord,
            get_generation_task_ledger,
        )

        get_generation_task_ledger().add(
            TaskRecord(
                task_id=f"artifact-{uuid.uuid4().hex[:16]}",
                kind=str(kind or "browser"),
                status=TASK_SUCCEEDED,
                local_path=str(path),
                owner_user_id=str(owner_user_id),
                session_id=str(session_id or ""),
                source="browser",
            )
        )
    return str(path)


async def persist_media(
    url_or_data: str,
    kind: str,
    task_id: str,
    index: int,
    out_dir: Optional[str] = None,
) -> str:
    """结果 URL 临时有效 → 立即下载本地化（data/generations/）。

    空回包（0 字节）**不落盘、不返回路径**：这里落的是全仓唯一的产物落盘点，
    一旦把空件当成功交回去，上游（Studio 镜头面、REST 台账、恢复循环、PDF 图块）
    就一律记成"有产物"，而文件永远打不开。

    out_dir=None 时落到模块级 GENERATION_OUTPUT_DIR；端点包装层传入自身模块全局
    （tests/api/test_generation_security.py 的 monkeypatch 契约保持）。
    """
    import base64 as _b64

    root = Path(out_dir) if out_dir else GENERATION_OUTPUT_DIR
    out_dir_path = root
    out_dir_path.mkdir(parents=True, exist_ok=True)
    # P0-1：task_id 参与文件名拼接，安全化后才允许落盘
    safe_name = safe_task_name(task_id)
    if url_or_data.startswith("data:"):
        header, _, payload = url_or_data.partition(",")
        ext = "png" if "image" in header else (
            "mp4" if "video" in header else ("mp3" if "audio" in header else "bin"))
        path = out_dir_path / f"{safe_name}_{index}.{ext}"
        content = _b64.b64decode(payload)
    else:
        # P1-7/U2：产物 URL 来自 provider 响应（base_url 可被调用方指定为自建
        # 端点），下载走 safe_fetch 单一 SSRF 安全门——连接前与每一跳 redirect
        # 都过出网校验（旧 aiohttp 路径仅首跳校验且自动跟随重定向，可被 302
        # 绕进内网/云元数据），响应体限量读取。阻塞下载入线程池，不堵事件
        # 循环（P1-10b 同款）。
        from neurova.security.safe_fetch import safe_fetch

        resp = await asyncio.to_thread(
            safe_fetch, url_or_data,
            timeout=120.0, max_bytes=_MAX_MEDIA_DOWNLOAD_BYTES,
            headers={"User-Agent": "Neurova-Generation/1.0"},
        )
        content_type = resp.headers.get("content-type", "")
        ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
               "video/mp4": "mp4", "audio/mpeg": "mp3", "audio/mp3": "mp3",
               "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a",
               "audio/ogg": "ogg", "audio/flac": "flac"}.get(
            content_type.split(";")[0], "bin")
        path = out_dir_path / f"{safe_name}_{index}.{ext}"
        content = resp.content
    if not content:
        raise RuntimeError(f"产物为空（0 字节），不落盘：{str(url_or_data)[:120]}")
    path.write_bytes(content)
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
                f"{t}：无实测协议支撑（视频生视频需专协议，"
                "登记缓后台账）"
            ))
        result.duration = time.monotonic() - start
        return result

    async def _generate_image(self, t: str, config: GenerationConfig) -> GenerationResult:
        model = (config.model or config.model_id or "").strip()
        n = max(1, int(config.num_outputs or 1))
        size = f"{max(1, int(config.width or 1024))}x{max(1, int(config.height or 1024))}"
        refs = [config.image_url] if (t == "image_to_image" and config.image_url) else []
        # 2026-09-15 自适应推导单源（含 model→provider 反查，画布/渠道同享）
        provider_id, protocol = derive_generation_protocol("image", model)
        try:
            creds = resolve_generation_creds(
                protocol, model, provider_id or None, None, None, DEFAULT_OPENAI_BASE)
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
                "protocol": protocol,
                "model": creds.model,
            },
        )

    async def _generate_video(self, t: str, config: GenerationConfig) -> GenerationResult:
        model = (config.model or config.model_id or "").strip()
        refs: List[str] = []
        last_frame = ""
        video_url = ""
        if t == "image_to_video" and config.image_url:
            refs = [config.image_url]
        elif t == "keyframe_to_video":
            if config.start_image_url:
                refs = [config.start_image_url]
            last_frame = config.end_image_url or ""
        elif t == "video_to_video":
            # M2：源视频 + 首尾帧（imageUrl/endImageUrl 语义位，见 GenerationConfig）
            video_url = config.video_url or ""
            if config.image_url:
                refs = [config.image_url]
            last_frame = config.end_image_url or ""
        # M2 用户可选分派：显式协议标签（extra_params.protocol）最优先，
        # 其次模型名探测；两者皆缺省落 dashscope-wan（resolve_video_protocol 默认支）
        protocol_label = str((config.extra_params or {}).get("protocol") or "")
        provider_id, protocol = derive_generation_protocol(
            "video", model, protocol_label=protocol_label)
        try:
            creds = resolve_generation_creds(
                protocol, model, provider_id or None, None, None, DEFAULT_WAN_BASE)
        except GenerationCredsError as e:
            return GenerationResult(success=False, error=str(e))
        duration = int(config.duration or 5)
        resolution = str((config.extra_params or {}).get("resolution") or "1080p")
        max_wait = float((config.extra_params or {}).get("max_wait", 900))
        try:
            result = await protocols.generate_video_wait(
                creds, config.prompt, duration=duration, resolution=resolution,
                ref_images=refs, max_wait=max_wait,
                last_frame=last_frame or None,
                # 仅 v2v 携带源视频通道（非 v2v 不改既有调用形态）
                **({"video_url": video_url} if video_url else {}))
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
                "protocol": protocol,
                "model": creds.model,
            },
        )
