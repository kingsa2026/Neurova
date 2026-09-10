# -*- coding: utf-8 -*-
"""AIGC 生成协议客户端（B2-a，QwenPaw Creator 实测协议矩阵移植）。

六条真实协议接入地址规则（禁止虚构端点）：

图片（同步优先，DASHSCOPE 异步优先/403 同步回退）
- OPENAI_COMPAT: ``{base}[/v1]/images/generations``（base 含 /v1 不重复加），
  Bearer，参考图走 images/edits multipart。
- ARK (doubao-seedream): ``{base}/api/v3/images/generations``，Bearer，
  参考图 image 字段 URL 直传/本地转 data URL。
- DASHSCOPE (qwen-image): base_url 即完整端点
  ``…/api/v1/services/aigc/multimodal-generation/generation``；
  头 ``X-DashScope-Async: enable`` → output.task_id → 轮询
  ``{api_root}/tasks/{task_id}``；403 回退同步。

视频（全部异步提交+轮询）
- WAN (百炼 Wan2.x/Wan3.0): 提交 ``{base}/services/aigc/video-generation/video-synthesis``
  （base 默认 ``https://dashscope.aliyuncs.com/api/v1``），头 X-DashScope-Async，
  轮询 ``{api_root}/tasks/{task_id}``。
- SEEDANCE2 (火山 Ark Seedance): 提交 ``{base}/api/v3/contents/generations/tasks``，
  轮询同 URL + ``/{task_id}``。
- VEO (Gemini Veo): 提交 ``{base}/models/{model}:predictLongRunning``（裸
  googleapis 主机自动补 /v1beta），头 x-goog-api-key，轮询 GET operation name。

URL/请求体构建为纯函数（可测），HTTP 用 aiohttp（可选依赖，缺库诚实报错）。
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import asyncio

import aiohttp

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DASHSCOPE_API_ROOT = "https://dashscope.aliyuncs.com/api/v1"
DEFAULT_ARK_BASE = "https://ark.cn-beijing.volces.com"
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class ImageProtocol(str, Enum):
    OPENAI_COMPAT = "openai_compat"
    ARK = "ark"
    DASHSCOPE = "dashscope"


class VideoProtocol(str, Enum):
    WAN = "wan"
    SEEDANCE2 = "seedance2"
    VEO = "veo"


# ── 协议解析：显式标签 → 后端映射（含中文标签）→ model/base_url 兜底探测 ──

_PROTOCOL_LABELS = {
    ImageProtocol.DASHSCOPE: ("dashscope", "qwen-image", "百炼", "阿里云百炼"),
    ImageProtocol.ARK: ("ark", "seedream", "火山", "火山引擎", "volcengine"),
    ImageProtocol.OPENAI_COMPAT: ("openai", "openai_compat", "gpt-image", "dall-e", "dalle"),
    VideoProtocol.WAN: ("wan", "wan2", "wan3", "百炼", "阿里云百炼", "dashscope"),
    VideoProtocol.SEEDANCE2: ("seedance", "seedance2", "火山", "火山引擎", "volcengine", "ark"),
    VideoProtocol.VEO: ("veo", "gemini", "google"),
}


def _match_label(label: str, candidates: Tuple[str, ...]) -> bool:
    return label.strip().lower() in candidates


def resolve_image_protocol(
    protocol_label: str = "", model_name: str = "", base_url: str = "",
) -> ImageProtocol:
    """显式协议标签 → 模型名/base_url 兜底探测 → 默认 OPENAI_COMPAT。"""
    if protocol_label:
        for proto, labels in _PROTOCOL_LABELS.items():
            if isinstance(proto, ImageProtocol) and _match_label(protocol_label, labels):
                return proto
    text = f"{model_name} {base_url}".lower()
    if "seedream" in text or "volces.com" in text:
        return ImageProtocol.ARK
    if "qwen-image" in text or "dashscope" in text:
        return ImageProtocol.DASHSCOPE
    if "gemini" in text:
        return ImageProtocol.DASHSCOPE  # 不可达分支防御：Gemini 无图像生成走 VEO/文生图
    return ImageProtocol.OPENAI_COMPAT


def resolve_video_protocol(
    protocol_label: str = "", model_name: str = "", base_url: str = "",
) -> VideoProtocol:
    if protocol_label:
        for proto, labels in _PROTOCOL_LABELS.items():
            if isinstance(proto, VideoProtocol) and _match_label(protocol_label, labels):
                return proto
    text = f"{model_name} {base_url}".lower()
    if "seedance" in text or "volces.com" in text:
        return VideoProtocol.SEEDANCE2
    if "veo" in text or "googleapis.com" in text:
        return VideoProtocol.VEO
    return VideoProtocol.WAN


# ── URL 拼接纯函数（实测矩阵的单源实现） ──


def openai_images_url(base_url: str) -> str:
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    if "/v1" in base:
        return f"{base}/images/generations"
    return f"{base}/v1/images/generations"


def ark_images_url(base_url: str) -> str:
    base = (base_url or DEFAULT_ARK_BASE).rstrip("/")
    if "/api/v3" in base:
        return f"{base}/images/generations"
    return f"{base}/api/v3/images/generations"


def dashscope_async_header() -> Dict[str, str]:
    return {"X-DashScope-Async": "enable"}


def dashscope_tasks_url(api_root: str, task_id: str) -> str:
    return f"{(api_root or DEFAULT_DASHSCOPE_API_ROOT).rstrip('/')}/tasks/{task_id}"


def wan_submit_url(base_url: str) -> str:
    base = (base_url or DEFAULT_DASHSCOPE_API_ROOT).rstrip("/")
    if "/services/aigc" in base:
        return f"{base}/video-generation/video-synthesis"
    return f"{base}/services/aigc/video-generation/video-synthesis"


def wan_tasks_root(base_url: str) -> str:
    base = (base_url or DEFAULT_DASHSCOPE_API_ROOT).rstrip("/")
    return base


def seedance_submit_url(base_url: str) -> str:
    base = (base_url or DEFAULT_ARK_BASE).rstrip("/")
    if "/api/v3" in base:
        return f"{base}/contents/generations/tasks"
    return f"{base}/api/v3/contents/generations/tasks"


def seedance_poll_url(base_url: str, task_id: str) -> str:
    return f"{seedance_submit_url(base_url)}/{task_id}"


def veo_submit_url(base_url: str, model: str) -> str:
    base = (base_url or DEFAULT_GEMINI_BASE).rstrip("/")
    host = urlparse(base).hostname or ""
    if host == "generativelanguage.googleapis.com" and "/v1beta" not in base and "/v1" not in base:
        base = f"{base}/v1beta"
    return f"{base}/models/{model}:predictLongRunning"


def veo_poll_url(base_url: str, operation_name: str) -> str:
    base = (base_url or DEFAULT_GEMINI_BASE).rstrip("/")
    if operation_name.startswith("http"):
        return operation_name
    if operation_name.startswith("/"):
        return f"{urlparse(base).scheme}://{urlparse(base).netloc}{operation_name}"
    return f"{base}/{operation_name}"


# ── 凭据载体 ──


@dataclass
class ProtocolCredentials:
    """按提供商独立凭据（B2-b）：api_key + base_url + model。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    protocol: str = ""


