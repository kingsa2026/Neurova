# -*- coding: utf-8 -*-
"""批 45 活体自证：缓存三本账收成一条之后，真链路上的读数。

要证的不是"某个函数返回值对"，而是四件事：
① 退役的两条入口真的不再可导入（留一条活路就等于留两本账）；
② 进程默认缓存在注册表里只有一条名字，`/metrics` 不再把一个进程记成两列；
③ 真 HTTP 面上「清缓存」仍然在登录门后，且清的是真实对象；
④ 搬家是**纯搬家**——同一串行为读数（LRU 逐出 / TTL 过期 / 命中率 / `get_or_set` 的
   None 判别 / `resize` / `clear`）在本树与 HEAD 那份旧实装上逐值相同。

另带一段反向校准（独立子进程）：手工再登记一条注册名，证明 ② 的读数不是恒真。
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PY = str(REPO / ".venv/Scripts/python.exe")
RETIRED = (
    "neurova.memory.core.cache",
    "neurova.memory.core",
    "neurova.cognitive_layers.memory_layer.cache",
)

# 行为探针：只依赖 MemoryCache 的公开契约；两棵树各跑一次，比对同一份 JSON
BEHAVIOR_PROBE = """
import json, time
from {mod} import MemoryCache

out = {{}}
c = MemoryCache(capacity=2)
c.set("a", 1); c.set("b", 2)
c.get("a")
c.set("c", 3)
out["lru"] = [sorted(c.keys()), "b" in c.keys(), len(c)]

t = MemoryCache(capacity=4, default_ttl=0.05)
t.set("k", "v"); t.get("k"); time.sleep(0.12)
st = t.get_stats()
out["ttl"] = [t.get("k"), st["misses"], st["hit_rate"]]

s = MemoryCache(capacity=4)
s.set("x", 1); s.get("x"); s.get("x"); s.get("nope")
st = s.get_stats()
out["stats"] = [st["hits"], st["misses"], st["evictions"], st["size"], st["capacity"], st["hit_rate"]]

g = MemoryCache(capacity=4)
out["get_or_set"] = [g.get_or_set("k1", lambda: "built"), g.get_or_set("k1", lambda: "again")]
g.set("nul", None)
out["none_is_not_a_miss"] = [g.get("nul", "DEFAULT"), g.get_or_set("nul", lambda: "rebuilt")]

r = MemoryCache(capacity=4)
for i in range(4):
    r.set(str(i), i)
out["resize"] = [r.resize(2), sorted(r.keys()), len(r)]

cl = MemoryCache(capacity=4)
cl.set("p", 1); cl.set("q", 2)
out["clear"] = [cl.clear(), len(cl), sorted(cl.keys())]

print(json.dumps(out, sort_keys=True, ensure_ascii=False))
"""

READINGS = []


def check(title, ok, detail=""):
    READINGS.append((bool(ok), title))
    print(("[OK]   " if ok else "[FAIL] ") + title + (f" | {detail}" if detail else ""))


def runPy(root, code):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([PY, "-c", code], cwd=str(root), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"repo={REPO}")

    # ---- [1] 退役入口不再可导入（独立子进程，避开本会话已加载的模块缓存）----
    survivors = []
    for mod in RETIRED:
        rc, _out, err = runPy(REPO, f"import importlib; importlib.import_module({mod!r})")
        if rc == 0:
            survivors.append(f"{mod} 仍可导入")
        elif "ModuleNotFoundError" not in err and "ImportError" not in err:
            survivors.append(f"{mod} 报的不是 ImportError：{err[-70:]}")
    check("[1] 三条退役入口全部不可导入（且失败原因点名）", not survivors, str(survivors))

    # ---- [2] 注册表里只有一条全局名字 ----
    rc, out, err = runPy(REPO, (
        "from neurova.core.cache import get_global_cache, iter_caches, GLOBAL_CACHE_NAME;"
        "get_global_cache(); print(GLOBAL_CACHE_NAME, sorted(n for n, _ in iter_caches()))"))
    check("[2] 取默认实例后注册表只有一条名字", out == "default ['default']", f"实得={out} {err[-70:]}")

    # ---- [3] /metrics 读数：default 那列有值，旧的两列名字都没有 ----
    rc, out, err = runPy(REPO, (
        "from neurova.core.cache import get_global_cache;"
        "from neurova.core.metrics import get_metrics;"
        "from prometheus_client import REGISTRY;"
        "c = get_global_cache(); c.set('a', 1); c.get('a'); c.get('b');"
        "get_metrics().observe_caches();"
        "print(REGISTRY.get_sample_value('neurova_cache_hit_rate', {'cache': 'default'}),"
        " REGISTRY.get_sample_value('neurova_cache_hit_rate', {'cache': 'memory_global'}),"
        " REGISTRY.get_sample_value('neurova_cache_hit_rate', {'cache': 'core_global'}))"))
    toks = out.replace(")", "").split()
    # print 用空格分隔三个读数，不是逗号——按逗号切会把整行当一个 token（本脚本第一版就这么误判过）
    ok3 = (rc == 0 and len(toks) == 3 and toks[0] not in ("None", "")
           and toks[1] == "None" and toks[2] == "None")
    check("[3] /metrics 只有 cache=default 一列（memory_global/core_global 都取不到）", ok3, f"实得={out}")

    # ---- [4] 真 HTTP 面：清缓存作用在真实对象上，名字进响应 ----
    rc, out, err = runPy(REPO, r"""
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from neurova.api.deps import get_current_user
from neurova.api.endpoints import settings as s
from neurova.core.cache import get_global_cache

