"""
多模型 LLM 客户端管理器

文件路径: neurova/llm/multi_model_client.py

职责:
1. 管理多个 LLM 客户端实例（按服务商和模型组织）
2. 支持运行时切换当前活跃模型
3. 支持按模型名称自动路由请求
4. 支持负载均衡策略

单例初始化契约 (LLM-2 修复):
- `_initialized` 标志仅在 `_initialize_default_clients()` 成功后置位
- 首次初始化失败时（如 api_key 解密失败、provider 未就绪）:
  * `_initialized` 不被置位 → 下次 `__init__` 会重试
  * 异常被记录到日志后重新抛出（不吞掉错误）
- 正常路径（无异常）时 `_initialized = True`，防止重复初始化
- `reset()` 可手动清除单例和 `_initialized`，强制下次重新初始化
- `chat()` 检测 `_clients` 为空时会自动 `refresh_all_providers()` 自愈

历史修复:
- P0-3 (C6): `__init__` 的 `_initialized` 检查移入 `cls._lock` (RLock) 内，修复 TOCTOU
- LLM-2: `_initialized = True` 从 `_initialize_default_clients()` 之前移到之后，
         修复首次初始化失败后永久跳过重试的 bug
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.llm.provider_manager import (
    LLMProviderManager,
    LoadBalancingStrategy,
    ProviderConfig,
    get_provider_manager,
)
from neurova.llm_client import (
    LLMClient,
    LLMConfig,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponse,
    LLMServiceUnavailableError,
)
from neurova.llm.providers.rate_limiter import (
    CircuitBreaker,
    ExponentialBackoff,
    CircuitBreakerOpen,
    with_retry_and_circuit_breaker,
)

logger = get_logger(__name__)


class ModelClient:
    """单个模型的客户端封装"""

    def __init__(self, client: LLMClient, provider: ProviderConfig, model: str):
        self.client = client
        self.provider = provider
        self.model = model
        self.request_count = 0
        self.error_count = 0
        self.last_used = 0.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.request_count == 0:
            return 1.0
        return (self.request_count - self.error_count) / self.request_count

    def increment_request(self, success: bool) -> None:
        """增加请求计数"""
        self.request_count += 1
        self.last_used = time.time()
        if not success:
            self.error_count += 1


class MultiModelLLMClient:
    """
    多模型 LLM 客户端管理器

    职责:
    1. 管理多个 LLM 客户端实例（按服务商和模型组织）
    2. 支持运行时切换当前活跃模型
    3. 支持按模型名称自动路由请求
    4. 支持负载均衡策略
    """

    _instance = None
    # scope → 实例 隔离注册表(admin 走 _instance 槽,保持存量兼容)
    _instances: Dict[str, "MultiModelLLMClient"] = {}
    # 使用 RLock（可重入锁）：__new__ 持锁后 __init__ 重入调用，Lock 会永久阻塞
    # 修复 P0-3 (C6): 原 threading.Lock() 不可重入，__init__ 内重入会死锁
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        scope = kwargs.get("scope")
        with cls._lock:
            if scope is None:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                return cls._instance
            inst = cls._instances.get(scope)
            if inst is None:
                inst = super().__new__(cls)
                cls._instances[scope] = inst
            return inst

    def __init__(
        self,
        provider_manager: Optional[LLMProviderManager] = None,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST,
        scope: Optional[str] = None,
    ):
        # 修复 P0-3 (C6): __init__ 的 _initialized 检查必须在锁内，
        # 否则两线程可同时通过 hasattr 检查（TOCTOU）
        # 注：__init__ 是实例方法，无 cls 参数，用 type(self) 获取类引用
        with type(self)._lock:
            if hasattr(self, "_initialized") and self._initialized:
                return

            self._scope = scope
            # 无参构造(scope=None)维持旧单例行为;显式 scope 走对应隔离配置
            self._provider_manager = provider_manager or get_provider_manager(
                scope=scope or "admin",
            )
            self._clients: Dict[str, ModelClient] = {}  # key: provider_id/model
            self._current_provider_id: Optional[str] = None
            self._current_model: Optional[str] = None
            self._round_robin_index = 0
            # 404 重连防抖：model -> 上次重连时刻（monotonic）。合理间隔内不重复
            # 触发 provider 重发现，防止模型已下线时形成请求风暴。
            self._last_404_reconnect: Dict[str, float] = {}
            # 使用 RLock：refresh_provider() 持锁后调用 _initialize_provider_clients()
            # 后者也获取 _init_lock，Lock 会死锁；RLock 可重入避免死锁
            self._init_lock = threading.RLock()

            # 初始化默认客户端
            # 修复 LLM-2: _initialized = True 原位于 _initialize_default_clients() 之前 (line 87),
            # 导致首次初始化失败后 _initialized 已为 True，下次 __init__ 直接 return 永久跳过重试。
            # 现仅在 _initialize_default_clients() 成功后置位，失败时不置位以允许下次 __init__ 重试。
            # 不吞掉异常：记录日志后重新抛出（遵循"不抹除报错信息"原则）。
            try:
                self._initialize_default_clients()
                self._initialized = True
            except Exception as e:
                logger.error("Failed to initialize default clients: %s", e)
                raise

    @classmethod
    def reset(cls) -> None:
        """重置单例，允许重新初始化。

        用途：当首次初始化因配置缺失（如 api_key 解密失败、provider 未就绪）
        导致 _clients 为空时，配置修复后调用 reset() 可让下次 get_multi_model_client()
        重新初始化。

        线程安全：在 cls._lock（RLock）保护下清除 _instance 和模块级单例。

        reset 链路穿透：同时调用 reset_provider_manager()，清除 provider_manager 单例。
        否则下次 __init__ → get_provider_manager() 仍返回旧的 _provider_manager
        （已缓存了空 api_key 的 providers），reset 链路在 provider_manager 处断裂。
        """
        with cls._lock:
            # 清除所有 scope 实例的 _initialized 标志（防止已存在的实例阻止重新初始化）
            for inst in list(cls._instances.values()):
                if hasattr(inst, "_initialized"):
                    inst._initialized = False
            cls._instances.clear()
            instance = cls._instance
            if instance is not None and hasattr(instance, "_initialized"):
                instance._initialized = False
            # 清除类级单例
            cls._instance = None
        # 清除模块级单例（在锁外，因为 get_multi_model_client 自己会加锁）
        global _multi_model_client, _multi_model_clients
        _multi_model_client = None
        _multi_model_clients.clear()

        # 清除 provider_manager 单例，确保 reset 链路穿透到 provider_manager 层
        # 延迟导入避免循环依赖（multi_model_client 顶部已 import provider_manager，
        # 但为保持 reset() 自包含与可测试性，这里显式延迟导入）
        try:
            from neurova.llm.provider_manager import reset_provider_manager
            reset_provider_manager()
        except ImportError as e:
            logger.warning("Could not reset provider_manager: %s", e)

    def _initialize_default_clients(self) -> None:
        """初始化默认客户端

        三重门控诊断日志 (修复 antipattern: 原 `if A and B and C:` 失败时无任何分支日志):
        - 三条件各自独立 return, 每个分支打 WARNING 指明具体失败原因
        - 三条件都满足时, 保持原逻辑 (调 _initialize_provider_clients + 设当前模型)
        - 关键诊断点: api_key 为空通常是 pycryptodome 缺失导致解密失败, 必须显式日志
        """
        default_provider = self._provider_manager.get_default_provider()
        if not default_provider:
            logger.warning("Skip init default clients: no default provider configured")
            return
        if not default_provider.enabled:
            logger.warning("Skip init default clients: default provider %s is disabled", default_provider.id)
            return
        if not default_provider.api_key:
            # 默认服务商无 key（常见于 api_key 解密失败/未配置）时，
            # 不应因此阻塞整个多模型客户端，回退到任意 enabled 且有 key 的服务商，
            # 否则 _clients 恒为空 → "[LLM Error] No client available"。
            logger.warning(
                "Default provider %s has empty api_key; falling back to a keyed provider",
                default_provider.id,
            )
            default_provider = self._find_kvable_provider()
            if not default_provider:
                logger.error(
                    "No enabled provider with valid api_key found; LLM unavailable until a key is configured"
                )
                return
            logger.info("Falling back default provider -> %s", default_provider.id)
        self._initialize_provider_clients(default_provider)
        if default_provider.default_model:
            self._current_provider_id = default_provider.id
            self._current_model = default_provider.default_model
            logger.info("Initialized default client: %s/%s", default_provider.id, default_provider.default_model)

    def _find_kvable_provider(self) -> Optional[ProviderConfig]:
        """在所有 enabled provider 中返回第一个具有有效 api_key 的服务商。

        list_providers() 已按 (-priority, name) 排序，因此首个命中即为优先级最高者，
        保证降级选择确定性。用于默认服务商无 key 时的兜底。
        """
        for provider in self._provider_manager.list_providers(enabled_only=True):
            if provider.api_key:
                return provider
        return None

    def _initialize_provider_clients(self, provider: ProviderConfig) -> None:
        """为服务商初始化客户端"""
        with self._init_lock:
            for model in provider.models:
                self._create_model_client(provider, model)
            if provider.default_model and provider.default_model not in provider.models:
                self._create_model_client(provider, provider.default_model)

    def _create_model_client(self, provider: ProviderConfig, model: str) -> Optional[ModelClient]:
        """创建模型客户端"""
        client_key = f"{provider.id}/{model}"
        if client_key in self._clients:
            return self._clients[client_key]

        try:
            if not provider.api_key:
                logger.warning("No API key for provider %s", provider.id)
                return None

            from neurova.llm.model_limits import get_model_max_tokens

            config = LLMConfig(
                api_key=provider.api_key,
                base_url=provider.base_url,
                model=model,
                max_tokens=get_model_max_tokens(model),
            )
            client = LLMClient(config)
            model_client = ModelClient(client=client, provider=provider, model=model)
            self._clients[client_key] = model_client
            return model_client
        except Exception as e:
            logger.error("Failed to create client for %s/%s: %s", provider.id, model, e)
            return None

    def get_client(
        self,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[ModelClient]:
        """获取客户端"""
        if provider_id and model:
            client_key = f"{provider_id}/{model}"
            return self._clients.get(client_key)

        # 按模型名称查找
        if model:
            for client in self._clients.values():
                if client.model == model or client.model.endswith(model):
                    return client

        # 返回当前客户端
        return self.get_current_client()

    def get_current_client(self) -> Optional[ModelClient]:
        """获取当前活跃客户端"""
        if self._current_provider_id and self._current_model:
            client_key = f"{self._current_provider_id}/{self._current_model}"
            client = self._clients.get(client_key)
            if client:
                return client

        # 如果没有当前客户端，返回第一个可用的
        if self._clients:
            return next(iter(self._clients.values()))

        logger.warning("No clients available")
        return None

    def set_active_model(self, provider_id: str, model: str) -> bool:
        """设置活跃模型"""
        client = self.get_client(provider_id, model)
        if not client:
            # 尝试创建客户端
            provider = self._provider_manager.get_provider(provider_id)
            if not provider:
                logger.warning("Provider %s not found", provider_id)
                return False
            client = self._create_model_client(provider, model)
            if not client:
                return False

        self._current_provider_id = provider_id
        self._current_model = model
        logger.info("Active model set to %s/%s", provider_id, model)
        return True

    def switch_to_next_model(self) -> bool:
        """切换到下一个模型"""
        if not self._clients:
            return False

        # 获取所有可用模型
        models = list(self._clients.values())
        if len(models) <= 1:
            return False

        # 查找当前模型的索引
        current_index = -1
        for i, client in enumerate(models):
            if client.provider.id == self._current_provider_id and client.model == self._current_model:
                current_index = i
                break

        # 切换到下一个
        next_index = (current_index + 1) % len(models)
        next_client = models[next_index]

        self._current_provider_id = next_client.provider.id
        self._current_model = next_client.model
        logger.info("Switched to model %s/%s", self._current_provider_id, self._current_model)
        return True

    def list_available_models(self) -> List[Dict[str, Any]]:
        """列出所有可用模型"""
        models = []
        for client in self._clients.values():
            models.append(
                {
                    "provider_id": client.provider.id,
                    "provider_name": client.provider.name,
                    "model": client.model,
                    "is_current": (
                        client.provider.id == self._current_provider_id and client.model == self._current_model
                    ),
                    "request_count": client.request_count,
                    "success_rate": client.success_rate,
                }
            )
        return models

    def refresh_provider(self, provider_id: str) -> bool:
        """刷新服务商客户端"""
        provider = self._provider_manager.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found", provider_id)
            return False

        # 移除旧客户端
        with self._init_lock:
            keys_to_remove = [k for k in self._clients.keys() if k.startswith(f"{provider_id}/")]
            for key in keys_to_remove:
                del self._clients[key]

            # 重新初始化
            if provider.enabled and provider.api_key:
                self._initialize_provider_clients(provider)
                logger.info("Refreshed provider %s", provider_id)
                return True

        return False

    def refresh_all_providers(self) -> None:
        """刷新所有服务商"""
        providers = self._provider_manager.list_providers()
        for provider in providers:
            self.refresh_provider(provider.id)

    # P2-2：retry/熔断装配（评测指出 rate_limiter.py 构件齐备但零装配）
    # per-provider 熔断器缓存：{provider_id: CircuitBreaker}
    _retry_guards: Dict[str, Any] = {}

    # 404 重连防抖间隔（秒）：同一模型两次重发现之间的最小间隔
    _RECONNECT_DEBOUNCE_SECONDS = 300.0

    @staticmethod
    def _classify_error(error: Exception) -> str:
        """按异常文本分类可路由的故障类型（429 限流 / 404 模型失效）。"""
        text = str(error or "")
        lowered = text.lower()
        if "429" in text or "rate limit" in lowered or "too many requests" in lowered:
            return "rate_limit"
        if (
            "404" in text
            or "not found" in lowered
            or "does not exist" in lowered
            or "not exist" in lowered
            or "decommissioned" in lowered
            or "model_not_found" in lowered
        ):
            return "not_found"
        return "unknown"

    def _note_404_reconnect(self, provider_id: Optional[str], model: Optional[str]) -> bool:
        """模型 404（下线/改名）→ 触发 provider 重发现，300s 防抖。

        Returns:
            True = 本次实际触发了重连；False = 防抖窗口内跳过。
        """
        key = f"{provider_id or '?'}/{model or '?'}"
        now = time.monotonic()
        last = self._last_404_reconnect.get(key)
        if last is not None and (now - last) < self._RECONNECT_DEBOUNCE_SECONDS:
            logger.warning(
                "模型 %s 404 处于重连防抖窗口（剩余 %.0fs），跳过重发现",
                key,
                self._RECONNECT_DEBOUNCE_SECONDS - (now - last),
            )
            return False
        self._last_404_reconnect[key] = now
        logger.warning("模型 %s 返回 404（可能下线/改名），触发服务商重发现", key)
        try:
            self._reconnect_provider(provider_id)
        except Exception as e:  # noqa: BLE001 - 重连失败不阻断错误返回
            logger.error("404 重连执行失败（provider=%s）: %s", provider_id, e)
        return True

    def _reconnect_provider(self, provider_id: Optional[str]) -> None:
        """404 后的重新连接：重建 provider 客户端 + 异步重发现上游模型列表。"""
        if provider_id:
            try:
                self.refresh_provider(provider_id)
                logger.info("404 重连：已重建 provider %s 客户端", provider_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("404 重连：重建 provider %s 客户端失败: %s", provider_id, e)
        # 重发现上游模型列表（异步 fire-and-forget；无运行事件循环时跳过）
        if provider_id:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._rediscover_provider_models(provider_id))
            except RuntimeError:
                logger.debug("404 重连：无运行事件循环，跳过上游模型重发现")

    async def _rediscover_provider_models(self, provider_id: str) -> None:
        """上游模型列表重发现：404 常见于模型下线/改名，重新 fetch 以对齐配置。"""
        try:
            fetch = getattr(self._provider_manager, "fetch_provider_models", None)
            if fetch is None:
                return
            models = await fetch(provider_id, merge=False)
            ids = [m.id for m in models]
            logger.info("404 重连：provider %s 上游模型重发现 %s 个", provider_id, len(ids))
            if ids:
                self.refresh_provider(provider_id)
        except Exception as e:  # noqa: BLE001 - 后台任务失败仅记录
            logger.warning("404 重连：provider %s 模型重发现失败: %s", provider_id, e)

    # 可重试集合：限流/连接/超时/服务不可用；认证错误不重试（换 key 才有意义）
    _RETRYABLE = (LLMRateLimitError, LLMConnectionError, LLMServiceUnavailableError, ConnectionError, TimeoutError)

    @staticmethod
    def _get_retry_guard(client) -> tuple:
        """按 provider 取 (RetryConfig, CircuitBreaker)——跨调用共享熔断状态。"""
        pid = getattr(getattr(client, "provider", None), "id", None) or id(client)
        guard = MultiModelLLMClient._retry_guards.get(pid)
        if guard is None:
            guard = (
                __import__("neurova.llm.providers.rate_limiter", fromlist=["RetryConfig"]).RetryConfig(
                    max_attempts=3, initial_delay=0.05, max_delay=1.0,
                    retryable_exceptions=MultiModelLLMClient._RETRYABLE,
                ),
                CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name=f"llm:{pid}"),
            )
            MultiModelLLMClient._retry_guards[pid] = guard
        return guard

    @staticmethod
    async def _chat_with_retry(client, messages: List[Dict[str, str]], **kwargs) -> Any:
        """per-provider retry/circuit 装配的单次底层调用。

        重试集合内的异常（限流/连接/超时）指数退避重试；认证错误与其余异常
        立即上抛（由 chat() 转 error 信封）。同 provider 连续失败触发熔断
        （拒绝请求不触达底层），recovery_timeout 后半开恢复。
        """
        from neurova.llm.providers.rate_limiter import RetryConfig

        rc, cb = MultiModelLLMClient._get_retry_guard(client)

        async def _attempt():
            return await asyncio.to_thread(client.client.chat, messages, **kwargs)

        wrapped = with_retry_and_circuit_breaker(retry_config=rc, circuit_breaker=cb)(_attempt)
        return await wrapped()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送聊天请求

        P2-2：底层调用经 per-provider retry/circuit 装配；
        P2-4：真实 usage 记入 TokenUsageAccounting（对账+成本）。
        """
        # P2 可选项：mock 注入点最前置（provider 解析之前，无 Key 可用）
        if _mock_enabled():
            import time as _time

            _t0 = _time.time()
            resp = _build_mock_response(messages)
            return {
                "success": True,
                "response": resp,
                "duration": _time.time() - _t0,
                "model": resp.model,
                "provider": "mock",
            }

        # auto failover：仅未显式指定 provider 时启用（显式指定尊重用户选择，不静默切换）
        auto_failover = not provider_id
        if auto_failover:
            self._failover_excluded = set()
        # __new__ 最小注入的测试实例可能不带 _clients，防御性读取
        max_attempts = max(1, len(getattr(self, "_clients", {}) or {})) if auto_failover else 1

        client = self._get_client_for_request(model, provider_id)
        last_result: Dict[str, Any] = {"success": False, "error": "No client available"}
        for _attempt in range(max_attempts):
            if not client:
                return last_result
            result = await self._chat_single_attempt(client, messages, **kwargs)
            if result.get("success"):
                return result
            last_result = result
            # 仅 429 退避 / 404 模型失效触发切换；认证/参数错误换模型无意义
            error_kind = self._classify_error(result.get("error") or "")
            if not auto_failover or error_kind not in ("rate_limit", "not_found"):
                return result
            logger.warning(
                "auto 切换：%s/%s 失败（%s），尝试下一可用候选",
                client.provider.id, client.model, error_kind,
            )
            client = self._next_failover_client(client.model)
        return last_result

    async def _chat_single_attempt(
        self,
        client: ModelClient,
        messages: List[Dict[str, str]],
        **kwargs,
    ) -> Dict[str, Any]:
        """单模型一次聊天尝试（原 chat 主体：限流/调用/记账/错误分类）。"""
        # P2-a：每模型限流（QPM+并发+429 暂停），acquire 在 retry 之前
        from neurova.llm.model_rate_limiter import (
            RateLimitExceeded,
            get_shared_limiter,
        )

        limiter = get_shared_limiter()
        model_key = client.model or "unknown"
        try:
            limiter.acquire(model_key, blocking=False)
        except RateLimitExceeded as e:
            client.increment_request(success=False)
            return {"success": False, "error": f"模型限流: {e}", "model": model_key, "provider": client.provider.id}

        try:
            start_time = time.time()
            # P2-2：底层调用经 per-provider retry/circuit 装配
            result = await self._chat_with_retry(client, messages, **kwargs)
            duration = time.time() - start_time

            client.increment_request(success=True)
            limiter.report_success(model_key)
            try:
                # P2-4 补刀：llm prometheus 埋点（此前 record_llm_call 零调用点）
                from neurova.core.metrics import get_metrics

                get_metrics().record_llm_call(client.provider.id, client.model, True, duration)
            except Exception:
                pass
            try:
                from neurova.core.usage_accounting import get_usage_accounting

                # P2-4：真实 token 对账（response.usage 为 OpenAI 返回值）；
                # 网关缺失 usage 时（与流式同源问题：部分兼容网关不回传）
                # 用 tiktoken 估值并标记 estimated，绝不做字符长度裸白造假。
                _usage = getattr(result, "usage", None)
                _prompt, _completion, _estimated = None, None, False
                if _usage:
                    def _uval(key):
                        v = getattr(_usage, key, None)
                        if v is None and isinstance(_usage, dict):
                            v = _usage.get(key)
                        return int(v or 0)

                    _prompt, _completion = _uval("prompt_tokens"), _uval("completion_tokens")
                else:
                    _est_client = getattr(client.client, "count_tokens", None)
                    if _est_client:
                        try:
                            _prompt = client.client.count_message_tokens(messages, tools=kwargs.get("tools"))
                        except Exception:  # noqa: BLE001
                            _prompt = 0
                        _completion = _est_client(getattr(result, "content", "") or "")
                        _estimated = True

                get_usage_accounting().record(
                    model=client.model,
                    provider=client.provider.id,
                    prompt_tokens=_prompt or 0,
                    completion_tokens=_completion or 0,
                    estimated=_estimated,
                )
                # 持久化历史：同一回 true usage 同时落 SQLite（重启不归零）。
                # user_id 取请求级 ContextVar（chat_pipeline.execute 注入），
                # 缺失记 anonymous —— 与内存记账同源不同命，失败静默。
                from neurova.core.identity_context import get_request_user_id
                from neurova.core.usage_history import get_usage_history

                get_usage_history().record(
                    model=client.model,
                    provider=client.provider.id,
                    prompt_tokens=_prompt or 0,
                    completion_tokens=_completion or 0,
                    estimated=_estimated,
                    user_id=get_request_user_id() or "anonymous",
                    duration_ms=int(duration * 1000),
                )
            except Exception:
                pass
            finally:
                limiter.release(model_key)
            return {
                "success": True,
                "response": result,
                "duration": duration,
                "model": client.model,
                "provider": client.provider.id,
            }
        except CircuitBreakerOpen as e:
            client.increment_request(success=False)
            try:
                from neurova.core.metrics import get_metrics

                get_metrics().record_circuit_rejection(client.provider.id)
                get_metrics().record_llm_call(
                    client.provider.id, client.model, False, time.time() - start_time
                )
            except Exception:
                pass
            finally:
                limiter.release(model_key)
            return {
                "success": False,
                "error": f"熔断打开（连续失败暂停请求）: {e}",
                "model": client.model,
                "provider": client.provider.id,
            }
        except Exception as e:
            client.increment_request(success=False)
            # P2-a：429 类错误反馈成该模型全局暂停（防继续撞限流）
            # 2026-09-03：错误分类驱动——429 → 指数退避暂停；404（模型下线/改名）
            # → 300s 防抖的 provider 重发现+重连；其余错误仅记录。
            error_kind = self._classify_error(e)
            if error_kind == "rate_limit":
                limiter.report_429(model_key, pause_seconds=30.0)
            elif error_kind == "not_found":
                self._note_404_reconnect(client.provider.id, client.model)
            try:
                from neurova.core.metrics import get_metrics

                get_metrics().record_llm_call(
                    client.provider.id, client.model, False, time.time() - start_time
                )
            except Exception:
                pass
            finally:
                limiter.release(model_key)
            return {
                "success": False,
                "error": str(e),
                "model": client.model,
                "provider": client.provider.id,
            }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
        **kwargs,
    ):
        """发送流式聊天请求"""
        # P2 可选项：mock 流式（content chunk + done/usage，与真实契约同形）
        if _mock_enabled():
            import time as _time

            _t0 = _time.time()
            resp = _build_mock_response(messages)
            text = resp.content
            step = max(1, len(text) // 4)
            for i in range(0, len(text), step):
                yield {"type": "content", "content": text[i : i + step]}
            yield {
                "type": "done",
                "content": "",
                "usage": {
                    "prompt_tokens": resp.usage.get("prompt_tokens", 0),
                    "completion_tokens": resp.usage.get("completion_tokens", 0),
                    "total_tokens": resp.usage.get("total_tokens", 0),
                    "duration": _time.time() - _t0,
                },
            }
            return

        client = self._get_client_for_request(model, provider_id)
        if not client:
            logger.warning("No client available for stream chat")
            yield {"error": "No client available"}
            return

        try:
            start_time = time.time()
            # P1 修复: chat_stream 是同步生成器，无法 `async for`（TypeError）。
            # 必须调用异步版本 chat_stream_async。
            stream_usage: Dict[str, int] = {}
            reply_text = ""
            first_token_ms = 0  # P1-8（OpenOcta 启发）：首块耗时入账
            async for chunk in client.client.chat_stream_async(messages, **kwargs):
                if first_token_ms == 0:
                    # 首个有效 chunk（含 reasoning/content/usage 任一载荷）
                    first_token_ms = int((time.time() - start_time) * 1000)
                # 根因修复 (2026-09-02): 流式 usage 在最后一个 chunk 携带全量
                # （LLMClient 已请求 stream_options.include_usage）——
                # 取最后一次非空值，逐 chunk 累加会把 token 双计。
                _u = getattr(chunk, "usage", None)
                if _u:
                    stream_usage = {
                        "prompt_tokens": getattr(_u, "prompt_tokens", None) if not isinstance(_u, dict) else _u.get("prompt_tokens"),
                        "completion_tokens": getattr(_u, "completion_tokens", None) if not isinstance(_u, dict) else _u.get("completion_tokens"),
                    }
                    stream_usage = {k: int(v or 0) for k, v in stream_usage.items()}
                reply_text += getattr(chunk, "content", "") or ""
                reply_text += getattr(chunk, "reasoning_content", "") or ""
                yield chunk
            duration = time.time() - start_time  # P2-4 补刀：原为丢弃结果的死语句
            client.increment_request(success=True)
            try:
                from neurova.core.metrics import get_metrics

                get_metrics().record_llm_call(client.provider.id, client.model, True, duration)
            except Exception:
                pass
            # 根因修复 (2026-09-02): 流式调用此前只透传 chunk、从不 record——
            # 无 usage 也记 1 次调用（calls 恒 0 的根因），有 usage 记真实 token。
            # 网关不回传 usage 时（实测 sensetime 流式恒空）用 tiktoken 估值并
            # 显式标记 estimated=True，供对账区分真值/估计值。
            try:
                from neurova.core.usage_accounting import get_usage_accounting

                _prompt = stream_usage.get("prompt_tokens")
                _completion = stream_usage.get("completion_tokens")
                _estimated = False
                if _prompt is None or _completion is None:
                    _est_client = getattr(client.client, "count_tokens", None)
                    if _est_client:
                        try:
                            _prompt = client.client.count_message_tokens(messages, tools=kwargs.get("tools"))
                        except Exception:  # noqa: BLE001 - 估值失败退 0，不阻断主流程
                            _prompt = 0
                        _completion = _est_client(reply_text)
                        _estimated = True
                    else:
                        _prompt = _prompt or 0
                        _completion = _completion or 0
                get_usage_accounting().record(
                    model=client.model or "unknown",
                    provider=client.provider.id,
                    prompt_tokens=_prompt or 0,
                    completion_tokens=_completion or 0,
                    estimated=_estimated,
                )
                # 持久化历史（同 chat 路径）：user_id 取请求级 ContextVar，缺失记 anonymous
                from neurova.core.identity_context import get_request_user_id
                from neurova.core.usage_history import get_usage_history

                get_usage_history().record(
                    model=client.model or "unknown",
                    provider=client.provider.id,
                    prompt_tokens=_prompt or 0,
                    completion_tokens=_completion or 0,
                    estimated=_estimated,
                    user_id=get_request_user_id() or "anonymous",
                    first_token_ms=first_token_ms,
                    duration_ms=int(duration * 1000),
                )
            except Exception:
                logger.debug("流式 usage 入账跳过", exc_info=True)
        except Exception as e:
            client.increment_request(success=False)
            try:
                from neurova.core.metrics import get_metrics

                get_metrics().record_llm_call(
                    client.provider.id, client.model, False, time.time() - start_time
                )
            except Exception:
                pass
            yield {"error": str(e)}

    def _resolve_available_fallback(
        self,
        exclude_models: Optional[set] = None,
    ) -> Optional[ModelClient]:
        """请求的 provider/model 不可用时的兜底客户端。

        目标：只要系统里存在任一个 enabled 且有 api_key 的服务商，就不允许
        返回 "No client available"。分两步：
        1. 已有可用客户端 → 直接返回当前/首个客户端；
        2. _clients 为空（冷启动或初始化失败）→ 触发 refresh_all_providers() 自愈，
           重建所有 enabled + 有 key 的服务商客户端后再取。

        ``exclude_models``：auto 失败切换时排除已失败模型（同能力下一候选）。

        根因背景：默认服务商（如 sensetime，优先级最高）可能没有 api_key，
        而其他有效服务商（如 b.ai）反而有 key；若严格按请求的 provider/model
        查找将永远拿不到客户端，导致 "[LLM Error] No client available"。
        """
        current = self.get_current_client()
        if current and (not exclude_models or current.model not in exclude_models):
            return current
        if exclude_models:
            # 失败切换：从全部客户端中选第一个不在排除集的（保持注册序）
            for client in self._clients.values():
                if client.model not in exclude_models:
                    return client
        logger.info("Auto-refreshing providers due to empty _clients")
        try:
            self.refresh_all_providers()
        except Exception as e:
            logger.warning("Auto-refresh failed: %s", e, exc_info=True)
        return self.get_current_client()

    def _next_failover_client(self, failed_model: Optional[str]) -> Optional[ModelClient]:
        """auto 失败切换：返回排除已失败模型后的下一候选（None=无候选）。"""
        exclude = getattr(self, "_failover_excluded", None) or set()
        if failed_model:
            exclude = set(exclude)
            exclude.add(failed_model)
        self._failover_excluded = exclude
        return self._resolve_available_fallback(exclude_models=exclude)

    def _resolve_available_fallback(
        self,
        exclude_models: Optional[set] = None,
    ) -> Optional[ModelClient]:
        """请求的 provider/model 不可用时的兜底客户端。

        目标：只要系统里存在任一个 enabled 且有 api_key 的服务商，就不允许
        返回 "No client available"。分两步：
        1. 已有可用客户端 → 直接返回当前/首个客户端；
        2. _clients 为空（冷启动或初始化失败）→ 触发 refresh_all_providers() 自愈，
           重建所有 enabled + 有 key 的服务商客户端后再取。

        ``exclude_models``：auto 失败切换时排除已失败模型（同能力下一候选）。

        根因背景：默认服务商（如 sensetime，优先级最高）可能没有 api_key，
        而其他有效服务商（如 b.ai）反而有 key；若严格按请求的 provider/model
        查找将永远拿不到客户端，导致 "[LLM Error] No client available"。
        """
        # __new__ 最小注入的测试实例可能不带 _clients/_current_*，防御性读取
        clients = getattr(self, "_clients", {}) or {}
        current_provider_id = getattr(self, "_current_provider_id", None)
        current_model = getattr(self, "_current_model", None)

        if exclude_models:
            # 失败切换：从全部客户端中选第一个不在排除集的（保持注册序）
            for client in clients.values():
                if client.model not in exclude_models:
                    return client
            return None  # 排除后无候选 → 终止 failover（有界）

        current = None
        if current_provider_id and current_model:
            current = clients.get(f"{current_provider_id}/{current_model}")
        if current is None and clients:
            current = next(iter(clients.values()))
        if current:
            return current
        logger.info("Auto-refreshing providers due to empty _clients")
        try:
            self.refresh_all_providers()
        except Exception as e:
            logger.warning("Auto-refresh failed: %s", e, exc_info=True)
        return self.get_current_client()

    def _get_client_for_request(
        self,
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> Optional[ModelClient]:
        """为请求获取客户端（支持懒加载非默认服务商）"""
        if provider_id and model:
            client = self.get_client(provider_id, model)
            if client:
                return client
            # 懒加载：尝试为指定的 provider/model 创建客户端
            client = self._try_lazy_init(provider_id, model)
            if client:
                return client
            # 指定的 provider/model 不可用（如该服务商无 api_key）→ 兜底到可用客户端，
            # 避免 "[LLM Error] No client available"（agent 配置指向无 key 的服务商）。
            logger.warning(
                "Requested provider=%s model=%s unavailable; falling back to an available client",
                provider_id, model,
            )
            return self._resolve_available_fallback()
        elif model:
            client = self.get_client(model=model)
            if client:
                return client
            # 按模型名查找所有服务商
            for provider in self._provider_manager.list_providers():
                if model in provider.models:
                    client = self._try_lazy_init(provider.id, model)
                    if client:
                        return client
            logger.warning(
                "Requested model=%s unavailable; falling back to an available client", model,
            )
            return self._resolve_available_fallback()
        else:
            return self._resolve_available_fallback()

    def _try_lazy_init(self, provider_id: str, model: str) -> Optional[ModelClient]:
        """尝试懒加载客户端 — 为非默认服务商动态创建"""
        provider = self._provider_manager.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found for lazy init", provider_id)
            return None
        if not provider.enabled:
            logger.warning("Provider %s is disabled", provider_id)
            return None
        if not provider.api_key:
            logger.warning("Provider %s has no API key, cannot create client", provider_id)
            return None
        client = self._create_model_client(provider, model)
        if client:
            logger.info("Lazily initialized client for %s/%s", provider_id, model)
        return client

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_requests = sum(c.request_count for c in self._clients.values())
        total_errors = sum(c.error_count for c in self._clients.values())

        return {
            "total_clients": len(self._clients),
            "current_provider": self._current_provider_id,
            "current_model": self._current_model,
            "total_requests": total_requests,
            "total_errors": total_errors,
            "models": self.list_available_models(),
        }


_multi_model_client: Optional[MultiModelLLMClient] = None
# scope → 实例 隔离注册表
# ── P2 可选项：LLM mock 环境注入点 ──
# NEUROVA_LLM_MOCK=1 时 chat/chat_stream 在 provider 解析之前返回 canned
# 响应（无 Key/无网络可跑通全链路：e2e/CI/本地演示）。信封与真实路径同形。
MOCK_ENV_FLAG = "NEUROVA_LLM_MOCK"


def _mock_enabled() -> bool:
    import os as _os

    return _os.environ.get(MOCK_ENV_FLAG, "").strip() == "1"


def _build_mock_response(messages: List[Dict[str, str]]) -> LLMResponse:
    """canned LLMResponse：回显最后一条用户消息（e2e 可断言贯通性）。"""
    last_user = ""
    for m in reversed(messages or []):
        if (m.get("role") or "").lower() == "user":
            last_user = str(m.get("content") or "")
            break
    return LLMResponse(
        content=f"[mock-llm] echo: {last_user}",
        model="mock-model",
        usage={"prompt_tokens": len(last_user), "completion_tokens": 8, "total_tokens": len(last_user) + 8},
        finish_reason="stop",
    )


_multi_model_clients: Dict[str, MultiModelLLMClient] = {}
_multi_model_clients_lock = threading.Lock()


def get_multi_model_client(scope: Optional[str] = None) -> MultiModelLLMClient:
    """获取 MultiModelLLMClient 单例(按 scope 隔离)

    - scope None/"admin":全局单例(存量行为)
    - scope "user:<user_id>":该用户独立实例(独立 provider manager)
    """
    global _multi_model_client
    if scope in (None, "admin"):
        if _multi_model_client is None:
            # 无参/默认走类级 _instance 槽(存量单例语义,既有重置链路兼容)
            _multi_model_client = MultiModelLLMClient(scope=None)
        return _multi_model_client
    # P3-e：键控 scope 首访 DCL——慢构造（建 provider manager/读盘）不可双创建
    client = _multi_model_clients.get(scope)
    if client is None:
        with _multi_model_clients_lock:
            client = _multi_model_clients.get(scope)
            if client is None:
                client = MultiModelLLMClient(scope=scope)
                _multi_model_clients[scope] = client
    return client


def reset_multi_model_client() -> None:
    """重置全部 MultiModelLLMClient 单例(按 scope)并穿透 provider_manager 层。"""
    MultiModelLLMClient.reset()


def scope_for_owner(owner_user_id: Optional[str]) -> Optional[str]:
    """Agent owner_user_id → LLM 配置 scope;无 owner 返回 None(走全局 admin)。"""
    if not owner_user_id:
        return None
    return f"user:{owner_user_id}"


__all__ = [
    "MultiModelLLMClient",
    "get_multi_model_client",
    "reset_multi_model_client",
    "scope_for_owner",
]
