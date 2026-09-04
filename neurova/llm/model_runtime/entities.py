"""统一模型契约 — 实体层（消息族 + 结果族 + 结构化输出）。

Dify §2.5 六型统一契约的 Neurova 落地（消息/结果两族同名对齐）。
全 dataclass + OpenAI dict 双向适配器（from/to_openai_dict）——
管线现状是 OpenAI dict 通道，适配器是契约与通道间的桥，零破坏。
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
# 多模态内容
# ══════════════════════════════════════════════════════════════

_DATA_URI = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<b64>[A-Za-z0-9+/=\s]+)$")


@dataclass
class TextPromptMessageContent:
    """文本内容块"""

    data: str = ""
    format: str = "text"

    def to_openai_content(self) -> Dict[str, Any]:
        return {"type": "text", "text": self.data}


@dataclass
class ImagePromptMessageContent:
    """图片内容块（data 支持 URL 或 base64；from_data_uri 自动识别）"""

    data: str = ""  # URL 或裸 base64
    mime_type: str = "image/png"
    format: str = "image"

    @classmethod
    def from_data_uri(cls, uri: str) -> "ImagePromptMessageContent":
        """data:[mime];base64,xxx 形态自动拆出 mime 与 base64 数据"""
        m = _DATA_URI.match(uri or "")
        if m:
            b64 = re.sub(r"\s+", "", m.group("b64"))
            return cls(data=b64, mime_type=m.group("mime"))
        return cls(data=uri or "")

    @property
    def base64_data(self) -> str:
        return self.data if self._is_base64() else ""

    @property
    def url(self) -> str:
        return self.data if not self._is_base64() else ""

    def _is_base64(self) -> bool:
        return bool(self.data) and not self.data.startswith(("http://", "https://"))

    def to_openai_content(self) -> Dict[str, Any]:
        url = self.data if self._is_base64() is False else f"data:{self.mime_type};base64,{self.data}"
        return {"type": "image_url", "image_url": {"url": url}}


PromptMessageContentType = Union[str, TextPromptMessageContent, ImagePromptMessageContent]


def _contents_to_openai(content: Union[str, List[Any]]) -> Any:
    """str 原样；内容块列表 → OpenAI 多模态数组（字符串块也归一为 text 块）"""
    if isinstance(content, str):
        return content
    out: List[Dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            out.append({"type": "text", "text": block})
        elif hasattr(block, "to_openai_content"):
            out.append(block.to_openai_content())
        else:
            out.append(block)
    return out


def _contents_from_openai(content: Any) -> Union[str, List[Any]]:
    """OpenAI 数组 → 内容块实例；纯文本保持 str（兼容现有管线语义）"""
    if isinstance(content, str) or content is None:
        return content or ""
    if not isinstance(content, list):
        return str(content)
    blocks: List[Any] = []
    for item in content:
        if not isinstance(item, dict):
            blocks.append(item)
            continue
        itype = item.get("type")
        if itype == "text":
            blocks.append(TextPromptMessageContent(data=str(item.get("text", ""))))
        elif itype == "image_url":
            src = (item.get("image_url") or {}).get("url", "")
            blocks.append(ImagePromptMessageContent.from_data_uri(src))
        else:
            blocks.append(item)
    return blocks


# ══════════════════════════════════════════════════════════════
# 消息族
# ══════════════════════════════════════════════════════════════


@dataclass
class PromptMessageTool:
    """工具定义（OpenAI function 形态；parameters 为 JSON Schema dict）"""

    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_openai_dict(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "PromptMessageTool":
        fn = d.get("function") or {}
        return cls(
            name=str(fn.get("name", "")),
            description=str(fn.get("description", "")),
            parameters=fn.get("parameters") or {},
        )


@dataclass
class PromptMessage:
    """消息基类：role 由子类固定；content 为 str 或内容块列表"""

    role: str = ""
    content: Union[str, List[PromptMessageContentType]] = ""
    name: str = ""

    def to_openai_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": _contents_to_openai(self.content)}
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "PromptMessage":
        raise NotImplementedError("用 prompt_messages_from_openai / 具体子类")


@dataclass
class SystemPromptMessage(PromptMessage):
    role: str = "system"

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "SystemPromptMessage":
        return cls(content=_contents_from_openai(d.get("content")), name=d.get("name", ""))


@dataclass
class UserPromptMessage(PromptMessage):
    role: str = "user"

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "UserPromptMessage":
        return cls(content=_contents_from_openai(d.get("content")), name=d.get("name", ""))


@dataclass
class ToolPromptMessage(PromptMessage):
    """工具结果消息（role=tool，携带 tool_call_id）"""

    role: str = "tool"
    tool_call_id: str = ""

    def to_openai_dict(self) -> Dict[str, Any]:
        d = super().to_openai_dict()
        d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "ToolPromptMessage":
        return cls(
            content=_contents_from_openai(d.get("content")),
            tool_call_id=str(d.get("tool_call_id", "")),
            name=d.get("name", ""),
        )


@dataclass
class AssistantPromptMessage(PromptMessage):
    """助手消息：可携带 tool_calls（OpenAI 形态的 dict 列表，契约不重复造形）"""

    role: str = "assistant"
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)

    def to_openai_dict(self) -> Dict[str, Any]:
        d = super().to_openai_dict()
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d

    @classmethod
    def from_openai_dict(cls, d: Dict[str, Any]) -> "AssistantPromptMessage":
        return cls(
            content=_contents_from_openai(d.get("content")),
            tool_calls=list(d.get("tool_calls") or []),
            name=d.get("name", ""),
        )


_ROLE_TO_CLS = {
    "system": SystemPromptMessage,
    "user": UserPromptMessage,
    "assistant": AssistantPromptMessage,
    "tool": ToolPromptMessage,
}


def prompt_messages_from_openai(raw: List[Dict[str, Any]]) -> List[PromptMessage]:
    """OpenAI dict 消息列表 → 类型化 PromptMessage 列表（按 role 多态）"""
    msgs: List[PromptMessage] = []
    for d in raw or []:
        cls = _ROLE_TO_CLS.get(str(d.get("role", "")))
        if cls is None:
            logger.debug("未知消息角色 %r，按 user 处理", d.get("role"))
            cls = UserPromptMessage
        msgs.append(cls.from_openai_dict(d))
    return msgs


def prompt_messages_to_openai(msgs: List[PromptMessage]) -> List[Dict[str, Any]]:
    """类型化消息列表 → OpenAI dict 列表（管线通道）"""
    return [m.to_openai_dict() for m in msgs or []]


# ══════════════════════════════════════════════════════════════
# 结果族
# ══════════════════════════════════════════════════════════════


@dataclass
class LLMUsage:
    """token 使用计量（键名归一；缺失补 0；total 缺失自动求和）"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency: float = 0.0

    @classmethod
    def from_provider_dict(cls, d: Optional[Dict[str, Any]]) -> "LLMUsage":
        d = d or {}
        prompt = int(d.get("prompt_tokens") or d.get("prompt") or 0)
        completion = int(d.get("completion_tokens") or d.get("completion") or 0)
        total = int(d.get("total_tokens") or 0) or (prompt + completion)
        return cls(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            latency=float(d.get("latency") or 0.0),
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResult:
    """非流式 LLM 结果（prompt + assistant 消息 + usage）"""

    model: str = ""
    message: AssistantPromptMessage = field(default_factory=AssistantPromptMessage)
    usage: LLMUsage = field(default_factory=LLMUsage)
    prompt_messages: List[PromptMessage] = field(default_factory=list)
    finish_reason: str = ""

    @classmethod
    def from_llm_response(cls, resp: Any, prompt: Optional[List[Dict[str, Any]]] = None) -> "LLMResult":
        """从既有 llm_client.LLMResponse 适配（增量桥接，不改旧类型）"""
        usage = resp.usage if isinstance(resp.usage, LLMUsage) else LLMUsage.from_provider_dict(resp.usage)
        return cls(
            model=str(resp.model or ""),
            message=AssistantPromptMessage(
                content=str(resp.content or ""),
                tool_calls=list(resp.tool_calls or []),
            ),
            usage=usage,
            prompt_messages=prompt_messages_from_openai(prompt or []),
            finish_reason=str(resp.finish_reason or ""),
        )


@dataclass
class LLMResultChunkDelta:
    """流式增量：content 片段；尾包携带 usage（Dify chunk/delta 两层形）"""

    index: int = 0
    content: str = ""
    usage: Optional[LLMUsage] = None


@dataclass
class LLMResultChunk:
    """流式块"""

    model: str = ""
    delta: LLMResultChunkDelta = field(default_factory=LLMResultChunkDelta)
    prompt_messages: List[PromptMessage] = field(default_factory=list)


@dataclass
class EmbeddingUsage:
    tokens: int = 0
    total_tokens: int = 0


@dataclass
class TextEmbeddingResult:
    """文本嵌入结果（批次顺序与输入一致）"""

    model: str = ""
    embeddings: List[List[float]] = field(default_factory=list)
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)