def media_to_data_url(path_or_url: str) -> str:
    """本地文件 → data URL；http(s) 原样返回。"""
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        return path_or_url
    if path_or_url.startswith("data:"):
        return path_or_url
    path = Path(path_or_url)
    if not path.is_file():
        raise FileNotFoundError(f"参考媒体不存在: {path_or_url}")
    suffix = path.suffix.lstrip(".").lower() or "png"
    mime = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "gif": "image/gif", "mp4": "video/mp4",
    }.get(suffix, "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


# ── HTTP 基元 ──


async def _post_json(url: str, headers: Dict[str, str], body: Dict[str, Any],
                     timeout: float = 60.0) -> Tuple[int, Dict[str, Any]]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.post(url, headers=headers, json=body) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {"raw": await resp.text()}
            return status, data


async def _get_json(url: str, headers: Dict[str, str],
                    timeout: float = 30.0) -> Tuple[int, Dict[str, Any]]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url, headers=headers) as resp:
            status = resp.status
            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = {"raw": await resp.text()}
            return status, data


# ── 图片协议：统一 generate（同步返回，异步型内部轮询） ──


def _dashscope_image_body(model: str, prompt: str, size: str, n: int,
                          ref_images: List[str]) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    for ref in ref_images:
        content.append({"image": ref})
    content.append({"text": prompt})
    body: Dict[str, Any] = {
        "model": model,
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"n": max(1, n)},
    }
    if size and "x" in size:
        body["parameters"]["size"] = size
    return body


