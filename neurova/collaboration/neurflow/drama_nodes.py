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
import re
import time
from typing import Any, Callable, Dict, List

from neurova.core.logger import get_logger
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
        "description": "将剧本拆分为分镜镜头，定义景别、运镜、时长与转场，供画面生成使用",
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
        "description": "为剧本台词生成配音文案并预估配音时长，可衔接 TTS 节点合成音频",
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
        "description": "将场景片段、配音、字幕合成为成片视频（预留 FFmpeg / 云端合成接口）",
        "sub_blocks": [
            {
                "id": "clips",
                "name": "clips",
                "type": "textarea",
                "label": "片段列表（逗号分隔）",
                "default": "",
                "placeholder": "scene_001.mp4, scene_002.mp4",
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
    """分镜脚本执行器

    将剧本文本按句子拆分为分镜镜头，定义景别/运镜/时长/转场。
    """
    script = config.get("script", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    aspect_ratio = config.get("aspect_ratio", "9:16")

    if not script:
        script = "第一幕：主角登场，面对众人的嘲讽。"

    sentences = [s.strip() for s in re.split(r"[。！？!?\n]", script) if s.strip()]
    if not sentences:
        sentences = [script]

    shots = []
    for idx, sent in enumerate(sentences, 1):
        shots.append(
            {
                "shot": idx,
                "description": sent,
                "duration": 3.0,
                "camera": "中景",
                "move": "固定",
                "transition": "cut",
                "aspect_ratio": aspect_ratio,
            }
        )

    return {
        "status": "success",
        "output": {
            "shots": shots,
            "count": len(shots),
            "aspect_ratio": aspect_ratio,
        },
    }


async def exec_scene_gen(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """场景画面生成执行器

    根据场景描述调用 AI 图像生成服务商（ComfyUI / OpenAI / 可灵 / 即梦 / 通义万相 / Stability）。
    服务不可用时自动降级为纯提示词生成。
    """
    scene = config.get("scene", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    style = config.get("style", "cinematic")
    provider = config.get("provider", "comfyui")

    if not scene:
        scene = "女主角在雨夜的城市街头奔跑"

    # 尝试调用外部图像生成服务
    try:
        result = await ImageGenClient().generate(
            provider=provider,
            prompt=scene,
            size="1024x1024",
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            return {
                "status": "success",
                "output": {
                    "image_url": output.get("url", ""),
                    "image_data": output.get("image_data"),
                    "scene": scene,
                    "style": style,
                    "provider": provider,
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("场景图像生成失败，降级为提示词模式: %s", e)

    prompts = [
        f"电影感全景画面：{scene}，{style}风格，高细节，8K，戏剧性光影",
        f"特写镜头：{scene}，浅景深，自然光，{style}风格，情绪饱满",
        f"空镜过渡：{scene}，无人机航拍视角，{style}风格，氛围感",
    ]

    return {
        "status": "success",
        "output": {
            "prompts": prompts,
            "scene": scene,
            "style": style,
            "provider": provider,
            "count": len(prompts),
            "fallback": True,
        },
    }


async def exec_voice_over(config: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """配音 / 旁白执行器

    整理台词并预估配音时长（中文语速约 4 字/秒）。
    """
    lines = config.get("lines", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    voice = config.get("voice", "女声 温柔")
    language = config.get("language", "zh")

    if not lines:
        lines = "你好，世界！欢迎来到我的短剧。"

    line_list = [l.strip() for l in str(lines).splitlines() if l.strip()]
    if not line_list:
        line_list = [lines]

    char_count = sum(len(l) for l in line_list)
    duration = round(max(1.0, char_count / 4.0), 2)

    return {
        "status": "success",
        "output": {
            "lines": line_list,
            "duration": duration,
            "voice": voice,
            "language": language,
            "estimated_chars_per_sec": 4.0,
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
    """视频合成执行器

    调用 AI 视频生成服务（可灵 / 即梦 / 通义万相 / ComfyUI）合成场景视频。
    服务不可用时降级为模拟合成任务描述。
    """
    clips = config.get("clips", "") or str(ctx.get("input") or ctx.get("inputs") or "")
    transition = config.get("transition", "fade")
    resolution = config.get("resolution", "1080x1920")
    provider = config.get("provider", "kling")

    scene_text = str(clips) if clips else "AI 生成短剧场景合成"

    try:
        result = await VideoGenClient().generate(
            provider=provider,
            prompt=scene_text,
            duration=15,
        )
        if result.get("status") == "success":
            output = result.get("output", {})
            return {
                "status": "success",
                "output": {
                    "video_url": output.get("video_url", ""),
                    "video_data": output.get("video_data"),
                    "provider": provider,
                    "resolution": resolution,
                    "duration": output.get("duration", 15),
                },
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("视频合成失败，降级为模拟合成: %s", e)

    clip_list = [c.strip() for c in str(clips).split(",") if c.strip()]
    if not clip_list:
        clip_list = ["scene_001.mp4", "scene_002.mp4"]

    return {
        "status": "success",
        "output": {
            "video": f"composed_{int(time.time())}.mp4",
            "clips": clip_list,
            "transition": transition,
            "provider": provider,
            "resolution": resolution,
            "duration": round(len(clip_list) * 3.0, 2),
            "fallback": True,
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