@dataclass
class RerankDocument:
    """重排命中文档：原始候选下标 + 文本 + 相关度得分"""

    index: int = 0
    text: str = ""
    score: float = 0.0


@dataclass
class RerankResult:
    """重排结果（docs 按 score 降序——调用方约定）"""

    model: str = ""
    docs: List[RerankDocument] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 结构化输出（一等契约）
# ══════════════════════════════════════════════════════════════

_FENCED_JSON = re.compile(r"```(?:json)?\s*\n(?P<body>.*?)\n\s*```", re.DOTALL)


@dataclass
class LLMStructuredOutput:
    """结构化输出契约：text 原文 + payload 解析结果 + schema 校验状态。

    structured=True 仅在「提取成功且 schema 校验通过（或未提供 schema）」。
    校验失败时 payload 保留供调试，validation_error 说明原因。
    """

    text: str = ""
    payload: Optional[Any] = None
    structured: bool = False
    validation_error: str = ""

    @classmethod
    def parse(cls, text: str, schema: Optional[Dict[str, Any]] = None) -> "LLMStructuredOutput":
        text = text or ""
        payload, err = _extract_json(text)
        if err:
            return cls(text=text, payload=None, structured=False, validation_error=err)
        if schema is not None:
            err = _validate_against_schema(payload, schema)
            if err:
                return cls(text=text, payload=payload, structured=False, validation_error=err)
        return cls(text=text, payload=payload, structured=True, validation_error="")


