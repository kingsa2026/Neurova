"""
LLM Client - 语言模型客户端
支持与 OpenAI 兼容的 API 进行通信，支持流式输出、错误重试、Token 计数等
支持预设配置快速初始化
"""

import asyncio
from neurova.core.logger import get_logger
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

# OpenAI 库导入（可选）
try:
    import openai
    from openai import APIConnectionError, APIError, AsyncOpenAI, AuthenticationError, OpenAI, RateLimitError

    OPENAI_AVAILABLE = True
    ASYNC_OPENAI_AVAILABLE = hasattr(openai, "AsyncOpenAI")
except ImportError:
    OPENAI_AVAILABLE = False
    ASYNC_OPENAI_AVAILABLE = False

    # 定义替代异常类
    class APIConnectionError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    class APIError(Exception):
        pass

    class AuthenticationError(Exception):
        pass

    logging.warning("openai 库未安装，LLM 客户端将使用模拟模式")


class LLMError(RuntimeError):
    """LLM 供应商错误基类（RuntimeError 子类，既有处理器向后兼容）"""


class LLMRateLimitError(LLMError):
    """请求频率过高（可退避重试）"""


class LLMAuthError(LLMError):
    """认证失败（不可重试）"""


class LLMConnectionError(LLMError):
    """连接失败（可重试）"""


class TokenLimitExceeded(LLMError):
    """输入 token 超出预算（不可重试，应优雅终止）"""


@dataclass
class LLMResponse:
    """LLM 响应数据结构"""

    content: str = ""
    role: str = "assistant"
    model: str = ""
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    usage: Dict[str, int] = field(default_factory=dict)
    finish_reason: Optional[str] = None
    response_id: Optional[str] = None


@dataclass
class LLMConfig:
    """LLM 配置"""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4"
    temperature: float = 0.7
    max_tokens: int = 131072
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 120
    max_retries: int = 3
    retry_delay: float = 1.0
    stream: bool = False
    preset_name: str = ""
    # 输入 token 预算闸门（None = 不限制）；请求前按消息+工具定义计数检查
    max_input_tokens: Optional[int] = None


