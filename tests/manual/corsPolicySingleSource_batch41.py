# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-14 批 41，§6-199）：CORS 口径单源，面板显示的必须是正在生效的那份。

判据档在 tmp 里比两侧；这一支要在**真 create_app + 真 HTTP 路由**上读，因为收口的对象是
「装配进中间件的那一份」与「管理面板回显的那一份」是不是同一个东西。中间件那侧一律按
`app.user_middleware` 里 CORSMiddleware 的**装配实参**读——那才是真正决定预检结果的输入。

1. 默认档（env 未设、配置文件缺失）：桌面壳 origin 预检 200 + ACAO 回显；
2. 同一 app 里非白名单 origin 预检仍 400（安全语义不回退）；
3. 默认档：面板回显 == 装配实参；
4. 设了 `NEUROVA_CORS_ORIGINS`：面板回显 == 装配实参 == env 那两条
   （建档时的缺陷正是面板显示了一份没在生效的清单）；
5. 同一档下面板与装配**逐键**相等（origins/credentials/methods/headers 四项一起比）；
6. env 压着时 PUT：落盘的是提交值，回执报的是生效值——写文件 ≠ 生效，本批把这件事摆到台面上；
7. 全程仓内真 `config/cors.json` 字节不变（2026-09 dee84dc 那次污染入库的复发面）；
8. 文件档（无 env + 文件写了自定义 origin 与 allow_credentials=false）：面板与预检一起改成
   文件值、装配实参里的凭证开关也跟着翻，默认那份桌面壳 origin 当场失效
   ——两侧一起变，才叫同一个来源；
9. 反向校准 A：把单源默认值里的桌面壳 origin 摘掉 ⇒ 预检必须 400（装配真从单源取）；
10. 反向校准 B：把单源 allow_headers 里的 X-Request-ID 摘掉 ⇒ 带该头的预检必须 400；
11. 撤桩复证：默认档预检回 200（不是桩件留下的假绿/假红）；
12. 装配点读数：setup_middleware 的 CORS 实参仍从单源取，且不再有第二份字面量清单。

