# -*- coding: utf-8 -*-
"""P2-3（审计 2026-11-04）：Tauri 主窗必须有显式 CSP。

`app.security.csp = null` 时前端一旦出现未消毒注入点，注入脚本可直调
`lib.rs` 自定义命令并携本地凭据访问 9527。CSP 必须至少：
- 默认只允许 self；
- 允许本机后端 9527 与 Tauri IPC；
- 允许 Google Fonts（index.html 在用）；
- 不允许 'unsafe-eval'。
"""
import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_CONF = _REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"
_ERROR_REPORTER = _REPO / "NeurUI" / "src" / "utils" / "errorReporter.ts"


def _conf() -> dict:
    return json.loads(_CONF.read_text(encoding="utf-8"))


def testCspIsExplicitAndCoversTheRealOrigins():
    csp = (_conf().get("app", {}).get("security") or {}).get("csp")
    assert isinstance(csp, str) and csp.strip(), "tauri CSP 仍为 null/空"
    assert "default-src 'self'" in csp
    assert "http://127.0.0.1:9527" in csp, "未放行本机后端"
    assert "ipc:" in csp or "http://ipc.localhost" in csp, "未放行 Tauri IPC"
    assert "fonts.googleapis.com" in csp, "index.html 的 Google Fonts 会被 CSP 拦掉"
    assert "fonts.gstatic.com" in csp
    assert "'unsafe-eval'" not in csp, "不允许为了省事放开 eval"


def testGlobalTauriStaysOnBecauseThereIsAConsumer():
    conf = _conf()
    assert conf["app"].get("withGlobalTauri") is True
    assert "__TAURI__" in _ERROR_REPORTER.read_text(encoding="utf-8"), (
        "withGlobalTauri 的唯一消费方消失后才可关闭；当前 errorReporter 仍在读"
    )
