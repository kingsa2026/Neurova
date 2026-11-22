# -*- coding: utf-8 -*-
"""Ollama 原生运行面客户端（R9，参照系 ad 追平批三）。

管理面早已原生（/api/tags、/api/pull，见 OllamaProvider）；运行面此前只有
OpenAI 兼容端点 /v1/chat/completions 一条路。部分部署不提供兼容端点时，
/v1 探测 404 → 本客户端以原生 /api/chat（NDJSON 流）兜底。

接口与 LLMClient 鸭子对齐（chat / chat_stream_async / count_tokens /
count_message_tokens），multi_model_client 零改动消费（同
AnthropicNativeClient / GeminiNativeClient 形态）。

**兼容优先**：仅当 ollamaCompatAvailable()=False（/v1/models 明确 404）才
选本客户端；探测结果按 base_url 缓存，进程内只探一次；探测异常一律按
兼容处理（保持既有错误语义，不因探测抖动改变行为）。
"""
from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Dict, List

from neurova.core.logger import get_logger
from neurova.llm_client import LLMResponse

logger = get_logger(__name__)

# /v1 探测缓存：base_url(去尾斜杠) -> 是否有兼容端点
_probe_cache: Dict[str, bool] = {}
_probe_lock = threading.Lock()


def ollamaNativeRoot(base_url: str) -> str:
    """兼容 base_url → 原生根（剥掉结尾的 /v1）。

    http://h:11434/v1 → http://h:11434；无 /v1 原样（剥尾斜杠）。
    """
    root = (base_url or "").rstrip("/")
    if root.lower().endswith("/v1"):
        root = root[:-3]
    return root


def _resetOllamaProbeCache() -> None:
    """测试隔离用：清空探测缓存。生产代码不应调用。"""
    with _probe_lock:
        _probe_cache.clear()


def ollamaCompatAvailable(base_url: str, api_key: str = "", timeout: float = 2.0) -> bool:
    """探测 Ollama 的 OpenAI 兼容端点是否可用。

    GET {base_url}/models：200 → 可用；404 → 不可用（走原生）；
    其余状态/异常 → 按可用处理（fail-open，保持既有兼容路径的错误语义）。
    """
    key = (base_url or "").rstrip("/")
    if not key:
        return True
    with _probe_lock:
        cached = _probe_cache.get(key)
    if cached is not None:
        return cached
    available = True
    try:
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.get(f"{key}/models", headers=headers, timeout=timeout)
        if resp.status_code == 404:
            available = False
            logger.info("Ollama 兼容端点探测 404（%s），运行面走原生 /api/chat", key)
    except Exception as e:  # noqa: BLE001 — 探测失败不改变既有兼容行为
        logger.debug("Ollama 兼容端点探测失败（按兼容处理）: %s", e)
        available = True
    with _probe_lock:
        _probe_cache[key] = available
    return available


def _nativeMessages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """OpenAI 形态消息 → Ollama /api/chat 消息（role/content 透传，剔除空键）。"""
    out: List[Dict[str, Any]] = []
    for m in messages or []:
        item: Dict[str, Any] = {"role": m.get("role", "user")}
        content = m.get("content", "")
        if content is not None:
            item["content"] = content
        if m.get("tool_calls"):
            item["tool_calls"] = m["tool_calls"]
        if m.get("tool_call_id"):
            item["tool_call_id"] = m["tool_call_id"]
        out.append(item)
    return out


def _nativeOptions(kwargs: Dict[str, Any], config) -> Dict[str, Any]:
    """采样参数 → Ollama options（temperature / num_predict≈max_tokens / top_p）。"""
    options: Dict[str, Any] = {}
    temperature = kwargs.get("temperature", getattr(config, "temperature", None))
    if temperature is not None:
        options["temperature"] = temperature
    max_tokens = kwargs.get("max_tokens", getattr(config, "max_tokens", None))
    if max_tokens:
        options["num_predict"] = max_tokens
    top_p = kwargs.get("top_p", getattr(config, "top_p", None))
    if top_p is not None:
        options["top_p"] = top_p
    return options