c = get_global_cache()
c.set("wipe-me", 1)
app = FastAPI()
app.include_router(s.router)
app.dependency_overrides[get_current_user] = lambda: {"id": "tester", "role": "admin"}
r = TestClient(app).post("/v1/settings/clear-cache")
data = r.json().get("data", {}) if r.status_code == 200 else {}
print(json.dumps({"status": r.status_code,
                  "default_cleared": (data.get("caches") or {}).get("default"),
                  "size_after": len(c)}, ensure_ascii=False))
""")
    ok4, detail4 = False, f"rc={rc} out={out[:140]} err={err[-90:]}"
    if rc == 0:
        try:
            d = json.loads(out)
            ok4 = d["status"] == 200 and d["size_after"] == 0 and d["default_cleared"] >= 1
            detail4 = str(d)
        except json.JSONDecodeError:
            pass
    check("[4] POST /v1/settings/clear-cache 真清掉默认实例（200 + default 计数进响应 + 清空）", ok4, detail4)

    # ---- [5] 真 create_app 下这条面仍在登录门后 ----
    rc, out, err = runPy(REPO, r"""
from fastapi.testclient import TestClient
from neurova.api.app import create_app
print(TestClient(create_app(), raise_server_exceptions=False)
      .post("/api/v1/settings/clear-cache").status_code)
""")
    check("[5] 未登录打这条面被挡（401/403）——收口没把门顺手拆了",
          rc == 0 and out in ("401", "403"), f"rc={rc} 实得={out[:60]}")

    # ---- [6] 反向校准：手工登记第二条名字，[2] 的读数立刻变两条 ----
    rc, out, err = runPy(REPO, (
        "from neurova.core.cache import get_global_cache, iter_caches, register_cache, MemoryCache;"
        "get_global_cache(); register_cache('second-column', MemoryCache(capacity=2));"
        "print(sorted(n for n, _ in iter_caches()))"))
    check("[6] 反向校准：再登记一条名字，读数就成两条（证明 [2] 有牙）",
          rc == 0 and "second-column" in out and "'default'" in out, f"实得={out}")

    # ---- [7] 纯搬家：本树与 HEAD 那份旧实装的行为读数逐值相同 ----
    wt = Path(tempfile.mkdtemp(prefix="b45-ab-")).resolve()
    add = subprocess.run(["git", "-C", str(REPO), "worktree", "add", "--detach", str(wt), "HEAD"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("[7a] HEAD 仓外 worktree 建得起", add.returncode == 0, add.stderr.strip()[:100])
    try:
        rcNew, newOut, newErr = runPy(REPO, BEHAVIOR_PROBE.format(mod="neurova.core.cache"))
        rcOld, oldOut, oldErr = runPy(wt, BEHAVIOR_PROBE.format(mod="neurova.memory.core.cache"))
        same = rcNew == rcOld == 0 and newOut and newOut == oldOut
        check("[7b] 六组行为读数与 HEAD 那份逐值相同（LRU/TTL/命中率/None 判别/resize/clear）",
              same, f"新={digestOf(newOut)} 旧={digestOf(oldOut)}"
                    + ("" if same else f" || 新:{newOut[:180]} || 旧:{oldOut[:180]} || {oldErr[-90:]}"))
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    bad = [t for ok, t in READINGS if not ok]
    print(f"\n读数 {len(READINGS)} 条，不成立 {len(bad)} 条" + (f"：{bad}" if bad else ""))
    return 1 if bad else 0


def digestOf(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12] if s else "空"


if __name__ == "__main__":
    sys.exit(main())