async def _dashscope_image_generate(
    creds: ProtocolCredentials, prompt: str, size: str, n: int,
    ref_images: List[str], timeout: float,
) -> Dict[str, Any]:
    endpoint = creds.base_url or (
        f"{DEFAULT_DASHSCOPE_API_ROOT}/services/aigc/multimodal-generation/generation"
    )
    headers = {
        "Authorization": f"Bearer {creds.api_key}",
        "X-DashScope-OssResourceResolve": "enable",
    }
    body = _dashscope_image_body(creds.model, prompt, size, n, ref_images)
    status, data = await _post_json(endpoint, {**headers, **dashscope_async_header()}, body, timeout)

    if status == 403:
        # 实测矩阵：403 → 同步回退（去掉异步头重发）
        status, data = await _post_json(endpoint, headers, body, timeout)
        if status >= 400:
            raise RuntimeError(f"DASHSCOPE 同步回退失败 HTTP {status}: {str(data)[:300]}")
        output = data.get("output") or {}
        urls = [r.get("url") or r.get("b64_image") for r in (output.get("results") or [])]
        return {"images": [u for u in urls if u], "task_id": None, "raw": data}

    if status >= 400:
        raise RuntimeError(f"DASHSCOPE 提交失败 HTTP {status}: {str(data)[:300]}")

    output = data.get("output") or {}
    task_id = output.get("task_id")
    if not task_id:
        urls = [r.get("url") or r.get("b64_image") for r in (output.get("results") or [])]
        return {"images": [u for u in urls if u], "task_id": None, "raw": data}

    # 异步：轮询 {api_root}/tasks/{task_id}
    api_root = DEFAULT_DASHSCOPE_API_ROOT
    for _ in range(60):
        await asyncio.sleep(5.0)
        poll_status, poll_data = await _get_json(
            dashscope_tasks_url(api_root, task_id), {"Authorization": f"Bearer {creds.api_key}"},
        )
        if poll_status >= 400:
            raise RuntimeError(f"DASHSCOPE 轮询失败 HTTP {poll_status}")
        p_out = poll_data.get("output") or {}
        task_status = str(p_out.get("task_status") or "").upper()
        if task_status == "SUCCEEDED":
            urls = [r.get("url") or r.get("b64_image") for r in (p_out.get("results") or [])]
            return {"images": [u for u in urls if u], "task_id": task_id, "raw": poll_data}
        if task_status in ("FAILED", "CANCELED", "UNKNOWN"):
            raise RuntimeError(f"DASHSCOPE 任务失败: {str(p_out)[:300]}")
    raise TimeoutError("DASHSCOPE 异步任务轮询超时")


async def _ark_image_generate(
    creds: ProtocolCredentials, prompt: str, size: str, n: int,
    ref_images: List[str], timeout: float,
) -> Dict[str, Any]:
    url = ark_images_url(creds.base_url)
    headers = {"Authorization": f"Bearer {creds.api_key}"}
    body: Dict[str, Any] = {
        "model": creds.model,
        "prompt": prompt,
        "response_format": "url",
        "n": max(1, n),
    }
    if size and "x" in size:
        body["size"] = size
    if ref_images:
        # seedream 参考图：image 字段（URL 直传 / 本地 data URL）
        body["image"] = ref_images[0]
    status, data = await _post_json(url, headers, body, timeout)
    if status >= 400:
        raise RuntimeError(f"ARK 提交失败 HTTP {status}: {str(data)[:300]}")
    images = [item.get("url") for item in (data.get("data") or []) if item.get("url")]
    return {"images": images, "task_id": None, "raw": data}


async def _openai_image_generate(
    creds: ProtocolCredentials, prompt: str, size: str, n: int,
    ref_images: List[str], timeout: float,
) -> Dict[str, Any]:
    url = openai_images_url(creds.base_url)
    headers = {"Authorization": f"Bearer {creds.api_key}"}
    body: Dict[str, Any] = {
        "model": creds.model or "gpt-image-1",
        "prompt": prompt,
        "n": max(1, n),
    }
    if size and "x" in size:
        body["size"] = size
    status, data = await _post_json(url, headers, body, timeout)
    if status >= 400:
        raise RuntimeError(f"OpenAI 兼容图像端点失败 HTTP {status}: {str(data)[:300]}")
    images = []
    for item in (data.get("data") or []):
        if item.get("b64_json"):
            images.append(f"data:image/png;base64,{item['b64_json']}")
        elif item.get("url"):
            images.append(item["url"])
    return {"images": images, "task_id": None, "raw": data}


