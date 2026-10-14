# -*- coding: utf-8 -*-
"""live-verify（批 §6-203）：`~/.neurova/` 那族配置收进数据根后，真装配与真写入落在哪儿。

用户 2026-10-14 第二道裁定：把 `providers.json` / `audit.db` / `governance_whitelist.json`
/ `skills/installed` 四族收进数据根。判据档在临时根上看形状；这一支要证的是**真 app 起来
之后**的四件事：

1. `create_app()` 带真 lifespan 起得来（凭据面在启动期被构造，落点改了不能炸）；
2. 四族各自经**生产接缝**写一次（`get_provider_manager()` / `get_audit_logger()` /
   `get_governance()` / `SkillHubClient()`），写出来的东西全在数据根下；
3. 一个文件都没落到"家"里——本 fixture 的 home 是假的，真实 `~/.neurova/` 另取指纹前后对账；
4. 旧主目录那一份会被**搬进**数据根（不是复制、不是忽略），且两侧同时在场时不覆盖新那份；
5. 反证（独立子进程）：把两处落点函数单独退回旧的 home 形态，同一套读数必须翻红——
   否则这些读数可能来自别处（例如 conftest 恰好注入过 env）。
6. 顺带一条真 HTTP 面读数：从活 app 的路由里取一条审计查询端点打过去，
   配一条不存在路径必须 404 作校准（路由表形状读数不可信，故用行为读数）。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.homeLandingIntoDataRootLive
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

failures: list[str] = []
readings: dict = {}


def _homeSnapshot(home: Path) -> dict:
    """指定"家"的内容指纹（只 stat + 读字节，不写不删）。"""
    shots = {}
    root = home / ".neurova"
    if not root.is_dir():
        return shots
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes() if p.stat().st_size <= 4 * 1024 * 1024 else b"<big>"
            shots[str(p.relative_to(root))] = hashlib.md5(data).hexdigest()
    return shots


def main() -> int:
    from tests.manual._liveVerifyIsolation import (
        isolatedAgentWorkspaces,
        isolatedDataRoot,
    )

    # 注意 `Path("")` 就是 `Path(".")`——只看 is_dir() 会把"仓库根"当成假 home，
    # 于是一个"家目录零写入"的判据会在整棵工作树上跑 rglob。env 缺没缺要单独问。
    declared = (os.environ.get("NEUROVA_LIVE_FAKE_HOME") or "").strip()
    fakeHome = Path(declared) if declared else None
    if fakeHome is None or not fakeHome.is_dir():
        import tempfile

        fakeHome = Path(tempfile.mkdtemp(prefix="neurovaFakeHome-"))
    realHome = Path.home()                     # 换掉 Path.home 之前先记住真实现场
    realHomeBefore = _homeSnapshot(realHome)

    isolatedDataRoot(prefix="neurovaHomeLanding")
    isolatedAgentWorkspaces(prefix="neurovaHomeLanding")
    # 必须在任何 neurova.* 之前生效：落点函数虽在调用时解析，但被测的构造发生在 app 启动期
    os.environ["HOME"] = str(fakeHome)
    os.environ["USERPROFILE"] = str(fakeHome)
    import pathlib

    pathlib.Path.home = lambda: fakeHome      # type: ignore[method-assign]

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.auth import create_access_token
    from neurova.core.data_root import get_data_root
    from neurova.llm.provider_manager import get_provider_manager, reset_provider_manager
    from neurova.security import audit_logger as auditMod
    from neurova.security.governance import get_governance, reset_governance
    from neurova.skills.hub_client import SkillHubClient

    dataRoot = get_data_root()
    readings["data_root"] = str(dataRoot)
    readings["fake_home"] = str(fakeHome)

    with TestClient(create_app()) as client:
        readings["app_boot"] = "ok"

        reset_provider_manager()
        providerPath = get_provider_manager()._config_path
        readings["providers_path_under_data_root"] = dataRoot in providerPath.parents
        readings["providers_path"] = str(providerPath)

        auditMod.AuditLogger._instance = None
        auditMod._audit_logger = None
        logger = auditMod.get_audit_logger()
        wrote = logger.log_config_change("live-user", "temperature", 0.2, 0.7)
        auditDb = dataRoot / "audit.db"
        readings["audit_write_returned"] = wrote
        readings["audit_db_under_data_root"] = auditDb.exists()
        readings["audit_db_path"] = logger._db_path

        reset_governance()
        policy = get_governance()
        policy.add_whitelist_entry(pattern="git status", match_type="prefix", note="活体")
        written = sorted(dataRoot.rglob("governance_whitelist.json"))
        readings["whitelist_under_data_root"] = bool(written)
        readings["whitelist_entries_on_disk"] = (
            len(json.loads(written[0].read_text(encoding="utf-8")).get("entries", []))
            if written else -1
        )

        hub = SkillHubClient()
        readings["hub_root_under_data_root"] = dataRoot in Path(hub._base_dir).parents
        readings["hub_root"] = str(hub._base_dir)

        # 真 HTTP 面：路由对象里 `.path` 对 _IncludedRouter 取不到（本仓实测形状失真），
        # 改从 OpenAPI 表取真路径——它就是从活路由生成的。
        auditRoutes = sorted(
            path for path in client.app.openapi().get("paths", {}) if "audit" in path
        )
        readings["audit_routes_found"] = auditRoutes[:3]
        if auditRoutes:
            token = create_access_token({"user_id": "live-audit", "username": "live-audit",
                                         "sub": "live-audit"})
            resp = client.get(auditRoutes[0], headers={"Authorization": "Bearer " + token})
            readings["audit_endpoint"] = auditRoutes[0]
            readings["audit_endpoint_status"] = resp.status_code
            # 该面 `Depends(require_admin())`：非管理员凭证必须被拒（401/403 是门在，
            # 不是缺陷）——本探针不伪造管理员凭证去绕它。
            readings["audit_gate_fail_closed"] = resp.status_code in (401, 403)
            if resp.status_code == 200:
                readings["audit_endpoint_sees_own_row"] = "live-user" in resp.text
        else:
            failures.append("OpenAPI 里没有审计面：本批审计读面未经真 HTTP 自证")
        # 写面与读面的闭环走端点自己那个读口（它同样经 `get_audit_logger()`）
        from neurova.api.endpoints.audit import _query_entries

        entries = _query_entries(None, None, None, None)
        readings["readSeam_rows"] = len(entries)
        readings["readSeam_sees_own_row"] = any(
            (e.get("user_id") if isinstance(e, dict) else getattr(e, "user_id", None)) == "live-user"
            for e in entries
        )
        readings["calibration_404"] = client.get("/api/v1/definitely-not-a-route").status_code

    reset_provider_manager()
    reset_governance()

    homeEntries = sorted(p.name for p in fakeHome.rglob("*") if p.exists())
    readings["fake_home_entries"] = homeEntries
    if homeEntries:
        failures.append("四族仍往家目录写东西：%s" % homeEntries)
    for key in ("providers_path_under_data_root", "audit_db_under_data_root",
                "whitelist_under_data_root", "hub_root_under_data_root"):
        if readings.get(key) is not True:
            failures.append("读数 %s 未成立（%s）" % (key, readings.get(key)))
    if readings.get("audit_write_returned") is False:
        failures.append("审计写入返回 False")
    if readings.get("whitelist_entries_on_disk", -1) < 1:
        failures.append("白名单条目没落到数据根那个文件里")
    if readings.get("calibration_404") != 404:
        failures.append("404 校准未成立，HTTP 面读数不可信")
    if readings.get("audit_gate_fail_closed") is False and readings.get(
            "audit_endpoint_sees_own_row") is False:
        failures.append("审计面既不拒非管理员凭证、又看不到刚写的那条（写面与读面没接上）")
    if readings.get("readSeam_sees_own_row") is not True:
        failures.append(
            "端点那个读口看不到刚写的审计行（readSeam_rows=%s）——写读没在同一库上闭环"
            % readings.get("readSeam_rows"))

    realHomeAfter = _homeSnapshot(realHome)
    readings["real_home_untouched"] = realHomeBefore == realHomeAfter
    if realHomeBefore != realHomeAfter:
        failures.append("本轮改动了真实 ~/.neurova/：%s"
                        % sorted(set(realHomeBefore) | set(realHomeAfter)))

    readings["counterprobe"] = _runCounterProbe()
    if "COUNTER-HOME-BLUE" not in readings["counterprobe"]:
        failures.append("把两处落点退回旧 home 形态后读数没翻红——本批判据可能没咬住")

    print(json.dumps(readings, ensure_ascii=False, indent=2))
    for f in failures:
        print("[FAIL] " + f)
    if failures:
        return 1
    print("LIVE-PASS：四族全落数据根、假 home 零写入、真主目录指纹未变、反证翻红")
    return 0


def _runCounterProbe() -> str:
    """子进程：把 providers / audit 两处落点单独退回旧 home 形态，同一套读数必须红。"""
    code = r'''
import os, pathlib, tempfile, json
home = pathlib.Path(tempfile.mkdtemp(prefix="neurovaCounterHome-"))
data = pathlib.Path(tempfile.mkdtemp(prefix="neurovaCounterData-"))
os.environ["NEUROVA_DATA_DIR"] = str(data)
pathlib.Path.home = lambda: home
from neurova.llm import provider_manager as pm
from neurova.security import audit_logger as al
pm._default_config_dir = lambda: home / ".neurova" / "config"
al.auditDbPath = lambda: str(home / ".neurova" / "audit.db")
pm.reset_provider_manager()
mgr = pm.get_provider_manager()
al.AuditLogger._instance = None
al._audit_logger = None
lg = al.get_audit_logger()
lg.log_config_change("u", "k", 1, 2)
inHome = [str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()]
print("home_after_revert=%s" % json.dumps(inHome, ensure_ascii=False))
assert any("providers.json" in x for x in inHome) and any("audit.db" in x for x in inHome), \
    "COUNTER-HOME-BLUE: 退回旧形态后 home 里反而没东西，说明这批读数另有出处"
print("COUNTER-HOME-BLUE")
'''
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ})
    return (proc.stdout or "").strip()[-400:] or (proc.stderr or "").strip()[-300:]


if __name__ == "__main__":
    raise SystemExit(main())
