# -*- coding: utf-8 -*-
r"""live-verify（批 64）：装侧不再把空壳钉成构件权威——但**可见性、闸与对照**一条都没松。

走真咽喉：`SkillService.install_skill`（写侧唯一入口，安装门＋落位＋记账都在里面）、
`call_skill`（读侧执法接缝）、真 `create_app()` + `TestClient` 的面板两面（对外可见性）。

六条腿各自钉一件事：
① 空壳装完，落盘账本里**不该有**构件摘要（本批的根修）；
② 同一只条目在列表／详情／投影面仍看得见且如实标不可用（§6-272 的读数，本批不许动——
   "不钉"不等于"删条目"，摘掉会让存量空壳在下一次启动集体蒸发）；
③ 日后把真 `main.py` 补进同一个目录 ⇒ 重开实例后 `call_skill` 要真跑出值，并且**这时才**首钉
   （改前读数：`artifact_digest_mismatch`，expected 是那份"什么都没有"的摘要）；
④ 对照：装一只带 `main.py` 的包 ⇒ 装完立刻钉，且等于该目录现量（不许把"不钉"做成一律不钉）；
⑤ 对照：带字节的包被改动 ⇒ 摘要不符照旧拒（写侧这一改不许弄松读侧那道闸）；
⑥ 仓内 `data/` 内容指纹跑前跑后不变（活体只写隔离根）。

数据根经 `tests/manual/_liveVerifyIsolation.isolatedDataRoot()` 单点隔离。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

ROOT = isolatedDataRoot(prefix="neurovaInstallPinB64")
DATA = REPO / "data"


def fingerprint():
    h = hashlib.md5()
    for p in sorted(DATA.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(DATA).as_posix().encode("utf-8"))
            h.update(str(p.stat().st_size).encode("ascii"))
    return h.hexdigest()


DATA_BEFORE = fingerprint()

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.security import artifact_digest as AD  # noqa: E402
from neurova.skills import library_service  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


AGENT = "b64-live"
ENTRY = "def main(**kwargs):\n    return {'ok': True, 'saw': sorted(kwargs)}\n"
failures = []


def read(what, probe):
    """结论 / 现场读数 / 缺陷读法 三件分开打印。"""
    try:
        ok, detail, hint = probe()
    except Exception as exc:  # noqa: BLE001
        ok, detail, hint = False, "探针异常 %r" % (exc,), ""
    print("[%s] %s — %s%s" % ("PASS" if ok else "FAIL", what, detail,
                              "" if ok else ("；缺陷读法：" + hint)))
    if not ok:
        failures.append(what[:6])
    return ok


def svc():
    """经批 60 那唯一取法拿实例——端点读的也是这一份，直调与 HTTP 面才在比同一本账。

    第一版这里自己 `SkillService(skills_dir=隔离根/installed)`，落点与端点用的库根不是同一个目录，
    第 2 腿就在 HTTP 面上找不到那条（红得像是"条目被摘掉了"，其实是脚本没写进那一本账）。
    """
    return library_service.agentLibrary(AGENT)


def freshInstance():
    """模拟重启：复位单例后重新经工厂取——写→读闭环要走装配点，不是靠内存态。"""
    library_service.reset_libraries_for_tests()
    return library_service.agentLibrary(AGENT)


def install(skill_id: str, files: dict):
    """走真安装咽喉；`files` 为空＝本机那种"只有 manifest.json"的空壳。"""
    s = svc()
    src = Path(ROOT) / "src" / skill_id
    src.mkdir(parents=True, exist_ok=True)
    (src / "manifest.json").write_text(json.dumps(
        {"id": skill_id, "name": skill_id, "version": "1.0.0", "source": "marketplace"},
        ensure_ascii=False), encoding="utf-8")
    for name, body in files.items():
        (src / name).write_text(body, encoding="utf-8")
    r = s.install_skill(str(src), skill_id=skill_id)
    assert r.get("success") is True, f"装配本身没成功，样本不成立：{r}"
    return s, s.skills_dir / skill_id


def ledgerDigest(service, skill_id: str) -> str:
    led = json.loads(Path(service.manifest_path).read_text(encoding="utf-8"))
    return str((led.get(skill_id) or {}).get(AD.DIGEST_FIELD) or "")


shellService, shellDir = install("b64-live-shell", files={})
realService, realDir = install("b64-live-real", files={"main.py": ENTRY})

read("1 空壳装完账本里没有构件摘要",
     lambda: (ledgerDigest(shellService, "b64-live-shell") == "",
              f"落盘目录内容={sorted(p.name for p in shellDir.iterdir())}，"
              f"账本摘要={ledgerDigest(shellService, 'b64-live-shell')[:26] or '(无)'}",
              "钉上了就是那份摘要不代表任何构件——日后补进真字节会被它判成篡改（§6-267 的写侧半边）"))


def leg2():
    client = TestClient(create_app())
    head = {"Authorization": "Bearer %s" % create_access_token(
        {"sub": "b64-live-user", "role": "admin", "user_id": "1", "neuser_id": "1"})}
    seen = {}
    for path in (f"/api/v1/skill-pool/private?agent_id={AGENT}",
                 f"/api/v1/skill-pool/agent/{AGENT}/skills"):
        items = client.get(path, headers=head).json()
        items = items if isinstance(items, list) else (items.get("skills") or [])
        row = next((i for i in items if isinstance(i, dict) and i.get("skill_id") == "b64-live-shell"), None)
        if row is None:
            return (False, f"{path} 里没有这一条", "先证看见，再谈标灰——条目被摘掉就是存量空壳集体蒸发那一形")
        seen[path.split("/skill-pool/")[1].split("?")[0]] = (row.get("available"),
                                                            bool(row.get("unavailable_reason")))
    info = shellService.get_skill_info("b64-live-shell")
    return (all(v == (False, True) for v in seen.values()) and info is not None,
            "两面读数=" + json.dumps(seen, ensure_ascii=False) + f"；详情面仍可见={info is not None}",
            "要么条目不见了，要么它被画成可得——本批只该让摘要不出现，读面口径一字不动")


read("2 空壳仍可见且如实标不可用（两面）", leg2)


def leg3():
    (shellDir / "main.py").write_text(ENTRY, encoding="utf-8")
    reopened = freshInstance()
    out = asyncio.run(reopened.call_skill("b64-live-shell", q=1))
    pinnedNow = ledgerDigest(reopened, "b64-live-shell")
    return (out.get("success") is True and (out.get("result") or {}).get("ok") is True
            and pinnedNow.startswith(AD.DIGEST_PREFIX),
            f"补字节后 success={out.get('success')}，error={str(out.get('error'))[:40]}，"
            f"此时账本摘要={pinnedNow[:26] or '(无)'}",
            "被拒即一次误钉把'后来补真字节'这条路永久钉死；补上后才首钉也没发生＝守卫被整体关掉")


read("3 日后补进真字节要跑得动，且这时才首钉", leg3)

read("4 对照：带 main.py 的包装完立刻钉且等于现量",
     lambda: (ledgerDigest(realService, "b64-live-real") == AD.digestDir(realDir),
              f"钉的是 {ledgerDigest(realService, 'b64-live-real')[:26]}，目录现量 {AD.digestDir(realDir)[:26]}",
              "不钉或钉错＝把'有构件才钉'做成了'一律不钉'，TOFU 那条腿从此白跑"))


def leg5():
    (realDir / "main.py").write_text("def main(**kwargs):\n    return {'sneaked': True}\n",
                                     encoding="utf-8")
    out = asyncio.run(freshInstance().call_skill("b64-live-real", q=1))
    return (out.get("success") is False and out.get("error") == AD.REASON_MISMATCH,
            f"success={out.get('success')}，error={str(out.get('error'))[:40]}",
            "篡改不再被拒＝写侧这一改把读侧那道闸也弄松了")


read("5 对照：已钉的包被改动仍报摘要不符", leg5)

print("    OBSERVE 隔离根=%s" % ROOT)
read("6 仓库 data/ 未被写入",
     lambda: (fingerprint() == DATA_BEFORE,
              f"跑前 {DATA_BEFORE[:12]} ↔ 跑后 {fingerprint()[:12]}",
              "两个指纹不同即本轮活体写进了仓内真数据根"))

print("\n== 得数：%s ==" % ("全部通过（6 腿）" if not failures else f"FAIL {failures}"))
sys.exit(1 if failures else 0)