class LLMClient:
    """LLM 客户端

    支持 OpenAI 兼容 API 的完整客户端实现，
    包含错误重试、流式输出、Token 计数等功能。
    """

    def __init__(self, config: LLMConfig, preset: Optional[Dict] = None):
        """
        初始化 LLM 客户端

        Args:
            config: LLM 配置
            preset: 预设配置（可选）
        """
        self.config = config
        self.logger = get_logger(__name__)

        # 应用预设配置
        if preset:
            self._apply_preset(preset)

        # 初始化客户端
        self.client = None
        self.async_client = None
        self._init_client()

        # 统计信息
        self._stats = {
            "total_calls": 0,
            "successful_calls": 0,
            "failed_calls": 0,
            "total_tokens": 0,
            "total_time": 0.0,
        }

    def _apply_preset(self, preset: Dict):
        """应用预设配置"""
        # 预设可能包含 api_key, base_url, model 等
        for key, value in preset.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

    def _init_client(self):
        """初始化 OpenAI 客户端"""
        if not OPENAI_AVAILABLE:
            self.logger.info("使用模拟模式（openai 库不可用）")
            return

        try:
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout,
                max_retries=self.config.max_retries,
            )

            if ASYNC_OPENAI_AVAILABLE:
                self.async_client = AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url,
                    timeout=self.config.timeout,
                    max_retries=self.config.max_retries,
                )

            self.logger.info("LLM 客户端初始化成功: model=%s", self.config.model)
        except Exception as e:
            self.logger.error("LLM 客户端初始化失败: %s", e)
            self.client = None
            self.async_client = None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """
        发送聊天请求

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            **kwargs: 额外参数，会覆盖 config 中的设置

        Returns:
            LLMResponse 响应对象
        """
        self._check_input_budget(messages, tools=kwargs.get("tools"))
        if not self.client:
            # 兜底模拟响应(离线测试/空 key)。静默假回复会污染生产对话,必须显式告警
            self.logger.warning(
                "LLMClient 未初始化(缺 key/配置失败),返回模拟响应: base_url=%s model=%s",
                getattr(self.config, "base_url", "?"),
                getattr(self.config, "model", "?"),
            )
            return self._mock_response(messages)

        start_time = time.time()

        try:
            # 构建请求参数
            from neurova.llm.model_limits import clamp_max_tokens
            params = {
                "model": self.config.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": clamp_max_tokens(
                    kwargs.get("max_tokens", self.config.max_tokens),
                    self.config.model,
                ),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "frequency_penalty": kwargs.get("frequency_penalty", self.config.frequency_penalty),
                "presence_penalty": kwargs.get("presence_penalty", self.config.presence_penalty),
            }

            # 如果有 tools 参数
            if "tools" in kwargs:
                params["tools"] = kwargs["tools"]

            # 调用 API
            response = self.client.chat.completions.create(**params)

            # 解析响应
            choice = response.choices[0]
            content = choice.message.content or ""

            # 提取 usage
            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            # 提取 tool_calls
            tool_calls = None
            if choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                    )

            # 更新统计
            self._stats["total_calls"] += 1
            self._stats["successful_calls"] += 1
            self._stats["total_tokens"] += usage.get("total_tokens", 0)
            self._stats["total_time"] += time.time() - start_time

            return LLMResponse(
                content=content,
                role="assistant",
                model=response.model,
                reasoning_content=getattr(choice.message, "reasoning_content", None),
                tool_calls=tool_calls,
                usage=usage,
                finish_reason=choice.finish_reason,
                response_id=response.id,
            )

        except Exception as e:
            self._stats["total_calls"] += 1
            self._stats["failed_calls"] += 1
            self._stats["total_time"] += time.time() - start_time

            self.logger.error("LLM 调用失败: %s", e)

            # 分类异常包装：限流/认证/连接/token 各自成类，供上层区分处理
            raise LLMClient._wrap_llm_error(e) from e

    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[LLMResponse]:
        """
        流式聊天请求

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Yields:
            LLMResponse 响应对象（每个 chunk）
        """
        self._check_input_budget(messages, tools=kwargs.get("tools"))
        if not self.client:
            yield from self._mock_stream_response(messages)
            return

        start_time = time.time()

        try:
            # 构建请求参数
            from neurova.llm.model_limits import clamp_max_tokens
            params = {
                "model": self.config.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": clamp_max_tokens(
                    kwargs.get("max_tokens", self.config.max_tokens),
                    self.config.model,
                ),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "frequency_penalty": kwargs.get("frequency_penalty", self.config.frequency_penalty),
                "presence_penalty": kwargs.get("presence_penalty", self.config.presence_penalty),
                "stream": True,
            }

            # 如果有 tools 参数
            if "tools" in kwargs:
                params["tools"] = kwargs["tools"]

            # 调用流式 API
            stream = self.client.chat.completions.create(**params)

            # 处理流式响应
            for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                content = choice.delta.content or ""

                # 提取 usage（可能在最后一个 chunk）
                usage = {}
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                # 提取 tool_calls
                tool_calls = None
                if choice.delta.tool_calls:
                    tool_calls = []
                    for tc in choice.delta.tool_calls:
                        if tc.function:
                            tool_calls.append(
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    # 流式 tool_calls 按 index 分片（首片带 id/name，
                                    # 后续片段仅 arguments 碎片）；透传 index 供上层合并
                                    "index": getattr(tc, "index", None),
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                            )

                # 更新统计
                self._stats["total_tokens"] += usage.get("total_tokens", 0)

                yield LLMResponse(
                    content=content,
                    role="assistant",
                    model=chunk.model,
                    reasoning_content=getattr(choice.delta, "reasoning_content", None),
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=choice.finish_reason,
                    response_id=chunk.id,
                )

            # 更新统计
            self._stats["total_calls"] += 1
            self._stats["successful_calls"] += 1
            self._stats["total_time"] += time.time() - start_time

        except Exception as e:
            self._stats["total_calls"] += 1
            self._stats["failed_calls"] += 1
            self._stats["total_time"] += time.time() - start_time

            self.logger.error("LLM 流式调用失败: %s", e)

            # 分类异常包装：限流/认证/连接/token 各自成类，供上层区分处理
            raise LLMClient._wrap_llm_error(e) from e

    async def chat_stream_async(self, messages: List[Dict[str, str]], **kwargs) -> AsyncIterator[LLMResponse]:
        """
        异步流式聊天请求

        Args:
            messages: 消息列表
            **kwargs: 额外参数

        Yields:
            LLMResponse 响应对象（每个 chunk）
        """
        self._check_input_budget(messages, tools=kwargs.get("tools"))
        if not self.async_client:
            # 回退到同步流式
            for response in self._mock_stream_response(messages):
                yield response
            return

        start_time = time.time()

        try:
            # 构建请求参数
            from neurova.llm.model_limits import clamp_max_tokens
            params = {
                "model": self.config.model,
                "messages": messages,
                "temperature": kwargs.get("temperature", self.config.temperature),
                "max_tokens": clamp_max_tokens(
                    kwargs.get("max_tokens", self.config.max_tokens),
                    self.config.model,
                ),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "frequency_penalty": kwargs.get("frequency_penalty", self.config.frequency_penalty),
                "presence_penalty": kwargs.get("presence_penalty", self.config.presence_penalty),
                "stream": True,
            }

            # 如果有 tools 参数
            if "tools" in kwargs:
                params["tools"] = kwargs["tools"]

            # 调用流式 API
            # P1 修复: 原实现误用同步 self.client，返回的同步 Stream 无法 `async for`，
            # 导致每次异步流式调用都 TypeError；必须用 async_client 并 await。
            stream = await self.async_client.chat.completions.create(**params)

            # 处理流式响应
            async for chunk in stream:
                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                content = choice.delta.content or ""

                # 提取 usage（可能在最后一个 chunk）
                usage = {}
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }

                # 提取 tool_calls
                tool_calls = None
                if choice.delta.tool_calls:
                    tool_calls = []
                    for tc in choice.delta.tool_calls:
                        if tc.function:
                            tool_calls.append(
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    # 流式 tool_calls 按 index 分片（首片带 id/name，
                                    # 后续片段仅 arguments 碎片）；透传 index 供上层合并
                                    "index": getattr(tc, "index", None),
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                            )

                # 更新统计
                self._stats["total_tokens"] += usage.get("total_tokens", 0)

                yield LLMResponse(
                    content=content,
                    role="assistant",
                    model=chunk.model,
                    reasoning_content=getattr(choice.delta, "reasoning_content", None),
                    tool_calls=tool_calls,
                    usage=usage,
                    finish_reason=choice.finish_reason,
                    response_id=chunk.id,
                )

            # 更新统计
            self._stats["total_calls"] += 1
            self._stats["successful_calls"] += 1
            self._stats["total_time"] += time.time() - start_time

        except Exception as e:
            self._stats["total_calls"] += 1
            self._stats["failed_calls"] += 1
            self._stats["total_time"] += time.time() - start_time

            self.logger.error("异步 LLM 流式调用失败: %s", e)

            # 分类异常包装：限流/认证/连接/token 各自成类，供上层区分处理
            raise LLMClient._wrap_llm_error(e) from e

    def _call_api(self, config: Optional[LLMConfig] = None) -> LLMResponse:
        """
        使用指定配置调用 API（内部方法）

        Args:
            config: LLM 配置（可选，默认使用 self.config）

        Returns:
            LLMResponse 响应对象
        """
        # 这个方法用于内部调用，如模型测试
        if config is None:
            config = self.config

        if not self.client:
            return LLMResponse(content="模拟响应", model=config.model)

        try:
            # 简单的测试调用
            response = self.client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10,
            )

            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    "total_tokens": response.usage.total_tokens if response.usage else 0,
                },
            )
        except Exception as e:
            self.logger.error("API 测试调用失败: %s", e)
            return LLMResponse(content=f"API 测试失败: {e}", model=config.model)

    def _mock_response(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """模拟响应（当 OpenAI 不可用时）"""
        # 构建简单的模拟响应
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        return LLMResponse(
            content=f"[模拟响应] 收到您的消息：{user_content[:100]}...",
            role="assistant",
            model="mock-model",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

    def _mock_stream_response(self, messages: List[Dict[str, str]]) -> Iterator[LLMResponse]:
        """模拟流式响应（当 OpenAI 不可用时）"""
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        # 分块返回
        response_text = f"[模拟响应] 收到您的消息：{user_content[:100]}..."
        chunk_size = 10
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i : i + chunk_size]
            yield LLMResponse(
                content=chunk,
                role="assistant",
                model="mock-model",
            )
            time.sleep(0.05)  # 模拟延迟

        # 最后一个 chunk 包含 usage
        yield LLMResponse(
            content="",
            role="assistant",
            model="mock-model",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            finish_reason="stop",
        )

    async def _mock_stream_response_async(self, messages: List[Dict[str, str]]) -> AsyncIterator[LLMResponse]:
        """异步模拟流式响应（当 OpenAI 不可用时）"""
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        # 分块返回
        response_text = f"[模拟响应] 收到您的消息：{user_content[:100]}..."
        chunk_size = 10
        for i in range(0, len(response_text), chunk_size):
            chunk = response_text[i : i + chunk_size]
            yield LLMResponse(
                content=chunk,
                role="assistant",
                model="mock-model",
            )
            await asyncio.sleep(0.05)  # 模拟延迟

        # 最后一个 chunk 包含 usage
        yield LLMResponse(
            content="",
            role="assistant",
            model="mock-model",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            finish_reason="stop",
        )

    _tokenizer = None  # tiktoken 编码器（进程级惰性共享）

    @classmethod
    def _get_tokenizer(cls):
        """tiktoken 编码器；下载/导入失败时返回 None（回退估算）"""
        if cls._tokenizer is not None:
            return cls._tokenizer
        try:
            import tiktoken

            cls._tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:  # noqa: BLE001 - 离线环境编码表下载失败
            logging.getLogger(__name__).debug("tiktoken 编码器不可用，回退估算: %s", e)
            return None
        return cls._tokenizer

    @staticmethod
    def _wrap_llm_error(e: Exception) -> Exception:
        """把 openai 异常分类为 LLMError 子类（限流/认证/连接），不丢失原语义"""
        if isinstance(e, TokenLimitExceeded):
            return e
        if isinstance(e, (APIConnectionError,)):
            return LLMConnectionError(f"连接失败: {e}")
        if isinstance(e, (RateLimitError,)):
            return LLMRateLimitError(f"请求频率过高: {e}")
        if isinstance(e, (AuthenticationError,)):
            return LLMAuthError(f"认证失败: {e}")
        if isinstance(e, (APIError,)):
            return RuntimeError(f"API 错误: {e}")
        return e

    def count_tokens(self, text: str) -> int:
        """
        统计文本 token 数量

        tiktoken 精确计数（cl100k_base），编码器不可用时回退到按字符估算。

        Args:
            text: 输入文本

        Returns:
            token 数量
        """
        if not text:
            return 0

        tokenizer = self._get_tokenizer()
        if tokenizer is not None:
            try:
                return len(tokenizer.encode(text))
            except Exception:  # noqa: BLE001 - 单条编码失败回退估算
                pass
        # 回退估算：每个字符约 1.5 tokens
        return int(len(text) * 1.5)

    # 每条消息的固定结构开销（role/name 等字段，OpenAI 经验值近似）
    _PER_MESSAGE_OVERHEAD = 4

    def count_message_tokens(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> int:
        """
        统计消息列表（可选含工具定义）的输入 token 总量

        Args:
            messages: OpenAI 格式消息列表
            tools: 工具 schema 列表（工具定义同样占用上下文预算）

        Returns:
            token 总量
        """
        total = 0
        for msg in messages or []:
            total += self._PER_MESSAGE_OVERHEAD
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                # 多模态 content：文本片段计数，图片片段按固定近似值
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total += self.count_tokens(str(part.get("text", "")))
                    elif isinstance(part, dict) and part.get("type") == "image_url":
                        total += 800  # 低分辨率图片近似
            for tc in (msg.get("tool_calls") or []) if isinstance(msg, dict) else []:
                fn = tc.get("function", {}) if isinstance(tc, dict) else {}
                total += self.count_tokens(str(fn.get("arguments", ""))) + self.count_tokens(str(fn.get("name", "")))
        for tool in tools or []:
            total += self.count_tokens(str(tool))
        return total

    def _get_effective_input_budget(self) -> Optional[int]:
        """
        推导生效的输入 token 预算。

        优先级：
        1. 显式配置 max_input_tokens（最高）
        2. 模型上下文窗口 - 输出预留（max_tokens 经 clamp 后）
        3. 未知模型 → None（不设闸门，fail-open）

        Returns:
            输入预算 token 数，或 None 表示不限
        """
        from neurova.llm.model_limits import get_model_context_window, clamp_max_tokens

        if self.config.max_input_tokens:
            return self.config.max_input_tokens
        context_window = get_model_context_window(self.config.model or "")
        if not context_window:
            return None
        output_reserve = clamp_max_tokens(self.config.max_tokens, self.config.model)
        # 输入预算 = 窗口 - 输出预留，最低保留 4096 输入空间防止预算归零
        return max(context_window - output_reserve, 4096)

    def _check_input_budget(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict]] = None) -> None:
        """输入 token 预算闸门：超限抛 TokenLimitExceeded（调用 API 之前）"""
        max_input = self._get_effective_input_budget()
        if not max_input:
            return
        input_tokens = self.count_message_tokens(messages, tools)
        if input_tokens > max_input:
            raise TokenLimitExceeded(
                f"输入 token 超出预算（估算 {input_tokens} > 上限 {max_input}，"
                f"模型 {self.config.model}），请压缩上下文或调大 max_input_tokens 配置"
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()

    def update_config(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)

        # 如果更新了 api_key 或 base_url，需要重新初始化客户端
        if "api_key" in kwargs or "base_url" in kwargs:
            self._init_client()

    def switch_preset(self, preset_name: str):
        """切换预设配置"""
        # 这个方法需要预设注册表
        # 暂时只更新 preset_name
        self.config.preset_name = preset_name
        self.logger.info("切换到预设: %s", preset_name)

    def list_available_presets(self, category: Optional[str] = None) -> List[Dict]:
        """
        列出可用的预设配置

        Args:
            category: 预设类别（可选）

        Returns:
            预设列表
        """
        # 这个方法需要预设注册表
        # 暂时返回空列表
        return []
