# -*- coding: utf-8 -*-
"""live-verify（批 50，§6-224）：八包补 `__all__`、隐式公开面登记表清零之后，真链路仍走得通。

判据档按 AST 数形状；这一支在**真导入 + 真取径 + 真装配**上取读数：

1. 八个包的运行时 `__all__` 逐个盖住那 44 名，且每个名字真取得到对象（不是 `None`、不是空话）；
2. 四条**真实取径**原样复算：`api/app.py` 经门面取状态与注册函数、`tool_executor` 经门面取运行时、
   `computer_use.scroll_semantics` 真调用取回读数、`memory_ingest.converters.CONVERTERS` 现读家数；
3. `neurova.execution_engine` 给出去的是 **tool_engine 真身**而非门面 handler 里那九枚同名空桩
   （方法数、`__module__`、`ToolStatus` 是不是真 Enum 三处读数）；
4. `memory_layer.TemperatureEngine` 既在 `__all__` 里、又真来自 `.temperature`；
5. 真 `create_app()` 装配：经 `ENDPOINT_MODULES` 挂出来的路由数量读数 + 一条真 GET + 一条 404 校准
   ——补 `__all__` 不许动挂载链；
6. **反向校准**：同一条取数打在 HEAD 那一份仓外工作树上，必须报出本批修掉的 8 包 44 名；
   本树必须报空。证明"零隐式公开面"是改出来的，不是取数没跑起来。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/declaredSurfaceFaces_batch50.py`
"""
from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
from tests.unit.core.test_packageDeclaredSurfaceCoversWhatIsTaken import (  # noqa: E402
    EXPECTED_FACES, undeclaredTakeaways)

REPO = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaDeclaredB50")
failures: list = []
observed: list = []


def read(idx: str, desc: str, fn) -> None:
    try:
        detail = fn()
        print("[%s] PASS %s%s" % (idx, desc, "  ← " + detail if detail else ""))
    except AssertionError as exc:
        failures.append("%s %s：%s" % (idx, desc, exc))
        print("[%s] FAIL %s：%s" % (idx, desc, exc))


def observe(desc: str, fn) -> None:
    try:
        print("    OBSERVE %s：%s" % (desc, fn()))
    except Exception as exc:  # noqa: BLE001 —— 观察项不记分，只留读数
        print("    OBSERVE %s：读数失败 %r" % (desc, exc))


def _allNamesFace(pkg: str) -> set:
    mod = importlib.import_module(pkg)
    declared = set(getattr(mod, "__all__", []) or [])
    want = EXPECTED_FACES[pkg]
    missing = sorted(want - declared)
    assert not missing, f"{pkg}.__all__ 缺 {missing}"
    nulls = [n for n in sorted(want) if getattr(mod, n, None) is None]
    assert not nulls, f"{pkg} 声明了却取不到对象：{nulls}"
    return "%d 名全在且全取得到" % len(want)


read("1", "八包运行时 __all__ 盖住 44 名且逐个取得到", lambda: "; ".join(
    "%s:%s" % (p.split(".")[-1], _allNamesFace(p)) for p in sorted(EXPECTED_FACES)))


def _liveTakePaths() -> str:
    from neurova.api.endpoints import (ENDPOINT_MODULES, get_app_state, register_endpoint_routers,
                                       set_app_state)
    from neurova.execution_layers import LocalExecutor, RuntimeType, get_runtime_manager
    from neurova.computer_use import scroll_semantics
    from neurova.memory_ingest.converters import CONVERTERS

    assert callable(register_endpoint_routers) and callable(get_app_state) and callable(set_app_state)
    assert len(ENDPOINT_MODULES) >= 30, f"注册表面读数异常：{len(ENDPOINT_MODULES)}"
    assert isinstance(RuntimeType.LOCAL.value, str) and callable(get_runtime_manager)
    assert {"exec", "start", "stop"} <= set(dir(LocalExecutor)), \
        f"LocalExecutor 的方法面变了：{sorted(dir(LocalExecutor))}"
    assert LocalExecutor(runtime_id="local").runtime_id == "local", "构造出来的实例读不到 runtime_id"
    assert len(CONVERTERS) >= 7 and all(callable(v) for v in CONVERTERS.values()), \
        f"CONVERTERS 读数异常：{len(CONVERTERS)}"
    up = scroll_semantics(scroll_y=-3)
    zero = scroll_semantics(scroll_x=0, scroll_y=0)
    assert isinstance(up, tuple) and len(up) == 2, f"scroll_semantics 形状变了：{up}"
    assert zero[0] == 3, f"两轴全 0 该回退 default_clicks=3，实得 {zero}"
    return ("ENDPOINT_MODULES=%d CONVERTERS=%d scroll(-3)=%s scroll(0,0)=%s"
            % (len(ENDPOINT_MODULES), len(CONVERTERS), up, zero))


read("2", "四条真实取径原样跑通", _liveTakePaths)


def _engineIsReal() -> str:
    engine = importlib.import_module("neurova.execution_engine")
    from neurova.execution_engine import tool_engine as real

    stubish = []
    for name in sorted(EXPECTED_FACES["neurova.execution_engine"]):
        obj = getattr(engine, name)
        if getattr(obj, "__module__", "") != "neurova.execution_engine.tool_engine":
            stubish.append((name, obj.__module__))
    assert not stubish, f"这些名字仍指向门面里的桩：{stubish}"
    methods = [k for k, v in vars(engine.ToolEngine).items()
               if not k.startswith("__") and callable(v)]
    assert len(methods) >= 3, f"ToolEngine 方法数 {len(methods)}——那才是空桩的形状"
    assert engine.ToolEngine is real.ToolEngine, "门面与子模块给的不是同一个对象（两本账）"
    assert isinstance(engine.ToolStatus.AVAILABLE, engine.ToolStatus), (
        "ToolStatus 不是真 Enum——桩那侧它是四个裸字符串")
    return "ToolEngine 方法=%d，ToolStatus 是真 Enum，门面与子模块 is 同一对象" % len(methods)


