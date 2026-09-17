"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class Alibaba1688Client:
    """1688 阿里巴巴开放平台客户端（ocean 网关，协议独立于 TOP）

    - 调用 URL：{gateway}/param2/{version}/{namespace}/{apiName}/{appKey}
    - 签名：HMAC-SHA1（大写十六进制）→ _aop_signature
    - token：param2/1/system.oauth2/getToken/{appKey}（路径已网关探测确认）
    - access_token 作为普通业务参数提交
    """

    KEY_NAMES = api.ALIBABA1688_KEY_NAMES
    PROVIDER = "阿里巴巴开放平台（1688）"

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> tuple:
        ak = app_key or (store_creds.app_key if store_creds else "") or (
            api.resolve_api_key(self.KEY_NAMES.get("app_key", []), "") or ""
        )
        sk = app_secret or (store_creds.app_secret if store_creds else "") or (
            api.resolve_api_key(self.KEY_NAMES.get("app_secret", []), "") or ""
        )
        at = access_token or (store_creds.access_token if store_creds else "") or (
            api.resolve_api_key(self.KEY_NAMES.get("access_token", []), "") or ""
        )
        rt = refresh_token or (store_creds.refresh_token if store_creds else "") or (
            api.resolve_api_key(self.KEY_NAMES.get("refresh_token", []), "") or ""
        )
        return ak, sk, at, rt

    def is_available(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> bool:
        ak, sk, at, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        return bool(ak and sk and (at or rt))

    async def _access_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> str:
        ak, sk, _, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        if access_token:
            return access_token
        cache_key = store_id or "default"
        cached = self._token_cache.get(cache_key) or {}
        if cached.get("token") and cached.get("expires_at", 0) > api.time.time() + 60:
            return str(cached["token"])
        if not rt:
            raise api.ExternalAPIError("1688 未配置 access_token / refresh_token")
        token = await self.fetch_token(app_key=ak, app_secret=sk, refresh_token=rt)
        self._token_cache[cache_key] = {"token": token, "expires_at": api.time.time() + 86400}
        return token

    async def fetch_token(
        self,
        app_key: str = "",
        app_secret: str = "",
        refresh_token: str = "",
        code: str = "",
        redirect_uri: str = "",
    ) -> str:
        """system.oauth2.getToken — 授权码换 token / refresh_token 刷新（路径已核实）"""
        path = f"param2/1/system.oauth2/getToken/{app_key}"
        params: Dict[str, Any] = {"grant_type": "refresh_token", "client_id": app_key, "client_secret": app_secret}
        if code:
            params["grant_type"] = "authorization_code"
            params["code"] = code
            if redirect_uri:
                params["redirect_uri"] = redirect_uri
        else:
            params["refresh_token"] = refresh_token
        params["_aop_signature"] = api._alibaba1688_sign(app_secret, path, params)
        data = await api._http_post(f"{api.ALIBABA1688_GATEWAY_URL}/{path}", data=params)
        payload = (data or {}).get("data") if isinstance(data, dict) else None
        token = (payload or {}).get("access_token") if isinstance(payload, dict) else None
        if not token and isinstance(data, dict):
            token = data.get("access_token")
        if not token:
            raise api.ExternalAPIError(f"1688 令牌获取失败: {data}")
        return str(token)

    async def call(
        self,
        namespace: str,
        api_name: str,
        biz_params: Optional[Dict[str, Any]] = None,
        version: str = "1",
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        refresh_token: str = "",
        store_id: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> Dict[str, Any]:
        ak, sk, at, rt = self._resolve(app_key, app_secret, access_token, refresh_token, store_creds)
        if not (ak and sk):
            raise api.ExternalAPIError("1688 未配置：需要 appKey/appSecret（NEUROVA_1688_API_KEY / 对应 SECRET 键）")
        token = at or await self._access_token(ak, sk, at, rt, store_id=store_id, store_creds=store_creds)
        path = f"param2/{version}/{namespace}/{api_name}/{ak}"
        params: Dict[str, Any] = dict(biz_params or {})
        if token:
            params["access_token"] = token
        params["_aop_signature"] = api._alibaba1688_sign(sk, path, params)
        data = await api._http_post(f"{api.ALIBABA1688_GATEWAY_URL}/{path}", data=params)
        if not isinstance(data, dict):
            raise api.ExternalAPIError(f"1688 响应格式异常: {data}")
        err = str(data.get("error_message") or data.get("errorMessage") or "") or str(data.get("error_code") or "")
        if err:
            raise api.ExternalAPIError(f"1688 错误: {err} {data}")
        return data

    async def fetch_prices(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        """com.alibaba.product/alibaba.product.get — 按 offerId 查询（字段名以官方文档核对为准，防御式提取）"""
        try:
            prices: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                resp = await self.call("com.alibaba.product", "alibaba.product.get", {"offerId": pid}, **creds)
                body = resp if isinstance(resp, dict) else {}
                live = body.get("result") if isinstance(body.get("result"), dict) else body
                prices[pid] = {
                    "price": api._first_float(live, ("price", "offerPrice", "salePrice", "priceInfo")),
                    "currency": "CNY",
                    "title": str(live.get("productName") or live.get("name") or "") if isinstance(live, dict) else "",
                    "raw": body,
                }
            return api._ok({"prices": prices}, "ali1688")
        except api.ExternalAPIError as exc:
            api.logger.warning("1688 价格查询失败: %s", exc)
            return api._fail(str(exc), "ali1688")

    async def fetch_inventory(self, product_ids: Optional[List[str]] = None, **creds) -> Dict[str, Any]:
        try:
            inventory: Dict[str, Any] = {}
            for pid in [str(p).strip() for p in (product_ids or []) if str(p).strip()]:
                resp = await self.call("com.alibaba.product", "alibaba.product.get", {"offerId": pid}, **creds)
                body = resp if isinstance(resp, dict) else {}
                live = body.get("result") if isinstance(body.get("result"), dict) else body
                inventory[pid] = {
                    "totalQuantity": api._first_int(live, ("amountOnSale", "quantity", "stock")),
                    "title": str(live.get("productName") or "") if isinstance(live, dict) else "",
                }
            return api._ok({"inventory": inventory}, "ali1688")
        except api.ExternalAPIError as exc:
            api.logger.warning("1688 库存查询失败: %s", exc)
            return api._fail(str(exc), "ali1688")


Alibaba1688Client.__module__ = api.__name__
Alibaba1688Client.__init__.__module__ = api.__name__
Alibaba1688Client._resolve.__module__ = api.__name__
Alibaba1688Client.is_available.__module__ = api.__name__
Alibaba1688Client._access_token.__module__ = api.__name__
Alibaba1688Client.fetch_token.__module__ = api.__name__
Alibaba1688Client.call.__module__ = api.__name__
Alibaba1688Client.fetch_prices.__module__ = api.__name__
Alibaba1688Client.fetch_inventory.__module__ = api.__name__
