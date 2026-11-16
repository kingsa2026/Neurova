# -*- coding: utf-8 -*-
"""记忆激活端点诚实化（审计 3.3-3，2026-11-17）：

`/enhanced-memory-search/activation/{id}` 读一个全仓无写入方的全局字典，
恒 200 返回伪造的零激活数据。激活账本没有生产写入方 → 端点未实现，
与同文件 /decay（P2-6 先例）同口径诚实 501，不谎报数据。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from neurova.api.endpoints.enhanced_memory_search_api import get_memory_activation


class TestActivationEndpointHonest:
    @pytest.mark.parametrize("memory_id", ["m-1", "any-id", ""])
    def test_unknown_activation_is_501_not_fake_zero(self, memory_id: str):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(get_memory_activation(memory_id))
        assert exc.value.status_code == 501, (
            "激活账本无生产写入方——读它只能得到伪造零值，必须诚实 501（对齐 /decay 口径）"
        )
        assert "激活" in str(exc.value.detail)

    def test_no_activation_store_left_behind(self):
        """死字典必须随接线退役（教义第 2/6 条：不留下一个只读假源）。"""
        import neurova.api.endpoints.enhanced_memory_search_api as ems

        assert not hasattr(ems, "_activations"), (
            "_activations 全仓无写入方，端点改 501 后它成为只读假源死码，必须删除"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