def _normalizeToolCalls(raw: Any) -> Any:
    """Ollama tool_calls（arguments 为对象）→ OpenAI 形态（arguments 为 JSON 串）。"""
    if not raw:
        return None
    out = []
    for call in raw:
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if not isinstance(args, str):
            args = json.dumps(args or {}, ensure_ascii=False)
        out.append({
            "id": call.get("id") or f"call_{uuid.uuid4().hex[:12]}",
            "type": "function",
            "function": {"name": fn.get("name", ""), "arguments": args},
        })
    return out


class OllamaNativeClient:
    """Ollama 原生 /api/chat 客户端（aiohttp；NDJSON 流）。"""

    def __init__(self, config, provider_id: str = "ollama"):
        self.config = config
        self.provider_id = provider_id
        self.logger = logger
        self.root = ollamaNativeRoot(getattr(config, "base_url", ""))

    # ── HTTP 薄层（测试可注入覆盖） ─────────────────────────────

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        api_key = getattr(self.config, "api_key", "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    async def _post_json(self, body: dict) -> dict:
        import aiohttp

        url = f"{self.root}/api/chat"
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers(), json=body) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Ollama API {resp.status}: {text[:300]}")
                return json.loads(text)

    async def _stream_ndjson_lines(self, body: dict):
        import aiohttp

        url = f"{self.root}/api/chat"
        timeout = aiohttp.ClientTimeout(total=600)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._headers(), json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Ollama API {resp.status}: {text[:300]}")
                buffer = b""
                async for raw in resp.content:
                    buffer += raw
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if line:
                            yield line.decode("utf-8", errors="replace")
                tail = buffer.strip()
                if tail:
                    yield tail.decode("utf-8", errors="replace")

    # ── 请求体组装 ───────────────────────────────────────────

    def _body(self, messages, **kwargs) -> dict:
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": _nativeMessages(messages),
            "stream": False,
        }
        options = _nativeOptions(kwargs, self.config)
        if options:
            body["options"] = options
        if kwargs.get("tools"):
            # Ollama /api/chat 原生工具形态（arguments 为对象）
            native_tools = []
            for tool in kwargs["tools"]:
                fn = tool.get("function") or {}
                native_tools.append({
                    "type": "function",
                    "function": {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters") or {},
                    },
                })
            body["tools"] = native_tools
        return body

    # ── LLMClient 兼容接口 ───────────────────────────────────

    async def chat(self, messages, **kwargs):
        body = self._body(messages, **kwargs)
        data = await self._post_json(body)
        message = data.get("message") or {}
        usage = {
            "prompt_tokens": int(data.get("prompt_eval_count") or 0),
            "completion_tokens": int(data.get("eval_count") or 0),
        }
        resp = LLMResponse(
            content=str(message.get("content") or ""),
            model=str(data.get("model") or self.config.model),
            usage=usage,
            finish_reason="stop" if data.get("done") else None,
        )
        tool_calls = _normalizeToolCalls(message.get("tool_calls"))
        if tool_calls:
            resp.tool_calls = tool_calls
            resp.finish_reason = "tool_calls"
        return resp

    async def chat_stream_async(self, messages, **kwargs):
        body = self._body(messages, **kwargs)
        body["stream"] = True
        async for line in self._stream_ndjson_lines(body):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            message = data.get("message") or {}
            usage = {}
            if data.get("done"):
                usage = {
                    "prompt_tokens": int(data.get("prompt_eval_count") or 0),
                    "completion_tokens": int(data.get("eval_count") or 0),
                }
            resp = LLMResponse(
                content=str(message.get("content") or ""),
                model=str(data.get("model") or self.config.model),
                usage=usage,
                finish_reason="stop" if data.get("done") else None,
            )
            tool_calls = _normalizeToolCalls(message.get("tool_calls"))
            if tool_calls:
                resp.tool_calls = tool_calls
                resp.finish_reason = "tool_calls"
            yield resp

    def count_tokens(self, text: str) -> int:
        """估算 token 数（走全仓唯一尺子；Ollama 无本地分词器，按类别上界）。"""
        from neurova.context.token_estimator import estimate_tokens

        return max(1, estimate_tokens(text))

    def count_message_tokens(self, messages, tools=None) -> int:
        """输入 token 总量（同 Anthropic 原生客户端口径：正文+工具目录上界）。"""
        total = 0
        for m in messages or []:
            total += self.count_tokens(str(m.get("content") or ""))
        if tools:
            total += self.count_tokens(json.dumps(tools, ensure_ascii=False))
        return max(1, total)
