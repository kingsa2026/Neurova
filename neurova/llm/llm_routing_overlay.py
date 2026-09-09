"""视觉能力按轮自动路由（2026-09-09）

用户需求：当前模型不具备图片/视频/音频理解能力时，带媒体的那一轮自动
路由到有该能力的模型上，前端用户无感知，轮次结束自动切回原模型。

设计（请求级覆盖，不动持久状态）：
- 覆盖载体是 ContextVar——请求任务内激活、请求结束随任务消亡，天然
  "自动切回"，无跨轮残留；并发请求各持各的 token，互不串扰。
- 覆盖生效点收敛在 AgentLLMClient（Agent 唯一 LLM 出口）：chat /
  chat_stream 发起请求前读取覆盖值，以 (provider_id, model) 发起；
  未激活时零行为变化。
- 能力判定复用既有事实源：provider.model_metadata.capabilities（多模态
  真实探测回写 "vision"）→ 名称/目录推断（capability_detector）兜底。
- 不落盘、不 rebuild_loop、不改 config.llm_config.model——用户手动选择
  的模型在下一轮（无媒体）原样生效。

不做音频/视频的原因：聊天管线当前仅图像有独立注入通道（vision_parts），
音频/视频轮尚无对应载荷，能力位预留（resolve 按 capability 参数化）。
"""

import contextlib
from contextvars import ContextVar
from typing import List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)

# (provider_id, model) 覆盖；None = 未激活
_vision_override: ContextVar[Optional[Tuple[str, str]]] = ContextVar(
    "vision_model_override", default=None
)

# 支持按媒体类型扩展的判定位；当前聊天链路仅消费 vision
_MEDIA_CAPABILITIES = ("vision", "audio", "video")


def get_vision_model_override() -> Optional[Tuple[str, str]]:
    """读取当前请求的模型覆盖（None=未激活）。"""
    return _vision_override.get()


def activate_vision_override(provider_id: str, model: str):
    """激活本请求的模型覆盖，返回 token 供 clear_vision_override 恢复。"""
    return _vision_override.set((provider_id, model))


def clear_vision_override(token) -> None:
    """按 token 恢复覆盖（支持嵌套激活）。"""
    _vision_override.reset(token)


@contextlib.contextmanager
def vision_routing_overlay(provider_id: str, model: str):
    """with 风格的作用域覆盖（测试/非管线调用方用）。"""
    token = activate_vision_override(provider_id, model)
    try:
        yield
    finally:
        clear_vision_override(token)


def _get_provider_manager():
    """provider manager 访问器（测试 monkeypatch 点）。

    MultiModelLLMClient 内部持有 per-scope manager；聊天链路的模型目录
    与它同源（providers.json），这里取全局实例即可——能力是模型的属性，
    与 scope 无关。
    """
    from neurova.llm.provider_manager import get_provider_manager

    return get_provider_manager()


def _model_has_capability(provider, model_id: str, capability: str) -> bool:
    """模型能力判定：显式元数据优先，名称/目录推断兜底（与探测回写同源）。"""
    meta = (getattr(provider, "model_metadata", None) or {}).get(model_id, {}) or {}
    caps = [str(c) for c in (meta.get("capabilities") or [])]
    if not caps:
        try:
            from neurova.llm.capability_detector import infer_capabilities

            caps = infer_capabilities(model_id)
        except Exception:  # noqa: BLE001 — 推断失败按无能力处理
            caps = []
    return capability in caps


def resolve_vision_capable_model(
    current_model: Optional[str],
    capability: str = "vision",
) -> Optional[Tuple[str, str]]:
    """在可用模型目录里找一个具备 capability 且不是当前模型的最优候选。

    当前模型已具备能力（探测元数据或名称推断）→ 返回 None，不无谓切换。
    选择规则与 provider 优先级一致：enabled 且有 api_key 的服务商中，
    priority 高者优先（list_providers 已按此排序）。

    返回 (provider_id, model)；全库无候选时返回 None
    （调用方保持现状，不凭空造能力、不强制降级）。
    """
    try:
        pm = _get_provider_manager()
    except Exception:  # noqa: BLE001 — 目录不可用时保持现状
        logger.debug("能力路由：provider manager 不可用，跳过覆盖", exc_info=True)
        return None

    current = (current_model or "").strip()
    if current:
        # 当前模型已具备能力则不覆盖（元数据优先，名称推断兜底）
        for provider in pm.list_providers(enabled_only=True):
            models = list(getattr(provider, "models", None) or [])
            if current in models or getattr(provider, "default_model", None) == current:
                if _model_has_capability(provider, current, capability):
                    return None
                break  # 找到属主但无能力 → 继续找候选

    candidates: List[Tuple[int, str, str]] = []
    for provider in pm.list_providers(enabled_only=True):
        if not (getattr(provider, "api_key", None) or getattr(provider, "encrypted_api_key", None)):
            continue
        for model_id in (getattr(provider, "models", None) or []):
            if current and model_id == current:
                continue
            if _model_has_capability(provider, model_id, capability):
                candidates.append((int(getattr(provider, "priority", 0) or 0), provider.id, model_id))
                break  # 每服务商取一个代表模型即可

    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    _, provider_id, model_id = candidates[0]
    return provider_id, model_id
