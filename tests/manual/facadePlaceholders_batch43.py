# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-14 批 43，§6-201）：把"永远走不到的 None 兜底"拆掉之后，真链路读得到真东西。

判据按 AST 数形状 + 闭包；这一支在**真 import / 真 create_app / 子进程反向校准**上读数：

1. 所有能导入的 `neurova` 包门面：**没有**一个公开符号是 `None`（旧形态下 HEAD 现读 8 个）；
2. 本批修好的四条坏指路给出的是真身对象（`SelfModel`/`UserProfile`/`GraphTraversal`/
   `SleepConsolidation`），不是同名复制；
3. 缓存只有一处出处（`neurova.core.cache`）——批 45 把 `memory_layer.cache` 薄壳与
   `neurova.memory.core.cache` 门面都退役了，原先"以薄壳为入口先导入会撞回门面"
   那条真循环因此失去载体，这里改读"出处只有一个模块名"；
4. `neurova.llm_client` 用的记账函数就是 `neurova.models.cost_tracking` 那一个对象
   ——旧形态那里有一套 no-op decorator 桩，若走到那条，LLM 记账会整个静默不落地；
5. `interfaces` 门面里 §3 允许的第三方门保留（`APIError is fastapi.HTTPException`），
   而仓内那半（`ErrorCodes`/`AuthProtocol`）已接真；
6. `neurova.llm.providers` 八个 provider 类全可取到（以前 None 时装配会静默退化）；
7. `neurova.channels` 门面的适配器是真类；
8. 真 `create_app()` + TestClient：被本批改过的端点面都还在（401 登录门，而不是 404/500）；
9. 反向校准（独立子进程）：把 `neurova.models.cost_tracking` 打死 ⇒ 现在**显式抛 ImportError**
   点名，而不是带着 no-op 桩继续跑（这就是教义第 2 条要的"诚实形态"）；
