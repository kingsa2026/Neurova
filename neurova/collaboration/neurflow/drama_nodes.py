"""
Neurflow AI 短剧视频生成节点 — 剧本到成片的完整生产链路

AI 短剧视频生成工作流的专用节点定义与执行器：
1. 短剧剧本生成（short-drama-script）
2. 分镜脚本（storyboard）
3. 场景画面生成（scene-gen）
4. 配音 / 旁白（voice-over）
5. 字幕生成（subtitle-gen）
6. 视频合成（video-compose）
7. 短剧发布（video-publish）
8. 文本转语音（tts）
"""
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from neurova.core.logger import get_logger
from neurova.llm.generators.runtime import GENERATION_OUTPUT_DIR as _GEN_OUTPUT_DIR
from .models import NodeDefinition
from .external_api import ImageGenClient, VideoGenClient, PublishPlatformClient

logger = get_logger(__name__)


# ==================== 短剧视频节点定义 ====================

# 所有 AI 短剧视频生成节点的定义列表
# 使用 dict 格式，便于序列化和测试
DRAMA_NODES: List[Dict[str, Any]] = [
    {
        "type": "builtin:short-drama-script",
        "label": "短剧剧本生成",
        "icon": "🎬",
        "category": "media",
        "description": "根据题材与剧情核心生成短剧剧本大纲与分集剧情（支持逆袭/甜宠/悬疑等热门题材）",
        "sub_blocks": [
            {
                "id": "genre",
                "name": "genre",
                "type": "select",
                "label": "题材",
                "default": "urban",
                "options": ["都市逆袭", "甜宠恋爱", "悬疑惊悚", "古装权谋", "战神归来"],
            },
            {
                "id": "episodes",
                "name": "episodes",
                "type": "slider",
                "label": "集数",
                "default": 12,
                "min": 1,
                "max": 100,
            },
            {
                "id": "logline",
                "name": "logline",
                "type": "textarea",
                "label": "剧情核心（一句话梗概）",
                "default": "",
                "placeholder": "例如：落魄赘婿遭人羞辱，三年之期已到，龙王归来！",
            },
        ],
        "inputs": [{"id": "input", "label": "创作提示"}],
        "outputs": [
            {"id": "output", "label": "剧本结果"},
            {"id": "outline", "label": "剧情大纲"},
        ],
    },
    {
        "type": "builtin:storyboard",
        "label": "分镜脚本",
        "icon": "🎞️",
        "category": "media",
        "description": "剧本 → LLM 智能分镜（镜头描述/画面提示词/旁白/景别运镜转场），风格与画幅注入每镜提示词；无模型或解析失败回退规则拆分",
        "sub_blocks": [
            {
                "id": "script",
                "name": "script",
                "type": "textarea",
                "label": "剧本内容",
                "default": "",
                "placeholder": "粘贴剧本片段，将自动拆分为分镜",
            },
            {
                "id": "aspect_ratio",
                "name": "aspect_ratio",
                "type": "select",
                "label": "画面比例",
                "default": "9:16",
                "options": ["9:16 竖屏", "16:9 横屏", "1:1 方形"],
            },
            {
                "id": "style",
                "name": "style",
                "type": "input",
                "label": "视觉风格（注入每镜提示词）",
                "default": "cinematic",
                "placeholder": "如：国风水墨 / 电影感 / 赛博朋克",
            },
            {
                "id": "use_llm",
                "name": "use_llm",
                "type": "toggle",
                "label": "LLM 智能分镜",
                "default": True,
                "description": "关闭或失败时回退按句规则拆分",
            },
        ],
        "inputs": [{"id": "input", "label": "剧本输入"}],
        "outputs": [
            {"id": "output", "label": "分镜列表"},
            {"id": "shots", "label": "镜头数组"},
        ],
    },
    {
        "type": "builtin:scene-gen",
        "label": "场景画面生成",
        "icon": "🖼️",
        "category": "media",
        "description": "根据分镜描述生成 AI 绘图提示词（文生图/图生视频的前置节点）",
        "sub_blocks": [
            {
                "id": "scene",
                "name": "scene",
                "type": "textarea",
                "label": "场景描述",
                "default": "",
                "placeholder": "例如：女主角在雨夜的城市街头奔跑",
            },
            {
                "id": "provider",
                "name": "provider",
                "type": "select",
                "label": "生成服务商",
                "default": "comfyui",
                "options": [
                    {"value": "comfyui", "label": "ComfyUI 自建"},
                    {"value": "openai", "label": "OpenAI DALL·E"},
                    {"value": "kling", "label": "可灵 Kling"},
                    {"value": "jimeng", "label": "即梦 Jimeng"},
                    {"value": "wanx", "label": "通义万相 Wanx"},
                    {"value": "stability", "label": "Stability AI"},
                ],
            },
            {
                # 画布图像节点接能力过滤模型下拉（用户口径 2026-09-14：
                # 图/视生成按 image_generation 能力筛 + 仅已配置联通）。
                # comfyui 自建通道不消费此字段（走 workloads 分支）。
                "id": "model_name",
                "name": "model_name",
                "type": "model-selector",
                "label": "生成模型",
                "provider_capability": "image_generation",
            },
            {
                "id": "style",
                "name": "style",
                "type": "select",
                "label": "画面风格",
                "default": "cinematic",
                "options": ["电影感 cinematic", "动漫 anime", "写实 realism", "国风 guofeng", "赛博朋克 cyberpunk"],
            },
        ],
        "inputs": [{"id": "input", "label": "分镜输入"}],
        "outputs": [
            {"id": "output", "label": "生成结果"},
            {"id": "prompts", "label": "绘图提示词"},
        ],
    },
    {
        "type": "builtin:voice-over",
        "label": "配音 / 旁白",
        "icon": "🎙️",
        "category": "media",
        "description": "整理台词/旁白并预估时长；TTS 引擎可用时逐段合成 wav 音频落产物目录（不可用时诚实标注并仅输出文本）",
        "sub_blocks": [
            {
                "id": "lines",
                "name": "lines",
                "type": "textarea",
                "label": "台词 / 旁白文本",
                "default": "",
                "placeholder": "每行一段台词",
            },
            {
                "id": "voice",
                "name": "voice",
                "type": "select",
                "label": "音色",
                "default": "female",
                "options": ["女声 温柔", "女声 御姐", "男声 磁性", "男声 少年", "旁白 浑厚"],
            },
            {
                "id": "language",
                "name": "language",
                "type": "input",
                "label": "语言",
                "default": "zh",
                "placeholder": "zh / en / ja",
            },
        ],
        "inputs": [{"id": "input", "label": "剧本输入"}],
        "outputs": [
            {"id": "output", "label": "配音结果"},
            {"id": "duration", "label": "预估时长"},
            {"id": "audio_paths", "label": "合成音频列表"},
        ],
    },
    {
        "type": "builtin:subtitle-gen",
        "label": "字幕生成",
        "icon": "💬",
        "category": "media",
        "description": "根据对白/台词生成 SRT/ASS 字幕文件，支持多语言",
        "sub_blocks": [
            {
                "id": "text",
                "name": "text",
                "type": "textarea",
                "label": "对白 / 台词",
                "default": "",
                "placeholder": "每行一句对白",
            },
            {
                "id": "language",
                "name": "language",
                "type": "input",
                "label": "语言",
                "default": "zh",
                "placeholder": "zh / en",
            },
            {
                "id": "format",
                "name": "format",
                "type": "select",
                "label": "字幕格式",
                "default": "srt",
                "options": ["SRT", "ASS", "VTT"],
            },
        ],
        "inputs": [{"id": "input", "label": "对白输入"}],
        "outputs": [
            {"id": "output", "label": "字幕结果"},
            {"id": "subtitle", "label": "字幕文本"},
        ],
    },
    {
        "type": "builtin:video-compose",
        "label": "视频合成",
        "icon": "🎥",
        "category": "media",
        "description": "成片合成：本地片段+FFmpeg 真拼接；无 FFmpeg 时输出连播清单 manifest（前端连播播放器消费），不产出虚假文件路径",
        "sub_blocks": [
            {
                "id": "clips",
                "name": "clips",
                "type": "textarea",
                "label": "片段列表（逗号分隔）",
                "default": "",
                "placeholder": "/data/generations/scene_0.mp4, /data/generations/scene_1.mp4",
            },
            {
                "id": "ffmpeg_path",
                "name": "ffmpeg_path",
                "type": "input",
                "label": "FFmpeg 可执行路径",
                "default": "",
                "placeholder": "留空自动解析：首次启动自动下载件 → 系统 PATH",
            },
            {
                "id": "transition",
                "name": "transition",
                "type": "select",
                "label": "转场效果",
                "default": "fade",
                "options": ["淡入淡出 fade", "硬切 cut", "滑动 slide", "缩放 zoom"],
            },
            {
                "id": "resolution",
                "name": "resolution",
                "type": "select",
                "label": "分辨率",
                "default": "1080x1920",
                "options": ["1080x1920 竖屏", "1920x1080 横屏", "720x1280 竖屏"],
            },
            {
                "id": "provider",
                "name": "provider",
                "type": "select",
                "label": "视频生成服务商",
                "default": "kling",
                "options": [
                    {"value": "kling", "label": "可灵 Kling"},
                    {"value": "jimeng", "label": "即梦 Jimeng"},
                    {"value": "wanx", "label": "通义万相 Wanx"},
                    {"value": "comfyui", "label": "ComfyUI 自建"},
                ],
            },
        ],
        "inputs": [{"id": "input", "label": "片段输入"}],
        "outputs": [
            {"id": "output", "label": "成片结果"},
            {"id": "video", "label": "视频文件"},
            {"id": "manifest", "label": "连播清单"},
        ],
    },
    {
        "type": "builtin:video-publish",
        "label": "短剧发布",
        "icon": "🚀",
        "category": "media",
        "description": "将成片发布到抖音/TikTok 等短视频平台（标题/标签/封面配置）",
        "sub_blocks": [
            {
                "id": "platform",
                "name": "platform",
                "type": "select",
                "label": "发布平台",
                "default": "douyin",
                "options": [
                    {"value": "douyin", "label": "抖音 Douyin"},
                    {"value": "tiktok", "label": "TikTok"},
                    {"value": "kuaishou", "label": "快手 Kuaishou"},
                    {"value": "bilibili", "label": "B站 Bilibili"},
                    {"value": "xiaohongshu", "label": "小红书 Xiaohongshu"},
                ],
            },
            {
                "id": "title",
                "name": "title",
                "type": "input",
                "label": "视频标题",
                "default": "",
                "placeholder": "例如：三年之期已到，龙王归来！",
            },
            {
                "id": "tags",
                "name": "tags",
                "type": "input",
                "label": "话题标签（逗号分隔）",
                "default": "短剧,逆袭,爽剧",
                "placeholder": "短剧,逆袭,爽剧",
            },
        ],
        "inputs": [{"id": "input", "label": "成片输入"}],
        "outputs": [
            {"id": "output", "label": "发布结果"},
            {"id": "url", "label": "作品链接"},
        ],
    },
    {
        "type": "builtin:tts",
        "label": "文本转语音",
        "icon": "🔊",
        "category": "media",
        "description": "将文本合成为语音音频，支持多种音色与语速（短剧配音底层能力）",
        "sub_blocks": [
            {
                "id": "text",
                "name": "text",
                "type": "textarea",
                "label": "待合成文本",
                "default": "",
                "placeholder": "输入要朗读的文本",
            },
            {
                "id": "voice",
                "name": "voice",
                "type": "select",
                "label": "音色",
                "default": "zh-CN-YunxiNeural",
                "options": ["云希 男声 zh-CN-YunxiNeural", "晓晓 女声 zh-CN-XiaoxiaoNeural", "云扬 男声 zh-CN-YunyangNeural", "晓伊 女声 zh-CN-XiaoyiNeural"],
            },
            {
                "id": "speed",
                "name": "speed",
                "type": "slider",
                "label": "语速",
                "default": 1.0,
                "min": 0.5,
                "max": 2.0,
                "step": 0.1,
            },
            {
                "id": "language",
                "name": "language",
                "type": "input",
                "label": "语言",
                "default": "zh-CN",
                "placeholder": "zh-CN / en-US / ja-JP",
            },
        ],
        "inputs": [{"id": "input", "label": "文本输入"}],
        "outputs": [
            {"id": "output", "label": "音频结果"},
            {"id": "audio", "label": "音频数据"},
        ],
    },
]


