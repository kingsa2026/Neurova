"""全自动广告调优的三条硬判据。

1. Amazon Ads 客户端必须真的能写：列活动、改预算/状态、改关键词出价；
2. 监控拿不到真实数据时必须如实标记 simulated，不许把模拟值当成功数据；
3. 写操作必须有闸门：未武装 → 要审批；超预算/出价上限 → 拒绝；已执行 → 幂等去重。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from neurova.collaboration.neurflow import commerce_nodes


class _FakeAdsClient:
    def __init__(self):
        self.listed = []
        self.campaign_updates = []
        self.keyword_updates = []

    async def list_campaigns(self, campaign_ids, profile_id="", region="na", **kwargs):
        self.listed.append({"campaign_ids": list(campaign_ids), "profile_id": profile_id})
        return {
            "status": "success",
            "output": {
                "campaigns": [
                    {"campaignId": "1", "dailyBudget": 100.0, "state": "ENABLED"},
                ]
            },
            "error": None,
            "provider": "amazon-ads",
        }

    async def update_campaigns(self, campaigns, profile_id="", region="na", **kwargs):
        self.campaign_updates.append({"campaigns": campaigns, "profile_id": profile_id})
        return {
            "status": "success",
            "output": {"campaigns": [dict(item, code="SUCCESS") for item in campaigns]},
            "error": None,
            "provider": "amazon-ads",
        }

    async def update_keywords(self, keywords, profile_id="", region="na", **kwargs):
        self.keyword_updates.append({"keywords": keywords, "profile_id": profile_id})
        return {
            "status": "success",
            "output": {"keywords": [dict(item, code="SUCCESS") for item in keywords]},
            "error": None,
            "provider": "amazon-ads",
        }


@pytest.fixture
def adsState(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_AD_ACTION_LEDGER", str(tmp_path / "ad_actions.json"))
    monkeypatch.setenv("NEUROVA_AD_ACTION_AUDIT", str(tmp_path / "ad_actions_audit.jsonl"))
    return tmp_path


class TestCredentialResolution:
    def test_envFallbackWhenSecretStoreHasNoValue(self, monkeypatch):
        """错误文案让设环境变量，解析链就必须读环境变量，否则按提示配置也永远"未配置"。"""
        from neurova.collaboration.neurflow import external_api as api

        monkeypatch.setattr(
            api, "get_secret_store", lambda: SimpleNamespace(get=lambda key: None)
        )
        monkeypatch.setenv("NEUROVA_AMAZON_ADS_CLIENT_ID", "env-client-id")

        assert api.get_api_key("NEUROVA_AMAZON_ADS_CLIENT_ID") == "env-client-id"
        assert api.resolve_api_key(["NEUROVA_AMAZON_ADS_CLIENT_ID"]) == "env-client-id"


class TestAmazonAdsWriteSurface:
    def test_clientExposesWriteMethods(self):
        from neurova.collaboration.neurflow.external_api import get_amazon_ads_client

        client = get_amazon_ads_client()
        for name in ("list_campaigns", "update_campaigns", "update_keywords"):
            assert callable(getattr(client, name, None)), (
                f"Amazon Ads 客户端缺少 {name}：全自动调优没有写入口，"
                "ad-streaming 只能产出计划不能执行"
            )

    @pytest.mark.asyncio
    async def test_updateCampaignsUsesV3VendorHeaderAndPut(self, monkeypatch):
        from neurova.collaboration.neurflow import external_api as api

        client = api.get_amazon_ads_client()
        captured = {}

        async def fakePut(url, headers=None, json=None, **kwargs):
            captured.update({"url": url, "headers": headers, "body": json})
            return {"campaigns": [{"campaignId": "1", "code": "SUCCESS"}]}

        monkeypatch.setattr(api, "_http_put", fakePut, raising=False)
        monkeypatch.setattr(client, "get_access_token", AsyncMock(return_value="tok"))

        result = await client.update_campaigns(
            [{"campaignId": "1", "dailyBudget": 12.5}],
            profile_id="p1",
            region="na",
            client_id="cid",
            client_secret="secret",
        )

        assert result["status"] == "success"
        assert captured["url"].endswith("/sp/campaigns")
        assert captured["headers"]["Accept"] == "application/vnd.spCampaign.v3+json"
        assert captured["headers"]["Content-Type"] == "application/vnd.spCampaign.v3+json"
        assert captured["headers"]["Amazon-Advertising-API-Scope"] == "p1"
        assert captured["body"]["campaigns"][0]["dailyBudget"] == 12.5

    @pytest.mark.asyncio
    async def test_updateKeywordsUsesKeywordVendorHeader(self, monkeypatch):
        from neurova.collaboration.neurflow import external_api as api

        client = api.get_amazon_ads_client()
        captured = {}

        async def fakePut(url, headers=None, json=None, **kwargs):
            captured.update({"url": url, "headers": headers, "body": json})
            return {"keywords": [{"keywordId": "k1", "code": "SUCCESS"}]}

        monkeypatch.setattr(api, "_http_put", fakePut, raising=False)
        monkeypatch.setattr(client, "get_access_token", AsyncMock(return_value="tok"))

        result = await client.update_keywords(
            [{"keywordId": "k1", "bid": 0.75}],
            profile_id="p1",
            client_id="cid",
            client_secret="secret",
        )

        assert result["status"] == "success"
        assert captured["url"].endswith("/sp/keywords")
        assert captured["headers"]["Accept"] == "application/vnd.spKeyword.v3+json"
        assert captured["body"]["keywords"][0]["bid"] == 0.75


class TestAdActionPolicy:
    def _policy(self, monkeypatch, armed=True):
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "1" if armed else "0")
        from neurova.collaboration.neurflow import ad_action_policy

        return ad_action_policy.AdActionPolicy.fromEnv()

    def test_budgetIncreaseOverCapIsDenied(self, monkeypatch):
        policy = self._policy(monkeypatch)
        decision = policy.evaluate("campaign_budget", before=100.0, proposed=200.0)
        assert decision["decision"] == "deny"
        assert any("比例" in reason or "上限" in reason for reason in decision["reasons"])

    def test_budgetIncreaseWithinCapIsAllowedWhenArmed(self, monkeypatch):
        policy = self._policy(monkeypatch, armed=True)
        decision = policy.evaluate("campaign_budget", before=100.0, proposed=120.0)
        assert decision["decision"] == "allow"

    def test_unarmedPolicyNeedsApproval(self, monkeypatch):
        policy = self._policy(monkeypatch, armed=False)
        decision = policy.evaluate("campaign_budget", before=100.0, proposed=120.0)
        assert decision["decision"] == "approval_required"

    def test_bidIncreaseOverCapIsDenied(self, monkeypatch):
        policy = self._policy(monkeypatch)
        decision = policy.evaluate("keyword_bid", before=1.0, proposed=2.0)
        assert decision["decision"] == "deny"

    def test_budgetBelowFloorIsDenied(self, monkeypatch):
        policy = self._policy(monkeypatch)
        decision = policy.evaluate("campaign_budget", before=10.0, proposed=0.5)
        assert decision["decision"] == "deny"
        assert any("下限" in reason for reason in decision["reasons"])

    def test_ledgerDedupesSameActionWithinWindow(self, tmp_path):
        from neurova.collaboration.neurflow import ad_action_policy

        ledger = ad_action_policy.AdActionLedger(
            path=str(tmp_path / "ledger.json"),
            auditPath=str(tmp_path / "audit.jsonl"),
        )
        key = ledger.key({"campaign_id": "1", "daily_budget": 120.0}, windowSeconds=3600)
        assert ledger.isApplied(key) is False
        ledger.record(key, {"status": "applied"})
        assert ledger.isApplied(key) is True
        assert json.loads((tmp_path / "ledger.json").read_text(encoding="utf-8"))["entries"]


class TestAdMonitorHonesty:
    @pytest.mark.asyncio
    async def test_monitorMarksSimulatedWhenApiUnavailable(self):
        failed = {"status": "failed", "output": None, "error": "no creds", "provider": "amazon"}
        with patch.object(
            commerce_nodes.CommercePlatformClient,
            "fetch_ad_metrics",
            AsyncMock(return_value=failed),
        ):
            result = await commerce_nodes.exec_ad_monitor(
                {"platform": "amazon", "ad_ids": "1,2"}, {}
            )

        assert result["status"] == "success"
        assert result["output"]["simulated"] is True
        assert result["output"]["data_quality"] == "simulated"
        assert result["output"]["source"] == "simulated"
        assert any("模拟" in alert.get("message", "") for alert in result["output"]["alerts"])

    @pytest.mark.asyncio
    async def test_monitorMarksRealDataWhenApiAvailable(self):
        real = {
            "status": "success",
            "output": {"items": [{"campaign_id": "1", "impressions": 10, "clicks": 1, "spend": 2.0}]},
            "error": None,
            "provider": "amazon-ads",
        }
        with patch.object(
            commerce_nodes.CommercePlatformClient,
            "fetch_ad_metrics",
            AsyncMock(return_value=real),
        ):
            result = await commerce_nodes.exec_ad_monitor(
                {"platform": "amazon", "ad_ids": "1"}, {}
            )

        assert result["status"] == "success"
        assert result["output"]["simulated"] is False
        assert result["output"]["data_quality"] == "real"


class TestAdStreamingApply:
    def _patchClient(self, monkeypatch, fake):
        monkeypatch.setattr(commerce_nodes, "get_amazon_ads_client", lambda: fake, raising=False)

    @pytest.mark.asyncio
    async def test_applyWithoutArmingNeedsApproval(self, adsState, monkeypatch):
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "0")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)

        result = await commerce_nodes.exec_ad_streaming(
            {
                "platform": "amazon",
                "apply": True,
                "campaign_id": "1",
                "daily_budget": "120",
                "profile_id": "p1",
            },
            {},
        )

        assert result["status"] == "approval_required"
        assert fake.campaign_updates == []
        assert result["proposed"]["daily_budget"] == 120.0

    @pytest.mark.asyncio
    async def test_applyWithinCapExecutesAndDedupes(self, adsState, monkeypatch):
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "1")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)
        config = {
            "platform": "amazon",
            "apply": True,
            "campaign_id": "1",
            "daily_budget": "120",
            "profile_id": "p1",
        }

        first = await commerce_nodes.exec_ad_streaming(config, {})
        second = await commerce_nodes.exec_ad_streaming(config, {})

        assert first["status"] == "applied"
        assert first["result"]["before"]["daily_budget"] == 100.0
        assert first["result"]["after"]["daily_budget"] == 120.0
        assert len(fake.campaign_updates) == 1
        assert second["status"] == "duplicate"
        assert len(fake.campaign_updates) == 1

    @pytest.mark.asyncio
    async def test_nodeConfigCannotArmItself(self, adsState, monkeypatch):
        """画布/提示词里写 auto_apply=true 不能绕过全局武装开关（只能收紧）。"""
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "0")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)

        result = await commerce_nodes.exec_ad_streaming(
            {
                "platform": "amazon",
                "apply": True,
                "campaign_id": "1",
                "daily_budget": "120",
                "profile_id": "p1",
                "auto_apply": "true",
            },
            {},
        )

        assert result["status"] == "approval_required"
        assert fake.campaign_updates == []

    @pytest.mark.asyncio
    async def test_dailyActionCapStopsRunaway(self, adsState, monkeypatch):
        """定时任务连跑时，同一活动的每日落地次数必须有上限。"""
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "1")
        monkeypatch.setenv("NEUROVA_ADS_MAX_ACTIONS_PER_DAY", "1")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)

        base = {
            "platform": "amazon",
            "apply": True,
            "campaign_id": "1",
            "profile_id": "p1",
        }
        first = await commerce_nodes.exec_ad_streaming(dict(base, daily_budget="110"), {})
        second = await commerce_nodes.exec_ad_streaming(dict(base, daily_budget="130"), {})

        assert first["status"] == "applied"
        assert second["status"] == "denied"
        assert "每日上限" in second["error"]
        assert len(fake.campaign_updates) == 1

    @pytest.mark.asyncio
    async def test_applyRefusesSimulatedUpstreamData(self, adsState, monkeypatch):
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "1")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)

        result = await commerce_nodes.exec_ad_streaming(
            {
                "platform": "amazon",
                "apply": True,
                "campaign_id": "1",
                "daily_budget": "120",
                "profile_id": "p1",
            },
            {"inputs": {"input": {"simulated": True}}},
        )

        assert result["status"] == "refused"
        assert fake.campaign_updates == []

    @pytest.mark.asyncio
    async def test_planOnlyStaysSuccessAndSaysNotExecuted(self, adsState, monkeypatch):
        result = await commerce_nodes.exec_ad_streaming(
            {"platform": "amazon", "budget": "1000"}, {}
        )
        assert result["status"] == "success"
        assert result["output"]["executed"] is False
        assert result["output"]["plan_only"] is True

    @pytest.mark.asyncio
    async def test_applyUsesUpstreamProposal(self, adsState, monkeypatch):
        """画布串联：ad-strategy 的 proposal 直接成为 ad-streaming 的目标值。"""
        monkeypatch.setenv("NEUROVA_ADS_AUTO_APPLY", "1")
        fake = _FakeAdsClient()
        self._patchClient(monkeypatch, fake)

        result = await commerce_nodes.exec_ad_streaming(
            {
                "platform": "amazon",
                "apply": True,
                "campaign_id": "1",
                "profile_id": "p1",
            },
            {
                "inputs": {
                    "input": {
                        "proposal": {"action": "campaign_budget", "delta_ratio": -0.10},
                        "simulated": False,
                    }
                }
            },
        )

        assert result["status"] == "applied"
        assert result["result"]["after"]["daily_budget"] == 90.0
        assert len(fake.campaign_updates) == 1


class TestAdStrategyProposal:
    @pytest.mark.asyncio
    async def test_highAcosProposesBudgetCut(self, monkeypatch):
        monkeypatch.setattr(commerce_nodes, "_get_agent", lambda: None)
        ctx = {
            "inputs": {
                "input": {
                    "summary": {"total_spend": 100.0, "total_sales": 50.0},
                    "simulated": False,
                    "metrics": [],
                }
            }
        }

        result = await commerce_nodes.exec_ad_strategy(
            {"platform": "amazon", "goal": "increase_sales"}, ctx
        )

        proposal = result["output"]["proposal"]
        assert result["output"]["data_quality"] == "real"
        assert proposal["action"] == "campaign_budget"
        assert proposal["delta_ratio"] < 0

    @pytest.mark.asyncio
    async def test_readsUpstreamFromWorkflowNodeResults(self, monkeypatch):
        """工作流引擎给的是 node_results[上游].output，不是顶层 inputs。"""
        monkeypatch.setattr(commerce_nodes, "_get_agent", lambda: None)
        ctx = {
            "expected_upstream": ["n2"],
            "node_results": {
                "n2": {
                    "status": "success",
                    "output": {
                        "summary": {"total_spend": 100.0, "total_sales": 50.0},
                        "simulated": False,
                        "metrics": [],
                    },
                }
            },
        }

        result = await commerce_nodes.exec_ad_strategy(
            {"platform": "amazon", "goal": "increase_sales"}, ctx
        )

        assert result["output"]["data_quality"] == "real"
        assert result["output"]["proposal"]["action"] == "campaign_budget"

    @pytest.mark.asyncio
    async def test_simulatedMetricsProposeNothing(self, monkeypatch):
        monkeypatch.setattr(commerce_nodes, "_get_agent", lambda: None)
        ctx = {
            "inputs": {
                "input": {
                    "summary": {"total_spend": 100.0, "total_sales": 50.0},
                    "simulated": True,
                    "metrics": [],
                }
            }
        }

        result = await commerce_nodes.exec_ad_strategy(
            {"platform": "amazon", "goal": "increase_sales"}, ctx
        )

        proposal = result["output"]["proposal"]
        assert result["output"]["data_quality"] == "simulated"
        assert proposal["action"] == "none"
        assert "模拟" in proposal["reason"]
