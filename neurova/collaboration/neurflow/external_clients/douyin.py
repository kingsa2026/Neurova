"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class DouyinEcomClient(api._OpenGatewayClientBase):
    """抖店开放平台客户端（op.jinritemai.com）

    网关 POST https://openapi-fxg.jinritemai.com，业务参数置于 param_json（紧凑 JSON），
    签名仅 app_key/method/param_json/timestamp/v 五键参与，响应 {err_no, message, data}，
    金额单位为分。
    业务 API：
    - 订单 order.searchList（create_time_start/end unix 秒，pay_amount 分）
    - 商品 product.listV2（discount_price 分 / stock_num 库存）
    抖店开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = api.DOUYIN_ECOM_KEY_NAMES
    OAUTH_REFRESH_URL = api.DOUYIN_ECOM_OAUTH_REFRESH_URL
    OAUTH_ID_FIELD = "app_key"
    PROVIDER = "抖店开放平台"

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
        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise api.ExternalAPIError(
                "抖店开放平台未配置：需要 NEUROVA_DOUYIN_ECOM_APP_KEY / NEUROVA_DOUYIN_ECOM_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        param_json = api.json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        signable = {
            "app_key": ak,
            "method": method,
            "param_json": param_json,
            "timestamp": str(int(api.time.time())),
            "v": "2",
        }
        params = dict(signable)
        params["sign_method"] = "md5"
        params["access_token"] = token
        params["sign"] = api._douyin_sign_md5(sk, signable)
        data = await api._http_post(api.DOUYIN_ECOM_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"抖店响应格式异常: {data}")
        err_no = data.get("err_no", data.get("code"))
        if err_no not in (0, None):
            raise api.ExternalAPIError(f"抖店错误 err_no={err_no}: {data.get('message')}")
        return data.get("data") or {}

    async def fetch_orders(
        self, create_time_start: int = 0, create_time_end: int = 0, **creds
    ) -> Dict[str, Any]:
        """order.searchList — 订单聚合（pay_amount 单位分）"""
        try:
            resp = await self.call(
                "order.searchList",
                {
                    "create_time_start": int(create_time_start),
                    "create_time_end": int(create_time_end),
                    "page": 0,
                    "size": 100,
                },
                **creds,
            )
            orders = resp.get("shop_order_list") or []
            total_fen = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_fen += int(o.get("pay_amount") or 0)
                except (TypeError, ValueError):
                    pass
                units += len(o.get("sku_order_list") or [])
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
                "douyin-ecom",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("抖店订单查询失败: %s", exc)
            return api._fail(str(exc), "douyin-ecom")

    async def fetch_products(self, page: int = 0, size: int = 100, **creds) -> Dict[str, Any]:
        """product.listV2 — 商品列表（discount_price 分 / stock_num 库存）"""
        try:
            resp = await self.call("product.listV2", {"page": page, "size": size}, **creds)
            products = resp.get("data") or resp.get("products") or []
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for p in products:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("product_id") or "")
                if not pid:
                    continue
                price_fen = p.get("discount_price") if p.get("discount_price") is not None else p.get("market_price")
                prices[pid] = {
                    "price": api._fen_to_yuan(price_fen),
                    "currency": "CNY",
                    "title": p.get("name", ""),
                }
                try:
                    stock = int(p.get("stock_num") or 0)
                except (TypeError, ValueError):
                    stock = 0
                inventory[pid] = {"totalQuantity": stock}
            return api._ok({"prices": prices, "inventory": inventory}, "douyin-ecom")
        except api.ExternalAPIError as exc:
            api.logger.warning("抖店商品查询失败: %s", exc)
            return api._fail(str(exc), "douyin-ecom")

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        prices = result["output"]["prices"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            prices = {k: v for k, v in prices.items() if k in wanted}
        return api._ok({"prices": prices}, "douyin-ecom")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        inventory = result["output"]["inventory"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            inventory = {k: v for k, v in inventory.items() if k in wanted}
        return api._ok({"inventory": inventory}, "douyin-ecom")


DouyinEcomClient.__module__ = api.__name__
DouyinEcomClient.call.__module__ = api.__name__
DouyinEcomClient.fetch_orders.__module__ = api.__name__
DouyinEcomClient.fetch_products.__module__ = api.__name__
DouyinEcomClient.fetch_prices.__module__ = api.__name__
DouyinEcomClient.fetch_inventory.__module__ = api.__name__
