"""
Model Adapter API 端点 v1.0.0
"""


from fastapi import APIRouter, HTTPException

router = APIRouter()


# ── In-memory store ────────────────────────────────────

_ADAPTERS = [
    {
        "id": "openai",
        "name": "OpenAI Adapter",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"],
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
    },
    {
        "id": "anthropic",
        "name": "Anthropic Adapter",
        "models": ["claude-3.5-sonnet", "claude-3-opus", "claude-3-haiku"],
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
    },
    {
        "id": "gemini",
        "name": "Gemini Adapter",
        "models": ["gemini-pro", "gemini-pro-vision"],
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
    },
    {
        "id": "ollama",
        "name": "Ollama Adapter",
        "models": ["llama3", "mistral", "codellama"],
        "supports_streaming": True,
        "supports_tools": False,
        "supports_vision": False,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter Adapter",
        "models": ["auto"],
        "supports_streaming": True,
        "supports_tools": True,
        "supports_vision": True,
    },
]


@router.get("/")
async def list_adapters():
    """列出所有已注册的模型适配器"""
    return {"code": 0, "message": "success", "data": {"adapters": _ADAPTERS, "total": len(_ADAPTERS)}}


@router.get("/{adapter_id}")
async def get_adapter(adapter_id: str):
    """获取指定适配器详情"""
    adapter = next((a for a in _ADAPTERS if a["id"] == adapter_id), None)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Adapter '{adapter_id}' not found")
    return {"code": 0, "message": "success", "data": adapter}


@router.post("/match")
async def match_model(body: dict):
    """检查模型是否可匹配已注册适配器"""
    model_name = body.get("model", "")
    if not model_name:
        raise HTTPException(status_code=400, detail="model is required")

    model_lower = model_name.lower()
    matches = []
    for adapter in _ADAPTERS:
        for m in adapter["models"]:
            if m.lower() in model_lower or model_lower in m.lower():
                matches.append({"adapter_id": adapter["id"], "adapter_name": adapter["name"], "matched_model": m})
                break

    # Fallback: try pattern matching
    if not matches:
        if any(k in model_lower for k in ["gpt", "chatgpt"]):
            matches.append({"adapter_id": "openai", "adapter_name": "OpenAI Adapter", "matched_model": model_name})
        elif "claude" in model_lower:
            matches.append(
                {"adapter_id": "anthropic", "adapter_name": "Anthropic Adapter", "matched_model": model_name}
            )
        elif "gemini" in model_lower:
            matches.append({"adapter_id": "gemini", "adapter_name": "Gemini Adapter", "matched_model": model_name})
        elif any(k in model_lower for k in ["llama", "mistral", "codellama", "qwen"]):
            matches.append({"adapter_id": "ollama", "adapter_name": "Ollama Adapter", "matched_model": model_name})

    return {
        "code": 0,
        "message": "success",
        "data": {"model": model_name, "matches": matches, "matched": len(matches) > 0},
    }
