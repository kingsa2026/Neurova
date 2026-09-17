"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class XiaohongshuClient(api._OpenGatewayClientBase):
    """小红书开放平台客户端（ark 网关）— 协议已复核

    - 网关 POST https://ark.xiaohongshu.com/ark/open_api/v3/common_controller（JSON）
    - 公共参数 method/appId/sign/timestamp(秒)/version=2.0/accessToken
    - 签名 MD5 固定串（小写），body 业务参数不参与
    - token：oauth.getAccessToken（code）/ oauth.refreshToken（refreshToken）同网关
    """

    KEY_NAMES = api.XHS_KEY_NAMES
    OAUTH_REFRESH_URL = api.XHS_GATEWAY_URL  # 仅用于语义对齐；实际刷新走 override 的 get_access_token
    OAUTH_ID_FIELD = "appId"
    PROVIDER = "小红书开放平台"

    async def get_access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        refresh_token: str = "",
        code: str = "",
    ) -> str:
        ak, sk, _, _ = self._resolve_credentials(app_key, app_secret, "", refresh_token, store_creds=None)
        if not (ak and sk):
            raise api.ExternalAPIError("小红书未配置：需要 appKey/appSecret")
        method = "oauth.getAccessToken" if code else "oauth.refreshToken"
        ts = int(api.time.time())
        body: Dict[str, Any] = {
            "method": method,
            "appId": ak,
            "sign": api._xiaohongshu_sign(method, ak, sk, api.XHS_VERSION, ts),
            "timestamp": ts,
            "version": api.XHS_VERSION,
        }
        if code:
            body["code"] = code
        else:
            body["refreshToken"] = refresh_token
        data = await api._http_post(api.XHS_GATEWAY_URL, json=body)
        payload = (data or {}).get("data") if isinstance(data, dict) else None
        token = (payload or {}).get("accessToken") if isinstance(payload, dict) else None
        if not token:
            raise api.ExternalAPIError(f"小红书令牌获取失败: {data}")
        return str(token)

    async def call(
        self,
        method: str,
        biz_params: Optional[Dict[str, Any]] = None,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, _, _ = self._resolve_credentials(app_key, app_secret, access_token, refresh_token, store_creds=store_creds)
        if not (ak and sk):
            raise api.ExternalAPIError("小红书未配置：需要 appKey/appSecret")
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        ts = int(api.time.time())
        body: Dict[str, Any] = {
            "method": method,
            "appId": ak,
            "sign": api._xiaohongshu_sign(method, ak, sk, api.XHS_VERSION, ts),
            "timestamp": ts,
            "version": api.XHS_VERSION,
            "accessToken": token,
        }
        body.update(biz_params or {})
        data = await api._http_post(api.XHS_GATEWAY_URL, json=body)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"小红书响应格式异常: {data}")
        if not data.get("success"):
            raise api.ExternalAPIError(f"小红书错误 {data.get('error_code')}: {data.get('error_msg')}")
        return data.get("data") or {}

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """product.getItemInfo — 按 itemId 查询（字段名防御式提取，raw 保留供核对）"""
        try:
            prices: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                data = await self.call("product.getItemInfo", {"itemId": pid}, **creds)
                live = data if isinstance(data, dict) else {}
                inner = live.get("itemInfo") if isinstance(live, dict) else None
                item = inner if isinstance(inner, dict) else live
                prices[pid] = {
                    "price": api._first_float(item, ("salePrice", "price", "referencePrice")),
                    "currency": "CNY",
                    "title": str(item.get("itemName") or item.get("title") or "") if isinstance(item, dict) else "",
                    "raw": live,
                }
            return api._ok({"prices": prices}, "xiaohongshu")
        except api.ExternalAPIError as exc:
            api.logger.warning("小红书价格查询失败: %s", exc)
            return api._fail(str(exc), "xiaohongshu")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """inventory.getSkuStockV2 — 按 skuId 查询库存"""
        try:
            inventory: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                data = await self.call("inventory.getSkuStockV2", {"skuId": pid}, **creds)
                live = data if isinstance(data, dict) else {}
                inner = live.get("skuStock") if isinstance(live, dict) else None
                item = inner if isinstance(inner, dict) else live
                inventory[pid] = {
                    "totalQuantity": api._first_int(item, ("quantity", "stock", "availableQuantity")),
                    "title": str(item.get("skuName") or "") if isinstance(item, dict) else "",
                    "raw": live,
                }
            return api._ok({"inventory": inventory}, "xiaohongshu")
        except api.ExternalAPIError as exc:
            api.logger.warning("小红书库存查询失败: %s", exc)
            return api._fail(str(exc), "xiaohongshu")

    async def fetch_orders(self, start_time: int = 0, end_time: int = 0, **creds) -> Dict[str, Any]:
        """order.getOrderList — 订单聚合（时间参数单位以官方文档为准，raw 保留）"""
        try:
            body: Dict[str, Any] = {"startTime": int(start_time), "endTime": int(end_time)}
            data = await self.call("order.getOrderList", body, **creds)
            orders_holder = data if isinstance(data, dict) else {}
            orders = orders_holder.get("orderList") or orders_holder.get("orders") or orders_holder.get("list") or []
            if isinstance(orders, dict):
                orders = orders.get("list") or orders.get("orders") or []
            orders = orders if isinstance(orders, list) else []
            total = 0.0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                total += float(api._first_float(o, ("payAmount", "payAmountFen", "amount")) or 0)
                units += api._first_int(o, ("itemCount", "quantity", "itemQuantity"))
            n = len(orders)
            return api._ok(
                {
                    "sales": round(total, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "xiaohongshu",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("小红书订单查询失败: %s", exc)
            return api._fail(str(exc), "xiaohongshu")


XiaohongshuClient.__module__ = api.__name__
XiaohongshuClient.get_access_token.__module__ = api.__name__
XiaohongshuClient.call.__module__ = api.__name__
XiaohongshuClient.fetch_prices.__module__ = api.__name__
XiaohongshuClient.fetch_inventory.__module__ = api.__name__
XiaohongshuClient.fetch_orders.__module__ = api.__name__
