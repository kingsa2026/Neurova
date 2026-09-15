# -*- coding: utf-8 -*-
"""DashScope 双地址分歧适配（用户实测反馈的「阿里地址不一样」场景）。

根因：用户的阿里服务商按文本配置 base_url=…/compatible-mode/v1；
AIGC wan 视频/qwen-image 协议必须走原生 …/api/v1 根。
provider_id 凭据解析会直接带出文本 base → 拼出
`compatible-mode/v1/services/aigc/...` 错误端点（官方文档已核实原生路径）。

契约：
- dashscope_native_root(): compatible-mode → scheme://host/api/v1；
  已是 api/v1 / 完整 services 端点原样返回；空→默认根。
- wan_submit_url / wan_tasks_root 经 native_root。
- _dashscope_image_generate: 文本 base 不再被当完整端点，回退原生端点。
"""
from neurova.llm.generators.protocols import (
    DEFAULT_DASHSCOPE_API_ROOT,
    dashscope_native_root,
    wan_submit_url,
    wan_tasks_root,
)

TEXT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_native_root_rewrites_compatible_mode():
    assert dashscope_native_root(TEXT_BASE) == DEFAULT_DASHSCOPE_API_ROOT


def test_native_root_preserves_native_and_full():
    assert dashscope_native_root("https://dashscope.aliyuncs.com/api/v1") == \
        "https://dashscope.aliyuncs.com/api/v1"
    full = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    assert dashscope_native_root(full) == full
    assert dashscope_native_root("") == DEFAULT_DASHSCOPE_API_ROOT


def test_wan_urls_survive_compatible_mode_base():
    url = wan_submit_url(TEXT_BASE)
    assert "compatible-mode" not in url
    assert url == f"{DEFAULT_DASHSCOPE_API_ROOT}/services/aigc/video-generation/video-synthesis"
    assert "compatible-mode" not in wan_tasks_root(TEXT_BASE)


def test_wan_urls_still_accept_explicit_services_base():
    # 既有矩阵语义：base 含 /services/aigc 时在该层级直接续接（不重复 services 段）
    base = "https://dashscope.aliyuncs.com/api/v1/services/aigc"
    assert wan_submit_url(base) == f"{base}/video-generation/video-synthesis"


def test_image_generate_falls_back_to_native_endpoint_on_text_base(monkeypatch):
    """provider 文本 base 不应被当完整图像端点；回退原生 multimodal-generation。"""
    import asyncio
    from neurova.llm.generators import protocols
    from neurova.llm.generators.protocols import ProtocolCredentials

    calls = []

    async def seq(url, headers, body, timeout=60.0):
        calls.append(url)
        if len(calls) == 1:
            return 403, {"e": 1}  # 异步头被拒 → 同步回退分支
        return 200, {"output": {"results": [{"url": "https://x/a.png"}]}}

    monkeypatch.setattr(protocols, "_post_json", seq)
    creds = ProtocolCredentials(api_key="k", base_url=TEXT_BASE,
                                model="qwen-image", protocol="dashscope")
    out = asyncio.run(protocols._dashscope_image_generate(
        creds, "画个方块", "1024x1024", 1, [], 30.0))
    assert out["images"] == ["https://x/a.png"]
    assert all("compatible-mode" not in u for u in calls), calls
    assert any("services/aigc/multimodal-generation/generation" in u for u in calls)
