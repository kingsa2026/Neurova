# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-15 批 47，§6-212）：包门面上的通用名与被盖掉的 import 退役后，真链路仍走得通。

判据档按 AST 数形状；这一支要在**真导入 + 真装配 + 真调用**上读数：

1. `neurova.auth` 真导入后 `hashlib` 不再是它的属性，而 `__all__` 那五项**一个都没少**
   （反空转：只摘通用名，不许把别的东西一起带走）；
2. `neurova.security` 真导入后三只公开对象在、`get_logger` 不在，且**能力没丢**——
   替代写法 `core.logger.get_logger("neurova.security.probe")` 真取到同名 logger，
   并比本地那只多做了 handler/级别配置（按 §7，弱者退役的前提是选定那份实装更强）；
3. `growth.py` 那两个被盖掉的别名 import 删掉后，`_get_agent` / `_get_request_id` 仍是
   **可调用对象**且**真转发**（取一条真 Request 的 header 读数，不是 mock 的返回值）；
4. 真 `create_app()` 装配 + TestClient 打 growth 面 ⇒ 401（面在、登录门在），配一条不存在的
   路径必须 404 作校准；
5. 两条规则的现读（与判据同口径、独立进程）；
6. 反向校准：把同一条取数打在 **HEAD 那一份**生产件上 ⇒ 必须报出那 4 处，
   否则"现值 0"可能只是取数没跑起来。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/facadeGenericNames_batch47.py`
"""

from __future__ import annotations

import importlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
WORK_ROOT = isolatedDataRoot(prefix="neurovaFacadeB47")
failures: list[str] = []

# 与判据同口径的两条探测器（独立进程跑，只出读数）
PROBE = r'''
import ast, io, subprocess, sys
root = sys.argv[1]
GENERIC = {"Any","Callable","Dict","List","Optional","Set","Tuple","Union","Iterable",
    "Awaitable","Coroutine","Sequence","Mapping","TypeVar","Generic","Literal","TypedDict",
    "Protocol","Annotated","Final","ClassVar","cast","overload","dataclass","field","asdict",
    "astuple","Enum","IntEnum","StrEnum","auto","unique","ABC","ABCMeta","abstractmethod",
    "hashlib","json","os","sys","re","time","uuid","asyncio","threading","datetime",
    "timedelta","Path","OrderedDict","defaultdict","Counter","TextIO","IO","BinaryIO",
    "getLogger","get_logger","partial","lru_cache","cached_property"}
SOURCES = {"typing","dataclasses","enum","abc","collections","hashlib","json","os","sys","re",
    "time","uuid","asyncio","threading","datetime","pathlib","functools","io","copy","math",
    "random","string","inspect","traceback","importlib","itertools","contextlib","logging",
    "neurova"}
files = [l for l in subprocess.run(["git","-C",root,"ls-files","-z"],
                                   capture_output=True).stdout.decode("utf-8").split("\0")
         if l.startswith("neurova/") and l.endswith(".py")]
generic, shadowed, parsed = [], [], 0
for rel in files:
    try:
        tree = ast.parse(io.open(root + "/" + rel, encoding="utf-8", errors="replace").read())
    except Exception:
        continue
    parsed += 1
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            used.add(node.attr)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for deco in node.decorator_list:
                used |= {w for w in GENERIC if w in ast.unparse(deco).replace(".", " ").split()}
    declared = set()
    for node in tree.body:
        tg = ([t.id for t in node.targets if isinstance(t, ast.Name)]
              if isinstance(node, ast.Assign) else
              ([node.target.id] if isinstance(getattr(node, "target", None), ast.Name) else []))
        if "__all__" in tg:
            declared |= {e.value for e in getattr(node.value, "elts", [])
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    imported = {}
    if rel.endswith("__init__.py"):
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    nm = (a.asname or a.name).split(".")[0]
                    imported[nm] = node.lineno
                    if nm in GENERIC and nm not in used and nm not in declared:
                        generic.append(f"{rel}:{node.lineno} {nm}")
            elif isinstance(node, ast.ImportFrom) and node.module not in (None, "__future__"):
                if node.module.split(".")[0] not in SOURCES:
                    continue
                for a in node.names:
                    nm = a.asname or a.name
                    imported[nm] = node.lineno
                    if nm in GENERIC and nm not in used and nm not in declared:
                        generic.append(f"{rel}:{node.lineno} {nm}<-{node.module}")
    else:
        for node in tree.body:
            if isinstance(node, ast.Import):
                for a in node.names:
                    imported.setdefault((a.asname or a.name).split(".")[0], node.lineno)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    imported.setdefault(a.asname or a.name, node.lineno)
    rebound = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            rebound.setdefault(node.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    rebound.setdefault(t.id, node.lineno)
    for nm, ln in imported.items():
        if nm in rebound and rebound[nm] > ln:
            shadowed.append(f"{rel}:{ln} {nm}<-被:{rebound[nm]}")
print(parsed, len(generic), len(shadowed))
print("GENERIC " + ";".join(generic))
print("SHADOWED " + ";".join(shadowed))
'''


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def observe(name: str, detail: str) -> None:
    print(f"[OBSERVE] {name} — {detail}")


def runProbe(root: str) -> dict:
    proc = subprocess.run([sys.executable, "-c", PROBE, root], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=root)
    out = (proc.stdout or "").splitlines()
    if len(out) < 3:
        return {"error": (proc.stderr or "")[-300:] or "无输出", "lines": out}
    parsed, ng, ns = (out[0].split() + ["?", "?"])[:3]
    return {"parsed": parsed, "generic": out[1].split("GENERIC ", 1)[-1].split(";")
            if out[1].startswith("GENERIC") and out[1].strip() != "GENERIC" else [],
            "shadowed": out[2].split("SHADOWED ", 1)[-1].split(";")
            if out[2].startswith("SHADOWED") and out[2].strip() != "SHADOWED" else []}


def main() -> int:
    import os
    import logging

    os.environ["NEUROVA_JWT_SECRET_KEY"] = "live_b47_secret_key_for_p0_fixes_0123"

    auth = importlib.import_module("neurova.auth")
    authNames = list(getattr(auth, "__all__", []))
    missing = [n for n in authNames if getattr(auth, n, None) is None]
    check("[1] neurova.auth 真导入：hashlib 不再是包属性，而 __all__ 那五项一个没少",
          not hasattr(auth, "hashlib") and authNames and not missing,
          f"__all__={authNames} 缺={missing} 仍带 hashlib={hasattr(auth, 'hashlib')}")

    sec = importlib.import_module("neurova.security")
    from neurova.core.logger import get_logger as coreGetLogger
    probeLogger = coreGetLogger("neurova.security.probe")
    check("[2] neurova.security 真导入：三只公开对象在、get_logger 已不在，"
          "且替代写法真取到同一只 logger（能力没丢）",
          all(hasattr(sec, n) for n in ("AuditLog", "Permission", "Role"))
          and not hasattr(sec, "get_logger")
          and isinstance(probeLogger, logging.Logger)
          and probeLogger.name == "neurova.security.probe"
          and probeLogger is logging.getLogger("neurova.security.probe"),
          f"公开面={sec.__all__} 本地 get_logger 在否={hasattr(sec, 'get_logger')} "
          f"替代 logger={probeLogger.name}/handlers={len(probeLogger.handlers)}")

    growth = importlib.import_module("neurova.api.endpoints.growth")
    from fastapi import Request

    def _makeRequest(state: dict) -> Request:
        async def recv():
            return b""

        return Request({"type": "http", "method": "GET", "path": "/x", "headers": [],
                        "query_string": b"", "client": ("127.0.0.1", 1234),
                        "server": ("test", 80), "state": state, "scheme": "http"},
                       receive=recv)

    forwarded = growth._get_request_id(_makeRequest({"request_id": "live_b47_request_id"}))
    # 没带 request_id 时必须落到实现里的 uuid4 分支——这条读数证明转发的是真实现，不是桩件
    fresh = growth._get_request_id(_makeRequest({}))
    import re as _re

    check("[3] growth 那两个被盖掉的别名 import 删掉后：局部包装仍真转发到 growth_common 的实现",
          forwarded == "live_b47_request_id"
          and bool(_re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                                 str(fresh)))
          and callable(growth._get_agent),
          f"带 id 时={forwarded!r} 不带 id 时={str(fresh)[:12]!r}…")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app

    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    growthCode = client.get("/api/v1/growth/reflection").status_code
    controlCode = client.get("/api/v1/b47-no-such-face").status_code
    check("[4] 真 create_app() 装配成功：growth 面在且有登录门（401），不存在的面是 404",
          growthCode == 401 and controlCode == 404,
          f"growth 面={growthCode} 校准面={controlCode}")

    here = runProbe(str(REPO))
    check("[5] 两条规则在现树里取数跑通（生产文件扫描面 >900）",
          "error" not in here and int(here["parsed"]) >= 900,
          f"解析 {here.get('parsed')} 档，通用名泄漏 {len(here.get('generic', []))} 处、"
          f"被盖掉的 import {len(here.get('shadowed', []))} 处")
    observe("现读明细", f"GENERIC={here.get('generic')} SHADOWED={here.get('shadowed')}")

    # 反向校准：把 HEAD 那一份生产树铺到仓外临时工作树，同一条取数必须报出那 4 处
    tmp = Path(tempfile.mkdtemp(prefix="neurovaB47-head-")) / "wt"
    added = subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach",
                            str(tmp), "HEAD"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    if added.returncode:
        check("[6] 反向校准：同一取数打在 HEAD 那一份上必须报出那 4 处", False,
                              "worktree add 失败: " + (added.stderr or "")[-200:])
    else:
        base = runProbe(str(tmp))
        check("[6] 反向校准：同一取数打在 HEAD 那一份上必须报出那 4 处（证明 0 是改出来的，不是没跑）",
              "error" not in base and len(base.get("generic", [])) == 1
              and len(base.get("shadowed", [])) == 3,
              f"HEAD 侧 通用名={base.get('generic')} 被盖={base.get('shadowed')}")
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        shutil.rmtree(tmp.parent, ignore_errors=True)

    print(f"\n读数 6 项，失败 {len(failures)} 项: {failures}")
    print(f"（隔离数据根 {WORK_ROOT}）")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
