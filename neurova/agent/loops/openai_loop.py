"""
OpenAI Loop - OpenAI 兼容模型适配循环

支持: GPT-4, GPT-3.5-turbo, GPT-4V, 以及所有 OpenAI 兼容 API
"""

import re

from neurova.core.logger import get_logger
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Agent 仅用于类型注解；运行时导入会与 agent_core 形成循环依赖
if TYPE_CHECKING:
    from neurova.agent_core import Agent

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
        # 停滞检测闭环（对标 OpenManus is_stuck/handle_stuck_state）：
        # 记录每轮 assistant 回复与工具调用签名，重复时注入"换策略"提示，
        # 连续停滞则终止工具循环（激活 agent_loop_detection 死代码的消费方）
        self._round_replies: List[str] = []
        self._last_round_calls: List[tuple] = []
        self._stagnation_count = 0
        logger.info("OpenAILoop initialized for agent: %s", agent.config.name)

    def _assess_stagnation(
        self, round_reply: str, current_calls: List[tuple], previous_calls: List[tuple]
    ) -> bool:
        """判定本轮是否停滞：内容与上一轮高度相似，或工具调用签名完全重复。

        空回复（纯工具轮）不参与内容停滞判定，避免误伤只调工具不说话的正常轮次。
        """
        try:
            from neurova.agent_loop_detection import calculate_similarity
        except ImportError:  # pragma: no cover - 模块缺失时退化为仅签名判定
            calculate_similarity = None

        previous_replies = [r for r in self._round_replies[:-1] if r]
        if round_reply and previous_replies:
            if calculate_similarity is not None:
                for prev in previous_replies[-2:]:
                    if calculate_similarity(round_reply, prev) >= 0.8:
                        return True
            elif round_reply in previous_replies:
                return True
        if current_calls and current_calls == previous_calls:
            return True
        return False

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
        self._round_replies = []  # 停滞检测：每轮 assistant 回复
        self._last_round_calls = []  # 停滞检测：上一轮工具调用签名
        self._stagnation_count = 0
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
        """流式预测入口（P1-1① 溢出恢复包装）。

        请求打开即上下文溢出（TokenLimitExceeded，且尚无内容产出）→ 折叠
        消息后单次重试（对标 QP scroll 恢复语义）；重试仍溢出原样抛出，
        不做第二次重试（防循环）。流中途溢出（已有内容）原样抛——重试会
        造成内容重复。
        """
        from neurova.context.recovery import (
            compact_messages_for_overflow,
            is_context_overflow_error,
        )

        first_error: Optional[BaseException] = None
        got_content = False
        try:
            async for event in self._predict_stream_once(request_params):
                if isinstance(event, dict) and event.get("type") == "content":
                    got_content = True
                yield event
            return
        except BaseException as e:  # noqa: BLE001 - 统一捕获后按类型分流
            first_error = e

        # 流中途已产出内容 → 重试会造成内容重复，原样抛
        if got_content or not is_context_overflow_error(first_error):
            raise first_error

        messages = request_params.get("messages") or []
        compact, info = compact_messages_for_overflow(messages)
        if info.get("folded_count", 0) <= 0:
            raise first_error  # 无可折叠内容，恢复无意义
        logger.warning(
            "[CTX_RECOVERY] 上下文溢出，折叠 %d 条消息后单次重试（%d → %d）",
            info["folded_count"], info["original_count"], info["compact_count"],
        )
        # 增强①：被折叠消息生成摘要回写池（fire-and-forget，不阻塞重试；
        # 无池/无摘要器 no-op——rollup 内部自兜底）
        try:
            pool = getattr(
                getattr(self.agent, "context_orchestrator", None), "context_pool", None
            )
            if pool is not None:
                asyncio.ensure_future(
                    pool.rollup_overflow_digest(info.get("folded_messages") or [])
                )
        except Exception:
            logger.debug("溢出摘要回写跳过", exc_info=True)
        retry_params = {**request_params, "messages": compact}
        async for event in self._predict_stream_once(retry_params):
            yield event

    async def _predict_stream_once(self, request_params: Dict) -> Any:
        """流式预测 — 实时 yield 结构化事件（content / reasoning / tool_call / tool_result / done）。

        底层 chat_stream 逐 chunk 产出 LLMResponse 对象（见 llm_client.chat_stream_async），
        失败时被 multi_model_client.chat_stream 包装为 {"error": ...} 字典。本方法负责：
        1. 把 chunk 实时转成 typed 事件（reasoning/content 逐片段转发，思考过程不再整块滞后）；
        2. 流式 tool_calls 分片按 index 合并为完整调用（OpenAI 兼容流中首片带 id/name，
           后续片段仅携带 arguments 碎片），流结束后执行并产出 tool_result 事件；
        3. 工具执行后以流式续写（递归本方法），直到模型不再调用工具；
        4. 整个生成器恰好 yield 一个 done 事件（携带最终轮正文快照）；
        5. error 字典抛 RuntimeError 交由管线降级，而不是静默返回空回复。
        """
        reply_parts: List[str] = []
        reasoning_parts: List[str] = []
        pending_tool_calls: List[Dict] = []
        finish_reason = ""
        # P2-4d：流式 usage 聚合（OpenAI 流式 usage 在最后一 chunk 携带全量）
        round_usage = None

        stream_kwargs = {k: v for k, v in request_params.items() if k not in ("messages", "stream")}
        async for chunk in self.llm_client.chat_stream(request_params["messages"], **stream_kwargs):
            if isinstance(chunk, dict):
                if chunk.get("error"):
                    raise self._raise_for_error_dict(chunk)
                continue
            content = getattr(chunk, "content", "") or ""
            if content:
                reply_parts.append(content)
                yield {"type": "content", "data": content}
            if getattr(chunk, "usage", None):
                u = chunk.usage
                round_usage = {
                    "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(u, "total_tokens", 0) or 0,
                }
            rtext = getattr(chunk, "reasoning_content", None)
            if rtext:
                reasoning_parts.append(rtext)
                yield {"type": "reasoning", "data": rtext}
            for tc_delta in getattr(chunk, "tool_calls", None) or []:
                self._merge_tool_call_delta(pending_tool_calls, tc_delta)
            if getattr(chunk, "finish_reason", None):
                finish_reason = chunk.finish_reason

        # 保存思考过程到 agent（供 post-chat 持久化/前端展示）
        if reasoning_parts and hasattr(self.agent, "_current_reasoning"):
            self.agent._current_reasoning = "".join(reasoning_parts)
            logger.info("🧠 捕获流式思考过程: %s 字符", len(self.agent._current_reasoning))

        if pending_tool_calls:
            self._tool_rounds += 1
            logger.info(
                "LLM returned %s tool calls (stream round %s)",
                len(pending_tool_calls), self._tool_rounds,
            )
            for tc in pending_tool_calls:
                yield {"type": "tool_call", "data": tc}

            tool_messages = await self.handle_tool_calls(pending_tool_calls, request_params["messages"])
            for tm in tool_messages:
                yield {"type": "tool_result", "data": tm}

            # 停滞检测：记录本轮回复与调用签名，重复时注入提示，连续停滞终止
            round_reply = "".join(reply_parts).strip()
            current_calls = [
                ((tc.get("function") or {}).get("name", ""), (tc.get("function") or {}).get("arguments", ""))
                for tc in pending_tool_calls
            ]
            stagnant = self._assess_stagnation(round_reply, current_calls, self._last_round_calls)
            self._round_replies.append(round_reply)
            self._last_round_calls = current_calls

            if stagnant:
                self._stagnation_count += 1
                if self._stagnation_count >= 2:
                    logger.warning(
                        "连续 %s 轮停滞（重复响应/调用），终止工具循环", self._stagnation_count
                    )
                    yield {
                        "type": "reasoning",
                        "data": "检测到连续重复的响应，已停止工具循环，避免无效重试。",
                    }
                    return
            else:
                self._stagnation_count = 0

            if self._tool_rounds <= 10:
                # 工具结果入历史后流式续写（递归），保持后续轮次同样逐 token 转发
                request_params["messages"].extend(tool_messages)
                if stagnant:
                    stagnation_prompt = (
                        "检测到重复的响应内容。请更换策略，避免重复已经尝试过的无效路径。"
                    )
                    request_params["messages"].append({"role": "user", "content": stagnation_prompt})
                async for event in self._predict_stream(request_params):
                    yield event
                return
            logger.warning("工具调用轮次超过上限 (%s)，停止递归", self._tool_rounds)

        yield {
            "type": "done",
            "reply": "".join(reply_parts),
            "finish_reason": finish_reason,
            "usage": round_usage,
        }

    @staticmethod
    def _raise_for_error_dict(chunk: Dict) -> Exception:
        """把流式错误 dict 转成分类异常（error_type 优先，缺省保持 RuntimeError 语义）。"""
        from neurova.llm_client import (
            LLMConnectionError,
            LLMAuthError,
            LLMRateLimitError,
            TokenLimitExceeded,
        )

        message = f"LLM 流式调用失败: {chunk.get('error')}"
        error_type = str(chunk.get("error_type") or "")
        mapping = {
            "rate_limit": LLMRateLimitError,
            "token_limit": TokenLimitExceeded,
            "auth": LLMAuthError,
            "connection": LLMConnectionError,
        }
        cls = mapping.get(error_type)
        if cls is not None:
            return cls(message)
        return RuntimeError(message)

    @staticmethod
    def _merge_tool_call_delta(pending: List[Dict], delta: Dict) -> None:
        """按 index 合并流式 tool_calls 分片。

        OpenAI 兼容流式响应中，一次工具调用被拆到多个 chunk：首片携带 id/name，
        后续片段 id/name 为 None、仅递增 arguments 文本。chat_stream_async 透传
        delta 的 index 字段，据此定位合并位置；无 index 时退化为追加新条目。
        """
        fn = delta.get("function") or {}
        index = delta.get("index")
        if index is None or index >= len(pending):
            pending.append(
                {
                    "id": delta.get("id"),
                    "type": delta.get("type") or "function",
                    "function": {
                        "name": fn.get("name") or "",
                        "arguments": fn.get("arguments") or "",
                    },
                }
            )
            return
        entry = pending[index]
        if delta.get("id"):
            entry["id"] = delta["id"]
        if fn.get("name"):
            entry["function"]["name"] = (entry["function"].get("name") or "") + fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] = (entry["function"].get("arguments") or "") + fn["arguments"]

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
