"""
视觉能力按轮自动路由（2026-09-09 用户需求）

场景：聊天页带图轮 model=None 时，若当前模型无 vision 能力，
本轮自动路由到有 vision 的模型；下一轮（无图）自动回到原模型。
前端用户无感知，不触发 rebuild_loop，不落盘，不改变用户手动选择的模型。

契约：
  1. resolve_vision_capable_model：
     - 当前模型已有 vision → 返回 None（无需覆盖）；
     - 找到其他有 vision 的可用模型 → 返回 (provider_id, model)；
     - 全库无 vision 模型 → 返回 None（保持现状，不凭空造能力）。
  2. vision 覆盖走请求级 ContextVar：激活后 AgentLLMClient.chat/chat_stream
     以覆盖模型发起请求；未激活时行为与旧版完全一致。
  3. ContextVar 不跨请求残留：token 过期后恢复原模型（自动切回）。
  4. ChatPipeline：vision_parts 非空且解析出覆盖模型 → 激活；
     无图轮永不激活。
"""

import pytest

from neurova.llm.llm_routing_overlay import (
    vision_routing_overlay,
    resolve_vision_capable_model,
    get_vision_model_override,
    activate_vision_override,
    clear_vision_override,
)


def _make_pm(monkeypatch, providers):
    """构造最小 provider manager 替身并让解析器走它。"""
    from types import SimpleNamespace

    from neurova.llm import llm_routing_overlay as overlay

    class FakePM:
        def __init__(self, ps):
            self._ps = {p["id"]: SimpleNamespace(**p) for p in ps}

        def list_providers(self, enabled_only=False):
            ps = list(self._ps.values())
            if enabled_only:
                ps = [p for p in ps if getattr(p, "enabled", True)]
            return ps

        def get_provider(self, pid):
            return self._ps.get(pid)

    fake = FakePM(providers)
    monkeypatch.setattr(overlay, "_get_provider_manager", lambda: fake)
    return fake


class TestResolveVisionCapableModel:
    def test_current_model_has_vision_returns_none(self, monkeypatch):
        # 有牙版本：当前模型有 vision，且库里存在其他 vision 候选——
        # 仍必须返回 None（2026-09-09 live 缺陷：原实现不查当前模型能力，
        # 该用例因"唯一候选即自身被排除"而碰巧通过）
        _make_pm(monkeypatch, [
            {"id": "p1", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["gpt-4o"],
             "model_metadata": {"gpt-4o": {"capabilities": ["text", "vision"]}}},
            {"id": "p2", "enabled": True, "api_key": "k", "priority": 5,
             "models": ["other-vision-model"],
             "model_metadata": {"other-vision-model": {"capabilities": ["vision"]}}},
        ])
        assert resolve_vision_capable_model("gpt-4o") is None

    def test_current_model_vision_by_name_inference_no_override(self, monkeypatch):
        # 当前模型名称自带 vision（如 DeepSeek-V4-Flash-Vision-Exp）→ 不切换
        _make_pm(monkeypatch, [
            {"id": "p1", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["DeepSeek-V4-Flash-Vision-Exp"], "model_metadata": {}},
            {"id": "p2", "enabled": True, "api_key": "k", "priority": 5,
             "models": ["gpt-4o"], "model_metadata": {}},
        ])
        assert resolve_vision_capable_model("DeepSeek-V4-Flash-Vision-Exp") is None

    def test_current_lacks_vision_returns_vision_model(self, monkeypatch):
        _make_pm(monkeypatch, [
            {"id": "ptext", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["deepseek-chat"],
             "model_metadata": {"deepseek-chat": {"capabilities": ["text"]}}},
            {"id": "pvis", "enabled": True, "api_key": "k", "priority": 5,
             "models": ["gpt-4o"],
             "model_metadata": {"gpt-4o": {"capabilities": ["text", "vision"]}}},
        ])
        got = resolve_vision_capable_model("deepseek-chat")
        assert got == ("pvis", "gpt-4o")

    def test_priority_ordering_among_vision_models(self, monkeypatch):
        _make_pm(monkeypatch, [
            {"id": "low", "enabled": True, "api_key": "k", "priority": 1,
             "models": ["m-low"], "model_metadata": {"m-low": {"capabilities": ["vision"]}}},
            {"id": "high", "enabled": True, "api_key": "k", "priority": 9,
             "models": ["m-high"], "model_metadata": {"m-high": {"capabilities": ["vision"]}}},
        ])
        got = resolve_vision_capable_model("no-vision-model")
        assert got == ("high", "m-high")

    def test_disabled_or_keyless_providers_skipped(self, monkeypatch):
        _make_pm(monkeypatch, [
            {"id": "cur", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["text-model"], "model_metadata": {"text-model": {"capabilities": ["text"]}}},
            {"id": "off", "enabled": False, "api_key": "k", "priority": 8,
             "models": ["m-off"], "model_metadata": {"m-off": {"capabilities": ["vision"]}}},
            {"id": "nokey", "enabled": True, "api_key": None, "priority": 7,
             "models": ["m-nokey"], "model_metadata": {"m-nokey": {"capabilities": ["vision"]}}},
        ])
        assert resolve_vision_capable_model("text-model") is None

    def test_name_inference_fallback_without_metadata(self, monkeypatch):
        # 无显式 capabilities 时按名称推断（gpt-4o 命中 preset 目录）
        _make_pm(monkeypatch, [
            {"id": "cur", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["deepseek-chat"], "model_metadata": {}},
            {"id": "pvis", "enabled": True, "api_key": "k", "priority": 5,
             "models": ["gpt-4o"], "model_metadata": {}},
        ])
        got = resolve_vision_capable_model("deepseek-chat")
        assert got == ("pvis", "gpt-4o")

    def test_no_vision_model_anywhere_returns_none(self, monkeypatch):
        _make_pm(monkeypatch, [
            {"id": "p1", "enabled": True, "api_key": "k", "priority": 1,
             "models": ["deepseek-chat"], "model_metadata": {"deepseek-chat": {"capabilities": ["text"]}}},
        ])
        assert resolve_vision_capable_model("deepseek-chat") is None

    def test_unknown_current_model_falls_to_name_inference(self, monkeypatch):
        # 当前模型不在任何元数据里（如自定义命名）→ 无 vision → 找别的
        _make_pm(monkeypatch, [
            {"id": "p1", "enabled": True, "api_key": "k", "priority": 10,
             "models": ["my-custom-model"], "model_metadata": {}},
            {"id": "p2", "enabled": True, "api_key": "k", "priority": 5,
             "models": ["gemini-2.5-flash"], "model_metadata": {}},
        ])
        got = resolve_vision_capable_model("my-custom-model")
        assert got == ("p2", "gemini-2.5-flash")