read("3", "execution_engine 给的是 tool_engine 真身，不是同名空桩", _engineIsReal)


def _temperatureEngine() -> str:
    layer = importlib.import_module("neurova.cognitive_layers.memory_layer")
    assert "TemperatureEngine" in (layer.__all__ or []), "TemperatureEngine 不在 __all__ 里"
    obj = layer.TemperatureEngine
    assert obj.__module__ == "neurova.cognitive_layers.memory_layer.temperature", obj.__module__
    return "来自 %s" % obj.__module__


read("4", "memory_layer 的 TemperatureEngine 已声明且来自真模块", _temperatureEngine)


def _liveApp() -> str:
    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.endpoints import ENDPOINT_MODULES

    app = create_app()
    # 本仓的路由挂在 `_IncludedRouter` 里（顶层 `app.routes` 只有 5 条裸 APIRoute）——
    # 探针第一版按顶层 `methods` 数，读出"只有 5 条"，那是我的口径比产品窄，不是挂载链断了。
    included = [r for r in app.routes if type(r).__name__ == "_IncludedRouter"]
    assert len(included) == len(ENDPOINT_MODULES), (
        f"挂出来的路由 {len(included)} 只与注册表面 {len(ENDPOINT_MODULES)} 项不符")
    leaves = [(sorted(sub.methods)[0],
               (getattr(r.include_context, "prefix", "") or "") + sub.path)
              for r in included for sub in getattr(r.original_router, "routes", [])
              if getattr(sub, "methods", None)]
    assert len(leaves) >= 200, f"经门面注册出来的叶子路由只有 {len(leaves)} 条"
    gets = sorted({p for m, p in leaves if m == "GET" and "{" not in p})
    assert gets, "没有一条不带路径参数的 GET 面可供探针"
    client = TestClient(app)
    assert client.get("/health").status_code == 200, "/health 不该挂"
    probe = next((p for p in gets if "/memory" not in p), gets[0])
    status = client.get(probe).status_code
    assert status != 404, f"{probe} 回 404——拼出来的路径没落在挂出来的面上"
    assert status < 500, f"{probe} 回 {status}（5xx 说明装配坏了）"
    calib = client.get("/api/v1/_no_such_face_probe_b50").status_code
    assert calib == 404, f"校准面应 404，实得 {calib}"
    return "门面注册面=%d 只/叶子=%d GET面=%d，探针 %s→%s，校准→%s" % (
        len(included), len(leaves), len(gets), probe, status, calib)


read("5", "真 create_app() 挂载链完好（补 __all__ 没动注册）", _liveApp)


def _headSideCalibration() -> str:
    """把同一条取数打在 HEAD 的仓外工作树：必须报出本批修掉的 8 包 44 名。

    基线侧铺入**本批这一份判据**（生产件留 HEAD 原样）——两侧同一把尺，差集才是改出来的。
    """
    base = Path(tempfile.mkdtemp(prefix="neurovaB50Head-"))
    worktree = base / "head"
    subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(worktree), "HEAD"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        judgeRel = "tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py"
        shutil.copyfile(REPO / judgeRel, worktree / judgeRel)
        code = (
            "import sys, json\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "import importlib.util\n"
            "spec = importlib.util.spec_from_file_location('j', sys.argv[1] + "
            "'/tests/unit/core/test_packageDeclaredSurfaceCoversWhatIsTaken.py')\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "g = {k: sorted(v) for k, v in m.undeclaredTakeaways().items()}\n"
            "print(json.dumps({'pkgs': len(g), 'names': sum(len(v) for v in g.values()), "
            "'per_pkg': {k: len(v) for k, v in g.items()}}, ensure_ascii=False))\n")
        p = subprocess.run([sys.executable, "-c", code, str(worktree)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", cwd=str(worktree))
        got = json.loads(p.stdout.strip().splitlines()[-1])
        assert got["pkgs"] == 8 and got["names"] == 44, (
            "HEAD 侧应报 8 包 44 名，实得 %s（stderr 尾：%s）" % (got, (p.stderr or "")[-200:]))
        mine = undeclaredTakeaways()
        assert not mine, f"本树仍有隐式公开面未清零：{ {k: sorted(v) for k, v in mine.items()} }"
        return "HEAD 侧=8 包 44 名｜本树=0 包 0 名（同一把尺、两个进程）"
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(worktree)],
                       capture_output=True)
        subprocess.run(["git", "-C", str(REPO), "worktree", "prune"], capture_output=True)
        shutil.rmtree(base, ignore_errors=True)


read("6", "反向校准：HEAD 侧报 8 包 44 名、本树报空", _headSideCalibration)

observe("本树 __all__ 逐包读数", lambda: {
    p: sorted(set(importlib.import_module(p).__all__ or []))[:2] for p in sorted(EXPECTED_FACES)})
observe("工作根隔离落点", lambda: str(WORK_ROOT))

print("\n总计：%d 项，失败 %d 项" % (6, len(failures)))
for f in failures:
    print("  - " + f)
sys.exit(1 if failures else 0)
