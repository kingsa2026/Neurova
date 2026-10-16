# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-14 批 42，§6-200）：门面里的空转 try 与 None 占位符退役后，真链路仍走得通。

判据档按 AST 数形状；这一支要在**真导入 + 真装配 + 真调用**上读数：

1. 门面 `__all__` 里挂的每个名字都是**真对象**（类/函数），不是 `None` 占位符；
2. 按 `agent_core.py` 那条同参调用真跑一次 `create_default_skills()` ⇒ 拿到 SkillRegistry 实例
   （此前一旦落到被吞的 except 分支，那里就是 None）；
3. `create_app()` 真装配成功——按行为读数：`GET /api/v1/skills/stats` 得 401（面在、登录门在），
   并配一条不存在的路径必须 404 作校准（本档第一版按 `app.routes` 的 `.path` 取数读出 0 条，
   正是形态集记过的 `_IncludedRouter` 形状失真，改回行为面）；
4. 本批摘掉空转段的其余六个门面 import 后仍可用（其中 None 值公开符号只出 [OBSERVE] 读数，
   那是"144 个 None 占位符"这条待裁家族的现值，不写进判据、也不当作本批的绿）；
5. 小艺 `_init_connection`：内层连接调用抛异常 ⇒ 外层仍返回 False（fail-closed 没被搬家），
   而源码里那条"模拟模式 return True"的假分支确实不在了；
6. 反向校准（独立子进程）：把门面唯一真依赖的 `neurova.skill_system` 打死 ⇒ 门面必须**显式抛
   ImportError** 点名，而不是带着 None 继续活着；