每档都重建一次应用：CORS 实参在 `setup_middleware` 那一刻定格，改 env/改桩后不重建就量不到
新口径。这里不起 lifespan（不用 `with client:`）——CORS 中间件与这两个设置端点都不依赖启动装配，
而跑启动会把每次重建拖到分钟级。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/corsPolicySingleSource_batch41.py`
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaCorsB41")
REPO_CORS_FILE = Path(__file__).resolve().parents[2] / "config" / "cors.json"

from fastapi.testclient import TestClient  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

failures: list[str] = []

ENV_KEY = "NEUROVA_CORS_ORIGINS"
TAURI = "http://tauri.localhost"
ADMIN = {"user_id": "live-b41", "username": "live-b41", "role": "admin", "neuser_id": "live-b41"}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<absent>"


def _assembledCors(app) -> dict:
    """真应用里 CORSMiddleware 的装配实参——中间件那侧的生效值就是这一份。"""
    entries = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(entries) == 1, f"真应用装配了 {len(entries)} 处 CORS 中间件，期望 1 处"
    return entries[0].kwargs


def buildClient():
    """真造一个应用（create_app 有单例，须先摘掉才会按当前 env/桩件重新装配 CORS）。"""
    import neurova.api.app as APPMOD
    from neurova.api import auth as AUTH

    APPMOD._app_instance = None
    app = APPMOD.create_app()
    app.dependency_overrides[AUTH.get_current_user] = lambda: dict(ADMIN)
    app.dependency_overrides[AUTH.get_current_userWithQueryToken] = lambda: dict(ADMIN)
    return TestClient(app, raise_server_exceptions=False)


def _preflight(client: TestClient, origin: str, req_headers: str = "content-type"):
    return client.options("/api/v1/auth/register",
                          headers={"Origin": origin,
                                   "Access-Control-Request-Method": "POST",
                                   "Access-Control-Request-Headers": req_headers})


def main() -> int:
    import os

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b41_secret_key_for_p0_fixes_0123"
    os.environ.pop(ENV_KEY, None)

    from neurova.api import cors_policy as CP
    from neurova.api import middleware as MW

    repoDigestBefore = _digest(REPO_CORS_FILE)
    absent = WORK_ROOT / "absent" / "cors.json"
    originalConfigFile = CP.configFile

    # ---------------------------------------------------------------- 默认档
    CP.configFile = lambda: absent
    try:
        client = buildClient()
        r = _preflight(client, TAURI)
        check("[1] 默认档（env 未设、无配置文件）桌面壳预检 200 且回显 ACAO",
              r.status_code == 200 and r.headers.get("access-control-allow-origin") == TAURI,
              f"{r.status_code} {r.text[:120]}")

        r2 = _preflight(client, "https://evil-b41.test")
        check("[2] 非白名单 origin 预检仍 400（安全语义不回退）",
              r2.status_code == 400, f"{r2.status_code} {r2.text[:100]}")

        shown = client.get("/api/v1/settings/cors").json()
        asm = _assembledCors(client.app)
        check("[3] 默认档：面板回显与装配实参同值",
              shown["origins"] == asm["allow_origins"], f"面板={str(shown['origins'])[:90]}")
    finally:
        CP.configFile = originalConfigFile

    # ---------------------------------------------------------------- env 档
    envPair = ["http://env-b41-one.test", "http://env-b41-two.test"]
    os.environ[ENV_KEY] = ", ".join(envPair)
    cfgPath = WORK_ROOT / "cors-under-env.json"
    CP.configFile = lambda: cfgPath
    try:
        client = buildClient()
        shown = client.get("/api/v1/settings/cors").json()
        asm = _assembledCors(client.app)
        check("[4] 设了 env：面板显示的就是装配进中间件的那份（建档时这里显示的是一份没生效的清单）",
              sorted(shown["origins"]) == sorted(envPair) == sorted(asm["allow_origins"]),
              f"面板={str(shown['origins'])[:70]} 装配={str(asm['allow_origins'])[:70]}")
        check("[5] 同一档下面板与装配逐键相等（origins/credentials/methods/headers 四项）",
              {"origins": asm["allow_origins"], "allow_credentials": asm["allow_credentials"],
               "allow_methods": asm["allow_methods"], "allow_headers": asm["allow_headers"]}
              == {k: shown[k] for k in ("origins", "allow_credentials",
                                        "allow_methods", "allow_headers")})

        wrote = ["http://written-b41.test"]
        put = client.put("/api/v1/settings/cors", json={"origins": wrote})
        body = put.json() if put.headers.get("content-type", "").startswith("application/json") else {}
        onDisk = json.loads(cfgPath.read_text(encoding="utf-8")).get("origins")
        check("[6] env 压着时 PUT：落盘的是提交值，回执报的是生效值（写文件≠生效，不再糊过去）",
              put.status_code == 200 and onDisk == wrote and body.get("origins") == envPair,
              f"{put.status_code} 落盘={onDisk} 回执={str(body.get('origins'))[:70]}")
    finally:
        CP.configFile = originalConfigFile
        os.environ.pop(ENV_KEY, None)

    check("[7] 全程没碰仓内真 config/cors.json（2026-09 污染入库的复发面）",
          _digest(REPO_CORS_FILE) == repoDigestBefore,
          f"{repoDigestBefore[:12]} → {_digest(REPO_CORS_FILE)[:12]}")

    # ---------------------------------------------------------------- 文件档
    fileOrigin = "http://file-b41.test"
    cfg2 = WORK_ROOT / "cors-file-only.json"
    cfg2.write_text(json.dumps({"origins": [fileOrigin], "allow_credentials": False}),
                    encoding="utf-8")
    CP.configFile = lambda: cfg2
    try:
        client = buildClient()
        shown = client.get("/api/v1/settings/cors").json()
        asm = _assembledCors(client.app)
        okFile = _preflight(client, fileOrigin).status_code == 200
        blockedDefault = _preflight(client, TAURI).status_code == 400
        check("[8] 文件档：面板、装配、预检一起改成文件值，默认那份当场失效（三处同源才叫单源）",
              shown["origins"] == [fileOrigin] and okFile and blockedDefault,
              f"面板={shown['origins']} 文件origin通={okFile} 默认被覆盖={blockedDefault}")
        check("[9] 文件档：面板可编辑的 allow_credentials 真的进了装配实参（此前写死 True）",
              shown["allow_credentials"] is False and asm["allow_credentials"] is False,
              f"面板={shown['allow_credentials']} 装配={asm['allow_credentials']}")
    finally:
        CP.configFile = originalConfigFile

    # ------------------------------------------------------------ 反向校准桩
    origDefaults, origHeaders = CP.DEFAULT_ORIGINS, CP.ALLOW_HEADERS
    CP.configFile = lambda: absent
    try:
        CP.DEFAULT_ORIGINS = tuple(o for o in origDefaults if o != TAURI)
        client = buildClient()
        r = _preflight(client, TAURI)
        check("[10] 反向校准 A：单源默认值少了桌面壳 ⇒ 预检必须 400（装配确实从单源取）",
              r.status_code == 400, f"{r.status_code} {r.text[:90]}")

        CP.DEFAULT_ORIGINS = origDefaults
        CP.ALLOW_HEADERS = tuple(h for h in origHeaders if h != "X-Request-ID")
        client = buildClient()
        r = _preflight(client, TAURI, req_headers="content-type, x-request-id")
        check("[11] 反向校准 B：单源 allow_headers 少了 X-Request-ID ⇒ 带该头的预检 400"
              "（装配处没留第二份头清单）",
              r.status_code == 400, f"{r.status_code} {r.text[:90]}")
    finally:
        CP.DEFAULT_ORIGINS, CP.ALLOW_HEADERS = origDefaults, origHeaders
        CP.configFile = originalConfigFile

    client = buildClient()
    r = _preflight(client, TAURI, req_headers="content-type, x-request-id")
    check("[12] 撤桩复证：默认档预检回 200（不是桩件留下的假绿/假红）",
          r.status_code == 200, f"{r.status_code} {r.text[:90]}")

    asmSrc = inspect.getsource(MW.setup_middleware)
    check("[13] 装配点读数：setup_middleware 的 CORS 四项实参全从单源取",
          "cors_policy.effectiveConfig()" in asmSrc
          and "cors_policy.ALLOW_METHODS" in asmSrc and "cors_policy.ALLOW_HEADERS" in asmSrc
          and not any(("PATCH" in ln or "tauri.localhost" in ln) for ln in asmSrc.splitlines()),
          "见 neurova/api/middleware.py 的 add_middleware 调用")

    print(f"\n读数 13 项，失败 {len(failures)} 项: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
