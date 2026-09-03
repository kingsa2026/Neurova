"""
会话语义标题生成（深度模块）。

契约（2026-09-03 需求：不要默认对话名，语义概括自动填充）：
- `generate_semantic_title` 永不抛错：LLM 成功 → 清洗后的标题；
  LLM 失败/超时/无客户端 → 回退首条用户消息截断（概括的下限）。
- 输出 ≤ MAX_TITLE_CHARS，去引号/换行/多余空白。
- `is_default_title` 后端/前端共用口径（默认名清单）。
"""
import asyncio
import re
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

MAX_TITLE_CHARS = 20
LLM_TIMEOUT_SECONDS = 10

# 默认标题清单：任一命中即视为"未命名"，需要自动填充。
DEFAULT_TITLES = {"新对话", "新建对话", "新会话", "New conversation", ""}

_SYSTEM_PROMPT = (
    "你是会话标题助手。根据对话内容生成一个简短、语义概括的标题，"
    "直接输出标题本身：不超过 {max} 个汉字，不要引号、不要标点、不要解释。"
)

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_FENCE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
_MARKDOWN_RE = re.compile(r"[*_#>|\[\]()]+")
_WHITESPACE_RE = re.compile(r"\s+")


def is_default_title(title: Optional[str]) -> bool:
    """是否默认/未命名标题。"""
    if title is None:
        return True
    return title.strip() in DEFAULT_TITLES


def _clean_title(text: str) -> str:
    t = (text or "")
    for ch in ('"', "'", "”", "“", "\n", "\r", "。", "！", "！"):
        t = t.replace(ch, " ")
    t = _WHITESPACE_RE.sub(" ", t).strip()
    if len(t) > MAX_TITLE_CHARS:
        t = t[:MAX_TITLE_CHARS].rstrip()
    return t


def fallback_title(content: str) -> str:
    """首条用户消息 → 干净截断（去 markdown/网址/代码/多余空白）。"""
    t = (content or "")
    t = _URL_RE.sub(" ", t)
    t = _FENCE_RE.sub(" ", t)
    t = _INLINE_CODE_RE.sub(" ", t)
    t = _MARKDOWN_RE.sub(" ", t)
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return _clean_title(t)


def _build_summary_context(first_user_content: str, assistant_reply: str) -> str:
    parts = [f"用户：{first_user_content[:200]}"]
    if assistant_reply:
        parts.append(f"助手：{assistant_reply[:200]}")
    return "\n".join(parts)


async def generate_semantic_title(
    first_user_content: str,
    assistant_reply: str = "",
    llm=None,
) -> str:
    """
    LLM 语义概括标题；任何失败/超时回退截断标题，绝不向上抛错。

    Args:
        first_user_content: 首条用户消息（必然非空，由调用方保证）
        assistant_reply: 该轮助手回复（可选，增强概括上下文）
        llm: 注入的 LLM 客户端（推荐传会话 agent 的 llm_client——带
             provider/model 上下文；None 时走多模型客户端默认 scope）
    """
    try:
        if llm is None:
            from neurova.llm.multi_model_client import get_multi_model_client

            llm = get_multi_model_client(scope=None)
        if llm is None:
            logger.warning("多模型客户端不可用，标题回退截断")
            return fallback_title(first_user_content)

        prompt = _SYSTEM_PROMPT.format(max=MAX_TITLE_CHARS) + "\n对话内容：\n" + _build_summary_context(
            first_user_content, assistant_reply
        )
        resp = await asyncio.wait_for(
            llm.chat([{"role": "user", "content": prompt}]),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        if isinstance(resp, dict):
            if not resp.get("success"):
                raise RuntimeError(resp.get("error") or "LLM 调用失败")
            resp = resp.get("response")
        text = _clean_title(getattr(resp, "content", "") or "")
        if text:
            return text
        logger.warning("LLM 标题为空，回退截断")
    except Exception as e:  # noqa: BLE001 —— 标题生成绝不能拖垮对话
        logger.warning("语义标题生成失败，回退截断: %s", e)
    return fallback_title(first_user_content)
