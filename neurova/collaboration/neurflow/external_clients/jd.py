"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class JdOpenClient(api._OpenGatewayClientBase):
    """京东开放平台客户端（open.jd.com）

    网关 POST https://api.jd.com/routerjson，业务参数置于 360buy_param_json，
    响应包装键 {method 点换下划线}_responce（京东历史拼写，兼容 _response）。
    业务 API：
    - 订单 jingdong.pop.order.search（orderPayment 单位元）
    - 商品 jingdong.ware.read.findSkuListPage（jdPrice/stockNum）
    京东开放平台不提供商品评论拉取 API。
    """

    KEY_NAMES = api.JD_KEY_NAMES
    OAUTH_REFRESH_URL = api.JD_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "京东开放平台"

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
        from datetime import datetime

        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise api.ExternalAPIError(
                "京东开放平台未配置：需要 NEUROVA_JD_APP_KEY / NEUROVA_JD_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "method": method,
            "app_key": ak,
            "access_token": token,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "v": "1.0",
            "format": "json",
            "360buy_param_json": api.json.dumps(biz_params or {}, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = api._router_sign_md5(sk, params)
        data = await api._http_post(api.JD_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"京东响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise api.ExternalAPIError(
                f"京东错误 {err.get('code')}: {err.get('zh_desc') or err.get('en_desc') or err.get('msg')}"
            )
        key = method.replace(".", "_")
        for suffix in ("_responce", "_response"):
            if key + suffix in data:
                return data[key + suffix] or {}
        for k, v in data.items():
            if k.endswith("_responce") or k.endswith("_response"):
                return v or {}
        raise api.ExternalAPIError(f"京东无法识别的响应: {data}")

    async def fetch_orders(self, start_date: str = "", end_date: str = "", **creds) -> Dict[str, Any]:
        """jingdong.pop.order.search — POP 订单聚合（orderPayment 单位元）"""
        try:
            resp = await self.call(
                "jingdong.pop.order.search",
                {"startDate": start_date, "endDate": end_date, "page": "1", "pageSize": "100"},
                **creds,
            )
            wrap = resp.get("orderInfoList") or {}
            orders = wrap.get("orderInfo") if isinstance(wrap, dict) else wrap
            orders = orders or []
            total_sales = 0.0
            units = 0
            for o in orders:
                if not isinstance(o, dict):
                    continue
                try:
                    total_sales += float(o.get("orderPayment") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(o.get("itemTotal") or 0)
                except (TypeError, ValueError):
                    pass
            n = len(orders)
            return api._ok(
                {
                    "sales": round(total_sales, 2),
                    "orders": n,
                    "units": units or n,
                    "avg_order_value": round(total_sales / n, 2) if n else 0.0,
                    "order_items": orders,
                    "currency": "CNY",
                },
                "jd",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("京东订单查询失败: %s", exc)
            return api._fail(str(exc), "jd")

    async def fetch_skus(self, page: str = "1", page_size: str = "100", **creds) -> Dict[str, Any]:
        """jingdong.ware.read.findSkuListPage — SKU 列表（jdPrice/stockNum）"""
        try:
            resp = await self.call(
                "jingdong.ware.read.findSkuListPage",
                {"page": page, "pageSize": page_size},
                **creds,
            )
            wrap = resp.get("skuList") or {}
            skus_raw = wrap.get("sku") if isinstance(wrap, dict) else wrap
            skus: Dict[str, Any] = {}
            for s in skus_raw or []:
                if not isinstance(s, dict):
                    continue
                sku_id = str(s.get("skuId") or "")
                if not sku_id:
                    continue
                price = s.get("jdPrice") if s.get("jdPrice") is not None else s.get("price")
                try:
                    price_val = float(price) if price is not None else None
                except (TypeError, ValueError):
                    price_val = None
                stock_raw = s.get("stockNum") if s.get("stockNum") is not None else s.get("stock")
                try:
                    stock = int(stock_raw or 0)
                except (TypeError, ValueError):
                    stock = 0
                skus[sku_id] = {
                    "price": price_val,
                    "stock": stock,
                    "title": s.get("title") or s.get("skuName") or "",
                    "currency": "CNY",
                }
            return api._ok({"skus": skus}, "jd")
        except api.ExternalAPIError as exc:
            api.logger.warning("京东 SKU 查询失败: %s", exc)
            return api._fail(str(exc), "jd")

    async def fetch_prices(self, sku_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """findSkuListPage 结果中筛选指定 skuId 的价格"""
        result = await self.fetch_skus(**creds)
        if result.get("status") != "success":
            return result
        skus = result["output"]["skus"]
        wanted = {str(s).strip() for s in (sku_ids or []) if str(s).strip()}
        prices = {
            sid: {"price": info["price"], "currency": "CNY", "title": info.get("title", "")}
            for sid, info in skus.items()
            if not wanted or sid in wanted
        }
        return api._ok({"prices": prices}, "jd")

    async def fetch_inventory(self, sku_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """findSkuListPage 结果中筛选指定 skuId 的库存（stockNum）"""
        result = await self.fetch_skus(**creds)
        if result.get("status") != "success":
            return result
        skus = result["output"]["skus"]
        wanted = {str(s).strip() for s in (sku_ids or []) if str(s).strip()}
        inventory = {
            sid: {"totalQuantity": info["stock"], "title": info.get("title", "")}
            for sid, info in skus.items()
            if not wanted or sid in wanted
        }
        return api._ok({"inventory": inventory}, "jd")


JdOpenClient.__module__ = api.__name__
JdOpenClient.call.__module__ = api.__name__
JdOpenClient.fetch_orders.__module__ = api.__name__
JdOpenClient.fetch_skus.__module__ = api.__name__
JdOpenClient.fetch_prices.__module__ = api.__name__
JdOpenClient.fetch_inventory.__module__ = api.__name__