10. 全仓现读：假降级节点 0 处（与判据同口径），并给出仍保留的正当兜底档数作对照。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/facadePlaceholders_batch43.py`
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaFacadeB43")
REPO_ROOT = Path(__file__).resolve().parents[2]

failures: list[str] = []

STUB_COST = r'''
import sys, types
sys.path.insert(0, r"@@ROOT@@")
blocked = types.ModuleType("neurova.models.cost_tracking")
blocked.__getattr__ = lambda name: (_ for _ in ()).throw(
    ImportError("b43 反向校准：假装 cost_tracking 不可用"))
sys.modules["neurova.models.cost_tracking"] = blocked
try:
    import neurova.llm_client  # noqa: F401
except ImportError as exc:
    print("RAISED:" + str(exc)[:150])
    sys.exit(0)
except Exception as exc:
    print("OTHER:" + type(exc).__name__ + ":" + str(exc)[:150])
    sys.exit(0)
import neurova.llm_client as L
import inspect
print("SWALLOWED:track_llm_call 来自 " + str(inspect.getsourcefile(L.track_llm_call)))
'''


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def main() -> int:
    import importlib
    import os

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b43_secret_key_for_p0_fixes_0123"

    facades = []
    for initFile in sorted((REPO_ROOT / "neurova").rglob("__init__.py")):
        if "__pycache__" in initFile.parts:
            continue
        pkg = initFile.relative_to(REPO_ROOT).as_posix()[: -len("/__init__.py")].replace("/", ".")
        try:
            mod = importlib.import_module(pkg)
        except Exception:
            continue
        nulls = [n for n in dir(mod) if not n.startswith("_") and getattr(mod, n, "?") is None]
        if nulls:
            facades.append(f"{pkg}:{nulls[:4]}")
    check("[1] 能导入的 neurova 包门面里没有 None 值公开符号", not facades,
          f"命中 {len(facades)} 档：{facades[:4]}")

    import neurova.memory as mem
    from neurova.cognitive_layers.memory_layer import models as layerModels
    from neurova.cognitive_layers.memory_layer.graph_traversal import GraphTraversal
    from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

    check("[2] 四条坏指路接回真身（同一对象，不是复制）",
          mem.SelfModel is layerModels.SelfModel and mem.UserProfile is layerModels.UserProfile
          and mem.GraphTraversal is GraphTraversal and mem.SleepConsolidation is SleepConsolidation,
          f"SelfModel={mem.SelfModel.__module__} GraphTraversal={mem.GraphTraversal.__module__}")

    cache = importlib.import_module("neurova.core.cache")
    check("[3] 缓存出处只有一处（薄壳与门面已随批 45 退役，循环失去载体）",
          cache.MemoryCache.__module__ == "neurova.core.cache", cache.MemoryCache.__module__)

    import neurova.llm_client as LC
    import neurova.models.cost_tracking as CT

    check("[4] llm_client 用的记账函数就是 cost_tracking 那一个（没有 no-op 桩顶在上面）",
          LC.track_llm_call is CT.track_llm_call and LC.record_llm_cost is CT.record_llm_cost,
          f"track_llm_call={LC.track_llm_call.__module__}")

    import neurova.interfaces as iface
    import fastapi

    check("[5] §3 允许的第三方门保留、仓内那半接真",
          iface.APIError is fastapi.HTTPException and hasattr(iface, "ErrorCodes")
          and iface.ErrorCodes is not None,
          f"APIError={iface.APIError.__name__} ErrorCodes={getattr(iface.ErrorCodes, '__name__', '?')}")

    providers = importlib.import_module("neurova.llm.providers")
    missing = [n for n in ("AnthropicProvider", "OpenAIProvider", "GeminiProvider", "OllamaProvider",
                          "OpenRouterProvider", "OpenCodeProvider", "BaseProvider", "ConnectionResult")
               if getattr(providers, n, None) is None]
    check("[6] llm.providers 门面的 8 个 provider 符号全可取（以前 None 会让装配静默退化）",
          not missing, f"缺 {missing}")

    chans = importlib.import_module("neurova.channels")
    check("[7] channels 门面给的是真适配器类",
          getattr(chans, "XiaoYiAdapter", None) is not None
          and getattr(chans, "ChannelManager", None) is not None,
          f"XiaoYiAdapter={getattr(chans.XiaoYiAdapter, '__module__', '?')}")

    from fastapi.testclient import TestClient

    import neurova.api.app as APPMOD
    APPMOD._app_instance = None
    app = APPMOD.create_app()
    client = TestClient(app, raise_server_exceptions=False)
    codes = {p: client.get(p).status_code for p in
             ("/api/v1/skills/stats", "/api/v1/settings/cors", "/api/v1/audit",
              "/api/v1/firewall/rules", "/api/v1/scheduler/tasks", "/api/v1/groups",
              "/api/v1/marketplace/skills")}
    # 这七条路径都是逐条实跑取到的读数（不是猜的）：6 个被本批改过 import 的端点模块里
    # audit/firewall/scheduler/groups/marketplace 各一条，加两条批 41 已核过的面。
    # 全部要求登录门（401/403）——出现 404 就是面掉了，出现 5xx 就是门面 import 链断了。
    check("[8] 真 create_app()：被改过的 6 个端点模块面都挂着且仍是登录门",
          all(c in (401, 403) for c in codes.values()), str(codes))

    proc = subprocess.run([sys.executable, "-c", STUB_COST.replace("@@ROOT@@", str(REPO_ROOT))],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(REPO_ROOT),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (proc.stdout or "").strip()
    line = out.splitlines()[-1] if out else "<无输出>"
    check("[9] 反向校准：打死 cost_tracking ⇒ 显式抛 ImportError（不再拿 no-op 桩继续跑）",
          line.startswith("RAISED:"), line)

    import importlib.util
    import ast as _ast

    sys.path.insert(0, str(REPO_ROOT / "tests" / "unit"))
    spec = importlib.util.spec_from_file_location(
        "jud43", REPO_ROOT / "tests" / "unit" / "test_noFirstPartyImportPlaceholder.py")
    jud = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(jud)
    offenders, legit = [], []
    for rel in jud._trackedPyFiles():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        offenders += jud.placeholderViolations(text, rel)
        try:
            tree = _ast.parse(text)
        except Exception:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Try) and node.handlers:
                placed = [t.id for h in node.handlers for st in h.body
                          if isinstance(st, _ast.Assign) and isinstance(st.value, _ast.Constant)
                          and st.value.value is None for t in st.targets if isinstance(t, _ast.Name)]
                if placed:
                    legit.append(rel)
    check("[10] 全仓现读：假降级 0 处；仍保留的正当兜底档数如实报出",
          not offenders, f"违规 {len(offenders)}；含 None 兜底的档 {len(set(legit))} 个文件")

    print(f"\n读数 10 项，失败 {len(failures)} 项: {failures}")
    print(f"（隔离数据根 {WORK_ROOT}）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
