"""
OpenAI Loop - OpenAI 兼容模型适配循环

支持: GPT-4, GPT-3.5-turbo, GPT-4V, 以及所有 OpenAI 兼容 API
"""

import re

from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from neurova.agent.loops.base import BaseAgentLoop
from neurova.agent.loops.registry import register_loop
from neurova.llm_client import LLMResponse

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# 工具降级判定（模块级，供测试与类方法共用）TOOLROBUST-B
# ══════════════════════════════════════════════════════════════
_AUTH_KEYS = re.compile(
    r"(invalid api key|authentication|unauthorized|forbidden|access denied|401|403|permission|credential)",
    re.IGNORECASE,
)
_HTTP_4XX_KEYS = re.compile(r"\b(400|422|409)\b")
_TOOL_KEYS = re.compile(r"(tool|function call|tool_choice|schema|parameter|argument)", re.IGNORECASE)
_SCHEMA_ERR_KEYS = re.compile(
    r"(missing|invalid).*(parameter|schema|argument|type)|parameters\.type", re.IGNORECASE
)


def _looks_like_unsupported_tools_error(err_str: str) -> bool:
    """判断错误文本是否属于"function calling 不被 API 支持"，避免误伤认证等非工具错误。

    返回 True 当且仅当：
    1. 错误文本不包含认证/权限关键词（401/403/"Invalid API key"等）；
    2. 命中 tools/function/schema/parameter 语义；
    3. 且同时命中 HTTP 4xx 状态码 或 明确 schema/参数缺失语义（如 "Missing required parameter"），
       以排除 "4000"/"400ms" 等无关数字误伤。
    """
    if not err_str:
        return False
    if _AUTH_KEYS.search(err_str):
        return False
    if not _TOOL_KEYS.search(err_str):
        return False
    return bool(_HTTP_4XX_KEYS.search(err_str) or _SCHEMA_ERR_KEYS.search(err_str))


