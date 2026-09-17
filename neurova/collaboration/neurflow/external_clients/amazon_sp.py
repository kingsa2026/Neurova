"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class AmazonSPAPIClient:
    """Amazon Selling Partner API 客户端（深模块）

    按官方文档实现真实调用流程：
    1. LWA 令牌交换：POST https://api.amazon.com/auth/o2/token
       form: grant_type=refresh_token & refresh_token & client_id & client_secret
    2. 区域端点 + 请求头：x-amz-access-token / x-amz-date / user-agent
    3. 各业务 API：
       - 价格   GET /products/pricing/v0/pricing（Product Pricing API v0）
       - 竞价   GET /products/pricing/v0/competitivePrice
       - 库存   GET /fba/inventory/v1/summaries（FBA Inventory API v1）
       - 评论   GET /customerFeedback/2024-06-01/items/{asin}/reviews/topics
       - 报表   POST /reports/2021-06-30/reports → getReport → getReportDocument
    """

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve_credentials(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> tuple:
        store_rt = store_creds.refresh_token if store_creds else ""
        store_cid = store_creds.app_key if store_creds else ""
        store_cs = store_creds.app_secret if store_creds else ""
        rt = refresh_token or store_rt or (api.resolve_api_key(api.AMAZON_SP_KEY_NAMES["refresh_token"], "") or "")
        cid = client_id or store_cid or (api.resolve_api_key(api.AMAZON_SP_KEY_NAMES["client_id"], "") or "")
        cs = client_secret or store_cs or (api.resolve_api_key(api.AMAZON_SP_KEY_NAMES["client_secret"], "") or "")
        return rt, cid, cs

    def is_available(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> bool:
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret, store_creds)
        return bool(rt and cid and cs)

    async def get_access_token(
        self, refresh_token: str = "", client_id: str = "", client_secret: str = ""
    ) -> str:
        """LWA 令牌交换，返回 access_token（有效期约 3600 秒）"""
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret)
        if not (rt and cid and cs):
            raise api.ExternalAPIError(
                "Amazon SP-API 未配置：需要 NEUROVA_AMAZON_SP_REFRESH_TOKEN / "
                "NEUROVA_AMAZON_SP_CLIENT_ID / NEUROVA_AMAZON_SP_CLIENT_SECRET"
            )
        data = await api._http_post(
            api.AMAZON_LWA_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": cid,
                "client_secret": cs,
            },
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise api.ExternalAPIError(f"LWA 令牌交换失败: {data}")
        return str(token)

    async def _access_token(
        self,
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        store_creds: Optional["StoreCredentials"] = None,
    ) -> str:
        import time

        now = time.time()
        rt, cid, cs = self._resolve_credentials(refresh_token, client_id, client_secret, store_creds)
        # 缓存按 (client_id, refresh_token 尾缀) 指纹隔离多店铺，不新增签名改动
        cache_key = f"{cid}|{rt[-6:] if len(rt) >= 6 else rt}"
        cached = self._token_cache.get(cache_key) or {}
        if cached.get("token") and cached.get("expires_at", 0) > now + 60:
            return str(cached["token"])
        token = await self.get_access_token(rt, cid, cs)
        self._token_cache[cache_key] = {"token": token, "expires_at": now + 3540}
        return token

    def _sp_headers(self, access_token: str) -> Dict[str, str]:
        from datetime import datetime, timezone

        return {
            "x-amz-access-token": access_token,
            "x-amz-date": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "user-agent": "Neurova/1.0 (Language=Python)",
            "Content-Type": "application/json",
        }

    def _region_base(self, region: str) -> str:
        return api.AMAZON_SP_REGIONS.get(str(region or "na").lower(), api.AMAZON_SP_REGIONS["na"])

    def resolve_marketplace_id(self, marketplace_id: str) -> str:
        """接受国家代码（US/DE/JP...）或原始 MarketplaceId"""
        mid = str(marketplace_id or "").strip()
        if not mid:
            return api.AMAZON_SP_MARKETPLACES["US"]
        return api.AMAZON_SP_MARKETPLACES.get(mid.upper(), mid)

    @staticmethod
    def _extract_offer_price(item: Dict[str, Any]) -> Dict[str, Any]:
        product = item.get("product") or {}
        best: Optional[Dict[str, Any]] = None
        for offer in product.get("offers") or []:
            for key in ("buyingPrice", "listingPrice"):
                money = offer.get(key) or {}
                amount = money.get("amount")
                if amount is None:
                    continue
                try:
                    price = float(amount)
                except (TypeError, ValueError):
                    continue
                if best is None or price < best["price"]:
                    best = {"price": price, "currency": str(money.get("currencyCode") or "")}
        return best or {"price": None, "currency": ""}

    async def fetch_prices(
        self,
        asins: List[str],
        marketplace_id: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Product Pricing API v0 getPricing — 按 ASIN 批量查询价格"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return api._fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin_list = [str(a).strip() for a in asins if str(a).strip()]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/products/pricing/v0/pricing"
            data = await api._http_get(
                url,
                headers=self._sp_headers(token),
                params={"MarketplaceId": mid, "ItemType": "Asin", "Asins": ",".join(asin_list)},
            )
            payload = data.get("payload") or []
            prices: Dict[str, Any] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                asin = item.get("asin")
                if not asin:
                    identifiers = (item.get("identifiers") or {})
                    asin = identifiers.get("asin")
                if asin:
                    prices[str(asin)] = self._extract_offer_price(item)
            return api._ok({"prices": prices, "marketplace_id": mid, "raw": payload}, "amazon")
        except api.ExternalAPIError as exc:
            api.logger.warning("SP-API 价格查询失败: %s", exc)
            return api._fail(str(exc), "amazon")

    async def fetch_competitive_prices(
        self,
        asins: List[str],
        marketplace_id: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Product Pricing API v0 getCompetitivePricing — 竞品竞价（Buy Box 等）"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return api._fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin_list = [str(a).strip() for a in asins if str(a).strip()]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/products/pricing/v0/competitivePrice"
            data = await api._http_get(
                url,
                headers=self._sp_headers(token),
                params={"MarketplaceId": mid, "ItemType": "Asin", "Asins": ",".join(asin_list)},
            )
            payload = data.get("payload") or []
            prices: Dict[str, Any] = {}
            for item in payload:
                if not isinstance(item, dict):
                    continue
                asin = item.get("asin")
                if not asin:
                    continue
                product = item.get("product") or {}
                competitive = product.get("competitivePricing") or {}
                best: Optional[Dict[str, Any]] = None
                for cp in competitive.get("competitivePrices") or []:
                    price_obj = (cp or {}).get("price") or {}
                    for key in ("landedPrice", "listingPrice"):
                        money = price_obj.get(key) or {}
                        amount = money.get("amount")
                        if amount is None:
                            continue
                        try:
                            price = float(amount)
                        except (TypeError, ValueError):
                            continue
                        if best is None or price < best["price"]:
                            best = {"price": price, "currency": str(money.get("currencyCode") or "")}
                prices[str(asin)] = best or {"price": None, "currency": ""}
            return api._ok({"prices": prices, "marketplace_id": mid, "raw": payload}, "amazon")
        except api.ExternalAPIError as exc:
            api.logger.warning("SP-API 竞价查询失败: %s", exc)
            return api._fail(str(exc), "amazon")

    async def fetch_inventory(
        self,
        skus: List[str],
        marketplace_id: str = "",
        region: str = "na",
        seller_id: str = "",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """FBA Inventory API v1 getInventorySummaries — FBA 库存汇总（sellerSkus ≤ 50）"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return api._fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        sku_list = [str(s).strip() for s in skus if str(s).strip()][:50]
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            params: Dict[str, Any] = {
                "granularityType": "Marketplace",
                "granularityId": mid,
                "marketplaceIds": mid,
                "details": "true",
            }
            if sku_list:
                params["sellerSkus"] = ",".join(sku_list)
            if seller_id:
                params["sellerId"] = str(seller_id).strip()
            url = f"{self._region_base(region)}/fba/inventory/v1/summaries"
            data = await api._http_get(url, headers=self._sp_headers(token), params=params)
            payload = data.get("payload") or {}
            inventory: Dict[str, Any] = {}
            for row in payload.get("inventorySummaries") or []:
                if not isinstance(row, dict):
                    continue
                sku = row.get("sellerSku")
                if not sku:
                    continue
                details = row.get("inventoryDetails") or {}
                inventory[str(sku)] = {
                    "asin": row.get("asin", ""),
                    "totalQuantity": row.get("totalQuantity", 0),
                    "fulfillableQuantity": details.get("fulfillableQuantity", 0),
                }
            return api._ok({"inventory": inventory, "marketplace_id": mid, "raw": payload}, "amazon")
        except api.ExternalAPIError as exc:
            api.logger.warning("SP-API 库存查询失败: %s", exc)
            return api._fail(str(exc), "amazon")

    async def fetch_review_topics(
        self,
        asin: str,
        marketplace_id: str = "",
        region: str = "na",
        sort_by: str = "MENTIONS",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Customer Feedback API v2024-06-01 getItemReviewTopics

        返回 ASIN 的正面/负面评论主题洞察（含评论片段）。
        注意：SP-API 不提供原始评论拉取与回复提交，仅提供主题洞察。
        """
        if not self.is_available(refresh_token, client_id, client_secret):
            return api._fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        asin = str(asin or "").strip()
        if not asin:
            return api._fail("Customer Feedback API 需要 ASIN", "amazon")
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            mid = self.resolve_marketplace_id(marketplace_id)
            url = f"{self._region_base(region)}/customerFeedback/2024-06-01/items/{asin}/reviews/topics"
            data = await api._http_get(
                url,
                headers=self._sp_headers(token),
                params={"marketplaceId": mid, "sortBy": sort_by or "MENTIONS"},
            )
            topics = data.get("topics") or {}
            return api._ok(
                {
                    "asin": asin,
                    "marketplace_id": mid,
                    "positive_topics": topics.get("positiveTopics") or [],
                    "negative_topics": topics.get("negativeTopics") or [],
                    "raw": data,
                },
                "amazon",
            )
        except api.ExternalAPIError as exc:
            api.logger.warning("SP-API 评论洞察查询失败: %s", exc)
            return api._fail(str(exc), "amazon")

    async def create_report(
        self,
        report_type: str,
        marketplace_ids: List[str],
        data_start_time: str = "",
        data_end_time: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API v2021-06-30 createReport"""
        if not self.is_available(refresh_token, client_id, client_secret):
            return api._fail("Amazon SP-API 未配置（需 refresh_token/client_id/client_secret）", "amazon")
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            body: Dict[str, Any] = {
                "reportType": str(report_type),
                "marketplaceIds": [self.resolve_marketplace_id(m) for m in marketplace_ids]
                or [api.AMAZON_SP_MARKETPLACES["US"]],
            }
            if data_start_time:
                body["dataStartTime"] = data_start_time
            if data_end_time:
                body["dataEndTime"] = data_end_time
            url = f"{self._region_base(region)}/reports/2021-06-30/reports"
            data = await api._http_post(url, headers=self._sp_headers(token), json=body)
            report_id = data.get("reportId") if isinstance(data, dict) else None
            if not report_id:
                return api._fail(f"createReport 未返回 reportId: {data}", "amazon")
            return api._ok({"reportId": str(report_id)}, "amazon")
        except api.ExternalAPIError as exc:
            api.logger.warning("SP-API createReport 失败: %s", exc)
            return api._fail(str(exc), "amazon")

    async def get_report(
        self,
        report_id: str,
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API getReport — 查询报表处理状态"""
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            url = f"{self._region_base(region)}/reports/2021-06-30/reports/{report_id}"
            data = await api._http_get(url, headers=self._sp_headers(token))
            return api._ok(data.get("payload") or {}, "amazon")
        except api.ExternalAPIError as exc:
            return api._fail(str(exc), "amazon")

    async def get_report_document(
        self,
        report_document_id: str,
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
    ) -> Dict[str, Any]:
        """Reports API getReportDocument — 获取报表文档下载地址"""
        try:
            token = await self._access_token(refresh_token, client_id, client_secret)
            url = f"{self._region_base(region)}/reports/2021-06-30/documents/{report_document_id}"
            data = await api._http_get(url, headers=self._sp_headers(token))
            return api._ok(data.get("payload") or {}, "amazon")
        except api.ExternalAPIError as exc:
            return api._fail(str(exc), "amazon")

    async def fetch_sales_report(
        self,
        report_type: str,
        marketplace_ids: List[str],
        data_start_time: str = "",
        data_end_time: str = "",
        region: str = "na",
        refresh_token: str = "",
        client_id: str = "",
        client_secret: str = "",
        max_polls: int = 10,
        poll_interval: float = 5.0,
    ) -> Dict[str, Any]:
        """完整报表流程：createReport → 轮询 getReport → getReportDocument"""
        created = await self.create_report(
            report_type=report_type,
            marketplace_ids=marketplace_ids,
            data_start_time=data_start_time,
            data_end_time=data_end_time,
            region=region,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
        if created.get("status") != "success":
            return created
        report_id = created["output"]["reportId"]
        fatal_status = {"CANCELLED", "FATAL"}
        for _ in range(max_polls):
            got = await self.get_report(
                report_id, region, refresh_token, client_id, client_secret
            )
            if got.get("status") != "success":
                return got
            payload = got.get("output") or {}
            status = str(payload.get("processingStatus") or "").upper()
            if status == "DONE":
                doc_id = payload.get("reportDocumentId") or ""
                doc = await self.get_report_document(
                    doc_id, region, refresh_token, client_id, client_secret
                )
                if doc.get("status") != "success":
                    return doc
                return api._ok(
                    {
                        "report_id": report_id,
                        "report_document_id": doc_id,
                        "document_url": (doc.get("output") or {}).get("url"),
                        "processing_status": "DONE",
                        "report_type": report_type,
                    },
                    "amazon",
                )
            if status in fatal_status:
                return api._fail(f"SP-API 报表处理失败: {status}", "amazon")
            await api._sleep(poll_interval)
        return api._fail(f"SP-API 报表轮询超时（reportId={report_id}）", "amazon")


AmazonSPAPIClient.__module__ = api.__name__
AmazonSPAPIClient.__init__.__module__ = api.__name__
AmazonSPAPIClient._resolve_credentials.__module__ = api.__name__
AmazonSPAPIClient.is_available.__module__ = api.__name__
AmazonSPAPIClient.get_access_token.__module__ = api.__name__
AmazonSPAPIClient._access_token.__module__ = api.__name__
AmazonSPAPIClient._sp_headers.__module__ = api.__name__
AmazonSPAPIClient._region_base.__module__ = api.__name__
AmazonSPAPIClient.resolve_marketplace_id.__module__ = api.__name__
AmazonSPAPIClient._extract_offer_price.__module__ = api.__name__
AmazonSPAPIClient.fetch_prices.__module__ = api.__name__
AmazonSPAPIClient.fetch_competitive_prices.__module__ = api.__name__
AmazonSPAPIClient.fetch_inventory.__module__ = api.__name__
AmazonSPAPIClient.fetch_review_topics.__module__ = api.__name__
AmazonSPAPIClient.create_report.__module__ = api.__name__
AmazonSPAPIClient.get_report.__module__ = api.__name__
AmazonSPAPIClient.get_report_document.__module__ = api.__name__
AmazonSPAPIClient.fetch_sales_report.__module__ = api.__name__