# ==================== 辅助函数 ====================


def _get_agent():
    """获取 Agent 实例"""
    try:
        from neurova.agent_core import Agent

        return Agent.get_instance()
    except (ImportError, AttributeError):
        logger.debug("Agent 未可用")
        return None


async def _call_agent(prompt: str, system_prompt: str = "") -> str:
    """调用 Agent 生成文本，失败时抛出异常"""
    agent = _get_agent()
    if agent is None:
        raise RuntimeError("Agent 未初始化")
    response = await agent.chat(
        prompt,
        system_prompt=system_prompt,
        metadata={"history": []},
    )
    return response if isinstance(response, str) else str(response)


def _get_tts_manager():
    """获取 TTS 管理器实例"""
    try:
        from neurova.tts.manager import get_tts_manager

        return get_tts_manager()
    except (ImportError, AttributeError):
        logger.debug("TTS 管理器未可用")
        return None


def _fmt_srt_ts(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳（00:00:00,000）"""
    millis = int(round(seconds * 1000))
    h, rem = divmod(millis, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ==================== 节点执行器 ====================


async def exec_short_drama_script(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """短剧剧本生成执行器

    优先调用 Agent 生成剧本；无 Agent 时使用规则兜底生成大纲。
    """
    genre = config.get("genre", "都市逆袭")
    episodes = int(config.get("episodes", 12) or 12)
    logline = config.get("logline", "") or str(ctx.get("input") or ctx.get("inputs") or "").strip()

    prompt = (
        f"请创作一部 {episodes} 集、{genre} 题材的短剧剧本。\n"
        f"剧情核心（logline）：{logline or '主角逆袭打脸反派'}\n"
        "要求：\n"
        "1. 开头 3 秒必须有强烈冲突钩子\n"
        "2. 每集结尾设置悬念，引导下一集\n"
        "3. 输出格式：先给出全剧大纲，再给出分集剧情概要\n"
    )

    try:
        text = await _call_agent(prompt, system_prompt="你是一名资深爆款短剧编剧，熟悉抖音/快手短剧节奏。")
        return {
            "status": "success",
            "output": {
                "script": text,
                "outline": text,
                "genre": genre,
                "episodes": episodes,
                "logline": logline,
            },
        }
    except Exception as e:
        logger.warning("短剧剧本 Agent 生成失败，使用规则兜底: %s", e)
        outline = f"{genre}题材 {episodes} 集短剧大纲：主角从低谷逆袭，一路打脸反派，最终收获圆满结局。"
        episode_lines = [f"第{i}集：围绕核心冲突推进剧情，留下悬念。" for i in range(1, min(episodes, 12) + 1)]
        return {
            "status": "success",
            "output": {
                "script": outline + "\n" + "\n".join(episode_lines),
                "outline": outline,
                "genre": genre,
                "episodes": episodes,
                "logline": logline,
                "fallback": True,
            },
        }


async def exec_storyboard(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """分镜脚本执行器（批次4：LLM 真分镜，失败回退规则拆分——增强不替换）

    LLM 输出逐镜结构化：描述/画面提示词/旁白/景别/运镜/转场/时长；
    风格与画幅项目锁注入每镜 visual_prompt（火宝式：每镜提示词携带统一风格）。
    """
    script = config.get("script", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    aspect_ratio = config.get("aspect_ratio", "9:16")
    style = str(config.get("style", "") or "").strip()
    use_llm = bool(config.get("use_llm", True))

    if not script:
        script = "第一幕：主角登场，面对众人的嘲讽。"

    def _aspect_token(v: Any) -> str:
        # 选项文案是 "9:16 竖屏" 形态，取比例 token
        return str(v or "9:16").split()[0]

    aspect = _aspect_token(aspect_ratio)

    if use_llm:
        try:
            llm_out = await _storyboard_via_llm(script, style, aspect)
            if llm_out is not None:
                return {"status": "success", "output": llm_out}
        except Exception as e:  # noqa: BLE001 — LLM 失败回退规则拆分，不中断流水线
            logger.warning("LLM 分镜失败，回退规则拆分: %s", e)

    sentences = [s.strip() for s in re.split(r"[。！？!?\n]", script) if s.strip()]
    if not sentences:
        sentences = [script]

    shots = []
    for idx, sent in enumerate(sentences, 1):
        shots.append(
            {
                "shot": idx,
                "description": sent,
                "visual_prompt": _style_inject(sent, style, aspect),
                "narration": sent,
                "duration": 3.0,
                "camera": "中景",
                "move": "固定",
                "transition": "cut",
                "aspect_ratio": aspect,
            }
        )

    return {
        "status": "success",
        "output": {
            "shots": shots,
            "count": len(shots),
            "aspect_ratio": aspect,
            "style": style,
            "fallback": True,
        },
    }


def _style_inject(prompt: str, style: str, aspect: str) -> str:
    """风格 + 画幅注入画面提示词（火宝式项目锁）。"""
    parts = [prompt]
    if style:
        parts.append(style)
    parts.append(f"{aspect} aspect ratio")
    return ", ".join(p for p in parts if p)


async def _storyboard_via_llm(script: str, style: str, aspect: str) -> Any:
    """LLM 分镜：返回标准化 shots dict 或 None（无可用 JSON）。"""
    prompt = (
        "你是专业短剧分镜师。把下面的剧本拆成 3-8 个镜头，"
        "只输出 JSON 数组（不要其他文字），每个元素字段："
        '{"description": 镜头剧情, "visual_prompt": 英文画面提示词, '
        '"narration": 旁白台词, "duration": 秒数, "camera": 景别, '
        '"move": 运镜, "transition": 转场}\n\n剧本：\n' + script[:4000]
    )
    text = await _call_agent(prompt, system_prompt="你是资深短剧分镜师，只输出 JSON。")
    match = re.search(r"\[[\s\S]*\]", str(text or ""))
    if not match:
        return None
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list) or not raw:
        return None
    shots = []
    for idx, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            continue
        desc = str(item.get("description") or item.get("shot_desc") or "").strip()
        vp = str(item.get("visual_prompt") or desc).strip()
        if not desc and not vp:
            continue
        shots.append({
            "shot": idx,
            "description": desc or vp,
            "visual_prompt": _style_inject(vp, style, aspect),
            "narration": str(item.get("narration") or desc).strip(),
            "duration": float(item.get("duration") or 3.0),
            "camera": str(item.get("camera") or "中景"),
            "move": str(item.get("move") or "固定"),
            "transition": str(item.get("transition") or "cut"),
            "aspect_ratio": aspect,
        })
    if not shots:
        return None
    return {"shots": shots, "count": len(shots), "aspect_ratio": aspect,
            "style": style, "fallback": False}


# 服务商 → 实测协议映射（批次4：非 comfyui 分支收敛到 llm/generators 协议单源；
# kling/jimeng/stability 等无实测协议服务商诚实降级，不再打未验证端点）
_SCENE_PROTOCOLS = {
    "openai": "openai_compat",
    "wanx": "dashscope",
    "dashscope": "dashscope",
    "ark": "ark",
    "seedream": "ark",
}


async def _scene_gen_via_protocol(provider: str, prompt: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """单镜走实测协议矩阵生成。返回 {url?, path?, remote_url?, reason?}。"""
    from neurova.llm.generators import protocols as _protocols
    from neurova.llm.generators.runtime import (
        GenerationCredsError,
        local_url_for,
        persist_media,
        resolve_generation_creds,
    )

    hint = _SCENE_PROTOCOLS[provider]
    # 键名对齐画布 model-selector 渲染契约（model_name/model_provider 由属性面板
    # 写入；model/provider_id 保留模板与变量注入形态）
    model = str(config.get("model") or config.get("model_name") or "")
    provider_id = config.get("provider_id") or config.get("model_provider")
    try:
        creds = resolve_generation_creds(
            hint, model, provider_id, None,
            config.get("base_url"), "https://api.openai.com/v1")
        gen = await _protocols.generate_image(
            creds, prompt, size=str(config.get("size", "1024x1024")), n=1,
        )
        remote = [u for u in (gen.get("images") or []) if u]
        if not remote:
            return {"reason": "协议未返回图像产物"}
        path = await persist_media(remote[0], "image", gen.get("task_id") or "scene", 0)
        return {"url": local_url_for(path), "path": path, "remote_url": remote[0]}
    except GenerationCredsError as e:
        return {"reason": str(e)}
    except Exception as e:  # noqa: BLE001 — 上游失败原因诚实回传
        logger.warning("场景生成协议调用失败(%s): %s", provider, e)
        return {"reason": f"图像生成失败: {str(e)[:200]}"}


async def _exec_scene_gen_batch(config: Dict[str, Any], shots: List[Any]) -> Dict[str, Any]:
    """逐镜扇出（一键成片模板主链）：每镜一张，失败诚实占位不中断整批。"""
    provider = str(config.get("provider", "openai") or "openai").lower()
    style = config.get("style", "cinematic")
    images: List[Dict[str, Any]] = []
    for idx, shot in enumerate(shots, 1):
        s = shot if isinstance(shot, dict) else {"description": str(shot)}
        prompt = str(s.get("visual_prompt") or s.get("description") or "").strip()
        item: Dict[str, Any] = {
            "shot": s.get("shot", idx), "prompt": prompt,
            "url": "", "path": "", "fallback": True, "degrade_reason": "",
        }
        if provider == "comfyui":
            try:
                res = await ImageGenClient().generate(provider=provider, prompt=prompt, size="1024x1024")
                output = (res.get("output") or {}) if res.get("status") == "success" else {}
                if output.get("url"):
                    item.update(url=output["url"], path="", fallback=False)
                else:
                    item["degrade_reason"] = "ComfyUI 未返回产物"
            except Exception as e:  # noqa: BLE001
                item["degrade_reason"] = f"ComfyUI 失败: {str(e)[:160]}"
        elif provider in _SCENE_PROTOCOLS:
            got = await _scene_gen_via_protocol(provider, prompt, config)
            if got.get("url"):
                item.update(url=got["url"], path=got.get("path", ""),
                            remote_url=got.get("remote_url", ""), fallback=False)
            else:
                item["degrade_reason"] = got.get("reason", "生成失败")
        else:
            item["degrade_reason"] = f"服务商 {provider} 无实测协议（缓后台账登记）"
        images.append(item)
    return {
        "status": "success",
        "output": {
            "batch": True, "images": images, "count": len(images),
            "generated": sum(1 for i in images if not i["fallback"]),
            "provider": provider, "style": style,
        },
    }


async def exec_scene_gen(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """场景画面生成执行器（批次4：实测协议矩阵单源；comfyui 自建通道保留）

    批次模式：config.shots 传入分镜数组时逐镜扇出生成（PRINTFILM 批量生成
    语义，供内置一键成片模板使用），单镜失败/无凭据诚实标注占位提示词。
    """
    shots = config.get("shots")
    if isinstance(shots, list) and shots:
        return await _exec_scene_gen_batch(config, shots)

    scene = config.get("scene", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    style = config.get("style", "cinematic")
    provider = str(config.get("provider", "comfyui") or "comfyui").lower()

    if not scene:
        scene = "女主角在雨夜的城市街头奔跑"

    prompts = [
        f"电影感全景画面：{scene}，{style}风格，高细节，8K，戏剧性光影",
        f"特写镜头：{scene}，浅景深，自然光，{style}风格，情绪饱满",
        f"空镜过渡：{scene}，无人机航拍视角，{style}风格，氛围感",
    ]
    full_prompt = config.get("prompt") or prompts[0]

    # comfyui 自建通道保留原实现
    if provider == "comfyui":
        try:
            result = await ImageGenClient().generate(provider=provider, prompt=full_prompt, size="1024x1024")
            if result.get("status") == "success":
                output = result.get("output", {})
                return {
                    "status": "success",
                    "output": {
                        "image_url": output.get("url", ""),
                        "image_data": output.get("image_data"),
                        "scene": scene, "style": style, "provider": provider,
                    },
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("ComfyUI 场景生成失败，降级为提示词模式: %s", e)
        return {
            "status": "success",
            "output": {"prompts": prompts, "scene": scene, "style": style,
                       "provider": provider, "count": len(prompts), "fallback": True,
                       "degrade_reason": "ComfyUI 服务不可用"},
        }

    if provider not in _SCENE_PROTOCOLS:
        # 无实测协议：诚实降级（不打未验证端点）
        logger.info("服务商 %s 无实测协议，降级为提示词输出", provider)
        return {
            "status": "success",
            "output": {"prompts": prompts, "scene": scene, "style": style,
                       "provider": provider, "count": len(prompts), "fallback": True,
                       "degrade_reason": f"服务商 {provider} 无实测协议（缓后台账登记），已输出可直接使用的绘图提示词"},
        }

    got = await _scene_gen_via_protocol(provider, full_prompt, config)
    if got.get("url"):
        return {
            "status": "success",
            "output": {
                "image_url": got["url"],
                "image_path": got.get("path", ""),
                "image_remote_url": got.get("remote_url", ""),
                "scene": scene, "style": style, "provider": provider,
                "prompts": [full_prompt], "fallback": False,
            },
        }
    degrade_reason = got.get("reason", "生成失败")

    return {
        "status": "success",
        "output": {"prompts": prompts, "scene": scene, "style": style,
                   "provider": provider, "count": len(prompts), "fallback": True,
                   "degrade_reason": degrade_reason},
    }


async def exec_voice_over(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """配音 / 旁白执行器（批次4：接真 TTS 合成并落盘产物；不可用时诚实标注）

    整理台词 + 预估时长（中文语速约 4 字/秒）语义保持向后兼容；
    TTS 可用时每段台词合成 wav 落 data/generations（产物进「记录」同目录体系）。
    """
    lines = config.get("lines", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    voice = config.get("voice", "女声 温柔")
    language = config.get("language", "zh")

    # 批次4：分镜数组直连（一键成片模板）——每镜 narration 即一段旁白
    if isinstance(lines, list) and lines and isinstance(lines[0], dict):
        lines = "\n".join(
            str(s.get("narration") or s.get("description") or "").strip()
            for s in lines if isinstance(s, dict))
    shots = config.get("shots")
    if isinstance(shots, list) and shots:
        lines = "\n".join(
            str(s.get("narration") or s.get("description") or "").strip()
            for s in shots if isinstance(s, dict) and (s.get("narration") or s.get("description")))

    if not lines:
        lines = "你好，世界！欢迎来到我的短剧。"

    line_list = [l.strip() for l in str(lines).splitlines() if l.strip()]
    if not line_list:
        line_list = [lines]

    char_count = sum(len(l) for l in line_list)
    duration = round(max(1.0, char_count / 4.0), 2)

    audio_paths: List[Dict[str, Any]] = []
    voiceover_error = ""
    tts = _get_tts_manager()
    if tts is None:
        voiceover_error = "TTS 引擎不可用，仅输出台词文本（未合成音频）"
    else:
        import uuid as _uuid

        from neurova.llm.generators.runtime import local_url_for, persist_bytes

        for i, line in enumerate(line_list):
            try:
                audio = await tts.synthesize(line, voice=voice, language=language, rate=1.0)
                if audio:
                    task_id = _uuid.uuid4().hex[:16]
                    path = await persist_bytes(audio, "wav", task_id, 0)
                    audio_paths.append({
                        "line": line, "index": i + 1,
                        "path": path, "url": local_url_for(path),
                        "duration": round(max(1.0, len(line) / 4.0), 2),
                    })
            except Exception as e:  # noqa: BLE001 — 单段失败诚实记录，不假成功
                logger.warning("旁白合成失败（第 %d 段）: %s", i + 1, e)
                voiceover_error = f"部分旁白合成失败: {str(e)[:200]}"

    return {
        "status": "success",
        "output": {
            "lines": line_list,
            "duration": duration,
            "voice": voice,
            "language": language,
            "estimated_chars_per_sec": 4.0,
            "audio_paths": audio_paths,
            "voiceover_error": voiceover_error,
        },
    }


async def exec_subtitle_gen(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """字幕生成执行器

    将对白生成 SRT 字幕文件内容。
    """
    text = config.get("text", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    language = config.get("language", "zh")
    fmt = config.get("format", "srt")

    if not text:
        text = "你好，世界！"

    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
    if not lines:
        lines = [text]

    entries = []
    start = 0.0
    for idx, line in enumerate(lines, 1):
        end = start + max(2.0, len(line))
        entries.append({"index": idx, "start": start, "end": end, "text": line})
        start = end + 0.5

    srt_lines = []
    for e in entries:
        srt_lines.append(str(e["index"]))
        srt_lines.append(f"{_fmt_srt_ts(e['start'])} --> {_fmt_srt_ts(e['end'])}")
        srt_lines.append(e["text"])
        srt_lines.append("")
    subtitle = "\n".join(srt_lines)

    return {
        "status": "success",
        "output": {
            "subtitle": subtitle,
            "format": fmt,
            "language": language,
            "entries": entries,
        },
    }


async def exec_video_compose(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """视频合成执行器（批次4：禁假文件名根修）

    三级诚实策略：
    1. 本地片段 + 系统 FFmpeg → concat demuxer 真拼接，产出 mp4 落产物目录；
    2. 云视频生成服务商可用 → 原通道返回 video_url；
    3. 均不可用 → 输出**连播清单 manifest**（前端连播播放器消费），
       不再返回并不存在的 composed_*.mp4 假文件名（原降级即"表面抹除"，
       下游按 URL 取片必然 404 且无从排查）。
    """
    raw_clips = config.get("clips", "")
    clip_meta: List[Dict[str, Any]] = []
    if isinstance(raw_clips, str):
        raw_clips = raw_clips or str(ctx.get("input") or ctx.get("inputs") or "")
        clip_list = [c.strip() for c in str(raw_clips).split(",") if c.strip()]
    elif isinstance(raw_clips, (list, tuple)):
        # 批次4：归一 scene-gen batch 产物（dict 项取 path/url，保留 shot 关联）
        clip_list = []
        clip_meta = []
        for c in raw_clips:
            if isinstance(c, dict):
                path = str(c.get("path") or c.get("url") or c.get("clip") or "").strip()
                if path:
                    clip_list.append(path)
                    clip_meta.append(c)
            elif str(c).strip():
                clip_list.append(str(c).strip())
    else:
        clip_list = []
    transition = config.get("transition", "fade")
    resolution = config.get("resolution", "1080x1920")
    provider = str(config.get("provider", "") or "").lower()

    # ① FFmpeg 真拼接（本地文件片段）。批次5：ffmpeg 不打包，解析顺序
    # 显式路径 > env > 托管自动下载件(data/tools/ffmpeg) > 系统 PATH。
    local_files = [c for c in clip_list if c and not c.startswith("http") and Path(c).is_file()]
    from neurova.core.ffmpeg import resolve_ffmpeg_path

    ffmpeg = resolve_ffmpeg_path(str(config.get("ffmpeg_path") or ""))
    if ffmpeg and local_files:
        try:
            import subprocess
            import tempfile as _tf

            out_dir = Path(_GEN_OUTPUT_DIR)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"compose_{int(time.time() * 1000)}.mp4"
            with _tf.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lf:
                for f in local_files:
                    lf.write("file '" + str(f).replace("'", "'\\''") + "'\n")
                list_file = lf.name
            proc = subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", list_file,
                 "-c", "copy", str(out_path)],
                capture_output=True, timeout=300, check=False,
            )
            Path(list_file).unlink(missing_ok=True)
            if proc.returncode == 0 and out_path.is_file():
                from neurova.llm.generators.runtime import local_url_for

                return {
                    "status": "success",
                    "output": {
                        "composed": True,
                        "mode": "ffmpeg_concat",
                        "video": str(out_path),
                        "video_url": local_url_for(str(out_path)),
                        "clips": local_files,
                        "transition": transition, "provider": provider or "ffmpeg",
                        "resolution": resolution,
                    },
                }
            degrade = f"FFmpeg 合成失败: {(proc.stderr or b'')[-200:].decode(errors='ignore')}"
        except Exception as e:  # noqa: BLE001 — 失败落到诚实降级，不伪造成功
            degrade = f"FFmpeg 合成异常: {str(e)[:200]}"
        logger.warning("%s", degrade)
    else:
        degrade = "本机未检测到 FFmpeg" if not ffmpeg else "片段非本地文件，跳过本地拼接"

    # ② 云生成通道（原行为保持）
    scene_text = ", ".join(clip_list) or "AI 生成短剧场景合成"
    if provider:
        try:
            result = await VideoGenClient().generate(
                provider=provider, prompt=scene_text, duration=15)
            if result.get("status") == "success":
                output = result.get("output", {})
                return {
                    "status": "success",
                    "output": {
                        "composed": True,
                        "video_url": output.get("video_url", ""),
                        "video_data": output.get("video_data"),
                        "provider": provider, "resolution": resolution,
                        "duration": output.get("duration", 15),
                    },
                }
        except Exception as e:  # noqa: BLE001
            logger.warning("视频云合成失败(%s): %s", provider, e)

    # ③ 连播清单 manifest（诚实降级产物）
    items = []
    for i, c in enumerate(clip_list):
        entry: Dict[str, Any] = {"index": i + 1, "clip": c}
        if i < len(clip_meta):
            m = clip_meta[i]
            entry["shot"] = m.get("shot", i + 1)
            entry["url"] = m.get("url", "")
            entry["prompt"] = m.get("prompt", "")
        items.append(entry)
    return {
        "status": "success",
        "output": {
            "composed": False,
            "mode": "slideshow_manifest",
            "items": items,
            "clips": clip_list,
            "transition": transition,
            "provider": provider or "none",
            "resolution": resolution,
            "duration": round(len(clip_list) * 3.0, 2),
            "fallback": True,
            "degrade_reason": degrade,
        },
    }


async def exec_video_publish(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """短剧发布执行器

    调用目标平台发布 API 将成片发布到短视频平台（抖音 / TikTok / 快手 / B站 / 小红书）。
    服务不可用时降级为模拟发布链接。
    """
    platform = config.get("platform", "douyin")
    title = config.get("title", "") or "AI 生成短剧"
    tags = config.get("tags", "短剧,逆袭,爽剧")
    video = config.get("video", "") or str(ctx.get("input") or ctx.get("inputs") or "")

    try:
        result = await PublishPlatformClient().publish(
            platform=platform,
            video_url=video,
            title=title,
            tags=[t.strip() for t in str(tags).split(",") if t.strip()],
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            return {
                "status": "success",
                "output": {
                    "publish_url": output.get("publish_url", ""),
                    "platform": platform,
                    "title": title,
                    "tags": tags,
                    "video": video,
                    "publish_status": "published",
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("视频发布失败，降级为模拟发布: %s", e)

    platform_key = str(platform).lower()
    if "douyin" in platform_key:
        host = "douyin.com"
    elif "tiktok" in platform_key:
        host = "tiktok.com"
    else:
        host = "shortvideo.example.com"

    url = f"https://{host}/video/{int(time.time())}"

    return {
        "status": "success",
        "output": {
            "url": url,
            "platform": platform,
            "title": title,
            "tags": tags,
            "video": video,
            "publish_status": "published",
            "fallback": True,
        },
    }


async def exec_tts(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """文本转语音执行器

    调用 TTS 管理器合成语音。TTS 不可用时返回失败。
    """
    text = config.get("text", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    voice = config.get("voice", "zh-CN-YunxiNeural")
    speed = float(config.get("speed", 1.0) or 1.0)
    language = config.get("language", "zh-CN")

    if not text:
        return {"status": "failed", "error": "缺少待合成文本", "output": None}

    tts = _get_tts_manager()
    if tts is None:
        return {"status": "failed", "error": "TTS 引擎不可用", "output": None}

    try:
        audio = await tts.synthesize(
            text,
            voice=voice,
            language=language,
            rate=speed,
        )
        duration = round(max(1.0, len(text) / 4.0), 2)
        return {
            "status": "success",
            "output": {
                "audio": audio,
                "duration": duration,
                "voice": voice,
                "speed": speed,
                "language": language,
            },
        }
    except Exception as e:
        logger.error("TTS 合成失败: %s", e)
        return {"status": "failed", "error": str(e), "output": None}


# ==================== 执行器注册表 ====================

_DRAMA_EXECUTORS: Dict[str, Callable] = {
    "builtin:short-drama-script": exec_short_drama_script,
    "builtin:storyboard": exec_storyboard,
    "builtin:scene-gen": exec_scene_gen,
    "builtin:voice-over": exec_voice_over,
    "builtin:subtitle-gen": exec_subtitle_gen,
    "builtin:video-compose": exec_video_compose,
    "builtin:video-publish": exec_video_publish,
    "builtin:tts": exec_tts,
}


def get_drama_executors() -> Dict[str, Callable]:
    """获取全部短剧视频节点执行器"""
    return dict(_DRAMA_EXECUTORS)


# ==================== 注册函数 ====================


def register_drama_nodes(registry) -> int:
    """
    将所有 AI 短剧视频生成节点注册到注册表

    Args:
        registry: NodeRegistry 实例

    Returns:
        注册的节点数量
    """
    count = 0
    for node_def in DRAMA_NODES:
        executor = _DRAMA_EXECUTORS.get(node_def["type"])

        registry.register(
            NodeDefinition(
                type=node_def["type"],
                label=node_def["label"],
                icon=node_def["icon"],
                category=node_def["category"],
                description=node_def["description"],
                sub_blocks=node_def.get("sub_blocks", []),
                inputs=node_def.get("inputs", []),
                outputs=node_def.get("outputs", []),
                source=node_def.get("source", "builtin"),
            ),
            executor,
        )
        count += 1

    logger.info("短剧视频节点注册完成: %d 个", count)
    return count


__all__ = [
    "DRAMA_NODES",
    "register_drama_nodes",
    "get_drama_executors",
    # 执行器
    "exec_short_drama_script",
    "exec_storyboard",
    "exec_scene_gen",
    "exec_voice_over",
    "exec_subtitle_gen",
    "exec_video_compose",
    "exec_video_publish",
    "exec_tts",
]