class OpenAILoop(BaseAgentLoop):
    """
    OpenAI 模型 Loop

    处理 OpenAI 兼容 API 的调用流程，
    支持工具调用 (tool_calls) 和流式输出。
    """

    def __init__(self, agent: "Agent"):
        super().__init__(agent)
        self._tool_rounds = 0  # 递归深度计数
        self._tools_supported = True  # 初始假设支持，400 后设为 False
        logger.info("OpenAILoop initialized for agent: %s", agent.config.name)

    # ══════════════════════════════════════════════════════════════
    # 工具降级健壮性（TOOLROBUST-B）
    # ══════════════════════════════════════════════════════════════
    def _is_tools_rejected_error(self, err_str: str) -> bool:
        """精确判断是否为"function calling 不被 API 支持"的错误，避免误伤认证等非工具错误。

        委托给模块级 _looks_like_unsupported_tools_error 以复用同一判定逻辑。
        返回 True 当且仅当：非认证/权限错误，且命中工具语义 + HTTP 4xx 或 schema 参数缺失语义。
        """
        return _looks_like_unsupported_tools_error(err_str)

    def _append_tool_hint(self, messages: List[Dict]) -> List[Dict]:
        """降级后把文本调用教学合并进 system 提示（不新增消息体，保持 system 靠前）。

        复用 context.orchestrator.get_tool_call_format_hint()；任何异常都静默跳过，
        避免降级路径再次因导入/内容问题抛异常。
        """
        try:
            from neurova.context.orchestrator import get_tool_call_format_hint

            hint = get_tool_call_format_hint()
        except Exception:
            hint = ""
        if not hint:
            return messages
        msgs = list(messages)
        for i, m in enumerate(msgs):
            if isinstance(m, dict) and m.get("role") == "system":
                msgs[i] = {**m, "content": (m.get("content") or "") + hint}
                return msgs
        msgs.insert(0, {"role": "system", "content": hint})
        return msgs

    async def predict_step(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None, stream: bool = False, **kwargs
    ) -> Any:
        """
        执行一步预测

        参数:
            messages: 对话历史
            tools: 可用工具列表 (OpenAI Schema 格式)
            stream: 是否流式输出
            **kwargs: 额外参数

        返回:
            LLMResponse 对象 (非流式) 或 AsyncGenerator (流式)
        """
        # 准备请求参数
        self._tool_rounds = 0  # 重置计数器
        # Bug B-10 修复:每次 predict_step 重置 _tools_supported = True。
        # 原实现一次性 400 后永久设为 False,后续所有 chat 都不注入 tools,
        # 工具调用静默失效,需重启 agent 才恢复。
        # 现改为 per-request 禁用:本次请求 400 后本次不传 tools,
        # 但不污染下一次 chat 请求(可能是不同模型/不同 schema)。
        self._tools_supported = True
        request_params = {
            "messages": messages,
            "stream": stream,
        }

        # 添加工具（如果 API 不支持则跳过）
        if tools and self._tools_supported:
            # 过滤格式不正确的工具（缺少 function 字段会触发 400 错误）
            valid_tools = [t for t in tools if isinstance(t, dict) and "function" in t]
            if valid_tools:
                request_params["tools"] = valid_tools
                request_params["tool_choice"] = kwargs.get("tool_choice", "auto")
            else:
                logger.warning("所有工具格式不正确，跳过 tools 注入")
        elif tools and not self._tools_supported:
            logger.info(f"跳过 tools 注入：API 不支持 function calling")

        # 添加其他参数
        for key in ["temperature", "max_tokens", "top_p", "frequency_penalty"]:
            if hasattr(self.agent.llm_client.config, key):
                value = getattr(self.agent.llm_client.config, key)
                if value is not None:
                    request_params[key] = value

        # 执行预测（如果 tools 导致 API 400，回退到无 tools 模式）
        try:
            if stream:
                return self._predict_stream(request_params)
            else:
                return await self._predict_normal(request_params)
        except Exception as e:
            err_str = str(e)
            # [TOOLROBUST-B] 精确判定 400：
            # 原实现用宽泛子串 "400"/"Invalid"/"Missing" 判断，会把 "Invalid API key"
            # 等认证错误误判为"工具不被支持"而静默降级，掩盖真实错误、另本轮无工具可用。
            # 现在：先排除认证/权限类错误，再要求同时命中 HTTP 4xx 状态码 + tools 语义才算降级。
            if tools and self._is_tools_rejected_error(err_str):
                logger.warning(
                    "[TOOLROBUST-B] function calling 疑似不被 API 支持，本轮降级为无 tools 重试并注入文本教学。错误: %s",
                    e,
                )
                self._tools_supported = False
                # 标记降级事件，供可观测（agent.ui / 监控可读）
                try:
                    if not hasattr(self.agent, "_tool_events"):
                        self.agent._tool_events = []
                    self.agent._tool_events.append({"type": "tools_degraded", "reason": err_str[:200]})
                except Exception:
                    pass
                request_params.pop("tools", None)
                request_params.pop("tool_choice", None)
                # 降级后注入文本调用教学，避免模型在无 tools 状态下完全不会调工具
                request_params["messages"] = self._append_tool_hint(request_params["messages"])
                if stream:
                    return self._predict_stream(request_params)
                else:
                    return await self._predict_normal(request_params)
            raise

    async def _predict_normal(self, request_params: Dict) -> LLMResponse:
        """普通预测 (非流式)。

        [TOOLROBUST-B] 自动降级：带 tools 的请求若被 API 拒绝（工具型 400），
        去掉 tools 并注入文本调用教学后重试一次，避免整轮崩溃且弱 provider 仍有工具通道。
        """
        try:
            response = await self.llm_client.chat(**request_params)
        except Exception as e:
            err_str = str(e)
            if request_params.get("tools") and self._is_tools_rejected_error(err_str):
                logger.warning(
                    "[TOOLROBUST-B] function calling 疑似不被 API 支持，本轮降级为无 tools 重试并注入文本教学。错误: %s",
                    e,
                )
                self._tools_supported = False
                try:
                    if not hasattr(self.agent, "_tool_events"):
                        self.agent._tool_events = []
                    self.agent._tool_events.append({"type": "tools_degraded", "reason": err_str[:200]})
                except Exception:
                    pass
                request_params.pop("tools", None)
                request_params.pop("tool_choice", None)
                # 降级后注入文本调用教学，避免模型在无 tools 状态下完全不会调工具
                request_params["messages"] = self._append_tool_hint(request_params["messages"])
                response = await self.llm_client.chat(**request_params)
            else:
                raise

        # 记录思考过程（用于前端展示）
        reasoning_content = getattr(response, "reasoning_content", None)
        if reasoning_content:
            # 将思考过程存储到 agent 上，供 chat() 方法读取
            if hasattr(self.agent, "_current_reasoning"):
                self.agent._current_reasoning = reasoning_content
            logger.info("🧠 捕获思考过程: %s 字符", len(reasoning_content))

        # 处理 tool_calls（部分 provider 响应无 tool_calls 字段，需容错）
        tool_calls = getattr(response, "tool_calls", None)
        if tool_calls:
            self._tool_rounds += 1
            if self._tool_rounds > 10:
                logger.warning("工具调用轮次超过上限 (%s)，停止递归", self._tool_rounds)
                return response

            logger.info("LLM returned %s tool calls (round %s)", len(tool_calls), self._tool_rounds)

            # 执行工具
            tool_messages = await self.handle_tool_calls(tool_calls, request_params["messages"])

            # 将工具结果添加到消息
            request_params["messages"].extend(tool_messages)

            # 递归调用，直到没有 tool_calls
            return await self._predict_normal(request_params)

        return response

    async def _predict_stream(self, request_params: Dict) -> Any:
        """流式预测 — 实时 yield 结构化事件（content / reasoning / tool_calls / done）"""
        reply_parts = []
        reasoning_parts = []
        pending_tool_calls = None

        # 传递 temperature/max_tokens 等参数到流式调用
        stream_kwargs = {k: v for k, v in request_params.items() if k not in ("messages", "stream")}
        async for event in self.llm_client.chat_stream(request_params["messages"], **stream_kwargs):
            if not isinstance(event, dict):
                reply_parts.append(str(event))
                yield {"type": "content", "data": str(event)}
                continue

            ev_type = event.get("type")
            if ev_type == "content":
                text = event.get("data", "")
                reply_parts.append(text)
                yield {"type": "content", "data": text}
            elif ev_type == "reasoning":
                rtext = event.get("data", "")
                reasoning_parts.append(rtext)
                yield {"type": "reasoning", "data": rtext}
            elif ev_type == "tool_calls":
                pending_tool_calls = event.get("data", [])
                self._tool_rounds += 1
                logger.info(
                    f"🔧 流式捕获 {len(pending_tool_calls)} 个 tool_calls: {[tc['function']['name'] for tc in pending_tool_calls]}"
                )
                for tc in pending_tool_calls:
                    yield {"type": "tool_call", "data": tc}
            elif ev_type == "done":
                finish_reason = event.get("finish_reason", "")
                full_reply = "".join(reply_parts)

                # 保存思考过程到 agent
                if reasoning_parts and hasattr(self.agent, "_current_reasoning"):
                    self.agent._current_reasoning = "".join(reasoning_parts)
                    logger.info("🧠 捕获流式思考过程: %s 字符", len(self.agent._current_reasoning))

                # 如果有待处理的 tool_calls，执行它们
                if pending_tool_calls:
                    # 先 yield 文本部分（如果有）
                    if full_reply.strip():
                        logger.info("📝 工具调用前已有文本: %s 字符", len(full_reply))

                    # 执行工具
                    tool_messages = await self.handle_tool_calls(pending_tool_calls, request_params["messages"])
                    for tm in tool_messages:
                        yield {"type": "tool_result", "data": tm}

                    if self._tool_rounds <= 10:
                        # 将工具结果加入消息，递归调用（非流式）
                        request_params["messages"].extend(tool_messages)
                        logger.info("🔄 工具执行完成，递归继续对话 (round %s)", self._tool_rounds)
                        continuation = await self._predict_normal(request_params)
                        if continuation:
                            cont_content = getattr(continuation, "content", None)
                            if cont_content:
                                yield {"type": "content", "data": cont_content}
                                full_reply = cont_content  # 使用续写结果作为最终回复
                            cont_reasoning = getattr(continuation, "reasoning_content", None)
                            if cont_reasoning:
                                yield {"type": "reasoning", "data": cont_reasoning}
                    else:
                        logger.warning("工具调用轮次超过上限 (%s)，停止递归", self._tool_rounds)

                yield {"type": "done", "reply": full_reply, "finish_reason": finish_reason}

        logger.debug("Stream completed")

    async def handle_tool_calls(self, tool_calls: List, messages: List[Dict]) -> List[Dict]:
        """
        处理工具调用 (重写基类方法，添加更多日志)
        """
        logger.info("Handling %s tool calls", len(tool_calls))
        return await super().handle_tool_calls(tool_calls, messages)


# 注册到全局注册表
try:
    from neurova.agent.loops.registry import register_loop

    @register_loop(
        r"gpt-.*|openai/.*|/v1/.*|glm-.*|kimi-.*|qwen.*|deepseek-.*|doubao-.*|"
        r"zhipu/.*|zai-org/.*|moonshot/.*|yi-.*|internlm-.*|baichuan-.*|"
        r"mistral-.*|llama-.*|mixtral-.*|gemini-.*|text-.*|chatglm-.*|"
        r"minimax-.*|Meta-.*|THUDM/.*|Qwen/.*|Pro/.*|SiliconFlow.*",
        priority=10,
    )
    class RegisteredOpenAILoop(OpenAILoop):
        """注册到全局注册表的 OpenAI Loop (通用兼容)"""


    logger.info("OpenAILoop registered to global registry")
except ImportError:
    logger.warning("Could not register OpenAILoop (registry not available)")
