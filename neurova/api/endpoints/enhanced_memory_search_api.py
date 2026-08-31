"""
Enhanced Memory Search API - 增强版记忆检索API

支持 NeRF 体渲染融合模式的配置和查询。
"""

import datetime
from neurova.core.logger import get_logger
import typing

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)
router = APIRouter()


def _get_all_recall_engines(request: Request) -> typing.List:
    """从所有活跃 Agent 中获取 NeurovaRecallEngine 实例"""
    engines = []
    agents = getattr(request.app.state, "agents", {})
    for agent_id, agent in agents.items():
        memory_agent = getattr(agent, "memory_agent", None)
        if memory_agent:
            recall_engine = getattr(memory_agent, "recall_engine", None)
            if recall_engine:
                engines.append(recall_engine)
    return engines


class EnhancedSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    min_score: float = Field(default=0.0, ge=0, le=1)
    include_metadata: bool = True


# NeRF 融合模式全局配置
_nerf_config: typing.Dict[str, typing.Any] = {
    "fusion_mode": "legacy",  # "legacy" | "nerf"
    "density_scale": 1.0,  # 体渲染密度缩放因子
    "channel_densities": {  # 各通道密度（置信度）
        "temperature": 0.7,
        "text": 0.9,
        "category": 0.5,
        "graph": 0.6,
        "emotion": 0.8,
        "voice": 0.4,
    },
}


# Simulated activation store
_activations: typing.Dict[str, dict] = {}


@router.post("/search")
async def enhanced_memory_search(body: EnhancedSearchRequest, request: Request):
    """增强版记忆检索 - 使用 NeurovaRecallEngine 多通道融合检索

    当 fusion_mode 为 "nerf" 时，使用 NeRF 体渲染融合；
    当 fusion_mode 为 "legacy" 时，使用传统加权求和。
    """
    engines = _get_all_recall_engines(request)
    if not engines:
        return {
            "code": 0,
            "message": "success",
            "data": {
                "query": body.query,
                "results": [],
                "total": 0,
                "scoring": {"method": "multi-layer", "layers": ["semantic", "temporal", "activation", "relevance"]},
            },
        }

    # 使用第一个引擎进行检索
    engine = engines[0]
    try:
        # 执行检索
        recalled_memories = engine.recall_flat(
            query=body.query,
            limit=body.top_k,
        )

        # 转换为 API 响应格式
        results = []
        for rm in recalled_memories:
            if hasattr(rm, "to_dict"):
                result_dict = rm.to_dict()
            else:
                result_dict = rm

            # 过滤低分结果
            if result_dict.get("score", 0) < body.min_score:
                continue

            results.append(result_dict)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "query": body.query,
                "results": results,
                "total": len(results),
                "fusion_mode": engine.fusion_mode,
                "scoring": {
                    "method": "nerf_volume_rendering" if engine.fusion_mode == "nerf" else "legacy_weighted_sum",
                    "layers": ["text", "temperature", "category", "graph", "emotion", "voice"],
                },
            },
        }
    except Exception as e:
        logger.error("增强记忆检索失败: %s", e)
        return {
            "code": -1,
            "message": f"检索失败: {str(e)}",
            "data": {"query": body.query, "results": [], "total": 0},
        }


@router.get("/stats")
async def get_retrieval_stats():
    """获取检索系统状态"""
    return {
        "code": 0,
        "message": "success",
        "data": {
            "total_memories": 0,
            "indexed_count": 0,
            "avg_activation": 0.0,
            "search_method": "enhanced_multi_layer",
            "last_decay_at": None,
        },
    }


