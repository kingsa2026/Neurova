"""M-?/L-13 回归测试：重建 OpenAI 客户端前必须 close 旧连接，避免连接池/TLS 泄漏。

红绿：无修复时 _init_client 在 update_config 重建客户端时不关闭旧连接
（旧 client.close() 从不调用）→ 本测试断言 first.close.called 为 True 会失败（红）；
修复后（L-13 在 _init_client 开头 close 旧连接）→ 绿。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import neurova.llm_client as llm_mod


def test_l13_closes_old_client_on_reinit():
    instances = []

    def fake_factory(**kwargs):
        inst = MagicMock()
        instances.append(inst)
        return inst

    with patch.object(llm_mod, "OpenAI", fake_factory, create=True), \
         patch.object(llm_mod, "AsyncOpenAI", fake_factory, create=True), \
         patch.object(llm_mod, "OPENAI_AVAILABLE", True), \
         patch.object(llm_mod, "ASYNC_OPENAI_AVAILABLE", True):
        from neurova.llm_client import LLMClient

        cfg = SimpleNamespace(
            api_key="k1",
            base_url="http://x",
            model="m",
            timeout=30,
            connect_timeout=10,
            max_retries=1,
            preset=None,
        )
        client = LLMClient(cfg)
        # 第一次 _init_client 创建了 OpenAI(实例0) + AsyncOpenAI(实例1)
        first_openai = instances[0]
        # 变更 api_key 触发 _init_client 重建 → 必须 close 旧连接
        client.update_config(api_key="k2")
        assert first_openai.close.called, "L-13: 重建客户端前必须 close 旧连接"
