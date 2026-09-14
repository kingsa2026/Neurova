# -*- coding: utf-8 -*-
"""创作专区 LLM 编排：系统提示词（自研，功能对标 huobao 四 agent）+ JSON 稳健抽取。

职责映射：script_rewriter（小说→分集剧本）/ extractor（角色场景道具抽取去重）/
storyboard_breaker（分镜拆解）/ prompt_generator（资产定妆与镜头提示词）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

SCRIPT_REWRITER = (
    "你是资深短剧编剧。把输入小说/故事拆解为分集拍摄脚本，只输出 JSON 数组，不要其它文字。"
    "每个元素字段：number(集序号 int)、title(集标题)、synopsis(一句话梗概)、"
    "content(该集正文脚本，标注场景与出场角色)、characters(角色名数组)、"
    "scenes(场景名数组)、props(道具名数组)。"
)

EXTRACTOR = (
    "你是短剧制片助手。从剧本中抽取角色、场景、道具，同名人只保留一条（合并描述）。"
    "只输出 JSON 对象：characters[{name,role,description,appearance,styling,personality}]、"
    "scenes[{location,time,prompt,lighting}]、props[{name,description}]。"
    "prompt 为可直接用于文生图的英文画面提示词。"
)

STORYBOARD_BREAKER = (
    "你是专业分镜师。把该集剧本拆为 3-12 个镜头，只输出 JSON 数组，不要其它文字。"
    "每个元素字段：number(镜头序号 int)、title、description(画面叙事)、"
    "image_prompt(英文文生图提示词)、video_prompt(镜头运动/主体动作描述)、"
    "narration(旁白台词)、camera(景别)、movement(运镜)、atmosphere(氛围)、"
    "bgm_prompt、sound_effect、duration(秒 number)、characters(出场角色名数组)、props(道具名数组)。"
)

PROMPT_GENERATOR = (
    "你是 AI 绘图提示词工程师。为给定角色/场景/道具生成定妆图英文提示词与"
    "可复用的参考图描述。只输出 JSON 数组，元素字段：id(与输入对应)、"
    "final_prompt(英文定妆提示词)。"
)


def extract_json(text: str, expect: str = "object") -> Optional[Any]:
    """从 LLM 输出稳健抽取 JSON（对象/数组）；失败返回 None（调用侧兜底）。

    支持 ```json 围栏、前后杂文、中文全角引号常见错误最小容错。
    """
    if not text:
        return None
    t = str(text).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", t, re.I)
    if fence:
        t = fence.group(1).strip()
    open_ch, close_ch = ("{", "}") if expect == "object" else ("[", "]")
    # 贪心截取最外层候选片段
    start = t.find(open_ch)
    end = t.rfind(close_ch)
    if start == -1 or end <= start:
        return None
    candidate = t[start:end + 1]
    for attempt in (candidate, candidate.replace("“", '"').replace("”", '"')
                    .replace("，", ",")):
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return None


async def call_llm(prompt: str, system_prompt: str = "",
                   model: Optional[str] = None, temperature: float = 0.7) -> str:
    """经 Agent 对话通道调用 LLM（与 drama 节点同源；失败抛异常由服务层兜底）。"""
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance("default")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Agent 通道不可用: {e}") from e
    if agent is None:
        raise RuntimeError("Agent 未初始化")
    metadata: dict = {"history": []}
    if model:
        metadata["model"] = model
    response = await agent.chat(prompt, system_prompt=system_prompt, metadata=metadata)
    return response if isinstance(response, str) else str(response)
