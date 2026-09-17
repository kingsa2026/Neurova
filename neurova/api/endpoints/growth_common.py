"""growth 域共享依赖（2026-09-16 growth.py 模块化拆分产物）。

子路由模块（personality_router / constitution_router / growth.py 其余端点）
共用 agent 解析与 request_id；envelope 构造统一在此，形态与
test_growth_envelope_consistency.py 钉死的 {code, message, data, request_id} 一致。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import Request


def get_agent(agent_id: str = "default"):
    """获取 Agent 实例（原 growth._get_agent，经聚合器 re-export 保持兼容）"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def get_request_id(request: Request) -> str:
    """获取请求ID（原 growth._get_request_id，经聚合器 re-export 保持兼容）"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def envelope(request_id: str, data: Any = None, message: str = "success") -> Dict[str, Any]:
    """growth 域统一 envelope（全端点唯一出口，禁止裸对象/裸数组返回）"""
    return {"code": 0, "message": message, "data": data, "request_id": request_id}