async def generate_image(
    creds: ProtocolCredentials,
    prompt: str,
    size: str = "1024x1024",
    n: int = 1,
    ref_images: Optional[List[str]] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """图片生成统一入口（同步返回；DASHSCOPE 异步型内部轮询收口）。"""
    protocol = (
        ImageProtocol(creds.protocol)
        if creds.protocol in (p.value for p in ImageProtocol)
        else resolve_image_protocol(creds.protocol, creds.model, creds.base_url)
    )
    refs = ref_images or []
    if protocol == ImageProtocol.DASHSCOPE:
        return await _dashscope_image_generate(creds, prompt, size, n, refs, timeout)
    if protocol == ImageProtocol.ARK:
        return await _ark_image_generate(creds, prompt, size, n, refs, timeout)
    return await _openai_image_generate(creds, prompt, size, n, refs, timeout)


# ── 视频协议：submit / poll 抽象（异步任务型） ──


async def submit_video(
    creds: ProtocolCredentials,
    prompt: str,
    duration: int = 5,
    resolution: str = "1080p",
    ref_images: Optional[List[str]] = None,
    audio: Optional[bool] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """提交视频生成任务，返回 {task_id, poll_url?, raw}。"""
    protocol = (
        VideoProtocol(creds.protocol)
        if creds.protocol in (p.value for p in VideoProtocol)
        else resolve_video_protocol(creds.protocol, creds.model, creds.base_url)
    )
    refs = ref_images or []
    if protocol == VideoProtocol.WAN:
        headers = {"Authorization": f"Bearer {creds.api_key}", **dashscope_async_header()}
        body: Dict[str, Any] = {
            "model": creds.model or "wan3.0-t2v-bundle",
            "input": {"prompt": prompt},
            "parameters": {"resolution": resolution, "duration": int(duration)},
        }
        if audio is not None:
            body["parameters"]["audio"] = bool(audio)
        if refs:
            # wan 参考媒体：公网 URL 直传（本地文件需百炼临时上传，暂不支持——诚实报错）
            for ref in refs:
                if not ref.startswith("http"):
                    raise ValueError("WAN 协议本地参考媒体需经百炼临时上传（暂未实现），请传公网 URL")
            body["input"]["media"] = refs
        status, data = await _post_json(wan_submit_url(creds.base_url), headers, body, timeout)
        if status >= 400:
            raise RuntimeError(f"WAN 提交失败 HTTP {status}: {str(data)[:300]}")
        task_id = (data.get("output") or {}).get("task_id")
        return {"task_id": task_id, "poll_url": dashscope_tasks_url(
            wan_tasks_root(creds.base_url), task_id or ""), "raw": data}

    if protocol == VideoProtocol.SEEDANCE2:
        headers = {"Authorization": f"Bearer {creds.api_key}"}
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for i, ref in enumerate(refs):
            role = "first_frame" if i == 0 else "reference_image"
            content.append({"type": "image_url", "role": role, "image_url": {"url": media_to_data_url(ref)}})
        body = {"model": creds.model, "content": content}
        status, data = await _post_json(seedance_submit_url(creds.base_url), headers, body, timeout)
        if status >= 400:
            raise RuntimeError(f"SEEDANCE2 提交失败 HTTP {status}: {str(data)[:300]}")
        task_id = data.get("id") or (data.get("output") or {}).get("task_id")
        return {"task_id": task_id, "poll_url": seedance_poll_url(creds.base_url, task_id or ""), "raw": data}

    # VEO
    headers = {"x-goog-api-key": creds.api_key}
    instance: Dict[str, Any] = {"prompt": prompt}
    for ref in refs:
        instance["image"] = {"bytesBase64Encoded": media_to_data_url(ref).split(",", 1)[-1],
                             "mimeType": "image/png"}
    body = {
        "instances": [instance],
        "parameters": {"durationSeconds": int(duration), "sampleCount": 1},
    }
    status, data = await _post_json(veo_submit_url(creds.base_url, creds.model), headers, body, timeout)
    if status >= 400:
        raise RuntimeError(f"VEO 提交失败 HTTP {status}: {str(data)[:300]}")
    op_name = data.get("name") or ""
    return {"task_id": op_name, "poll_url": veo_poll_url(creds.base_url, op_name), "raw": data}


async def poll_video(
    creds: ProtocolCredentials, task_id: str, poll_url: str = "",
) -> Dict[str, Any]:
    """轮询一次视频任务：返回 {status: running|succeeded|failed, video_url?, error?, raw}。"""
    protocol = (
        VideoProtocol(creds.protocol)
        if creds.protocol in (p.value for p in VideoProtocol)
        else resolve_video_protocol(creds.protocol, creds.model, creds.base_url)
    )
    if protocol == VideoProtocol.WAN:
        url = poll_url or dashscope_tasks_url(wan_tasks_root(creds.base_url), task_id)
        status, data = await _get_json(url, {"Authorization": f"Bearer {creds.api_key}"})
        if status >= 400:
            return {"status": "failed", "error": f"HTTP {status}", "raw": data}
        out = data.get("output") or {}
        task_status = str(out.get("task_status") or "").upper()
        if task_status == "SUCCEEDED":
            url_video = (out.get("video_url") or (out.get("results") or [{}])[0].get("url"))
            return {"status": "succeeded", "video_url": url_video, "raw": data}
        if task_status in ("FAILED", "CANCELED", "UNKNOWN"):
            return {"status": "failed", "error": str(out)[:300], "raw": data}
        return {"status": "running", "raw": data}

    if protocol == VideoProtocol.SEEDANCE2:
        url = poll_url or seedance_poll_url(creds.base_url, task_id)
        status, data = await _get_json(url, {"Authorization": f"Bearer {creds.api_key}"})
        if status >= 400:
            return {"status": "failed", "error": f"HTTP {status}", "raw": data}
        st = str(data.get("status") or "").lower()
        video_url = None
        for item in (data.get("content") or {}).get("video_url", []) or []:
            video_url = item.get("url") if isinstance(item, dict) else item
        if (data.get("content") or {}).get("video_url") and isinstance(
            (data.get("content") or {}).get("video_url"), str
        ):
            video_url = data["content"]["video_url"]
        if st == "succeeded":
            return {"status": "succeeded", "video_url": video_url, "raw": data}
        if st in ("failed", "cancelled"):
            return {"status": "failed", "error": str(data)[:300], "raw": data}
        return {"status": "running", "raw": data}

    # VEO
    url = poll_url or veo_poll_url(creds.base_url, task_id)
    status, data = await _get_json(url, {"x-goog-api-key": creds.api_key})
    if status >= 400:
        return {"status": "failed", "error": f"HTTP {status}", "raw": data}
    done = bool(data.get("done"))
    if done:
        response = (data.get("response") or {})
        videos = response.get("generateVideoResponse", {}).get("generatedSamples") or \
            response.get("generatedSamples") or []
        video_url = (videos[0].get("video", {}).get("uri") if videos else None)
        return {"status": "succeeded", "video_url": video_url, "raw": data}
    return {"status": "running", "raw": data}


async def generate_video_wait(
    creds: ProtocolCredentials,
    prompt: str,
    duration: int = 5,
    resolution: str = "1080p",
    ref_images: Optional[List[str]] = None,
    audio: Optional[bool] = None,
    poll_interval: float = 10.0,
    max_wait: float = 900.0,
) -> Dict[str, Any]:
    """submit + 轮询直到完成（阻塞式封装，供同步调用方使用）。"""
    submitted = await submit_video(creds, prompt, duration, resolution, ref_images, audio)
    task_id = submitted.get("task_id")
    if not task_id:
        raise RuntimeError(f"视频任务提交未返回 task_id: {str(submitted.get('raw'))[:300]}")
    poll_url = submitted.get("poll_url") or ""
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)
        result = await poll_video(creds, task_id, poll_url)
        if result["status"] != "running":
            return result
    raise TimeoutError("视频生成轮询超时")


# ── B2-d（#7167 对齐）：脚本对白带入生成提示词 + 逐字校验守卫 ────────────────


def build_video_prompt_with_dialogue(
    prompt: str, dialogue_lines: List[str],
) -> str:
    """把叙事脚本的台词逐句并入视频生成提示词。

    QwenPaw #7167：叙事视频缺对白的根因是台词只存在于脚本层、从未进入
    生成提示词。此函数把台词以「角色对白（逐字使用）」段落并入 prompt，
    供视频模型把对白渲染进语音/字幕。
    """
    cleaned = [line.strip() for line in dialogue_lines if line and line.strip()]
    if not cleaned:
        return prompt
    dialogue_block = "\n".join(f"- {line}" for line in cleaned)
    return (
        f"{prompt}\n\n"
        f"角色对白（必须逐字使用，不得改写、不得省略）:\n{dialogue_block}"
    )


def check_dialogue_presence(
    final_prompt: str, dialogue_lines: List[str],
) -> Dict[str, Any]:
    """逐字校验守卫：台词是否逐句进入最终提示词（missing_narrative_dialogue）。"""
    missing = [
        line for line in dialogue_lines
        if line and line.strip() and line.strip() not in final_prompt
    ]
    return {
        "ok": not missing,
        "missing_narrative_dialogue": missing,
        "checked": len([l for l in dialogue_lines if l and l.strip()]),
    }
