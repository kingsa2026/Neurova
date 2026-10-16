# -*- coding: utf-8 -*-
"""live-verify（工单 2026-10-12 批 14，裁定乙）：语言面在**活 app** 上真走一遍。

判据档（`tests/unit/api/test_languageFaceReadSurface.py`）挂的是手搭的 `FastAPI()`；这一支要证的是
另一件事——`/api/v1/language/*` 在 `create_app()` 的真实路由表里真的可达（注册表那一行不是装饰）、
真吃**真 JWT**（不是 `dependency_overrides` 给的假身份）、偏好真的落到隔离数据根并能被
**另一个进程**读回、覆盖层写面真的只认管理员、而内置那条 `is_approved` 门一寸没松。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/languageFace_batch14.py`
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402

WORK_ROOT = isolatedDataRoot(prefix="neurovaLanguage14")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402

BASE = "/api/v1/language"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _headers(sub: str, role: str) -> dict:
    token = create_access_token({"sub": sub, "username": sub, "role": role})
    return {"Authorization": f"Bearer {token}"}


def _dataDirFingerprint() -> str:
    """仓库 `data/` 的内容指纹（名 + 字节数 + mtime），不取文件清单——
    清单看不见原地改写与等量搬移。"""
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
    from neurova.language import manager as languageManagerModule
    from neurova.language.manager import LanguageManager
    from neurova.language.models import Language

    before = _dataDirFingerprint()
    app = create_app()

    with TestClient(app) as client:
        userHeaders = _headers("u-live-1", "user")
        otherHeaders = _headers("u-live-2", "user")
        adminHeaders = _headers("u-live-admin", "admin")

        prefsPath = Path(get_data_root()) / "language_preferences.json"
        check("1 真路由可达：GET preferences/mine 用真 JWT 回 200",
              client.get(f"{BASE}/preferences/mine", headers=userHeaders).status_code == 200,
              client.get(f"{BASE}/preferences/mine", headers=userHeaders).text[:120])
        check("2 读面前盘上不该有偏好文件", not prefsPath.exists(), str(prefsPath))

        view = client.get(f"{BASE}/preferences/mine", headers=userHeaders).json()["data"]
        check("3 没设过就如实报未设（不把默认值冒充成用户做过的决定）",
              view["configured"] is False and view["source"] == "default", json.dumps(view))

        put = client.put(f"{BASE}/preferences/mine", headers=userHeaders,
                         json={"primary_language": "zh-CN", "auto_detect": False})
        check("4 PUT `zh-CN` 归一成 `zh` 并回显来路",
              put.status_code == 200 and put.json()["data"]["primary_language"] == "zh"
              and put.json()["data"]["requested_tag"] == "zh-CN", put.text[:160])
        check("5 偏好真的落到隔离数据根（不是 CWD 相对、不在译文目录里）",
              prefsPath.is_file() and str(prefsPath).startswith(str(WORK_ROOT)), str(prefsPath))
        disk = json.loads(prefsPath.read_text(encoding="utf-8")) if prefsPath.is_file() else {}
        check("6 落盘内容里有这个人且落的是归一后的码",
              disk.get("preferences", {}).get("u-live-1", {}).get("primary_language") == "zh",
              json.dumps(disk)[:200])

        another = LanguageManager(data_dir=str(Path(get_data_root()) / "language"))
        check("7 第二个实例（＝重启）从盘上读回同一个人同一个语言",
              another.get_user_preference("u-live-1") is not None
              and another.get_user_preference("u-live-1").primary_language is Language.CHINESE)

        secondProcess = subprocess.run(
            [sys.executable, "-c",
             "import json,os;"
             "p=os.path.join(os.environ['NEUROVA_DATA_DIR'],'language_preferences.json');"
             "print(json.load(open(p,encoding='utf-8'))['preferences']['u-live-1']['primary_language'])"],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "NEUROVA_DATA_DIR": str(WORK_ROOT), "PYTHONIOENCODING": "utf-8"})
        check("8 换一个进程读回同一条（跨进程持久，不是进程内字典）",
              secondProcess.stdout.strip() == "zh",
              (secondProcess.stdout or secondProcess.stderr).strip()[:160])

        bad = client.put(f"{BASE}/preferences/mine", headers=userHeaders,
                         json={"primary_language": "klingon"})
        check("9 不识别的语言码：400 且点名",
              bad.status_code == 400 and "klingon" in bad.text, bad.text[:120])
        auto = client.put(f"{BASE}/preferences/mine", headers=userHeaders,
                          json={"primary_language": "auto"})
        check("10 `auto` 不许当首选语言（那件事由 auto_detect 承载）",
              auto.status_code == 400 and "auto_detect" in auto.text, auto.text[:160])
        check("11 被拒的写入没改盘上那条",
              json.loads(prefsPath.read_text(encoding="utf-8"))["preferences"]["u-live-1"]
              ["primary_language"] == "zh")

        otherView = client.get(f"{BASE}/preferences/mine", headers=otherHeaders).json()["data"]
        check("12 换一个人的 token 读到的是他自己的（按属主隔离）",
              otherView["configured"] is False and otherView["user_id"] == "u-live-2",
              json.dumps(otherView)[:160])

        denied = client.put(f"{BASE}/overlay/ui-overlay", headers=userHeaders,
                            json={"translations": {"live.probe.title": {"zh-CN": "活体覆盖"}}})
        check("13 覆盖层写面对普通用户是 403（未审内容进 UI 的入口）",
              denied.status_code == 403, denied.text[:120])

        written = client.put(f"{BASE}/overlay/ui-overlay", headers=adminHeaders,
                             json={"translations": {"live.probe.title": {"zh-CN": "活体覆盖"}}})
        check("14 管理员写覆盖层回 200 且真落盘",
              written.status_code == 200
              and (Path(get_data_root()) / "language" / "ui-overlay.json").is_file(),
              written.text[:160])

        overlay = client.get(f"{BASE}/overlay", headers=userHeaders,
                             params={"namespace": "ui-overlay", "language": "zh-CN"}).json()["data"]
        entries = {e["key"]: e for e in overlay["entries"]}
        check("15 覆盖层读面把写完的那条读得出来（§6-145 那条「写完没人读」的正面）",
              entries.get("live.probe.title", {}).get("value") == "活体覆盖",
              json.dumps(overlay)[:200])
        check("16 读出来的状态如实：approved=false / translator=user",
              entries.get("live.probe.title", {}).get("approved") is False
              and entries.get("live.probe.title", {}).get("translator") == "user")
        check("17 语言码来路可追：requested_tag 与 resolved_language 各自给出",
              overlay["requested_tag"] == "zh-CN" and overlay["resolved_language"] == "zh")

        liveManager = languageManagerModule.get_language_manager()
        builtin = liveManager.get_translation("live.probe.title", Language.CHINESE,
                                              namespace="ui-overlay")
        check("18 内置读路的 is_approved 门没松（未审的仍不冒充成成品文案）",
              builtin != "活体覆盖", repr(builtin))

        badWrite = client.put(f"{BASE}/overlay/ui-overlay", headers=adminHeaders,
                              json={"translations": {"live.probe2": {"klingon": "x"}}})
        check("19 覆盖层写面的拒因点名坏码，且整批不落盘",
              badWrite.status_code == 400 and "klingon" in badWrite.text, badWrite.text[:160])
        check("20 拒收那批没被写进文件",
              "live.probe2" not in (Path(get_data_root()) / "language" / "ui-overlay.json")
              .read_text(encoding="utf-8"))

        traversal = client.put(f"{BASE}/overlay/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                               headers=adminHeaders,
                               json={"translations": {"k": {"zh-CN": "v"}}})
        check("21 命名空间穿越到不了译文目录之外",
              traversal.status_code in (400, 404)
              and not (Path(get_data_root()).parent / "passwd").exists(),
              str(traversal.status_code))

        check("22 摘掉凭证：两个读面都是 401（补读面没放宽鉴权门）",
              client.get(f"{BASE}/preferences/mine").status_code == 401
              and client.get(f"{BASE}/overlay", params={"language": "zh"}).status_code == 401)
        check("23 校准格：真的不存在的路径回 404（401 不是「逢路径都 401」的假象）",
              client.get(f"{BASE}/this-route-does-not-exist").status_code == 404)

        revoked = client.put(f"{BASE}/preferences/mine", headers=userHeaders,
                             json={"primary_language": "en-US"})
        check("24 二次写入是替换不是追加",
              revoked.status_code == 200
              and json.loads(prefsPath.read_text(encoding="utf-8"))
              ["preferences"]["u-live-1"]["primary_language"] == "en")

    check("25 仓库 data/ 未被本轮写入（内容指纹逐字节相同）",
          _dataDirFingerprint() == before, "指纹变化即说明隔离没生效")

    recent = [p for p in (Path(__file__).resolve().parents[2] / "data").rglob("*")
              if p.is_file() and time.time() - p.stat().st_mtime < 300]
    check("26 仓库 data/ 最近 5 分钟零改写", recent == [], str([str(x) for x in recent[:3]]))

    print()
    if failures:
        print(f"结果：{len(failures)} 项 FAIL → {failures}")
        return 1
    print("结果：全部 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
