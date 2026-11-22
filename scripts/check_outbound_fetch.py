# -*- coding: utf-8 -*-
"""出站 HTTP 静态扫描（U2 卡）：neurova/ 下直用 HTTP 库的文件必须登记在案。

口径（教义第 6 条·单一事实源）：
- SSRF 判定单源 = ``neurova/security/url_guard.py``；抓取使能层 =
  ``neurova/security/safe_fetch.py``（逐跳强制 url_guard）与引擎层
  ``neurova/http_fetch.py``（curl_cffi/urllib，不自动跟随）。
- ``neurova/**/*.py`` 中凡直用 ``requests`` / ``httpx`` / ``aiohttp`` /
  ``urllib.request``（含函数内惰性 import 与 ``urlopen(...)`` 调用）的文件，
  必须命中本脚本末尾的 ALLOW_REGISTRY（逐条带理由）——未登记即违规，
  退出码 1。目标：登记表只减不增，遗留逐步清零。
- tests/ 不在扫描范围（测试自行 mock，不做出站）。

用法：``python scripts/check_outbound_fetch.py``（CI/预提交可直挂）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOT = REPO_ROOT / "neurova"

# 直用出站 HTTP 库的形态（行级；函数内惰性 import 同样命中）
_PATTERNS = (
    re.compile(r"^\s*import\s+(requests|httpx|aiohttp)\b"),
    re.compile(r"^\s*from\s+(requests|httpx|aiohttp)\s+import\b"),
    re.compile(r"^\s*import\s+urllib\.request\b"),
    re.compile(r"^\s*from\s+urllib\.request\s+import\b"),
    re.compile(r"^\s*from\s+urllib\s+import\b[^#\n]*\brequest\b"),
    re.compile(r"\burlopen\s*\("),
)

# ══════════════════════════════════════════════════════════════
# 登记表（唯一豁免出处；新增条目必须在 PR 说明理由）
# 目标遗留 = 0：新出站点一律走 safe_fetch / url_guard + http_fetch 通路。
# ══════════════════════════════════════════════════════════════
ALLOW_REGISTRY: dict[str, str] = {
    # ── 安全门与引擎自身 ──
    "neurova/security/safe_fetch.py": "safe_fetch 使能层自身（判定委托 url_guard 单源）",
    "neurova/http_fetch.py": "引擎层：curl_cffi 优先、urllib 兜底（禁自动跟随），经 safe_fetch/validator 契约暴露",
    # ── 已接 url_guard 单源、带等效逐跳/白名单防护的点位 ──
    "neurova/api/endpoints/webhooks.py": "webhook 投递前已过 url_guard 单源复检（U2 卡明确不在本卡范围）",
    "neurova/collaboration/neurflow/builtin.py": "流程节点出站唯一通道 _safe_request 已带等效 SSRF 防护（_validate_outbound_url + 禁跟随 opener）；收口单源属另一张卡",
    "neurova/knowledge/adapters.py": "各远程知识库适配器调用前过 _validate_remote_url（等效 SSRF 校验；收口单源属另一张卡）",
    "neurova/plugins/plugin_sources.py": "仅允许已注册插件源 host 白名单，且重定向后复查最终 host（强于单源判定的等效防护）",
    "neurova/skills/market_sources.py": "仅允许已注册市场源 host 白名单",
    # ── 运维配置端点（base_url 非用户内容驱动；egress 台账 C 类豁免）──
    "neurova/agent/neuacp/registry.py": "硬编码官方 CDN 常量 REGISTRY_URL，不受用户影响",
    "neurova/asr/remote_whisper_engine.py": "自部署 whisper 服务地址，运维配置",
    "neurova/channels/dingtalk.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/discord.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/feishu.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/feishu_auth.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qclaw.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qclaw_service.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qq.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qq_ws.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qqbot.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/qrcode_auth.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/sip.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/telegram_adapter.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/telegram_api_client.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/wechat_auth.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/wechat_ilink_client.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/wechat_kf.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/wechat_messaging.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/channels/wecom.py": "第三方平台 API 常量 + 运维配置凭据拼接",
    "neurova/collaboration/neurflow/comfyui_client.py": "ComfyUI/外部 API 地址，运维配置",
    "neurova/collaboration/neurflow/external_api.py": "外部 API 地址，运维配置",
    "neurova/computer_use/browser_manager.py": "本机浏览器自动化后端（CDP 端口探测），私网是功能本身",
    "neurova/computer_use/camofox_server_backend.py": "本机 camofox 自动化后端，运维配置",
    "neurova/computer_use/camofox_supervisor.py": "本机 camofox 自动化后端，运维配置",
    "neurova/computer_use/capability_state.py": "本机自动化后端能力探测，运维配置",
    "neurova/core/crash_report.py": "运维配置的崩溃上报端点",
    "neurova/core/env_check.py": "固定官方运行库安装包地址",
    "neurova/core/ffmpeg.py": "ffmpeg 资源下载，固定官方地址",
    "neurova/guest_agent/client.py": "guest agent 内部客户端，base_url 运维配置",
    "neurova/knowledge/enterprise/connectors_erp.py": "企业 ERP 连接器地址，运维配置",
    "neurova/knowledge/enterprise/connectors_lakehouse.py": "企业数仓连接器地址，运维配置",
    "neurova/knowledge/mcp_source.py": "MCP 知识源地址，运维配置",
    "neurova/llm/adapters/openai_adapter.py": "LLM provider base_url 运维配置（本地模型就跑在 127.0.0.1）",
    "neurova/llm/embeddings_channel.py": "LLM provider base_url 运维配置",
    "neurova/llm/generators/protocols.py": "LLM provider 实测协议端点，base_url 运维配置",
    "neurova/llm/provider_usage_adapters.py": "LLM provider 用量端点，运维配置",
    "neurova/llm/providers/anthropic_client.py": "LLM provider base_url 运维配置",
    "neurova/llm/providers/anthropic_provider.py": "LLM provider base_url 运维配置",
    "neurova/llm/providers/error_mapping.py": "仅引用 httpx 异常类型做错误归一，无出站请求",
    "neurova/llm/providers/gemini_client.py": "LLM provider base_url 运维配置",
    "neurova/llm/providers/gemini_provider.py": "LLM provider base_url 运维配置",
    "neurova/llm/providers/lm_studio_provider.py": "本地模型端点（127.0.0.1），运维配置",
    "neurova/llm/providers/multimodal_prober.py": "LLM provider 探测端点，运维配置",
    "neurova/llm/providers/ollama_native.py": "本地模型端点（127.0.0.1），运维配置",
    "neurova/llm/providers/ollama_provider.py": "本地模型端点（127.0.0.1），运维配置",
    "neurova/llm/providers/openai_provider.py": "LLM provider base_url 运维配置",
    "neurova/llm/providers/openrouter_provider.py": "LLM provider base_url 运维配置",
    "neurova/llm/rerank_client.py": "LLM rerank 端点，运维配置",
    "neurova/llm_client.py": "LLM provider 客户端，base_url 运维配置",
    "neurova/notifications/negative_screen.py": "负反馈推送端点，运维配置",
    "neurova/notifications/push_sender.py": "推送端点，运维配置",
    "neurova/skill_system/core.py": "_search_web 固定 google.com 端点，用户内容仅进 query 参数",
    "neurova/telemetry/otlp.py": "运维配置的遥测上报端点",
    "neurova/tool_layers/mcp_client.py": "MCP server 地址，运维配置（http 配置门另接 url_guard）",
    "neurova/tool_layers/mcp_oauth.py": "MCP OAuth 端点，运维配置",
    "neurova/tts/model_downloader.py": "模型分发源地址（HF_ENDPOINT 等），运维配置",
    "neurova/tunnel/agent.py": "隧道基础设施端点，运维配置",
    # ── 在途文件（他会话作业中，迁移由对应卡处理）──
    "neurova/agent/scheduler.py": "在途（他会话）：automation webhook_url 出站点，待对应卡接入单源",
    "neurova/api/endpoints/knowledge_ingestion.py": "在途（他会话）：/import-url 抓取出站点（入口已过 validate_public_http_url 单源），逐跳收敛由对应卡处理",
    "neurova/channels/wechat_media.py": "在途（他会话）：iLink 媒体下载出站点，待对应卡接入单源",
    "neurova/skills/hub_client.py": "在途（他会话）：hub API/技能包下载出站点，待对应卡接入单源",
    "neurova/skills/market_adapters.py": "在途（他会话）：市场条目抓取/技能包下载出站点，待对应卡接入单源",
    # ── 功能本身即私网面 ──
    "neurova/api/endpoints/mobile_pairing.py": "手机配对 preflight 探测入站来源，合法私网地址是功能本身",
}


def flagLines(text: str) -> list[str]:
    """返回命中直用 HTTP 库形态的行号（1 起）。"""
    hits = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if any(p.search(line) for p in _PATTERNS):
            hits.append(lineno)
    return hits


def scanTree(root: Path, registry: dict[str, str] | None = None) -> list[dict]:
    """扫描 root 下全部 .py，返回未登记的直用 HTTP 库文件（违规清单）。"""
    registry = ALLOW_REGISTRY if registry is None else registry
    violations = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("tests/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = flagLines(text)
        if not hits:
            continue
        rel_key = "neurova/" + rel if root.name == "neurova" else str(path)
        if rel_key in registry:
            continue
        violations.append({"file": rel_key, "lines": hits[:5], "count": len(hits)})
    return violations


def main(argv: list[str] | None = None) -> int:
    violations = scanTree(SCAN_ROOT)
    if violations:
        print(f"[check_outbound_fetch] 发现 {len(violations)} 个未登记的直用 HTTP 库文件：")
        for v in violations:
            print(f"  ✗ {v['file']}（{v['count']} 处，如 L{',L'.join(map(str, v['lines']))}）")
        print("出站点必须走 neurova.security.safe_fetch（或接 url_guard + http_fetch validator 通路）；")
        print("确有遗留须在 scripts/check_outbound_fetch.py 的 ALLOW_REGISTRY 显式登记并说明理由。")
        return 1
    print(f"[check_outbound_fetch] 通过：neurova/ 下直用 HTTP 库的文件均已登记（{len(ALLOW_REGISTRY)} 条，目标清零）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
