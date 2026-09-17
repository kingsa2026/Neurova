"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class TikTokShopClient(api._OpenGatewayClientBase):
    """TikTok Shop Partner 客户端（partner.tiktokshop.com）

    REST 网关 https://open-api.tiktokglobalshop.com，版本在路径（/product/202309/...）。
    公共查询参数 app_key/access_token/timestamp(unix 秒)/sign；
    签名 SHA256(secret + 按 key 升序 key+value 拼接 + secret) 小写，POST 请求体参与签名。
    金额为最小货币单位（分）。响应 {code, message, data}。
    业务 API：
    - 商品 GET /product/202309/products（price.sale_price / skus.stock_infos）
    - 订单 POST /order/202309/orders/search（payment_amount）
    TikTok Shop 开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = api.TIKTOK_SHOP_KEY_NAMES
    OAUTH_REFRESH_URL = api.TIKTOK_SHOP_GATEWAY_URL + api.TIKTOK_SHOP_TOKEN_REFRESH_PATH
    OAUTH_ID_FIELD = "app_key"
    PROVIDER = "TikTok Shop 开放平台"

    async def _request(
        self,
        http_method: str,
        path: str,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
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
                "TikTok Shop 未配置：需要 NEUROVA_TIKTOK_SHOP_APP_KEY / NEUROVA_TIKTOK_SHOP_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "app_key": ak,
            "access_token": token,
            "timestamp": str(int(api.time.time())),
        }
        params.update(query or {})
        # shop_cipher：2024 起业务 API 强制字段，取自店铺注册表 extra
        shop_cipher = ""
        if store_creds is not None:
            shop_cipher = str((store_creds.extra or {}).get("shop_cipher") or "")
        if shop_cipher:
            params["shop_cipher"] = shop_cipher
        signable = dict(params)
        if body:
            signable.update({k: api._stringify_param(v) for k, v in body.items()})
        params["sign"] = api._tiktok_sign_sha256(sk, signable)
        url = api.TIKTOK_SHOP_GATEWAY_URL + path
        if http_method.upper() == "GET":
            data = await api._http_get(url, params=params)
        else:
            data = await api._http_post(url, params=params, json=body or {})
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"TikTok Shop 响应格式异常: {data}")
        code = data.get("code")
        if code not in (0, None):
            raise api.ExternalAPIError(f"TikTok Shop 错误 code={code}: {data.get('message')}")
        return data.get("data") or {}

    async def fetch_shop_cipher(self, **creds) -> Dict[str, Any]:
        """GET /authorization/202309/shops — 取回授权店铺与 shop_cipher（连接测试用）"""
        try:
            data = await self._request("GET", "/authorization/202309/shops", **creds)
            return api._ok({"shops": data.get("shops") or []}, "tiktok")
        except api.ExternalAPIError as exc:
            api.logger.warning("TikTok Shop 店铺列表查询失败: %s", exc)
            return api._fail(str(exc), "tiktok")

    async def fetch_products(self, page_size: int = 100, **creds) -> Dict[str, Any]:
        """GET /product/202309/products — 商品列表（金额为最小货币单位）"""
        try:
            data = await self._request(
                "GET", "/product/202309/products", query={"page_size": str(page_size)}, **creds
            )
            prices: Dict[str, Any] = {}
            inventory: Dict[str, Any] = {}
            for p in data.get("products") or []:
                if not isinstance(p, dict):
                    continue
                pid = str(p.get("id") or "")
                if not pid:
                    continue
                sale = ((p.get("price") or {}).get("sale_price")) or {}
                prices[pid] = {
                    "price": api._fen_to_yuan(sale.get("amount")),
                    "currency": str(sale.get("currency_code") or ""),
                    "title": p.get("title", ""),
                }
                stock = 0
                for sku in p.get("skus") or []:
                    for info in (sku or {}).get("stock_infos") or []:
                        try:
                            stock += int((info or {}).get("available_stock") or 0)
                        except (TypeError, ValueError):
                            pass
                inventory[pid] = {"totalQuantity": stock}
            return api._ok({"prices": prices, "inventory": inventory}, "tiktok")
        except api.ExternalAPIError as exc:
            api.logger.warning("TikTok Shop 商品查询失败: %s", exc)
            return api._fail(str(exc), "tiktok")

    async def search_orders(
        self, create_time_ge: int = 0, create_time_lt: int = 0, **creds
    ) -> Dict[str, Any]:
        """POST /order/202309/orders/search — 订单聚合（payment_amount 最小货币单位）"""
        try:
            body = {
                "create_time_ge": int(create_time_ge),
                "create_time_lt": int(create_time_lt),
                "page_size": 100,
            }
            data = await self._request("POST", "/order/202309/orders/search", body=body, **creds)
            orders = data.get("orders") or []
            total_cents = 0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                amount = (o.get("payment_amount") or {}).get("amount")
                try:
                    total_cents += int(float(amount or 0))
                except (TypeError, ValueError):
                    pass
                for line in o.get("line_items") or []:
                    try:
                        units += int((line or {}).get("quantity") or 0)
                    except (TypeError, ValueError):
                        pass
            n = len(orders)
            return api._ok(
                {
                    "sales": round(total_cents / 100.0, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_cents / 100.0 / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "USD",
                },
                "tiktok",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("TikTok Shop 订单查询失败: %s", exc)
            return api._fail(str(exc), "tiktok")

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        prices = result["output"]["prices"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            prices = {k: v for k, v in prices.items() if k in wanted}
        return api._ok({"prices": prices}, "tiktok")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        result = await self.fetch_products(**creds)
        if result.get("status") != "success":
            return result
        inventory = result["output"]["inventory"]
        wanted = {str(p).strip() for p in (product_ids or []) if str(p).strip()}
        if wanted:
            inventory = {k: v for k, v in inventory.items() if k in wanted}
        return api._ok({"inventory": inventory}, "tiktok")


TikTokShopClient.__module__ = api.__name__
TikTokShopClient._request.__module__ = api.__name__
TikTokShopClient.fetch_shop_cipher.__module__ = api.__name__
TikTokShopClient.fetch_products.__module__ = api.__name__
TikTokShopClient.search_orders.__module__ = api.__name__
TikTokShopClient.fetch_prices.__module__ = api.__name__
TikTokShopClient.fetch_inventory.__module__ = api.__name__