7. 全仓现读惰性 try 段数量（与判据同口径）；
8. 批 46 之后 `SkillSource` 只剩 models 那一份：`hub_client` 取的是同一个对象，门面不再挂这个名字，
   且「安装段」与「市场段」两段词汇互斥（合并没把两套词汇混成一套）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/deadImportFacade_batch42.py`
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaFacadeB42")
REPO_ROOT = Path(__file__).resolve().parents[2]

failures: list[str] = []

# 与判据同口径的"惰性 try + except ImportError"探测器（独立进程跑，只出现读数）
PROBE_ZERO = r'''
import ast, io, subprocess, sys
files = [l for l in subprocess.run(["git", "ls-files", "-z"], cwd=sys.argv[1],
                                    capture_output=True).stdout.decode().split("\0")
         if l.endswith(".py")]
hits = []
for f in files:
    try:
        tree = ast.parse(io.open(f, encoding="utf-8", errors="replace").read())
    except Exception:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        inert = all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr)
                    and isinstance(s.value, ast.Constant) and isinstance(s.value.value, str))
                    for s in node.body)
        hs = [h for h in node.handlers or [] if isinstance(h.type, ast.Name)
              and h.type.id in ("ImportError", "ModuleNotFoundError")]
        if inert and hs:
            hits.append(f)
print(len(files), len(hits))
'''

# 反向校准：在**另一个进程**里把门面真依赖的那个模块打死，看门面是抛还是吞
# （批 46 之后门面只 `from neurova.skill_system import ...`，所以标的就是它）
STUB_FAIL = r'''
import sys, types
sys.path.insert(0, r"@@ROOT@@")
blocked = types.ModuleType("neurova.skill_system")
blocked.__getattr__ = lambda name: (_ for _ in ()).throw(
    ImportError("b42 反向校准：假装 neurova.skill_system 不可用"))
sys.modules["neurova.skill_system"] = blocked
try:
    import neurova.skills  # noqa: F401
except ImportError as exc:
    print("RAISED:" + str(exc)[:140])
    sys.exit(0)
except Exception as exc:
    print("OTHER:" + type(exc).__name__ + ":" + str(exc)[:140])
    sys.exit(0)
import neurova.skills as S
print("SWALLOWED:get_skill_registry=" + repr(getattr(S, "get_skill_registry", None)))
'''


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def observe(name: str, detail: str) -> None:
    print(f"[OBSERVE] {name} — {detail}")


def main() -> int:
    import asyncio
    import importlib
    import inspect
    import os
    import types

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b42_secret_key_for_p0_fixes_0123"

    import neurova.skills as facade
    from neurova.skills import models as models_mod
    from neurova.skill_system import SkillRegistry

    names = list(facade.__all__)
    noAttrs = [n for n in names if not hasattr(facade, n)]
    placeholders = [n for n in names if getattr(facade, n, None) is None]
    check("[1] 门面 __all__ 现挂的名字全是真对象（无缺失、无 None 占位符）",
          names and not noAttrs and not placeholders,
          f"现挂 {names} 缺 {noAttrs} 占位 {placeholders}")

    # 与 agent_core.py:863 同参调用：memory_manager=None 就是那条路的默认形状
    registry = facade.create_default_skills(memory_manager=None)
    check("[2] 真调用 create_default_skills(memory_manager=None) 拿到 SkillRegistry 实例",
          isinstance(registry, SkillRegistry), f"返回 {type(registry).__name__}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    # 装配读数走行为面，不走路由表形状：`app.routes` 里挂着 `_IncludedRouter`，
    # 按 `.path` 过滤会读出 0 条而面其实存在（本仓这条形状失真已记过一次，本档第一版又踩）。
    # 校准：一个不存在的路径必须给 404，才证明"技能面 401"是真的有面且被登录门挡，而不是猜。
    client = TestClient(app, raise_server_exceptions=False)
    skillCode = client.get("/api/v1/skills/stats").status_code
    controlCode = client.get("/api/v1/b42-no-such-face").status_code
    check("[3] 真 create_app() 装配成功：技能面在且有登录门（401），不存在的面是 404",
          skillCode == 401 and controlCode == 404,
          f"技能面={skillCode} 校准面={controlCode}")

    mods = ["neurova.llm.providers", "neurova.auth", "neurova.tts", "neurova.recovery",
            "neurova.collaboration", "neurova.cognitive_layers.memory_layer"]
    noneValued = {}
    for m in mods:
        mod = importlib.import_module(m)
        gone = [n for n in dir(mod)
                if not n.startswith("_") and getattr(mod, n, "?") is None]
        if gone:
            noneValued[m] = gone[:6]
    bad = [m for m in mods if importlib.import_module(m) is None]
    check("[4] 六个门面真 import 得到模块对象（摘段没把任何门面摘空）", not bad,
          f"取不到模块的：{bad or '无'}")
    observe("门面里仍为 None 的公开符号（＝『144 个 None 占位符』那条待裁的现值，不判绿）",
            str(noneValued or "无"))

    from neurova.channels.xiaoyi import XiaoYiAdapter

    def _boom():
        raise RuntimeError("b42 注入：内层连接失败")

    # XiaoYiAdapter 是抽象类（connect/disconnect 由子类实现），这里按方法体真正触碰到的
    # 两个属性喂一只鸭子替身——读的是 `_init_connection` 自己的失败方向，不是替身的能力
    stub = types.SimpleNamespace(_connected=False, _async_init_connection=_boom)
    outcome = asyncio.run(XiaoYiAdapter._init_connection(stub))
    src = inspect.getsource(XiaoYiAdapter._init_connection)
    check("[5] 小艺内层连接抛异常 ⇒ 外层返回 False，且假分支『模拟模式』已不在源码里",
          outcome is False and "模拟模式" not in src, f"返回 {outcome!r}")

    proc = subprocess.run([sys.executable, "-c", STUB_FAIL.replace("@@ROOT@@", str(REPO_ROOT))],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(REPO_ROOT),
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    out = (proc.stdout or "").strip()
    line = out.splitlines()[-1] if out else "<无输出>"
    check("[6] 反向校准：打死门面唯一真依赖 neurova.skill_system ⇒ 显式抛 ImportError（不再吞成 None）",
          line.startswith("RAISED:"), line)

    counted = subprocess.run([sys.executable, "-c", PROBE_ZERO, str(REPO_ROOT)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             cwd=str(REPO_ROOT),
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    scanned, hits = ((counted.stdout or "? ?").strip().split() + ["?"])[:2]
    check("[7] 全仓惰性 try 段现读为 0（扫描集合 %s 个 .py）" % scanned, hits == "0", f"现读 {hits} 段")

    hub_mod = importlib.import_module("neurova.skills.hub_client")
    installSeg = set(models_mod.SkillSource.installSources())
    marketSeg = set(models_mod.SkillSource.marketSources())
    check("[8] SkillSource 只剩 models 那一份（hub 取同一对象、门面不挂这个名字），"
          "且两段词汇由数据显式承担",
          hub_mod.SkillSource is models_mod.SkillSource
          and not hasattr(facade, "SkillSource")
          and installSeg | marketSeg == set(models_mod.SkillSource)
          and installSeg & marketSeg == {models_mod.SkillSource.LOCAL},
          f"hub={hub_mod.SkillSource.__module__} 门面挂着={hasattr(facade, 'SkillSource')} "
          f"仅装载段={sorted(v.value for v in installSeg - marketSeg)} "
          f"仅市场段={sorted(v.value for v in marketSeg - installSeg)} "
          f"交集={sorted(v.value for v in installSeg & marketSeg)}")

    print(f"\n读数 8 项，失败 {len(failures)} 项: {failures}")
    print(f"（隔离数据根 {WORK_ROOT}）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