class TestOverrideScope:
    def test_activate_and_auto_revert(self):
        assert get_vision_model_override() is None
        token = activate_vision_override("pvis", "gpt-4o")
        try:
            assert get_vision_model_override() == ("pvis", "gpt-4o")
        finally:
            clear_vision_override(token)
        assert get_vision_model_override() is None  # 自动切回

    def test_nested_activation_restores_previous(self):
        t1 = activate_vision_override("pa", "ma")
        try:
            t2 = activate_vision_override("pb", "mb")
            try:
                assert get_vision_model_override() == ("pb", "mb")
            finally:
                clear_vision_override(t2)
            assert get_vision_model_override() == ("pa", "ma")
        finally:
            clear_vision_override(t1)
        assert get_vision_model_override() is None

    def test_context_manager_scoped(self):
        with vision_routing_overlay("px", "mx"):
            assert get_vision_model_override() == ("px", "mx")
        assert get_vision_model_override() is None


class TestAgentLLMClientOverlay:
    """覆盖激活后 AgentLLMClient 必须按覆盖模型发请求。"""

    def test_chat_uses_override_model(self, monkeypatch):
        from neurova import agent_core

        captured = {}

        class FakeMMC:
            async def chat(self, messages, model=None, provider_id=None, **kw):
                captured["model"] = model
                captured["provider_id"] = provider_id
                from neurova.llm_client import LLMResponse

                return {"success": True, "response": LLMResponse(content="ok", model=model or "cur")}

        monkeypatch.setattr(agent_core.AgentLLMClient, "_get_client", lambda self: FakeMMC())

        client = agent_core.AgentLLMClient(model="cur-model")
        with vision_routing_overlay("pvis", "vision-model"):
            import asyncio

            asyncio.run(client.chat([{"role": "user", "content": "hi"}]))

        assert captured["model"] == "vision-model"
        # 覆盖不钉 provider：钉死会禁用 auto-failover，候选 key 失效时整轮硬失败
        assert captured["provider_id"] is None

    def test_chat_without_overlay_unchanged(self, monkeypatch):
        from neurova import agent_core

        captured = {}

        class FakeMMC:
            async def chat(self, messages, model=None, provider_id=None, **kw):
                captured["model"] = model
                from neurova.llm_client import LLMResponse

                return {"success": True, "response": LLMResponse(content="ok", model=model or "cur")}

        monkeypatch.setattr(agent_core.AgentLLMClient, "_get_client", lambda self: FakeMMC())

        client = agent_core.AgentLLMClient(model="cur-model")
        import asyncio

        asyncio.run(client.chat([{"role": "user", "content": "hi"}]))
        assert captured["model"] == "cur-model"


