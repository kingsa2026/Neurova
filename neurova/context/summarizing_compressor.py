"""
真摘要压缩器（P1-1③，对标 QP scroll ContinuationSummary 语义）

把被折叠的中段轮次交给 LLM 生成/增量更新摘要：
- 注入式 llm_call（async callable(prompt) -> str）——零硬依赖
- 失败语义：超时/异常一律返回 previous_summary（"失败保留旧摘要"）
- 成功结果脱敏（防密钥经摘要泄漏进 prompt）
- prompt 含 previous_summary（增量语义）+ 各 chunk 的 turn_id（定位）

归档无损语义不变：压缩只影响视图组装侧的摘要质量，被折叠 chunk 本身
仍完整保留在池/台账中。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Awaitable, Callable, List, Optional

from neurova.context.pool_models import ContextInput

logger = logging.getLogger(__name__)

# 脱敏模式（摘要出口）：常见密钥形态
_REDACT_PATTERNS = (
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{20,})"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(token\s*[=:]\s*)\S+"),
    re.compile(r"(?i)(password\s*[=:]\s*)\S+"),
)

_DEFAULT_PROMPT_TEMPLATE = """你是对话摘要器。请把以下被折叠的早期对话轮次，合并进已有摘要，\
输出一段连续的中文摘要（不要罗列、不要解释）。保留：用户的持久偏好、未完成的任务、\
关键决定与事实。丢弃：寒暄、重复内容。

[已有摘要]
{previous_summary}

[待合并的早期轮次]
{chunks}

[输出新摘要]"""


def _redact(text: str) -> str:
    """摘要出口脱敏：带捕获组的模式保留键名只脱敏值，其余整段替换。"""
    result = text or ""
    for pattern in _REDACT_PATTERNS:
        if pattern.groups:
            result = pattern.sub(r"\1[REDACTED]", result)
        else:
            result = pattern.sub("[REDACTED]", result)
    return result


class SummarizingCompressor:
    """LLM 增量摘要器（注入式，失败保留旧摘要）。"""

    def __init__(
        self,
        llm_call: Optional[Callable[[str], Awaitable[str]]],
        timeout_s: float = 60.0,
        prompt_template: str = _DEFAULT_PROMPT_TEMPLATE,
        max_chunks_in_prompt: int = 40,
    ):
        self._llm_call = llm_call
        self._timeout_s = timeout_s
        self._prompt_template = prompt_template
        self._max_chunks_in_prompt = max_chunks_in_prompt

    async def summarize(
        self,
        chunks: List[ContextInput],
        previous_summary: str = "",
    ) -> Optional[str]:
        """对被折叠 chunk 生成增量摘要。

        Returns:
            str: 新摘要（脱敏后）
            previous_summary: LLM 失败/超时（保留旧摘要语义）
            None: 无 llm_call 或无 chunk（调用方据此跳过摘要流程）
        """
        if self._llm_call is None or not chunks:
            return None

        lines = []
        for c in chunks[: self._max_chunks_in_prompt]:
            turn_id = (c.metadata or {}).get("turn_id", "")
            role = (c.metadata or {}).get("role", "")
            prefix = f"[{turn_id}{'/' + role if role else ''}] " if turn_id else ""
            lines.append(f"{prefix}{c.content}")
        prompt = self._prompt_template.format(
            previous_summary=previous_summary or "（无）",
            chunks="\n".join(lines),
        )

        try:
            raw = await asyncio.wait_for(self._llm_call(prompt), timeout=self._timeout_s)
        except asyncio.TimeoutError:
            logger.info("summarize timeout (%.0fs); keep previous summary", self._timeout_s)
            return previous_summary or None
        except Exception as e:
            logger.info("summarize failed (%s); keep previous summary", e)
            return previous_summary or None

        if not (raw or "").strip():
            return previous_summary or None
        return _redact(raw.strip())
