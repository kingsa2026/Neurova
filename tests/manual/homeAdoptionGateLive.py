# -*- coding: utf-8 -*-
"""live-verify（批 §6-204）：数据根被指到别处时，真装配不得伸手搬走主目录旧物。

事故形状（本仓 2026-10-14 实测发生过）：`tests/conftest.py:58` 把整轮跑测的数据根注入
临时目录，home 没被一起隔离——§6-203 的"空缺即收养"于是把开发者 `~/.neurova/` 下的
`providers.json`（18 家、13 份加密凭据）、`audit.db`、`governance_whitelist.json`
`shutil.move` 进了 `Temp/neurovaDataRoot-<随机>/`。判据档在临时 home 上跑，看不见这条
支路；这一支要证的是**真 app 起来、四个生产接缝都走一遍**之后的三件事：

1. 四份旧物**原地不动**（假 home 里逐份仍在，内容没被搬走也没被复制进数据根）；
2. 真实 `~/.neurova/` 指纹前后一致（既没被搬走，也没被反向写回）；
3. 反证（独立子进程）：把权利闸单独摘掉（`homeAdoptionAllowed` 桩成恒真），
   同一套动作必须把假 home 里的旧物**搬空**——否则"没搬"可能只是脚本没够着那条支路。

home 一律用临时目录冒充：真主目录只做只读指纹对照，探针不往那里写东西——
要验的是"不动"，造在假 home 里同样咬得住，而造在真 home 里就是拿用户的凭据做实验。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.homeAdoptionGateLive
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: 假 home 里四族的旧落点（相对 `.neurova`）；audit.db 用 0 字节（SQLite 认空文件为库）。
_SEEDS = {
    "config/providers.json": "SENTINEL-PROVIDERS",
    "audit.db": "",
    "config/governance_whitelist.json": "SENTINEL-WHITELIST",
    "skills/installed/pkg-a/skill.json": "SENTINEL-PKG",
}
MARKER = "SENTINEL"


def _homeSnapshot(home: Path) -> dict:
    shots = {}
    root = home / ".neurova"
    if not root.is_dir():
        return shots
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes() if p.stat().st_size <= 4 * 1024 * 1024 else b"<big>"
            shots[str(p.relative_to(root))] = hashlib.md5(data).hexdigest()
    return shots


def _seedFakeHome(fakeHome: Path) -> None:
    for rel, payload in _SEEDS.items():
        target = fakeHome / ".neurova" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")


def main() -> int:
    from tests.manual._liveVerifyIsolation import (
        isolatedAgentWorkspaces,
        isolatedDataRoot,
    )

    failures: list[str] = []
    readings: dict = {}

    fakeHome = Path(tempfile.mkdtemp(prefix="neurovaGateFakeHome-"))
    _seedFakeHome(fakeHome)
    fakeHomeBefore = _homeSnapshot(fakeHome)

    realHome = Path.home()
    realHomeBefore = _homeSnapshot(realHome)

    # 事故形状＝数据根被注入到一个**不等于默认推导**的临时址（conftest 就是这么干的）
    isolatedDataRoot(prefix="neurovaGateData")
    isolatedAgentWorkspaces(prefix="neurovaGateData")
    import pathlib

    pathlib.Path.home = lambda: fakeHome      # type: ignore[method-assign]

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.core.data_root import get_data_root, homeAdoptionAllowed
    from neurova.llm.provider_manager import get_provider_manager, reset_provider_manager
    from neurova.security import audit_logger as auditMod
    from neurova.security.governance import get_governance, reset_governance
    from neurova.skills.hub_client import SkillHubClient

    dataRoot = get_data_root()
    readings["data_root"] = str(dataRoot)
    readings["fake_home"] = str(fakeHome)
    readings["gate_reads_false_under_foreign_root"] = homeAdoptionAllowed() is False

    with TestClient(create_app()):
        readings["app_boot"] = "ok"

        reset_provider_manager()
        providerPath = get_provider_manager()._config_path
        readings["providers_written_in_data_root"] = dataRoot in providerPath.parents

        auditMod.AuditLogger._instance = None
        auditMod._audit_logger = None
        logger = auditMod.get_audit_logger()
        readings["audit_write_returned"] = logger.log_config_change(
            "live-gate", "temperature", 0.2, 0.7)

        reset_governance()
        policy = get_governance()
        readings["whitelist_write_returned"] = policy.add_whitelist_entry(
            pattern="git status", match_type="prefix", note="活体")

        hub = SkillHubClient()
        readings["hub_root_in_data_root"] = dataRoot in Path(hub._base_dir).parents

    reset_provider_manager()
    reset_governance()

    fakeHomeAfter = _homeSnapshot(fakeHome)
    readings["fake_home_entries_after"] = sorted(fakeHomeAfter)
    readings["fake_home_untouched"] = fakeHomeBefore == fakeHomeAfter
    if fakeHomeBefore != fakeHomeAfter:
        failures.append("假 home 里的旧物被动过（搬走或改写）：%s ≠ %s"
                        % (sorted(fakeHomeBefore), sorted(fakeHomeAfter)))

    # 没搬走之外还要证"也没复制进来"：数据根下任何一份带哨兵内容的文件都是第二落点
    copied = [str(p.relative_to(dataRoot)) for p in dataRoot.rglob("*")
              if p.is_file() and p.stat().st_size <= 1024 * 1024
              and MARKER.encode() in p.read_bytes()]
    readings["sentinel_copied_into_data_root"] = copied
    if copied:
        failures.append("旧物被复制进数据根＝同一份东西两个落点：%s" % copied)

    realHomeAfter = _homeSnapshot(realHome)
    readings["real_home_untouched"] = realHomeBefore == realHomeAfter
    if realHomeBefore != realHomeAfter:
        failures.append("本轮改动了真实 ~/.neurova/：%s"
                        % sorted(set(realHomeBefore) | set(realHomeAfter)))

    if readings["gate_reads_false_under_foreign_root"] is not True:
        failures.append("权利闸在注入的别处根下没有判 False——事故形状仍会搬")
    for key in ("providers_written_in_data_root", "hub_root_in_data_root"):
        if readings.get(key) is not True:
            failures.append("读数 %s 未成立（%s）" % (key, readings.get(key)))
    if readings["audit_write_returned"] is False:
        failures.append("审计写入返回 False：新落点没被用起来")

    readings["counterprobe"] = _runCounterProbe()
    if "COUNTER-MOVE-BLUE" not in readings["counterprobe"]:
        failures.append("摘掉权利闸后旧物没被搬空——本批读数可能没咬住那条支路")

    print(json.dumps(readings, ensure_ascii=False, indent=2))
    for f in failures:
        print("[FAIL] " + f)
    if failures:
        return 1
    print("LIVE-PASS：别处根下四族旧物原地不动、真主目录指纹未变、摘闸反证把假 home 搬空")
    return 0


def _runCounterProbe() -> str:
    """子进程：把闸桩成恒真（退回 §6-203 的形状），同一套动作必须把假 home 搬空。"""
    code = r'''
import json, os, pathlib, tempfile
fakeHome = pathlib.Path(tempfile.mkdtemp(prefix="neurovaCounterGateHome-"))
data = pathlib.Path(tempfile.mkdtemp(prefix="neurovaCounterGateData-"))
os.environ["NEUROVA_DATA_DIR"] = str(data)
for rel, payload in {
    "config/providers.json": "SENTINEL-PROVIDERS",
    "config/governance_whitelist.json": "SENTINEL-WHITELIST",
    "skills/installed/pkg-a/skill.json": "SENTINEL-PKG",
}.items():
    p = fakeHome / ".neurova" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(payload, encoding="utf-8")
pathlib.Path.home = lambda: fakeHome
from neurova.core import data_root
data_root.homeAdoptionAllowed = lambda: True          # 摘闸＝§6-203 的形状
from neurova.llm.provider_manager import _default_config_dir
from neurova.security.governance import _default_whitelist_path
from neurova.skills.hub_client import SkillHubClient
_default_config_dir()
_default_whitelist_path()
SkillHubClient()
left = sorted(str(p.relative_to(fakeHome)) for p in fakeHome.rglob("*") if p.is_file())
moved = sorted(str(p.relative_to(data)) for p in data.rglob("*") if p.is_file())
print("home_left=%s" % json.dumps(left))
print("data_now=%s" % json.dumps(moved))
assert not any("providers.json" in x for x in left), "摘了闸仍没搬走＝收养这条路本来就不在"
assert any(p.endswith("providers.json") for p in moved), "搬走却没进数据根＝落点另有出处"
print("COUNTER-MOVE-BLUE")
'''
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = (proc.stdout or "").strip()
    return out[-500:] or (proc.stderr or "").strip()[-300:]


if __name__ == "__main__":
    raise SystemExit(main())