def _extract_json(text: str) -> tuple:
    """围栏 ```json 优先，其次裸 JSON；均失败报错"""
    m = _FENCED_JSON.search(text)
    candidates = [m.group("body")] if m else []
    candidates.append(text.strip())
    for cand in candidates:
        try:
            return json.loads(cand), ""
        except (json.JSONDecodeError, ValueError):
            continue
    return None, "响应中未找到可解析的 JSON"


def _validate_against_schema(payload: Any, schema: Dict[str, Any]) -> str:
    """jsonschema 校验（可选依赖；不可用时跳过校验视为通过）"""
    try:
        import jsonschema
    except ImportError:
        logger.debug("jsonschema 未安装，跳过 schema 校验")
        return ""
    try:
        jsonschema.validate(payload, schema)
        return ""
    except jsonschema.ValidationError as e:
        # 只取路径与摘要，原始异常字符串可能巨长
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        return f"schema 校验失败 @{path}: {e.message}"


__all__ = [
    "TextPromptMessageContent",
    "ImagePromptMessageContent",
    "PromptMessageTool",
    "PromptMessage",
    "SystemPromptMessage",
    "UserPromptMessage",
    "AssistantPromptMessage",
    "ToolPromptMessage",
    "prompt_messages_from_openai",
    "prompt_messages_to_openai",
    "LLMUsage",
    "LLMResult",
    "LLMResultChunk",
    "LLMResultChunkDelta",
    "EmbeddingUsage",
    "TextEmbeddingResult",
    "RerankDocument",
    "RerankResult",
    "LLMStructuredOutput",
]
