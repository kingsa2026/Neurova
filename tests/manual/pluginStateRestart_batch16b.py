# -*- coding: utf-8 -*-
"""live-verify（台账 §6-164，裁定「落盘状态 + 只发现不装载」）：插件登记状态跨**进程**真走一遍。

判据档（`tests/unit/plugins/test_pluginStateSurvivesRestart.py`）在同一个进程里换实例模拟重启；
这一支要证的是另一件事：**换一个操作系统进程、同一份隔离数据根**，面板读到的
"装过什么、启没启用"还在，而"装载/挂载"确实不在——后者是这条裁定的安全边界
（P3 的来源白名单与构件完整性没做之前，开机自启第三方代码不是便利而是风险）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/pluginStateRestart_batch16b.py`
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaPluginState16b")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402

BASE = "/api/v1/plugins"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _adminHeaders() -> dict:
    token = create_access_token({"sub": "u-admin", "username": "u-admin", "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def _writePluginDir(root: Path, name: str = "probe") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps({
        "name": name, "version": "1.0.0", "description": "state probe",
        "entry_point": "main.py", "module_class": "ProbePlugin",
        "permissions": {}, "framework_surfaces": [], "api_endpoints": [],
    }), encoding="utf-8")
    (directory / "main.py").write_text(
        "from neurova.plugins.base_plugin import BasePlugin\n\n\n"
        "class ProbePlugin(BasePlugin):\n"
        "    async def on_initialize(self):\n        pass\n\n"
        "    async def on_start(self):\n        pass\n\n"
        "    async def on_stop(self):\n        pass\n\n"
        "    async def on_destroy(self):\n        pass\n", encoding="utf-8")
    return directory


def _repoDataFingerprint() -> str:
    root = Path(__file__).resolve().parents[2] / "data"
    if not root.exists():
        return "<absent>"
    digest = hashlib.md5()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            st = path.stat()
            digest.update(f"{path.relative_to(root)}|{st.st_size}|{int(st.st_mtime)}".encode())
    return digest.hexdigest()


def main() -> int:
    from neurova.plugins import plugin_manager as managerModule
    from neurova.plugins import plugin_route_mount

    before = _repoDataFingerprint()
    pluginRoot = Path(get_data_root()) / "plugins"
    pluginRoot.mkdir(parents=True, exist_ok=True)
    statePath = pluginRoot / "state.json"
    directory = _writePluginDir(pluginRoot)

    managerModule.reset_plugin_manager()
    plugin_route_mount.resetPluginMounts()
    app = create_app()

    with TestClient(app) as client:
        headers = _adminHeaders()

        installed = client.post(f"{BASE}/probe/install", headers=headers,
                                json={"source": str(directory)})
        check("1 真 app 上安装回 200（注册表那行不是装饰）",
              installed.status_code == 200, installed.text[:160])
        check("2 状态文件真落在插件根里", statePath.is_file(), str(statePath))

        listed = client.get(f"{BASE}/", headers=headers).json()["data"]
        check("3 列表读得到这条，且没有把「读不出」混进来",
              listed["total"] == 1 and listed["state_load_error"] is None,
              json.dumps(listed, ensure_ascii=False)[:200])

        enabled = client.post(f"{BASE}/probe/enable", headers=headers)
        check("4 启用回 200", enabled.status_code == 200, enabled.text[:120])
        check("5 enabled 写进了文件",
              json.loads(statePath.read_text(encoding="utf-8"))
              ["plugins"]["probe"]["enabled"] is True)

        loaded = client.post(f"{BASE}/probe/load", headers=headers)
        check("6 装载回 200（运行期状态，本进程内看得见）",
              loaded.status_code == 200, loaded.text[:160])

    # 换一个操作系统进程读同一份根：这才是"重启"，换实例只是"换了个对象"
    second = subprocess.run(
        [sys.executable, "-c",
         "import json,os;"
         "from neurova.plugins.plugin_manager import PluginManager;"
         "m=PluginManager();"
         "r=m.get_plugin('probe');"
         "print(json.dumps({'installed': r is not None,"
         " 'enabled': getattr(r,'enabled',None),"
         " 'loaded': getattr(r,'loaded',None),"
         " 'load_error': m.stateLoadError,"
         " 'unregistered': m.unregisteredPluginDirs()}))"],
        capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "NEUROVA_DATA_DIR": str(get_data_root())})
    try:
        reading = json.loads(second.stdout.strip().splitlines()[-1])
    except Exception:
        reading = {"raw": (second.stdout + second.stderr)[-260:]}

    check("7 第二个进程读得到同一条登记", reading.get("installed") is True, str(reading)[:200])
    check("8 enabled 跨进程存活（那是人给的决定）", reading.get("enabled") is True, str(reading)[:200])
    check("9 loaded **不**跨进程复活（开机不自启第三方代码）",
          reading.get("loaded") is False, str(reading)[:200])
    check("10 未登记的目录不会被当成已安装",
          "probe" not in (reading.get("unregistered") or []), str(reading)[:200])

    # 先把进程内单例丢掉（＝重启）：上一段里它已经装载过，不重建成新实例就会读到
    # 进程内的 loaded=True，那条拒挂读数就测不到了（本仓记过的"写侧与读侧不同源"同族）。
    managerModule.reset_plugin_manager()
    with TestClient(app) as client:
        headers = _adminHeaders()
        mount = client.post(f"{BASE}/probe/routes/mount", headers=headers)
        check("11 重启后挂载被如实拒（entry_not_loaded），不静默成功也不自动装载",
              mount.status_code in (409, 500) and "entry_not_loaded" in mount.text,
              f"{mount.status_code} {mount.text[:160]}")
        stillListed = client.get(f"{BASE}/", headers=headers).json()["data"]
        check("11b 拒挂之后登记与 enabled 仍在（状态没被一次失败的回滚吃掉）",
              stillListed["total"] == 1
              and (stillListed["items"][0].get("enabled") is True),
              json.dumps(stillListed, ensure_ascii=False)[:200])

    # 损坏文件：列表不许读成"这台机器没装过插件"
    statePath.write_text("not json at all", encoding="utf-8")
    managerModule.reset_plugin_manager()
    with TestClient(app) as client:
        headers = _adminHeaders()
        listed = client.get(f"{BASE}/", headers=headers).json()["data"]
    check("12 坏状态文件被点名，而不是读成空列表",
          listed["state_load_error"] == "state_store_corrupt", json.dumps(listed)[:200])
    check("13 损坏现场被改名隔离（下一次写入不会覆盖掉它）",
          any(p.name.startswith("state.json.corrupt-") for p in pluginRoot.iterdir()),
          str([p.name for p in pluginRoot.iterdir()])[:200])

    check("14 仓库 data/ 未被本轮写入", _repoDataFingerprint() == before)

    print()
    if failures:
        print(f"结果：{len(failures)} 项 FAIL → {failures}")
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
