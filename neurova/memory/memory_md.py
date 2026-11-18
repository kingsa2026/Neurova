# -*- coding: utf-8 -*-
"""人机共编长期记忆 MEMORY.md（QwenPaw 对照批 B2）。

每个 Agent 一份 `MEMORY.md`（落 `data/agents/<agent_id>/`）：
- **人**：经 console API 直接读写（共编入口）；
- **机**：build_context 把内容作为高优先记忆段注入 system；
- 蒸馏（LLM 归纳回写）属后续批次，本模块只负责存取与注入格式。

边界：内容是**用户可编辑的长期记忆**，不走 memory_admission（那是模型
写入侧的准入闸）；读侧截断到 `_MAX_CHARS`，防止超大文件撑爆 prompt。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from neurova.core.data_root import dataLanding

logger = logging.getLogger(__name__)

#: 注入与存储的长度上界（字符）：超出部分截断并留痕——共编文件是长期资产，
#: 不设上界会让一次误编辑撑爆此后每一轮的 prompt。
_MAX_CHARS = 64 * 1024

_INJECTION_HEADER = "【长期记忆（人机共编 MEMORY.md）】"


def memoryMdPath(agent_id: str) -> Path:
    """某 agent 的 MEMORY.md 落点（data/agents/<agent_id>/MEMORY.md）。"""
    return dataLanding("agents", str(agent_id or "default"), "MEMORY.md")


def readMemoryMd(agent_id: str) -> str:
    """读共编记忆内容；文件不存在/异常返回空串（不抛——缺文件是常态）。"""
    path = memoryMdPath(agent_id)
    try:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")[:_MAX_CHARS]
    except Exception as e:  # noqa: BLE001 - 读失败按空处理并留痕
        logger.warning("读取 MEMORY.md 失败（%s）：%s", path, e)
        return ""


def writeMemoryMd(agent_id: str, content: str) -> str:
    """写共编记忆内容（人机共编的"人"侧入口）。返回实际落盘内容。"""
    path = memoryMdPath(agent_id)
    text = str(content or "")[:_MAX_CHARS]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("MEMORY.md 已更新：%s（%d 字符）", path, len(text))
    return text


def memoryMdContextLines(agent_id: str) -> list:
    """build_context 的注入段：有内容时返回 [标题行, 内容行]；空则 []。"""
    content = readMemoryMd(agent_id).strip()
    if not content:
        return []
    return [_INJECTION_HEADER, content]
