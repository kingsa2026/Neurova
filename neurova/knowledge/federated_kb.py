"""远程 KB 联邦检索服务（P1-4 消费面——把 MultiKBRouter 接进真实配置）。

断链修复：knowledge/adapters.get_adapter 工厂此前零消费——远程库
（iflow/feishu/ima/custom）只有配置管理没有检索入口。本服务把用户的
is_active 配置装配为适配器清单，经 MultiKBRouter 选库检索。

- api_key 经 storage.decrypt_api_key 可逆解密注入适配器配置（属主隔离：
  只装配 get_configs_by_user(user_id) 的配置）
- 0/1 库零成本直通；多库 LLM 选库（llm_call 可注入，缺省不路由全库检索）
- 单库故障不拖垮整批；结果带 config_id 溯源
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class _ConfigKBAdapterProxy:
    """配置条目 → KBAdapter 的轻量代理（kb_id=配置 id，溯源用）"""

    def __init__(self, config: Dict[str, Any], api_key: Optional[str]):
        from neurova.knowledge.adapters import get_adapter

        self.kb_id = str(config.get("id", ""))
        self.name = str(config.get("name", self.kb_id))
        self.description = str((config.get("settings") or {}).get("description", ""))
        # settings 即适配器契约形态（base_url/dataset_id 等由管理页写入）
        settings = dict(config.get("settings") or {})
        if api_key:
            settings["api_key"] = api_key
        self._adapter = get_adapter(str(config.get("source_type", "custom")), settings)

    async def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        return await self._adapter.search(query, limit=limit)


class FederatedKBService:
    """多库联邦检索（配置驱动；LLM 选库可选）"""

    def __init__(self, storage: Any):
        self._storage = storage

    def _assemble_adapters(
        self, configs: List[Dict[str, Any]], decrypt: Any
    ) -> List[Any]:
        """is_active 配置 → 适配器清单（解密失败/非 active 跳过）"""
        adapters: List[Any] = []
        for cfg in configs or []:
            if not cfg.get("is_active"):
                continue
            cid = str(cfg.get("id", ""))
            api_key = None
            if cfg.get("api_key_encrypted"):
                # 声明了加密 key 但解密不出 → 远程调用必失败，跳过该配置
                try:
                    api_key = decrypt(cid) if decrypt else None
                except Exception as e:  # noqa: BLE001
                    logger.warning("KB 配置 %s api_key 解密失败（跳过）: %s", cid, e)
                    continue
                if not api_key:
                    logger.warning("KB 配置 %s api_key 解密为空（跳过）", cid)
                    continue
            try:
                adapters.append(_ConfigKBAdapterProxy(cfg, api_key))
            except Exception as e:  # noqa: BLE001
                logger.warning("KB 适配器构造失败 %s: %s", cid, e)
        return adapters

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        llm_call: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """联邦检索入口（结果带 kb_id=config_id 溯源）"""
        empty = {"query": query, "selected_kb_ids": [], "results": [], "total": 0}
        try:
            configs = self._storage.get_configs_by_user(user_id)
        except Exception as e:  # noqa: BLE001 — 存储故障优雅空结果
            logger.warning("KB 配置读取失败: %s", e)
            return empty

        def _decrypt(cid: str) -> Optional[str]:
            return self._storage.decrypt_api_key(cid)

        adapters = self._assemble_adapters(configs, _decrypt)
        if not adapters:
            return empty

        from neurova.knowledge.multi_kb_router import MultiKBRouter

        router = MultiKBRouter(llm_call=llm_call)
        return await router.search(query, adapters, limit=limit)


__all__ = ["FederatedKBService"]