@router.get("/settings")
async def get_memory_search_settings(current_user: dict = Depends(get_current_user)):
    """获取记忆搜索设置 — 登录用户可读"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    return {
        "code": 0,
        "message": "success",
        "data": {
            "search_method": "hybrid",
            "top_k": 10,
            "score_threshold": 0.5,
            "decay": {
                "enabled": True,
                "rate": cfg.get("temperature.decay_rate"),
                "half_life_days": cfg.get("auto_context.compression_threshold_days"),
                "min_score": cfg.get("threshold.default"),
            },
        },
    }


@router.put("/settings")
async def update_memory_search_settings(body: dict, admin: dict = Depends(require_admin())):
    """更新记忆搜索设置 — 仅管理员"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    updates = {}
    if "decay" in body:
        decay = body["decay"]
        if "rate" in decay:
            updates["temperature.decay_rate"] = decay["rate"]
        if "half_life_days" in decay:
            updates["auto_context.compression_threshold_days"] = decay["half_life_days"]
        if "min_score" in decay:
            updates["threshold.default"] = decay["min_score"]
    updated = cfg.update_and_save(updates)
    return {"code": 0, "message": f"Updated {len(updated)} setting(s)", "data": {"updated": updated}}


@router.get("/nerf-settings")
async def get_nerf_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取 NeRF 体渲染融合设置 — 登录用户可读

    优先从活跃 Agent 的 recall_engine 获取实时设置，
    如果没有活跃 Agent 则返回全局默认设置。
    """
    # 尝试从活跃引擎获取设置
    engines = _get_all_recall_engines(request)
    if engines:
        # 使用第一个引擎的设置作为当前设置
        settings = engines[0].get_fusion_settings()
        return {
            "code": 0,
            "message": "success",
            "data": {
                "fusion_mode": settings["fusion_mode"],
                "density_scale": settings["density_scale"],
                "channel_densities": settings["channel_densities"],
                "available_modes": ["legacy", "nerf"],
                "mode_descriptions": {
                    "legacy": "传统加权求和: score × weight × time_decay",
                    "nerf": "NeRF 体渲染: Σ T_i · σ_i · c_i · w_i（透射率加权积分）",
                },
                "active_engines_count": len(engines),
            },
        }

    # 没有活跃引擎时返回全局默认设置
    return {
        "code": 0,
        "message": "success",
        "data": {
            "fusion_mode": _nerf_config["fusion_mode"],
            "density_scale": _nerf_config["density_scale"],
            "channel_densities": _nerf_config["channel_densities"],
            "available_modes": ["legacy", "nerf"],
            "mode_descriptions": {
                "legacy": "传统加权求和: score × weight × time_decay",
                "nerf": "NeRF 体渲染: Σ T_i · σ_i · c_i · w_i（透射率加权积分）",
            },
            "active_engines_count": 0,
        },
    }


@router.put("/nerf-settings")
async def update_nerf_settings(
    body: dict, request: Request, admin: dict = Depends(require_admin())
):
    """更新 NeRF 体渲染融合设置 — 仅管理员

    body:
        fusion_mode: "legacy" | "nerf"
        density_scale: float (0.1 ~ 5.0)
        channel_densities: dict (可选)

    设置会同步到所有活跃 Agent 的 recall_engine。
    """
    global _nerf_config

    # 准备更新参数
    fusion_mode = body.get("fusion_mode")
    density_scale = body.get("density_scale")
    channel_densities = body.get("channel_densities")

    # 验证参数
    if fusion_mode and fusion_mode not in ("legacy", "nerf"):
        raise HTTPException(status_code=400, detail=f"Invalid fusion_mode: {fusion_mode}")
    if density_scale is not None:
        density_scale = max(0.1, min(5.0, float(density_scale)))

    # 更新全局配置（用于无活跃引擎时的默认值）
    if fusion_mode:
        _nerf_config["fusion_mode"] = fusion_mode
    if density_scale is not None:
        _nerf_config["density_scale"] = density_scale
    if channel_densities and isinstance(channel_densities, dict):
        for ch, val in channel_densities.items():
            if ch in _nerf_config["channel_densities"]:
                _nerf_config["channel_densities"][ch] = max(0.0, min(1.0, float(val)))

    # 同步到所有活跃引擎
    engines = _get_all_recall_engines(request)
    updated_count = 0
    for engine in engines:
        try:
            engine.update_fusion_settings(
                fusion_mode=fusion_mode,
                density_scale=density_scale,
                channel_densities=channel_densities,
            )
            updated_count += 1
        except Exception as e:
            logger.warning("更新 recall_engine 设置失败: %s", e)

    logger.info(
        f"NeRF 设置已更新: fusion_mode={_nerf_config['fusion_mode']}, "
        f"density_scale={_nerf_config['density_scale']}, "
        f"engines_updated={updated_count}/{len(engines)}"
    )

    return {
        "code": 0,
        "message": f"NeRF settings updated ({updated_count} engines synced)",
        "data": {
            **_nerf_config,
            "engines_updated": updated_count,
        },
    }


@router.post("/nerf-settings/reset")
async def reset_nerf_settings(request: Request, admin: dict = Depends(require_admin())):
    """重置 NeRF 设置为默认值 — 仅管理员

    重置会同步到所有活跃 Agent 的 recall_engine。
    """
    global _nerf_config

    # 默认配置
    defaults = {
        "fusion_mode": "legacy",
        "density_scale": 1.0,
        "channel_densities": {
            "temperature": 0.7,
            "text": 0.9,
            "category": 0.5,
            "graph": 0.6,
            "emotion": 0.8,
            "voice": 0.4,
        },
    }

    # 更新全局配置
    _nerf_config = defaults.copy()

    # 同步到所有活跃引擎
    engines = _get_all_recall_engines(request)
    updated_count = 0
    for engine in engines:
        try:
            engine.update_fusion_settings(
                fusion_mode="legacy",
                density_scale=1.0,
                channel_densities=defaults["channel_densities"],
            )
            updated_count += 1
        except Exception as e:
            logger.warning("重置 recall_engine 设置失败: %s", e)

    logger.info("NeRF 设置已重置为默认值, engines_reset=%s/%s", updated_count, len(engines))

    return {
        "code": 0,
        "message": f"NeRF settings reset to defaults ({updated_count} engines synced)",
        "data": {
            **_nerf_config,
            "engines_updated": updated_count,
        },
    }


@router.get("/channel-weights")
async def get_channel_weights(
    intent: str = Query(default="exploratory"),
    current_user: dict = Depends(get_current_user),
):
    """获取指定意图的通道权重（用于前端可视化）— 登录用户可读"""
    # 意图 → 通道权重映射
    intent_weights = {
        "factual": {"text": 0.40, "temperature": 0.20, "category": 0.20, "graph": 0.10, "emotion": 0.05, "voice": 0.05},
        "temporal": {
            "temperature": 0.50,
            "text": 0.15,
            "category": 0.10,
            "graph": 0.10,
            "emotion": 0.10,
            "voice": 0.05,
        },
        "causal": {"graph": 0.50, "text": 0.15, "category": 0.10, "temperature": 0.10, "emotion": 0.10, "voice": 0.05},
        "comparative": {
            "category": 0.35,
            "text": 0.25,
            "graph": 0.15,
            "temperature": 0.10,
            "emotion": 0.10,
            "voice": 0.05,
        },
        "exploratory": {
            "text": 0.25,
            "temperature": 0.20,
            "graph": 0.20,
            "category": 0.15,
            "emotion": 0.10,
            "voice": 0.10,
        },
    }
    weights = intent_weights.get(intent, intent_weights["exploratory"])
    return {"code": 0, "message": "success", "data": {"intent": intent, "weights": weights}}


@router.post("/decay")
async def decay_activations():
    """手动触发激活衰减"""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"code": 0, "message": "Activation decay triggered", "data": {"triggered_at": now, "affected_count": 0}}


@router.post("/analyze")
async def analyze_query(body: dict):
    """分析查询意图和建议策略"""
    query = body.get("query", "")
    words = query.split()
    intent = "factual" if len(words) <= 3 else "contextual"

    return {
        "code": 0,
        "message": "success",
        "data": {
            "query": query,
            "intent": intent,
            "suggested_strategy": "semantic_search" if len(words) > 5 else "keyword_search",
            "confidence": 0.75,
        },
    }


@router.get("/activation/{memory_id}")
async def get_memory_activation(memory_id: str):
    """获取特定记忆的激活状态"""
    act = _activations.get(
        memory_id, {"memory_id": memory_id, "activation_level": 0.0, "last_accessed": None, "access_count": 0}
    )
    return {"code": 0, "message": "success", "data": act}
