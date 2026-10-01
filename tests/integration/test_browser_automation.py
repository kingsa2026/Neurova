# -*- coding: utf-8 -*-
"""浏览器选路与状态面判据（原为零断言的 print 脚本，按工单集 §19 D-7 ④ 改写）。

## 原形态为什么必须改

`test_browser_automation` 通篇 `print` 且每步都裹在 `try/except Exception: print(错误)` 里
—— 任何一步坏掉都只是多打一行字，永远不会让一次跑测失败；它还真去导航
`example.com`、`localhost:8080` 并执行 JS。`test_routing_logic` 稍好一点，但它也只是
把"期望后端"和"实际后端"并排打印，`✓/✗` 不参与判定（全 ✗ 也照样"通过"）。

按 `AGENTS.md` §4，临时验证脚本即用即删、不留测试根；但按 D-7 拍板**不删**——
删等于把"这份设计意图存在过"抹掉。所以这里把它改写成无副作用的真断言，
并把旧期望表原样留在注释里作为历史。

## 今天真守得住的两件事

1. 选路的入参形状：目标 URL 绝不会被当成后端名回吐；没配规则时一律走默认优先级链。
2. 状态面的键形状与后端可用性读数（原脚本第 1 步的真实意图）。

## 历史期望表（内置启发式，从未落地）

原脚本按这张表打印期望：`localhost/内网 → playwright`、`cloudflare.com → scrapling-stealthy`、
`SPA 路径 → scrapling-dynamic`。生产里没有这套内置启发式，也没有 `scrapling-stealthy`/
`scrapling-dynamic` 这两个后端名——今天的选路是**配置文件驱动**（`routing.rules`），
没配就是默认链。把它照原样实现会造出与配置面并存的第二套选路口径，故只做反向锁。
"""

from neurova.computer_use.browser_manager import BrowserManager, BrowserResult


def testUrlArgIsNeverEchoedBackAsABackendName():
    """路由的反向锁：入参是 URL 时，返回值只能是后端名。

    把 URL 原样当后端名返回是最坏的一种错——调用方拿到一个"看着像名字"的值，
    下一跳才在 `_get_backend` 处炸，故障点离根因隔了一层。
    """
    manager = BrowserManager(config={})
    resolved = manager._resolve_backend("https://example.com/app/dashboard")
    assert "://" not in resolved, resolved
    assert resolved in set(manager._backends) | {"camofox"}, \
        f"返回了一个既不在册也不是 camofox 的名字：{resolved}"


def testWithoutRoutingRulesEveryUrlTakesTheDefaultChain():
    """没配 `routing.rules` 时不设任何隐式启发式：一律默认优先级链。

    这条钉的是"不要偷偷长出一套内置路由"——那会与配置文件那套并存成两份口径。
    """
    manager = BrowserManager(config={})
    for url in ("http://localhost:3000", "http://127.0.0.1:8080",
                "https://cloudflare.com/test", "https://example.com/app/dashboard"):
        assert manager._routeForUrl(url) is None, f"无规则却命中了内置启发式：{url}"


def testConfiguredRulesWinOverTheDefaultChain():
    """配置面驱动的正对照：规则命中时优先于默认链（与上一条合起来才是完整契约）。"""
    manager = BrowserManager(config={
        "routing": {"rules": [{"pattern": r"cloudflare\.com", "backend": "camofox"}]},
        "backends": {"camofox": {"type": "local"}},
    })
    assert manager._resolve_backend("https://api.cloudflare.com/x") == "camofox"
    assert manager._backend_configs.get("camofox") == {"type": "local"}, manager._backend_configs


def testStatusSurfaceReportsBackendsAndDependencyReadings():
    """状态面的键（原脚本第 1 步逐个 print 的那些）——少一个键就是某项自检静默消失。"""
    status = BrowserManager(config={}).get_status()

    assert {"available_backends", "active_backend", "has_playwright",
            "has_scrapling", "has_websockets", "has_camofox_server", "camofox_url"} <= set(status), \
        sorted(status)
    assert isinstance(status["available_backends"], list)
    assert isinstance(status["has_playwright"], bool)


def testBrowserActionsAreCoroutinesReturningTheResultContract():
    """动作面契约形状：全部是协程且声明返回 `BrowserResult`。

    原脚本用 `result.get("status")` 读返回值——那个键从来不存在（生产返回
    `BrowserResult`，字段是 `success`）。这条把形状写死，免得再有人照 dict 形态写代码。
    """
    import inspect

    manager = BrowserManager(config={})
    for action in ("navigate", "dom_snapshot", "extract_text", "extract_links", "screenshot"):
        method = getattr(manager, action)
        assert inspect.iscoroutinefunction(method), f"{action} 不再是协程"
        annotation = inspect.signature(method).return_annotation
        assert annotation is BrowserResult, f"{action} 的返回契约变了：{annotation!r}"
