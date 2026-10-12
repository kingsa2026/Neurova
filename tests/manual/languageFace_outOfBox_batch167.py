# -*- coding: utf-8 -*-
"""live-verify（台账 §6-167，裁定「先取长补短再退役」）：开箱默认在**活 app** 上真走一遍。

判据档（`tests/language/testOutOfBoxDefaultLayer.py` + 
`tests/unit/api/testRetiredGlobalLanguageDefault.py`）挂的是手搭的 `FastAPI()`；这一支要证的
是另一件事——

1. `/api/v1/language/preferences/default` 在 `create_app()` 的真路由表里可达，真吃**真 JWT**，
   写面真只认管理员；
2. 那条决定**真的作用到没选过语言的人身上**（这是"取长补短"的全部意义：取进来的东西
   如果没人读，它就还是死的），并且**不会**被回写成那个人的偏好；
3. 盘上落的是顶层 `default` 键而不是一条用户行，换个进程读得回来；
4. 旧的 settings 写面真拒（三个写口逐一），且一次 GET 不改写数据根里的文件；
5. 第二、三套实现（`settings_manager` 的按人语言、`user_workspace` 的默认配置）在活进程里
   确实不再存在；
6. 仓库 `data/` 一个字节都没被这轮写过。

跑法：`PYTHONPATH=$(git rev-parse --show-toplevel) python tests/manual/languageFace_outOfBox_batch167.py`
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

WORK_ROOT = isolatedDataRoot(prefix="neurovaLang167")

from fastapi.testclient import TestClient  # noqa: E402

from neurova.api.app import create_app  # noqa: E402
from neurova.api.auth import create_access_token  # noqa: E402
from neurova.core.data_root import get_data_root  # noqa: E402

LANGUAGE_BASE = "/api/v1/language"
SETTINGS_BASE = "/api/v1/settings"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(name)


def _headers(sub: str, role: str) -> dict:
    token = create_access_token({"sub": sub, "username": sub, "role": role})
    return {"Authorization": f"Bearer {token}"}


def _dataDirFingerprint() -> str:
    """仓库 `data/` 的内容指纹（名 + 字节数 + mtime）；清单看不见原地改写与等量搬移。"""
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
    from neurova.core import settings_manager as settingsManagerModule
    from neurova.core import user_workspace as userWorkspaceModule
    from neurova.language import manager as languageManagerModule
    from neurova.language.manager import LanguageManager

    before = _dataDirFingerprint()
    root = Path(get_data_root())
    prefsPath = root / languageManagerModule.PREFERENCES_FILE_NAME
    appSettingsPath = root / "app_settings.json"

    # 先铺一份"历史残留"：老装机上盘里可能真有一条 general.language / 顶层 language。
    # 它考验的是退役的第二半：**读数里不许再有，而读操作也不许顺手改写别人的文件**。
    appSettingsPath.write_text(json.dumps({
        "general": {"app_name": "Neurova", "language": "zh-CN"},
        "flat": {"theme": "light", "language": "fr"},
    }), encoding="utf-8")
    residueBytes = appSettingsPath.read_bytes()

    app = create_app()
    with TestClient(app) as client:
        userHeaders = _headers("u-167-none", "user")
        pickerHeaders = _headers("u-167-picker", "user")
        adminHeaders = _headers("u-167-admin", "admin")

        got = client.get(f"{LANGUAGE_BASE}/preferences/default", headers=userHeaders)
        check("1 真路由可达：GET preferences/default 用真 JWT 回 200",
              got.status_code == 200, got.text[:140])
        check("2 没人定过起点时如实报未设（configured=false / source=builtin）",
              got.json()["data"]["configured"] is False
              and got.json()["data"]["source"] == "builtin", str(got.json()["data"])[:160])
        check("3 一次 GET 不在盘上留下偏好文件", not prefsPath.exists(), str(prefsPath))

        forbidden = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=userHeaders,
                               json={"primary_language": "en", "auto_detect": False})
        check("4 非管理员写开箱默认是 403（它影响所有还没选过的人）",
              forbidden.status_code == 403, forbidden.text[:120])

        put = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=adminHeaders,
                         json={"primary_language": "pt-BR", "auto_detect": False})
        check("5 管理员写成功且区域码在面这一侧归一",
              put.status_code == 200 and put.json()["data"]["primary_language"] == "pt",
              put.text[:140])
        payload = json.loads(prefsPath.read_text(encoding="utf-8"))
        check("6 落的是顶层 default 键、版本没被抬",
              payload.get("version") == languageManagerModule.PREFERENCES_STORE_VERSION
              and payload["default"]["primary_language"] == "pt", str(payload)[:180])
        check("7 那条起点不占 preferences 里的用户行",
              languageManagerModule.OUT_OF_BOX_OWNER not in (payload.get("preferences") or {}),
              str(list((payload.get("preferences") or {}).keys())))

        mine = client.get(f"{LANGUAGE_BASE}/preferences/mine", headers=userHeaders).json()["data"]
        check("8 没选过语言的人真的被那条起点作用到（source=out_of_box, primary=pt）",
              mine["source"] == "out_of_box" and mine["primary_language"] == "pt", str(mine)[:170])
        check("9 但这个人 configured 仍是 false（别人的决定不冒充成他做过的）",
              mine["configured"] is False, str(mine["configured"]))
        check("10 这次「读并生效」没有把他写成一条偏好行",
              "u-167-none" not in (json.loads(prefsPath.read_text(encoding="utf-8"))
                                   .get("preferences") or {}), str(payload)[:120])

        picked = client.put(f"{LANGUAGE_BASE}/preferences/mine", headers=pickerHeaders,
                            json={"primary_language": "ja", "auto_detect": False})
        check("11 有人自己选过之后他压过开箱默认",
              picked.status_code == 200
              and client.get(f"{LANGUAGE_BASE}/preferences/mine",
                             headers=pickerHeaders).json()["data"]["source"] == "user",
              picked.text[:120])

        secondProcess = subprocess.run(
            [sys.executable, "-c",
             "import json,os;"
             "p=os.path.join(os.environ['NEUROVA_DATA_DIR'],'language_preferences.json');"
             "d=json.load(open(p,encoding='utf-8'));"
             "print(d['default']['primary_language'], d['preferences']['u-167-picker']['primary_language'])"],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "NEUROVA_DATA_DIR": str(WORK_ROOT)})
        check("12 换一个进程读回同一条起点与同一个人的偏好（跨进程持久）",
              secondProcess.stdout.strip() == "pt ja",
              (secondProcess.stdout or secondProcess.stderr).strip()[:180])

        again = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=adminHeaders,
                           json={"primary_language": "de", "auto_detect": False})
        check("13 管理员改起点后，没选过的人跟着改（起点对他仍然有效）",
              again.status_code == 200
              and client.get(f"{LANGUAGE_BASE}/preferences/mine",
                             headers=userHeaders).json()["data"]["primary_language"] == "de",
              again.text[:120])
        check("14 而已经自己选过的那个人不受影响（没被冻住的那条不受这次改动波及）",
              client.get(f"{LANGUAGE_BASE}/preferences/mine",
                         headers=pickerHeaders).json()["data"]["primary_language"] == "ja")

        bad = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=adminHeaders,
                         json={"primary_language": "klingon"})
        check("15 不识别的语言码：400 且点名",
              bad.status_code == 400 and "klingon" in bad.text, bad.text[:120])
        auto = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=adminHeaders,
                          json={"primary_language": "auto"})
        check("16 `auto` 当首选语言是 400 而不是 500（构造点拒，契约不冒充运行时故障）",
              auto.status_code == 400 and "auto" in auto.text, auto.text[:120])
        wrongOwner = client.put(f"{LANGUAGE_BASE}/preferences/default", headers=adminHeaders,
                                json={"primary_language": "en", "user_id": "victim"})
        check("17 请求体里没有「替他人绑」的口（多一个 user_id 直接 422）",
              wrongOwner.status_code == 422, wrongOwner.text[:120])
        check("18 被拒的三次写入没把盘上那条起点改走",
              json.loads(prefsPath.read_text(encoding="utf-8"))["default"]["primary_language"]
              == "de")

        anonymous = client.get(f"{LANGUAGE_BASE}/preferences/default")
        check("19 补读面没放宽鉴权门：无凭证 401",
              anonymous.status_code == 401, anonymous.text[:100])

        settingsBody = client.get(SETTINGS_BASE, headers=adminHeaders).json()["settings"]
        check("20 GET /settings 不再回显 language（顶层与 general 两处都没有）",
              "language" not in settingsBody
              and "language" not in (settingsBody.get("general") or {}),
              str(list(settingsBody.keys()))[:170])
        check("21 盘上有残留也不影响读数，而 general 的邻座还在",
              settingsBody["general"].get("app_name") == "Neurova"
              and settingsBody.get("theme") == "light", str(settingsBody.get("general")))
        check("22 一次 GET 没有改写数据根里那份文件（读操作不顺手清理别人的盘）",
              appSettingsPath.read_bytes() == residueBytes)

        # 拒收那三次不许动盘——注意比的是**字节不变**，不是"盘上没有 language"：
        # 盘上那条是本脚本自己铺的历史残留，而退役的口径是"读数里不再出现、写面不再接受"，
        # 不是"顺手替别人清理文件"（那条边界由 [22] 钉着）。
        bytesBeforeRefusal = appSettingsPath.read_bytes()
        refusedSection = client.put(SETTINGS_BASE, headers=adminHeaders, json={"settings": {
            "general": {"app_name": "Neurova", "language": "en"}}})
        check("23 写 general 段带 language：400 且给出去处",
              refusedSection.status_code == 400
              and "/api/v1/language" in refusedSection.text, refusedSection.text[:150])
        refusedFlat = client.put(SETTINGS_BASE, headers=adminHeaders,
                                 json={"settings": {"language": "en"}})
        check("24 平铺那个同名键也拒（同一个面的第二个写口）",
              refusedFlat.status_code == 400, refusedFlat.text[:120])
        refusedSingle = client.put(f"{SETTINGS_BASE}/language", headers=adminHeaders,
                                   json={"value": "en"})
        check("25 单键 PUT 也拒（三处同根因逐一验，漏一处旧键就从那活回来）",
              refusedSingle.status_code == 400
              and "/api/v1/language" in refusedSingle.text, refusedSingle.text[:120])
        check("26 三次拒收都没改写盘（回了 400 就把状态留在原处，不写一半）",
              appSettingsPath.read_bytes() == bytesBeforeRefusal)
        refusedBytes = appSettingsPath.read_bytes()
        neighbours = client.put(SETTINGS_BASE, headers=adminHeaders,
                                json={"settings": {"theme": "dark"}})
        check("27 拒的不是整个面：邻座键照样能写",
              neighbours.status_code == 200
              and neighbours.json()["settings"]["theme"] == "dark", neighbours.text[:120])
        check("27b 而那次合法写入确实落了盘（写面没被一起变成装饰）",
              appSettingsPath.read_bytes() != refusedBytes)

        check("28 第二套实现真不在活进程里（settings_manager 没有按人语言接口）",
              not hasattr(settingsManagerModule.SettingsManager, "get_user_language")
              and not hasattr(settingsManagerModule.SettingsManager, "set_user_language"))
        workspaceDefaults = userWorkspaceModule.UserWorkspace(
            user_id="u-167", base_path=WORK_ROOT / "ws")._get_default_config()
        check("29 第三套实现真不在（user_workspace 默认配置里没有 language，邻座仍在）",
              "language" not in workspaceDefaults and "timezone" in workspaceDefaults,
              str(sorted(workspaceDefaults.keys())))

        rebuilt = LanguageManager(data_dir=str(WORK_ROOT / "language"))
        check("30 再建一个管理器也从盘上读回同一条起点（重启语义，进程内字典不算）",
              rebuilt.resolvePreference("whoever")[1] == "out_of_box"
              and rebuilt.resolvePreference("whoever")[0].primary_language.value == "de")

        # 本批改了这个面，就顺手把这道的门实测一次（不照旧表抄——API_REFERENCE 里
        # `/api/v1/settings` 那行写的是"无认证"，而端点自己挂着 `Depends(get_current_user)`；
        # 名实不符那笔账在 §6-158 已登记为"整表从未逐模块复核"，这里只交本批动过的那一行的读数）
        anonWhole = client.get(SETTINGS_BASE)
        check("31 无凭证 GET /settings 的实测门（交文档那行按读数写）",
              anonWhole.status_code in (401, 403), "实测 %s" % anonWhole.status_code)
        anonSingle = client.get(f"{SETTINGS_BASE}/theme")
        check("32 无凭证 GET /settings/{key} 同一道门",
              anonSingle.status_code in (401, 403), "实测 %s" % anonSingle.status_code)
        calibrated = client.get("/api/v1/settings/zzz-not-a-key", headers=adminHeaders)
        check("33 校准格：真不存在的键回 404（401/403 不是「逢路径都拒」的假象）",
              calibrated.status_code == 404, "实测 %s" % calibrated.status_code)

    check("34 仓库 data/ 未被本轮写入（内容指纹逐字节相同）",
          _dataDirFingerprint() == before)
    recent = [p for p in (Path(__file__).resolve().parents[2] / "data").rglob("*")
              if p.is_file() and p.stat().st_mtime > time.time() - 300] \
        if (Path(__file__).resolve().parents[2] / "data").exists() else []
    check("35 仓库 data/ 最近 5 分钟零改写", recent == [], str([str(x) for x in recent[:3]]))

    print()
    print("全部通过" if not failures else "失败 %s 项：%s" % (len(failures), failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
