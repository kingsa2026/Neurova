"""P1-4 多库路由消费面（TDD）——远程 KB 联邦检索服务。

断链修复：get_adapter 工厂此前零消费（远程库只有配置没有检索入口）。
FederatedKBService 把用户的远程 KB 配置装配为适配器清单，经
MultiKBRouter 选库检索：
- 配置 is_active=True 才进清单；api_key 经 storage.decrypt_api_key 注入
- 0/1 库零成本直通（不调 LLM）；多库 LLM 选库失败兜底全库
- 单库检索失败不影响其余库；结果带 config_id 溯源
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.knowledge.federated_kb import FederatedKBService


def _config(cid, source_type="iflow", is_active=True, settings=None):
    return {
        "id": cid, "user_id": "u1", "name": f"库-{cid}",
        "source_type": source_type, "is_active": is_active,
        "api_key_encrypted": "enc:xxx", "settings": settings or {},
    }


class TestAdapterAssembly:
    def test_active_configs_become_adapters(self, tmp_path):
        svc = FederatedKBService(storage=MagicMock())
        cfgs = [_config("c1"), _config("c2", is_active=False)]
        adapters = svc._assemble_adapters(cfgs, decrypt=lambda cid: "key-" + cid)
        assert [a.kb_id for a in adapters] == ["c1"], "非 active 配置不进清单"
        assert adapters[0].name == "库-c1"

    def test_decrypt_failure_skips_config(self, tmp_path):
        svc = FederatedKBService(storage=MagicMock())
        adapters = svc._assemble_adapters([_config("c1")], decrypt=lambda cid: None)
        assert adapters == [], "解密失败的配置（无 api_key）不进远程清单"


class TestFederatedSearch:
    @pytest.mark.asyncio
    async def test_single_kb_direct_search(self, tmp_path):
        storage = MagicMock()
        svc = FederatedKBService(storage=storage)
        fake_adapter = MagicMock()
        fake_adapter.kb_id = "c1"
        fake_adapter.name = "库-1"
        fake_adapter.description = "d"
        fake_adapter.search = AsyncMock(return_value={"success": True, "results": [{"text": "r1"}]})

        with patch.object(svc, "_assemble_adapters", return_value=[fake_adapter]):
            outcome = await svc.search("q", user_id="u1", llm_call=None)

        assert outcome["results"][0]["text"] == "r1"
        assert outcome["results"][0]["kb_id"] == "c1"
        fake_adapter.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multi_kb_llm_routing(self):
        svc = FederatedKBService(storage=MagicMock())

        def _mk(cid):
            a = MagicMock()
            a.kb_id = cid
            a.name = f"库-{cid}"
            a.description = "d"
            a.search = AsyncMock(return_value={"success": True, "results": [{"text": f"r-{cid}"}]})
            return a

        a1, a2 = _mk("c1"), _mk("c2")
        with patch.object(svc, "_assemble_adapters", return_value=[a1, a2]):
            outcome = await svc.search(
                "q", user_id="u1",
                llm_call=AsyncMock(return_value={"kb_ids": ["c2"]}),
            )
        assert [r["kb_id"] for r in outcome["results"]] == ["c2"]
        a1.search.assert_not_awaited(), "未被选中的库不检索"

    @pytest.mark.asyncio
    async def test_storage_error_returns_empty_gracefully(self):
        storage = MagicMock()
        storage.get_configs_by_user.side_effect = RuntimeError("db gone")
        svc = FederatedKBService(storage=storage)
        outcome = await svc.search("q", user_id="u1")
        assert outcome["results"] == [] and outcome["total"] == 0
