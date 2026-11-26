# -*- coding: utf-8 -*-
"""S2 出站点位 SSRF 复检扫荡——B 类应防护点位清单断言（先红后绿）。

单源：``neurova/security/url_guard.py``（判定）＋ ``safe_fetch`` / ``mcp_transport``
（把判定返回的地址计划固定到本次连接）。B 类点位必须引用这些安全入口之一。

本测试把"外部/用户内容驱动但尚未过 url_guard"的出站点位**硬编码为清单**，
逐点断言其模块已引用 url_guard 单源。点位新增/移除必须同步改本清单并
说明原因（教义第 5 条：同一根因全命中点扫荡；教义第 6 条：单一事实源）。

── 豁免台账（C 类：运维配置基础设施 / 已有等效防护，不套 url_guard）──
- neurova/llm/**（providers、embeddings_channel、rerank_client、provider_usage_adapters）：
  LLM provider base_url 为运维配置，本地模型（ollama/lm_studio）就跑在 127.0.0.1，
  套 guard 会断本地模型。
- neurova/asr/remote_whisper_engine.py：自部署 whisper 服务地址，运维配置。
- neurova/channels/**（dingtalk/feishu/qq/qqbot/qq_ws/wecom/wechat_auth/qrcode_auth/
  telegram_*/qclaw*/sip 等）：第三方平台 API 常量 + 运维配置凭据拼接，URL 主机不受
  用户消息内容影响。
- neurova/tool_executor.py 内 searxng（settings.searxng_url 运维配置的自托管实例，
  常在私网/127.0.0.1）与 Bing/wttr.in（固定公网端点，用户内容仅进 query 参数）。
- neurova/api/endpoints/knowledge_ingestion.py：/import-url 入口先校验，
  _fetch_url 再经 safe_fetch 逐跳固定 DNS。
- neurova/api/endpoints/webhooks.py：create/update/test 共用 URL 闸，test 投递
  经 safe_fetch 固定 DNS。
- neurova/knowledge/adapters.py：远程 URL 判定已收口 url_guard，IMA 默认
  JSON-RPC 传输把解析计划交给 http_fetch.request_once。
- neurova/knowledge/ingest_bridge.py、neurova/web_reach/**、
  neurova/api/endpoints/shared_config.py、neurova/tool_layers/mcp_config.py、
  neurova/tool_layers/mcp_client.py、neurova/tool_layers/mcp_oauth.py、
  neurova/collaboration/neurflow/builtin.py、neurova/security/governance.py：
  已接 url_guard / safe_fetch / mcp_transport 单源（A 类）。
- neurova/plugins/plugin_sources.py：仅允许已注册插件源 host 白名单，且重定向后
  复查最终 host（强于 url_guard 的等效防护）。
- neurova/skills/market_sources.py：仅允许已注册市场源 host 白名单，实际下载
  也经 safe_fetch 固定 DNS，并按单技能包预算限量。
- neurova/api/endpoints/mobile_pairing.py preflight：admin 面对外地址连通性预检，
  auto/direct 模式探测入站来源（合法私网地址是功能本身），套 guard 会断手机配对。
- neurova/agent/neuacp/registry.py：硬编码官方 CDN 常量 REGISTRY_URL，不受用户影响。
- neurova/core/env_check.py：固定官方运行库安装包地址。
- neurova/core/crash_report.py、neurova/telemetry/otlp.py：运维配置的遥测上报端点。
- neurova/tts/model_downloader.py：模型分发源地址（HF_ENDPOINT 等）运维配置。
- neurova/knowledge/enterprise/connectors_lakehouse.py：企业数仓连接器地址，运维配置。
- neurova/skill_system/core.py _search_web：固定 google.com 端点，用户内容仅进 query。
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]

#: B 类点位清单：URL 受外部/用户内容影响、请求前必须过 url_guard 单源。
#: (模块相对路径, 点位说明)
EGRESS_POINTS_REQUIRING_GUARD = [
    (
        "neurova/tool_executor.py",
        "_execute_web_fetch：web_fetch 工具抓取任意 url（模型/用户完全可控），"
        "经 resolvePublicUrl→http_fetch 固定 DNS",
    ),
    (
        "neurova/agent/scheduler.py",
        "WebhookTaskExecutor.execute：automation webhook_url 由任务创建者指定，"
        "POST 经 safe_fetch 逐跳固定 DNS",
    ),
    (
        "neurova/skills/market_adapters.py",
        "_http_get/_download_file：技能市场 API 响应驱动的条目抓取与技能包下载，"
        "download_url 来自远端响应，请求经 safe_fetch",
    ),
    (
        "neurova/skills/hub_client.py",
        "_http_fetch：hub API 拉取与 download_url 技能包下载，请求经 safe_fetch",
    ),
    (
        "neurova/channels/wechat_media.py",
        "iLink 媒体下载：media_url 取自 iLink API 响应体，服务端再经 safe_fetch 拉取",
    ),
]

_GUARD_CALL_RE = re.compile(
    r"assert_public_url|is_public_url|validate_public_http_url|"
    r"resolvePublicUrl|assertHopAllowed|safe_fetch\.safe_fetch"
)
_GUARD_IMPORT_RE = re.compile(
    r"neurova\.security\.(?:url_guard|safe_fetch|mcp_transport)|"
    r"from neurova\.security import safe_fetch"
)


def _moduleSource(rel_path: str) -> str:
    path = _REPO_ROOT / rel_path
    assert path.is_file(), f"点位模块不存在: {path}"
    return path.read_text(encoding="utf-8")


def testB类点位模块已引用UrlGuard单源():
    """逐点断言 B 类模块已 import url_guard 且调用其入口之一。"""
    missing = []
    for rel_path, reason in EGRESS_POINTS_REQUIRING_GUARD:
        source = _moduleSource(rel_path)
        has_import = bool(_GUARD_IMPORT_RE.search(source))
        has_call = bool(_GUARD_CALL_RE.search(source))
        if not (has_import and has_call):
            missing.append(
                f"{rel_path}（{reason}）→ import={has_import}, call={has_call}"
            )
    assert not missing, (
        "以下出站点位受外部/用户内容影响但未过 url_guard 单源（SSRF 面）:\n  "
        + "\n  ".join(missing)
    )


def testB类点位清单无重复无遗漏格式完整():
    """清单卫生：路径唯一、说明非空、路径均在 neurova/ 下。"""
    paths = [p for p, _ in EGRESS_POINTS_REQUIRING_GUARD]
    assert len(paths) == len(set(paths)), "B 类清单存在重复点位"
    for rel_path, reason in EGRESS_POINTS_REQUIRING_GUARD:
        assert rel_path.startswith("neurova/"), f"点位必须落在 neurova/ 内: {rel_path}"
        assert reason.strip(), f"点位缺说明: {rel_path}"
