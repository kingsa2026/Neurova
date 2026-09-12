# -*- coding: utf-8 -*-
"""工厂消费 QwenPaw 规范键（照搬参数表后后端必须真实吃到）。

前端字段表对齐 QwenPaw 后，凭据经 extra 传入。_create_adapter 必须：
1. 优先消费 QwenPaw 规范键（dingtalk: client_id/client_secret；feishu: domain；
   wechat: base_url/bot_token_file；qq: app_id/client_secret 即可认证——官方
   Bot {appid}.{token} 头已废弃，token 不再是必需）；
2. 兼容旧 NV 顶层 app_id/app_secret（存量配置与 needs_scan 路径不回归）。

全程离线：requests/httpx 网络面打桩（工厂/认证不得在单测出网）。

wecom 不移名：QwenPaw wecom=智能机器人（bot_id+secret+ws），NV wecom=企业应用
（corpid+agentid+回调），不同产品协议——bot_id→corpid 假映射属"表面抹除"，
登记为协议移植后续项。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from neurova.api.endpoints.channel_config import _create_adapter
from neurova.channels.base import ChannelConfig


class _DeadResponse:
    status_code = 500

    def json(self):
        return {}

    def raise_for_status(self):
        raise RuntimeError("offline")


class _DeadRequests:
    """工厂认证网络面替身：属性存在即可，调用一律失败（诚实反映未配置）。"""

    class exceptions:  # noqa: N801 - 镜像 requests.exceptions 命名空间
        class RequestException(Exception):
            pass

    @staticmethod
    def post(*a, **k):
        return _DeadResponse()

    @staticmethod
    def get(*a, **k):
        return _DeadResponse()


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import neurova.channels.qq as qq_mod

    monkeypatch.setattr(qq_mod, "requests", _DeadRequests)

    # wechat 认证链：不真连 iLink 验证（token 直通断言用）
    from neurova.channels.wechat_auth import WeChatAuthMixin

    monkeypatch.setattr(WeChatAuthMixin, "_verify_ilink_token", lambda self: True)


def _cfg(channel_type, **top):
    return ChannelConfig(channel_type=channel_type, enabled=True, **top)


# ------------------------------------------------------------------
# 保存端点的 QwenPaw 键提升（掩码回读/身份冲突依赖规范键）
# ------------------------------------------------------------------


def test_promote_dingtalk_client_id_to_canonical():
    from neurova.api.endpoints.channel_config import ChannelConfigRequest, _promote_qp_credentials

    req = ChannelConfigRequest(
        channel_type="dingtalk",
        app_id="",
        app_secret="",
        extra={"client_id": "ci-9", "client_secret": "cs-9"},
    )
    _promote_qp_credentials("dingtalk", req)
    assert req.app_id == "ci-9"
    assert req.app_secret == "cs-9"


def test_promote_never_clobbers_top_level():
    from neurova.api.endpoints.channel_config import ChannelConfigRequest, _promote_qp_credentials

    req = ChannelConfigRequest(
        channel_type="dingtalk", app_id="top", app_secret="", extra={"client_id": "ci-9"}
    )
    _promote_qp_credentials("dingtalk", req)
    assert req.app_id == "top"


def test_wecom_not_promoted_different_protocol():
    """wecom：QwenPaw=智能机器人(bot_id)，NV=企业应用(corpid)——不同协议禁假映射。"""
    from neurova.api.endpoints.channel_config import ChannelConfigRequest, _promote_qp_credentials

    req = ChannelConfigRequest(channel_type="wecom", app_id="", extra={"bot_id": "bid"})
    _promote_qp_credentials("wecom", req)
    assert req.app_id == ""


# ------------------------------------------------------------------
# 钉钉：QwenPaw 用 client_id/client_secret
# ------------------------------------------------------------------


def test_dingtalk_consumes_client_id_secret_from_extra():
    adapter = _create_adapter(
        "dingtalk",
        _cfg("dingtalk", extra={"client_id": "ding-abc", "client_secret": "ding-sec"}),
    )
    assert adapter.config.app_id == "ding-abc"
    assert adapter.config.app_secret == "ding-sec"


def test_dingtalk_legacy_top_level_still_works():
    adapter = _create_adapter(
        "dingtalk", _cfg("dingtalk", app_id="legacy-id", app_secret="legacy-sec")
    )
    assert adapter.config.app_id == "legacy-id"


# ------------------------------------------------------------------
# 飞书：domain 必须透传到 adapter（照搬 QwenPaw feishu 参数）
# ------------------------------------------------------------------


def test_feishu_domain_forwarded_to_adapter():
    adapter = _create_adapter(
        "feishu", _cfg("feishu", app_id="fs", app_secret="sec", extra={"domain": "lark"})
    )
    assert adapter.config.extra.get("domain") == "lark"
    # domain 消费：lark → open.larksuite.com（QwenPaw FeishuConfig.domain 语义）
    assert adapter.api_base.startswith("https://open.larksuite.com")


# ------------------------------------------------------------------
# QQ：app_id+client_secret 即认证（官方 v2，token 已废弃为必需）
# ------------------------------------------------------------------


def test_qq_consumes_client_secret_from_extra():
    adapter = _create_adapter(
        "qq", _cfg("qq", extra={"app_id": "qq-app", "client_secret": "qq-cs"})
    )
    assert adapter.app_id == "qq-app"
    assert adapter.secret == "qq-cs"


# ------------------------------------------------------------------
# 微信 iLink：工厂路由到真实协议新适配器（端到端重建）；wecom 模式留旧路
# ------------------------------------------------------------------


def test_wechat_ilink_factory_routes_to_real_protocol_adapter(tmp_path):
    from neurova.channels.wechat_ilink import WeChatILinkAdapter

    adapter = _create_adapter(
        "wechat",
        _cfg(
            "wechat",
            extra={
                "mode": "ilink",
                "base_url": "https://gw.custom.example",
                "bot_token": "tok-xyz",
                "bot_token_file": str(tmp_path / "wx_token"),
            },
        ),
    )
    assert isinstance(adapter, WeChatILinkAdapter), "ilink 必须走真实协议适配器"
    assert adapter._base_url == "https://gw.custom.example"
    assert adapter._bot_token == "tok-xyz"
    # QwenPaw 键名 bot_token_file 映射为 NV 的 token_file
    assert adapter._token_file == str(tmp_path / "wx_token")


def test_wechat_wecom_mode_stays_on_legacy_adapter():
    from neurova.channels.wechat import WeChatAdapter
    from neurova.channels.wechat_ilink import WeChatILinkAdapter

    adapter = _create_adapter(
        "wechat", _cfg("wechat", extra={"mode": "wecom", "corpid": "", "corpsecret": ""})
    )
    assert isinstance(adapter, WeChatAdapter)
    assert not isinstance(adapter, WeChatILinkAdapter)