class TestModelNameResolution:
    """_get_client_for_request 按模型名解析契约。

    2026-09-09 live 缺陷：get_client(model=X) 找不到目标模型时静默回落
    current/default 客户端，覆盖模型名被整体丢弃（请求仍打默认 Kimi 400）。
    """

    def _client(self, monkeypatch, clients, current=("modelscope", "kimi")):
        from types import SimpleNamespace

        from neurova.llm.multi_model_client import MultiModelLLMClient

        c = MultiModelLLMClient.__new__(MultiModelLLMClient)
        c._clients = {f"{p}/{m}": SimpleNamespace(model=m) for p, m in clients}
        c._current_provider_id, c._current_model = current
        c._provider_manager = SimpleNamespace(list_providers=lambda **kw: [])
        monkeypatch.setattr(
            type(c), "_try_lazy_init",
            lambda self, pid, m: self._clients.get(f"{pid}/{m}") or f"lazy:{pid}/{m}",
        )
        return c

    def test_exact_name_match_returns_client(self, monkeypatch):
        c = self._client(monkeypatch, [("modelscope", "kimi"), ("amd", "vision-model")])
        got = c._get_client_for_request("vision-model")
        assert got.model == "vision-model"

    def test_unknown_name_lazily_inits_not_silent_fallback(self, monkeypatch):
        # 已注册 provider 有该模型但无客户端 → 必须懒加载，不得回落 default
        from types import SimpleNamespace

        c = self._client(monkeypatch, [("modelscope", "kimi")])
        c._provider_manager = SimpleNamespace(list_providers=lambda **kw: [
            SimpleNamespace(id="amd", models=["DeepSeek-V4-Flash-Vision-Exp"])
        ])
        got = c._get_client_for_request("DeepSeek-V4-Flash-Vision-Exp")
        assert got == "lazy:amd/DeepSeek-V4-Flash-Vision-Exp"

    def test_truly_unknown_model_falls_back_after_lazy_attempt(self, monkeypatch):
        c = self._client(monkeypatch, [("modelscope", "kimi")])
        got = c._get_client_for_request("no-such-model")
        assert got.model == "kimi"  # 兜底语义保留


class TestPipelineWiring:
    """ChatPipeline：vision_parts 非空 → 激活覆盖；无图轮不激活。"""

    def _pipeline(self):
        from neurova.agent.chat_pipeline import ChatPipeline

        return object.__new__(ChatPipeline)

    def test_setup_activates_when_vision_parts_present(self, monkeypatch):
        from neurova.llm import llm_routing_overlay
        from neurova.agent import chat_pipeline as cp

        p = self._pipeline()
        # 当前模型无 vision → 解析到覆盖
        monkeypatch.setattr(llm_routing_overlay, "resolve_vision_capable_model", lambda cur: ("pvis", "vis-model"))
        monkeypatch.setattr(p, "_current_model_name", lambda: "text-model")

        from types import SimpleNamespace

        ctx = SimpleNamespace(_pending_vision_parts=[{"type": "image_url"}])
        token = p._maybe_activate_vision_routing(ctx)
        try:
            assert llm_routing_overlay.get_vision_model_override() == ("pvis", "vis-model")
        finally:
            llm_routing_overlay.clear_vision_override(token)

    def test_setup_skips_when_no_vision_parts(self, monkeypatch):
        from neurova.llm import llm_routing_overlay
        from neurova.agent import chat_pipeline as cp

        p = self._pipeline()
        monkeypatch.setattr(llm_routing_overlay, "resolve_vision_capable_model", lambda cur: ("pvis", "vis-model"))
        monkeypatch.setattr(p, "_current_model_name", lambda: "text-model")

        from types import SimpleNamespace

        ctx = SimpleNamespace(_pending_vision_parts=None)
        token = p._maybe_activate_vision_routing(ctx)
        assert token is None  # 未激活

    def test_setup_skips_when_current_model_already_vision(self, monkeypatch):
        from neurova.llm import llm_routing_overlay
        from neurova.agent import chat_pipeline as cp

        p = self._pipeline()
        monkeypatch.setattr(llm_routing_overlay, "resolve_vision_capable_model", lambda cur: None)
        monkeypatch.setattr(p, "_current_model_name", lambda: "gpt-4o")

        from types import SimpleNamespace

        ctx = SimpleNamespace(_pending_vision_parts=[{"type": "image_url"}])
        token = p._maybe_activate_vision_routing(ctx)
        assert token is None

    def test_flush_activates_before_clearing_parts(self, monkeypatch):
        """防回归：flush 必须先激活路由再清 _pending_vision_parts。

        2026-09-09 live-verify 实测缺陷：先清后激活导致守卫恒早退，
        图像轮从未覆盖模型（单元测试直调方法未走 flush 全流程而漏网）。
        """
        from types import SimpleNamespace

        from neurova.agent import chat_pipeline as cp
        from neurova.llm import llm_routing_overlay

        p = self._pipeline()
        monkeypatch.setattr(
            llm_routing_overlay, "resolve_vision_capable_model", lambda cur: ("pvis", "vis-model")
        )
        monkeypatch.setattr(p, "_current_model_name", lambda: "text-model")
        applied = []
        monkeypatch.setattr(p, "_apply_vision_attachments", lambda ctx, parts: applied.append(parts))

        ctx = SimpleNamespace(context=[], _pending_vision_parts=[{"type": "image_url"}])
        p._flush_vision_attachments(ctx)

        assert applied  # 图像已挂载
        assert ctx._pending_vision_parts is None  # 切片已清
        assert ctx._vision_override_token is not None  # 路由已激活（在清空前）
        llm_routing_overlay.clear_vision_override(ctx._vision_override_token)
        assert llm_routing_overlay.get_vision_model_override() is None
