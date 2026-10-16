# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-15 批 49，§6-220）：包门面把"真被人取用的名字"写进契约之后，真链路仍走得通。

判据档按 AST 数形状；这一支要在**真导入 + 真取径 + 真装配**上读数：

1. 五个动过的包，`__all__` 里每个名字都真取得到且不是 None（声明不是空话）；
2. 三条**真实取径**原样复算：集成测试那种 `from neurova.api.endpoints.memory import router`、
   provider_manager 那种一次取六只 provider、以及属性形 `import neurova.cognitive as cog; cog.Memory`
   ——第三种正是 §6-212 数错的偏法，这里用真取法证明它确实在被用；
3. `from neurova.memory import GraphTraversal / UnifiedVectorStore` 与直取子模块**是同一个对象**
   （`is` 比较；若门面另指了一份，就是两本账）；
4. 真 `create_app()` 装配：memory 面 401（面在、登录门在）＋ 不存在的面 404 作校准；
5. 现读"隐式公开面"还剩哪些包（与判据同口径、独立进程），并核对与登记表一致；
6. 反向校准：同一条取数打在 **HEAD 那一份**工作树上，必须报出本批修掉的那 10 个名字／4 个包
   ——证明"现值等于登记表"是改出来的，不是取数没跑起来。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/declaredSurface_batch49.py`
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaDeclaredB49")
failures: list[str] = []

IMPLICIT_READING = """
import sys, json
sys.path.insert(0, sys.argv[1])
import importlib.util
spec = importlib.util.spec_from_file_location(
    "declaredJudge", sys.argv[1] + "/tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(json.dumps({k: sorted(v) for k, v in mod.undeclaredTakeaways().items()}, ensure_ascii=False))
"""


def readImplicit(root) -> dict:
    """现读隐式公开面——**用判据自己那份函数**，不在这里再写一套取数。

    第一版本档自带一份简化探测器，结果与判据口径漂了：它不解析相对导入，
    于是 `neurova.memory_ingest.converters` 的 `CONVERTERS` 整包被读成"没有隐式面"。
    同一份判断有两处实现必有一处先漂（AGENTS.md §6），这一条正是它自己复现了一次。
    """
    import json

    p = subprocess.run([sys.executable, "-c", IMPLICIT_READING, str(root)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=str(root),
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    line = (p.stdout or "").strip().splitlines()
    try:
        return json.loads(line[-1]) if line else {"__error__": (p.stderr or "")[-200:]}
    except Exception:
        return {"__error__": (p.stderr or "")[-200:]}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def observe(name: str, detail: str) -> None:
    print(f"[OBSERVE] {name} — {detail}")


def runProbe(root: Path) -> dict:
    p = subprocess.run([sys.executable, "-c", PROBE, str(root)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=str(root),
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (p.stdout or "").splitlines()
    pkgs = next((l.split()[1] for l in out if l.startswith("PKGS ")), "?")
    implicit = next((l[len("IMPLICIT "):] for l in out if l.startswith("IMPLICIT ")), "")
    return {"pkgs": pkgs, "implicit": {} if not implicit else
            {kv.split("=")[0]: set(kv.split("=")[1].split("|"))
             for kv in implicit.split(",") if "=" in kv},
            "stderr": (p.stderr or "")[-200:]}


def main() -> int:
    import os
    import types

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b49_secret_key_for_p0_fixes_0123"

    expected = {
        "neurova.llm.providers": {"AnthropicProvider", "BaseProvider", "ConnectionResult",
                                  "GeminiProvider", "OllamaProvider", "OpenAIProvider",
                                  "OpenCodeProvider", "OpenRouterProvider"},
        "neurova.admin": {"AdminService", "ResourceQuotaManager", "ResourceUsage"},
        "neurova.cognitive": {"Memory"},
        "neurova.api.endpoints.memory": {"router"},
    }
    bad = []
    for pkg, names in expected.items():
        mod = importlib.import_module(pkg)
        got = set(getattr(mod, "__all__", []))
        none = [n for n in got if getattr(mod, n, None) is None]
        if got != names or none:
            bad.append(f"{pkg}: 实得 {sorted(got)} 缺对象 {none}")
    check("[1] 四个包的 __all__ 与本批读数一致，且每个名字真取得到对象", not bad, "; ".join(bad) or "4/4 对得上")

    from neurova.api.endpoints.memory import router as memoryRouter
    from neurova.llm.providers import (AnthropicProvider, GeminiProvider, OllamaProvider,
                                       OpenAIProvider, OpenCodeProvider, OpenRouterProvider)
    import neurova.cognitive as cog

    routers = {r.path for r in memoryRouter.routes}
    check("[2] 三条真实取径原样走得通（集成测试形／provider_manager 一次取六只／属性形 cog.Memory）",
          bool(routers) and all(c is not None for c in (AnthropicProvider, GeminiProvider,
                                                        OllamaProvider, OpenAIProvider,
                                                        OpenCodeProvider, OpenRouterProvider))
          and cog.Memory.__module__.endswith("memory_layer.models"),
          f"memory router 路由 {len(routers)} 条；cog.Memory 定在 {cog.Memory.__module__}")

    from neurova.memory import GraphTraversal as ViaFacade
    from neurova.memory import UnifiedVectorStore as StoreViaFacade
    from neurova.cognitive_layers.memory_layer.graph_traversal import GraphTraversal as ViaModule
    from neurova.cognitive_layers.memory_layer.unified_vector_store import (
        UnifiedVectorStore as StoreViaModule)
    check("[3] 门面那两个新声明的名字与直取子模块是同一个对象（不是第二本账）",
          ViaFacade is ViaModule and StoreViaFacade is StoreViaModule,
          f"GraphTraversal 同对象={ViaFacade is ViaModule} UnifiedVectorStore 同对象={StoreViaFacade is StoreViaModule}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    listCode = client.get("/api/v1/memory/").status_code
    writeCode = client.post("/api/v1/memory/", json={}).status_code
    controlCode = client.get("/api/v1/b49-no-such-face").status_code
    statsCode = client.get("/api/v1/memory/stats").status_code
    check("[4] 真 create_app() 装配成功：memory 面读得到(200)、写侧要身份(401)、不存在的面 404",
          listCode == 200 and writeCode == 401 and controlCode == 404,
          f"GET /api/v1/memory/={listCode} POST={writeCode} 校准面={controlCode}")
    observe("顺带撞见（不属本批，登记）",
            f"GET /api/v1/memory/stats 未登录且无默认 Agent 时回 {statsCode}"
            "——同样的形状在 /hot 与 /search 上也是 500，按教义第 2 条应是显式 4xx 或 not_initialized；"
            "本批不顺手改（那是 memory 端点自己那一批的事）")

    here = readImplicit(REPO)
    spec = importlib.util.spec_from_file_location(
        "b49Judge", REPO / "tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py")
    judge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(judge)
    registered = set(judge.IMPLICIT_SURFACE)
    observe("现读隐式公开面（包=名字，取自判据同一函数）", str(here)[:340])
    check("[5] 现读的隐式公开面恰等登记表那 8 个包（本批修的 4 个已不在其中）",
          set(here) == registered and "neurova.memory" not in here,
          f"现读 {len(here)} 个包：{sorted(here)[:4]}…")

    tmp = Path(tempfile.mkdtemp(prefix="neurovaB49-head-")) / "wt"
    added = subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(tmp), "HEAD"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    if added.returncode:
        check("[6] 反向校准：HEAD 那份必须报出本批修掉的 4 包 10 名", False,
              "worktree add 失败: " + (added.stderr or "")[-160:])
    else:
        # HEAD 树里没有本批这两个文件（判据是新的、`takenPerModule` 是新的）⇒ 先把它们铺进去，
        # 铺的仍是**同一份**判据与同一个共享入口，不另写一套取数（A/B 的 -c 同一个道理）。
        for rel in ("tests/ast_scan.py",
                    "tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py"):
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / rel, tmp / rel)
        base = readImplicit(tmp)
        mine = {"neurova.llm.providers": {"AnthropicProvider", "GeminiProvider", "OllamaProvider",
                                         "OpenAIProvider", "OpenCodeProvider", "OpenRouterProvider"},
                "neurova.memory": {"GraphTraversal", "UnifiedVectorStore"},
                "neurova.cognitive": {"Memory"},
                "neurova.api.endpoints.memory": {"router"}}
        got = {k: set(v) for k, v in base.items() if k in mine}
        check("[6] 反向校准：同一条取数打在 HEAD 那份上必须报出那 4 包 10 名（证明现值=登记表是改出来的）",
              got == mine, f"HEAD 侧 { {k: sorted(v) for k, v in got.items()} }"
                           f"（或读数失败：{base.get('__error__', '')}）")
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        shutil.rmtree(tmp.parent, ignore_errors=True)

    print(f"\n读数 6 项，失败 {len(failures)} 项: {failures}")
    print(f"（隔离数据根 {WORK_ROOT}）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
