# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-13 批 31，§6-172 / P3 插件半区）：登记钉的摘要真能在装载前拦住换包。

技能半区那支（`tests/manual/artifactIntegrity_batch30.py`）证的是 zip 上传面；这一支换到
插件面，读的是同一条性质在**第二个存储点**上成不成立（`state.json`，而不是 `manifest.json`）：

1. 真 `create_app()` + 真 `POST /api/v1/plugins/{id}/install`（插件目录当场造在真插件根内）；
2. 读**盘上的 state.json**：登记时钉下的摘要必须在，且等于该目录现状的聚合值；
3. 未改动 ⇒ `enable` → `load` 真把插件实例化（不是把布尔翻一下）；
4. 换一个字节 ⇒ 重建管理器（该组件的重启态：`state.json` 是唯一事实源）后 `load` 必须 409
   并点名 `artifact_digest_mismatch` —— 拒因走的是 `_REASON_TO_STATUS` 那张单点映射表；
5. 反照：把盘上摘要抹掉 ⇒ 回到 TOFU 首钉放行（否则第 4 项可能只是"永远拒"的假绿）。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/pluginArtifact_batch31.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaPluginB31")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.core.data_root import dataPath  # noqa: E402
from neurova.security import artifact_digest as AD  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


failures: list[str] = []
NAME = "liveprobe31"

#: 作者基类的最小合法实现：四个抽象方法齐备，装载真能实例化。
_BODY = (
    "from neurova.plugins.base_plugin import BasePlugin\n"
    "class LiveProbe31(BasePlugin):\n"
    "    def on_initialize(self):\n        self.initialized = True\n"
    "    def on_start(self):\n        self.started = True\n"
    "    def on_stop(self):\n        self.started = False\n"
    "    def on_destroy(self):\n        self.destroyed = True\n"
)


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _writePlugin(root: Path) -> Path:
    pdir = root / NAME
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "manifest.json").write_text(json.dumps({
        "name": NAME, "version": "1.0.0", "description": "live probe", "author": "qa",
        "entry_point": "main.py", "dependencies": [],
        "permissions": {}, "framework_surfaces": []}), encoding="utf-8")
    (pdir / "main.py").write_text(_BODY, encoding="utf-8")
    return pdir


def main() -> int:
    print(f"数据根（注入隔离）: {WORK_ROOT}")

    from neurova.api.app import create_app
    from neurova.api.auth import get_current_user
    from neurova.plugins.plugin_manager import (
        STATE_FILE_NAME, get_plugin_manager, reset_plugin_manager)

    pluginRoot = dataPath("plugins")
    Path(pluginRoot).mkdir(parents=True, exist_ok=True)
    pdir = _writePlugin(Path(pluginRoot))

    app = create_app(enable_memory=False, enable_channels=False)
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "1", "username": "ops", "role": "admin"}
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            installed = client.post(f"/api/v1/plugins/{NAME}/install",
                                    json={"source": str(pdir)})
            check("[1] 真 HTTP 登记面收下插件", installed.status_code == 200,
                  f"{installed.status_code} {installed.text[:160]}")
            if installed.status_code != 200:
                return 1

            stateFile = Path(pluginRoot) / STATE_FILE_NAME
            stored = json.loads(stateFile.read_text(encoding="utf-8"))
            pinned = str((stored.get("plugins") or {}).get(NAME, {}).get(AD.DIGEST_FIELD) or "")
            check("[2] 摘要落进了 state.json（读盘不是读内存）",
                  pinned.startswith(AD.DIGEST_PREFIX), pinned[:22] or "(缺)")
            check("[3] 钉的就是登记时那份字节", pinned == AD.digestDir(pdir),
                  f"钉={pinned[:18]}… 现={AD.digestDir(pdir)[:18]}…")

            check("[4] 先启用", client.post(f"/api/v1/plugins/{NAME}/enable").status_code == 200,
                  client.post(f"/api/v1/plugins/{NAME}/enable").text[:120])
            first = client.post(f"/api/v1/plugins/{NAME}/load")
            check("[5] 没动过 ⇒ 真装载", first.status_code == 200,
                  f"{first.status_code} {first.text[:160]}")

            (pdir / "main.py").write_text(_BODY + "\n# swapped after registration\n",
                                           encoding="utf-8")
            # 该组件重启态＝从 state.json 重建（它没有别的持久态），故这里 reset 一次
            # 而不是在同一实例上重复装载（已 loaded 的记录会直接回实例，那是选定行为）。
            reset_plugin_manager()
            get_plugin_manager(str(pluginRoot)).enable_plugin(NAME)
            second = client.post(f"/api/v1/plugins/{NAME}/load")
            check("[6] 换一个字节后重建管理器 ⇒ 装载被拒且语义是 409",
                  second.status_code == 409, f"{second.status_code} {second.text[:200]}")
            check("[7] 拒因点名是完整性问题（并带两边读数）",
                  AD.REASON_MISMATCH in second.text and second.text.count("sha256:") >= 2,
                  second.text[:220])

            fresh = json.loads(stateFile.read_text(encoding="utf-8"))
            fresh["plugins"][NAME][AD.DIGEST_FIELD] = ""
            stateFile.write_text(json.dumps(fresh), encoding="utf-8")
            reset_plugin_manager()
            get_plugin_manager(str(pluginRoot)).enable_plugin(NAME)
            third = client.post(f"/api/v1/plugins/{NAME}/load")
            check("[8] 反照：摘要被抹掉时是 TOFU 首钉放行，不是拒绝",
                  third.status_code == 200, f"{third.status_code} {third.text[:180]}")
            relatched = str(json.loads(stateFile.read_text(encoding="utf-8"))
                            ["plugins"][NAME].get(AD.DIGEST_FIELD) or "")
            check("[9] 首钉落盘且等于当前盘上那份（换包后的字节）",
                  relatched == AD.digestDir(pdir) and relatched != pinned,
                  relatched[:22] or "(没落盘)")
    finally:
        app.dependency_overrides.clear()
        reset_plugin_manager()

    print("\nLIVE-VERIFY PASSED / 工单 2026-10-13 批 31（P3 构件完整性·插件半区）"
          if not failures else f"\nLIVE-VERIFY FAILED：{failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
