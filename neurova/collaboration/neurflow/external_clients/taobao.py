"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class TaobaoTopClient(api._OpenGatewayClientBase):
    """淘宝开放平台（TOP）客户端

    按官方文档实现真实调用流程：
    1. 网关：POST https://eco.taobao.com/router/rest（表单）
    2. 公共参数：method/app_key/session/timestamp(yyyy-MM-dd HH:mm:ss)/format/v/sign_method/sign
    3. 签名：MD5(secret + 按 key 升序 key+value 拼接 + secret) 大写
    4. 业务 API：
       - 商品/价格/库存 taobao.item.get（price 单位元，num 为库存）
       - 订单 taobao.trades.sold.get（payment 单位元）
       - 评论 taobao.traderates.get（result=好评/中评/差评）
    """

    KEY_NAMES = api.TAOBAO_KEY_NAMES
    OAUTH_REFRESH_URL = api.TAOBAO_OAUTH_TOKEN_URL
    OAUTH_ID_FIELD = "client_id"
    PROVIDER = "淘宝开放平台（TOP）"

    _RATE_SENTIMENT = {"差评": "negative", "中评": "neutral", "好评": "positive"}
    _RATE_SCORE = {"差评": 1, "中评": 3, "好评": 5}

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
        """TOP 网关调用，返回 {method}_response 包装内的业务数据"""
        from datetime import datetime

        ak, sk, _, _ = self._resolve_credentials(
            app_key, app_secret, access_token, refresh_token, store_creds=store_creds
        )
        if not (ak and sk):
            raise api.ExternalAPIError(
                "淘宝 TOP 未配置：需要 NEUROVA_TAOBAO_APP_KEY / NEUROVA_TAOBAO_APP_SECRET"
            )
        token = await self._access_token(
            app_key, app_secret, access_token, refresh_token, store_id=store_id, store_creds=store_creds
        )
        params: Dict[str, Any] = {
            "method": method,
            "app_key": ak,
            "session": token,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }
        for k, v in (biz_params or {}).items():
            params[k] = api._stringify_param(v)
        params["sign"] = api._router_sign_md5(sk, params)
        data = await api._http_post(api.TAOBAO_GATEWAY_URL, data=params)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"TOP 响应格式异常: {data}")
        if "error_response" in data:
            err = data.get("error_response") or {}
            raise api.ExternalAPIError(f"TOP 错误 {err.get('code')}: {err.get('sub_msg') or err.get('msg')}")
        key = method.replace(".", "_") + "_response"
        if key in data:
            return data[key] or {}
        for k, v in data.items():
            if k.endswith("_response"):
                return v or {}
        raise api.ExternalAPIError(f"TOP 无法识别的响应: {data}")

    async def fetch_prices(self, num_iids: List[str], **creds) -> Dict[str, Any]:
        """taobao.item.get — 按 num_iid 查询价格（price 单位元）"""
        ids = [str(i).strip() for i in num_iids if str(i).strip()][:20]
        try:
            prices: Dict[str, Any] = {}
            raw_items: List[Dict[str, Any]] = []
            for nid in ids:
                resp = await self.call(
                    "taobao.item.get",
                    {"num_iid": nid, "fields": "num_iid,title,price,num"},
                    **creds,
                )
                item = resp.get("item") or {}
                price = item.get("price")
                try:
                    price_val = float(price) if price is not None else None
                except (TypeError, ValueError):
                    price_val = None
                prices[nid] = {"price": price_val, "currency": "CNY", "title": item.get("title", "")}
                raw_items.append(item)
            return api._ok({"prices": prices, "raw": raw_items}, "taobao")
        except api.ExternalAPIError as exc:
            api.logger.warning("淘宝价格查询失败: %s", exc)
            return api._fail(str(exc), "taobao")

    async def fetch_inventory(self, num_iids: List[str], **creds) -> Dict[str, Any]:
        """taobao.item.get — 按 num_iid 查询库存（num 字段）"""
        ids = [str(i).strip() for i in num_iids if str(i).strip()][:20]
        try:
            inventory: Dict[str, Any] = {}
            for nid in ids:
                resp = await self.call(
                    "taobao.item.get",
                    {"num_iid": nid, "fields": "num_iid,title,num"},
                    **creds,
                )
                item = resp.get("item") or {}
                try:
                    qty = int(item.get("num") or 0)
                except (TypeError, ValueError):
                    qty = 0
                inventory[nid] = {"totalQuantity": qty, "title": item.get("title", "")}
            return api._ok({"inventory": inventory}, "taobao")
        except api.ExternalAPIError as exc:
            api.logger.warning("淘宝库存查询失败: %s", exc)
            return api._fail(str(exc), "taobao")

    async def fetch_sold_trades(
        self, start_created: str = "", end_created: str = "", **creds
    ) -> Dict[str, Any]:
        """taobao.trades.sold.get — 已卖出订单聚合（payment 单位元）"""
        try:
            resp = await self.call(
                "taobao.trades.sold.get",
                {
                    "start_created": start_created,
                    "end_created": end_created,
                    "fields": "tid,type,status,payment,created,pay_time,num_iids,num",
                    "page_no": "1",
                    "page_size": "100",
                },
                **creds,
            )
            trades_wrap = resp.get("trades") or {}
            trades = trades_wrap.get("trade") if isinstance(trades_wrap, dict) else trades_wrap
            trades = trades or []
            total_sales = 0.0
            units = 0
            for t in trades:
                if not isinstance(t, dict):
                    continue
                try:
                    total_sales += float(t.get("payment") or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    units += int(t.get("num") or 0)
                except (TypeError, ValueError):
                    pass
            orders = len(trades)
            return api._ok(
                {
                    "sales": round(total_sales, 2),
                    "orders": orders,
                    "units": units or orders,
                    "avg_order_value": round(total_sales / orders, 2) if orders else 0.0,
                    "order_items": trades,
                    "currency": "CNY",
                },
                "taobao",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("淘宝订单查询失败: %s", exc)
            return api._fail(str(exc), "taobao")

    async def fetch_rates(self, num_iid: str, **creds) -> Dict[str, Any]:
        """taobao.traderates.get — 按 num_iid 拉取商品评论（好评/中评/差评）"""
        try:
            resp = await self.call(
                "taobao.traderates.get",
                {"rate_type": "get", "num_iid": str(num_iid), "page_no": "1", "page_size": "100"},
                **creds,
            )
            rates_wrap = resp.get("rates") or {}
            rates = rates_wrap.get("rate") if isinstance(rates_wrap, dict) else rates_wrap
            items: List[Dict[str, Any]] = []
            for r in rates or []:
                if not isinstance(r, dict):
                    continue
                result = str(r.get("result") or "")
                items.append(
                    {
                        "id": r.get("id"),
                        "content": r.get("content", ""),
                        "sentiment": self._RATE_SENTIMENT.get(result, "positive"),
                        "rating": self._RATE_SCORE.get(result),
                    }
                )
            return api._ok({"items": items, "num_iid": str(num_iid)}, "taobao")
        except api.ExternalAPIError as exc:
            api.logger.warning("淘宝评论查询失败: %s", exc)
            return api._fail(str(exc), "taobao")


TaobaoTopClient.__module__ = api.__name__
TaobaoTopClient.call.__module__ = api.__name__
TaobaoTopClient.fetch_prices.__module__ = api.__name__
TaobaoTopClient.fetch_inventory.__module__ = api.__name__
TaobaoTopClient.fetch_sold_trades.__module__ = api.__name__
TaobaoTopClient.fetch_rates.__module__ = api.__name__


class XianyuClient(TaobaoTopClient):
    """闲鱼开放平台客户端 — 复用 TOP 协议（网关/MD5 签名/OAuth），业务分类为闲鱼

    官方文档（open.goofish.com/doc/quick-start.html）：
    服务端 TOPAPI 经淘宝开放平台"阿里生态API开发 → 闲鱼垂直行业-B端"申请；
    method 命名空间与权限包以"闲鱼开放平台 API 列表"为准。
    """

    KEY_NAMES = api.XIANYU_KEY_NAMES
    PROVIDER = "闲鱼开放平台（TOP 生态）"

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        return api._fail(
            "闲鱼 TOP method 名待官方文档核对（设计 §2.3），协议层（网关/MD5/OAuth）已就绪",
            "xianyu",
        )


XianyuClient.__module__ = api.__name__
XianyuClient.fetch_prices.__module__ = api.__name__
