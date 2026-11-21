# -*- coding: utf-8 -*-
"""R7（参照系 ad 追平批二）：模型能力位同源校验。

契约：同一 (model_id, 元数据能力位) 下，管理端模型列表的能力出口
（model.py::_response_capabilities）与 llm_router 注册表的能力位
（register_provider_from_config → detect_model_capabilities）必须一致
——两处都不得各自私接第二套推断源。
"""

from neurova.llm.llm_router import get_llm_router, register_provider_from_config
from neurova.llm.routing.auto_selector import resolveAutoChatModel


def test_endpoint_and_router_agree_on_understanding_caps():
    from neurova.api.endpoints.model import _response_capabilities

    for model_id, meta_caps in (
        ("tool-model", ["text", "tool_use"]),
        ("vis-model", ["text", "vision"]),
        ("plain-model", ["text"]),
    ):
        register_provider_from_config(
            f"src-{model_id}", "src", [model_id],
            {model_id: {"capabilities": list(meta_caps)}}, scope="admin",
        )
        router_caps = None
        for p in get_llm_router().list_providers("admin"):
            if p["provider_id"] == f"src-{model_id}":
                router_caps = p["models"][0]["capabilities"]
        endpoint_caps = _response_capabilities(model_id, list(meta_caps))
        # 理解类能力位两处一致（端点侧仅额外合并图/视频生成推断，本例无）
        assert set(meta_caps) <= set(router_caps), (model_id, router_caps)
        assert set(meta_caps) <= set(endpoint_caps), (model_id, endpoint_caps)


def test_router_selection_consumes_the_same_caps():
    """路由消费的就是这份能力位：tool_use 模型被能力选型命中。"""
    register_provider_from_config(
        "solo-tool", "solo", ["tool-model"],
        {"tool-model": {"capabilities": ["text", "tool_use"]}}, scope="admin",
    )
    assert resolveAutoChatModel(scope="admin", needs_tools=True) == ("solo-tool", "tool-model")
