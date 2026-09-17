"""Platform client implementation; shared dependencies remain on the facade."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import external_api as api


class AmazonAdsClient:
    """Amazon Ads API 客户端 — 独立于 SP-API 的广告开放平台

    - 认证：LWA client_credentials，scope=advertising::campaign_management
    - 请求头：Authorization Bearer + Amazon-Advertising-API-ClientId
      + Amazon-Advertising-API-Scope（profileId）
    - 报表：POST /reporting/reports → 轮询 GET /reporting/reports/{id} → 下载 NDJSON
    """

    def __init__(self) -> None:
        self._token_cache: Dict[str, Any] = {}

    def _resolve_credentials(self, client_id: str = "", client_secret: str = "") -> tuple:
        cid = api.resolve_api_key(api.AMAZON_ADS_KEY_NAMES["client_id"], client_id)
        cs = api.resolve_api_key(api.AMAZON_ADS_KEY_NAMES["client_secret"], client_secret)
        return cid, cs

    def is_available(self, client_id: str = "", client_secret: str = "") -> bool:
        cid, cs = self._resolve_credentials(client_id, client_secret)
        return bool(cid and cs)

    async def get_access_token(self, client_id: str = "", client_secret: str = "") -> str:
        cid, cs = self._resolve_credentials(client_id, client_secret)
        if not (cid and cs):
            raise api.ExternalAPIError(
                "Amazon Ads API 未配置：需要 NEUROVA_AMAZON_ADS_CLIENT_ID / "
                "NEUROVA_AMAZON_ADS_CLIENT_SECRET"
            )
        data = await api._http_post(
            api.AMAZON_LWA_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={
                "grant_type": "client_credentials",
                "scope": "advertising::campaign_management",
                "client_id": cid,
                "client_secret": cs,
            },
        )
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise api.ExternalAPIError(f"Amazon Ads LWA 令牌交换失败: {data}")
        return str(token)

    def _ads_headers(self, token: str, client_id: str, profile_id: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Amazon-Advertising-API-ClientId": str(client_id),
            "Amazon-Advertising-API-Scope": str(profile_id),
            "Content-Type": "application/json",
            "user-agent": "Neurova/1.0 (Language=Python)",
        }

    def _region_base(self, region: str) -> str:
        return api.AMAZON_ADS_REGIONS.get(str(region or "na").lower(), api.AMAZON_ADS_REGIONS["na"])

    async def fetch_campaign_metrics(
        self,
        campaign_ids: List[str],
        metrics: List[str],
        start_date: str,
        end_date: str,
        profile_id: str,
        region: str = "na",
        client_id: str = "",
        client_secret: str = "",
        max_polls: int = 10,
        poll_interval: float = 3.0,
    ) -> Dict[str, Any]:
        """Sponsored Products 活动指标报表（v3 reporting，异步生成）"""
        cid, cs = self._resolve_credentials(client_id, client_secret)
        if not (cid and cs):
            return api._fail("Amazon Ads API 未配置（需 client_id/client_secret）", "amazon-ads")
        if not str(profile_id or "").strip():
            return api._fail("Amazon Ads API 需要 profileId（GET /v2/profiles 获取）", "amazon-ads")
        try:
            token = await self.get_access_token(client_id, client_secret)
            headers = self._ads_headers(token, cid, profile_id)
            base = self._region_base(region)
            columns = ["campaignId", "campaignName"]
            for m in metrics or []:
                col = api.AMAZON_ADS_METRIC_COLUMNS.get(str(m).lower(), str(m))
                if col not in columns:
                    columns.append(col)
            configuration: Dict[str, Any] = {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": ["campaign"],
                "columns": columns,
                "reportTypeId": "spCampaigns",
                "timeUnit": "DAILY",
                "format": "JSON",
            }
            id_list = [str(c).strip() for c in campaign_ids if str(c).strip()]
            if id_list:
                configuration["filters"] = [{"field": "campaignId", "values": id_list}]
            body = {
                "name": "Neurova campaign metrics report",
                "startDate": start_date,
                "endDate": end_date,
                "configuration": configuration,
            }
            submit = await api._http_post(f"{base}/reporting/reports", headers=headers, json=body)
            report_id = submit.get("reportId") if isinstance(submit, dict) else None
            if not report_id:
                return api._fail(f"Amazon Ads 报表创建失败: {submit}", "amazon-ads")
            for _ in range(max_polls):
                status_resp = await api._http_get(
                    f"{base}/reporting/reports/{report_id}", headers=headers
                )
                st = str(status_resp.get("status") or "").upper()
                if st == "COMPLETED":
                    doc_url = status_resp.get("url") or ""
                    rows = await self._download_rows(doc_url)
                    return api._ok(
                        {
                            "items": self._aggregate_rows(rows),
                            "report_id": str(report_id),
                            "raw_rows": rows[:50],
                        },
                        "amazon-ads",
                    )
                if st in ("FAILED", "CANCELLED"):
                    return api._fail(f"Amazon Ads 报表处理失败: {st}", "amazon-ads")
                await api._sleep(poll_interval)
            return api._fail(f"Amazon Ads 报表轮询超时（reportId={report_id}）", "amazon-ads")
        except api.ExternalAPIError as exc:
            api.logger.warning("Amazon Ads 指标查询失败: %s", exc)
            return api._fail(str(exc), "amazon-ads")

    async def _download_rows(self, url: str) -> List[Dict[str, Any]]:
        import json as _json

        if not url:
            return []
        text = await api._http_get_text(url)
        rows: List[Dict[str, Any]] = []
        for line in str(text).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = _json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows

    @staticmethod
    def _aggregate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        aggregated: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            cid = str(row.get("campaignId") or "unknown")
            entry = aggregated.setdefault(
                cid, {"campaign_id": cid, "campaign_name": row.get("campaignName", "")}
            )
            for key, value in row.items():
                if key in ("campaignId", "campaignName"):
                    continue
                if isinstance(value, (int, float)):
                    entry[key] = round(float(entry.get(key, 0)) + float(value), 4)
        return list(aggregated.values())


AmazonAdsClient.__module__ = api.__name__
AmazonAdsClient.__init__.__module__ = api.__name__
AmazonAdsClient._resolve_credentials.__module__ = api.__name__
AmazonAdsClient.is_available.__module__ = api.__name__
AmazonAdsClient.get_access_token.__module__ = api.__name__
AmazonAdsClient._ads_headers.__module__ = api.__name__
AmazonAdsClient._region_base.__module__ = api.__name__
AmazonAdsClient.fetch_campaign_metrics.__module__ = api.__name__
AmazonAdsClient._download_rows.__module__ = api.__name__
AmazonAdsClient._aggregate_rows.__module__ = api.__name__
