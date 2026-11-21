"""
start_server 静默退出取证——红绿灯 TDD

根因（2026-11-21 凌晨连续两次实测）:
    后端进程以退出码 1 静默消失（03:44:53 与 03:48:4x，server.log 均无任何
    收尾记录）。start_server.main() 的 `except Exception` 接不住 SystemExit
    （uvicorn server.py:118/192 等处以 sys.exit(STARTUP_FAILURE) 终止），
    SystemExit 直接穿透全部日志面，进程零痕迹死亡，事后无法归案。

契约（防回归）:
    main() 遇 SystemExit 时必须：
    1. 不再静默——向 stdout（start.py 已重定向 → server.log）写入点名退出码
       的 fatal 行与抛出点 traceback；
    2. 走 crash_report.report_startup_failure 上报面留底（stage="runtime-exit"）；
    3. 以原退出码返回（进程退出码语义不变）。
"""

import types

import pytest


def test_main_systemexit_is_logged_and_reported_not_silent(monkeypatch, capsys):
    import start_server

    # 装配面全部打桩：本测试只验证"SystemExit 被留痕"，不拉真应用
    monkeypatch.setattr(
        "neurova.core.port_guard.preflightPortAvailable", lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.core.env_check.preflight_torch_runtime", lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.evolution.closed_loop.bootstrap_evolution_persistence",
        lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.evolution.closed_loop.bootstrap_evolution_protections",
        lambda *a, **k: {})
    monkeypatch.setattr(
        "neurova.api.app.create_app",
        lambda *a, **k: types.SimpleNamespace(title="test", version="0"),
    )
    reported = {}
    monkeypatch.setattr(
        "neurova.core.crash_report.report_startup_failure",
        lambda exc, stage, app_version=None: reported.update(stage=stage, exc=exc),
    )

    def _fatal_run(*args, **kwargs):
        raise SystemExit(1)

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", _fatal_run)

    # 红灯判据：修复前 SystemExit 直接穿透 main()，进程零痕迹退出
    result = start_server.main()

    assert result == 1
    out = capsys.readouterr().out
    assert "SystemExit" in out
    assert reported["stage"] == "runtime-exit"
    assert reported["exc"] is not None


def test_main_systemexit_nonint_code_still_returns_one(monkeypatch, capsys):
    import start_server

    monkeypatch.setattr(
        "neurova.core.port_guard.preflightPortAvailable", lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.core.env_check.preflight_torch_runtime", lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.evolution.closed_loop.bootstrap_evolution_persistence",
        lambda *a, **k: None)
    monkeypatch.setattr(
        "neurova.evolution.closed_loop.bootstrap_evolution_protections",
        lambda *a, **k: {})
    monkeypatch.setattr(
        "neurova.api.app.create_app",
        lambda *a, **k: types.SimpleNamespace(title="test", version="0"),
    )
    monkeypatch.setattr(
        "neurova.core.crash_report.report_startup_failure",
        lambda exc, stage, app_version=None: None,
    )

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: (_ for _ in ()).throw(SystemExit("boom")))

    assert start_server.main() == 1
