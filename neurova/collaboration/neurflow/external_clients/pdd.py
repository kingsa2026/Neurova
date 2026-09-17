"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class PddOpenClient(api._OpenGatewayClientBase):
    """拼多多开放平台客户端（open.pinduoduo.com）

    网关 POST https://gw-api.pinduoduo.com/api/router，type 为 API 名，
    业务参数平铺为顶层表单字段，timestamp 为 unix 秒，金额单位为分。
    业务 API：
    - 订单 pdd.order.list.get（pay_amount 单位分）
    - 商品 pdd.goods.information.get（min_group_price 分 / goods_quantity 库存）
    拼多多开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = api.PDD_KEY_NAMES
    OAUTH_REFRESH_URL = api.PDD_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "拼多多开放平台"

    async def call(
        self,
        api_type: str,
        biz_params: Optional[Dict[str, Any]] = None,
        client_id: str = "",
        client_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        cid, cs, _, _ = self._resolve_credentials(
            client_id, client_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (cid and cs):
            raise api.ExternalAPIError(
                "拼多多开放平台未配置：需要 NEUROVA_PDD_CLIENT_ID / NEUROVA_PDD_CLIENT_SECRET"
            )
        token = await self._access_token(
            client_id, client_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "type": api_type,
            "client_id": cid,
            "access_token": token,
            "timestamp": str(int(api.time.time())),
            "data_type": "JSON",
        }
        for k, v in (biz_params or {}).items():
            params[k] = api._stringify_param(v)
        params["sign"] = api._router_sign_md5(cs, params)
        data = await api._http_post(api.PDD_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"拼多多响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise api.ExternalAPIError(
                f"拼多多错误 {err.get('error_code')}: {err.get('sub_msg') or err.get('error_msg')}"
            )
        key = api_type.replace(".", "_") + "_response"
        if key in data:
            return data[key] or {}
        for k, v in data.items():
            if k.endswith("_response"):
                return v or {}
        raise api.ExternalAPIError(f"拼多多无法识别的响应: {data}")

    async def fetch_orders(
        self, start_updated_at: int = 0, end_updated_at: int = 0, **creds
    ) -> Dict[str, Any]:
        """pdd.order.list.get — 订单聚合（pay_amount 单位分）"""
        try:
            resp = await self.call(
                "pdd.order.list.get",
                {
                    "start_updated_at": int(start_updated_at),
                    "end_updated_at": int(end_updated_at),
                    "page": 1,
                    "page_size": 100,
                },
                **creds,
            )
            orders = resp.get("order_list") or []
            total_fen = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_fen += int(o.get("pay_amount") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(o.get("goods_amount") or 0)
                except (TypeError, ValueError):
                    pass
            n = len(orders)
            return api._ok(
                {
                    "sales": round(total_fen / 100.0, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_fen / 100.0 / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "pdd",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("拼多多订单查询失败: %s", exc)
            return api._fail(str(exc), "pdd")

    async def fetch_goods(self, goods_ids: List[str], **creds) -> Dict[str, Any]:
        """pdd.goods.information.get — 按 goods_id 查价格（分）与库存（goods_quantity）"""
        ids = [str(g).strip() for g in goods_ids if str(g).strip()][:20]
        try:
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for gid in ids:
                resp = await self.call("pdd.goods.information.get", {"goods_id": gid}, **creds)
                for detail in resp.get("goods_details") or []:
                    if not isinstance(detail, dict):
                        continue
                    key = str(detail.get("goods_id") or gid)
                    prices[key] = {
                        "price": api._fen_to_yuan(detail.get("min_group_price")),
                        "currency": "CNY",
                        "title": detail.get("goods_name", ""),
                    }
                    try:
                        qty = int(detail.get("goods_quantity") or 0)
                    except (TypeError, ValueError):
                        qty = 0
                    inventory[key] = {"totalQuantity": qty}
            return api._ok({"prices": prices, "inventory": inventory}, "pdd")
        except api.ExternalAPIError as exc:
            api.logger.warning("拼多多商品查询失败: %s", exc)
            return api._fail(str(exc), "pdd")

    async def fetch_prices(self, goods_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_goods(goods_ids or [], **creds)
        if result.get("status") != "success":
            return result
        return api._ok({"prices": result["output"]["prices"]}, "pdd")

    async def fetch_inventory(self, goods_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_goods(goods_ids or [], **creds)
        if result.get("status") != "success":
            return result
        return api._ok({"inventory": result["output"]["inventory"]}, "pdd")


PddOpenClient.__module__ = api.__name__
PddOpenClient.call.__module__ = api.__name__
PddOpenClient.fetch_orders.__module__ = api.__name__
PddOpenClient.fetch_goods.__module__ = api.__name__
PddOpenClient.fetch_prices.__module__ = api.__name__
PddOpenClient.fetch_inventory.__module__ = api.__name__
