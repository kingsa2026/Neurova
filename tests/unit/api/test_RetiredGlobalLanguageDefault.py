# -*- coding: utf-8 -*-
"""退役面：全局语言默认从 settings 里退净，写面拒收并给出去处（台账 §6-167）。

用户 2026-10-12 裁「先取长补短再退役」。取的那一半在
`tests/language/test_OutOfBoxDefaultLayer.py`（开箱默认接进语言层），本档管**退干净**：

- `core/app_settings.py` 的 `GENERAL_DEFAULTS["language"]` —— 键摘掉（`app_name` 那格不动）；
- `api/endpoints/settings.py` 的 `_default_settings["language"]` —— 同一个面的**第二个**同名键；
- `core/settings_manager.py` 的 `get_user_language`/`set_user_language` 与两处 key 白名单；
- `core/user_workspace.py` 默认配置里的 `"language"`。

## 为什么"摘掉默认值"不够，必须让写面拒收

`PUT /settings` 的 body 是 `Dict[str, Any]`，没有任何闭集校验（实测今天写 `"zh_CN"`
这种下划线码也照样回 200）。只删默认表的话，旧调用方仍能把 `general.language` **写回盘上**，
而 `GET /settings` 又原样回显它——那就得到一根**只写不读**的新断链，比原先更糟，
因为原先它至少还有个默认值陪着。按教义第 2 条，退役后的键必须以**显式 400 ＋ 去处**暴露。

## 扫描口径为什么收在这四个文件上

`"language"` 这个键名在生产码里还服务于**另一件事**（neurflow 代码模板节点的编程语言、
媒体节点的播报语种），全仓一刀切会把无关命中算进来、或者逼出一份会过期的豁免名单
（判据问错对象那一族）。所以形状扫描只覆盖这四张默认表所在文件；跨面的保护由
"读活对象"那几格承担——它们本身就是行为判据，谁把键加回去就红。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import settings as SETTINGS
from neurova.core import app_settings as APPS
from neurova.core import settings_manager as SM
from neurova.core import user_workspace as UW
from tests.auth_headers import overrideIdentity

ADMIN = {"user_id": "a1", "username": "a1", "role": "admin"}
BASE = "/api/v1/settings"

#: 四张默认表所在的文件——退役面的形状扫描口径（见模块 docstring 末段）。
DEFAULT_TABLE_FILES = (
    Path(APPS.__file__),
    Path(SETTINGS.__file__),
    Path(SM.__file__),
    Path(UW.__file__),
)


def _languageDefaultEntries(files) -> List[str]:
    """挑出把 `"language"` 当**字典键**且值是字符串常量的落点（按 AST）。

    只认字典项与下标赋值两种形态：拒收面自己那份 `RETIRED_LANGUAGE_KEY = "language"`
    是元组里的常量，不该被算成"又建了一份默认值"（自我指涉那枚形态，§6-162）。
    """
    hits: List[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.name
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if (isinstance(key, ast.Constant) and key.value == "language"
                            and isinstance(value, ast.Constant)
                            and isinstance(value.value, str)):
                        hits.append("%s:%d" % (rel, node.lineno))
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and target.slice.value == "language"
                            and isinstance(node.value, ast.Constant)
                            and isinstance(node.value.value, str)):
                        hits.append("%s:%d" % (rel, node.lineno))
    return sorted(set(hits))


@pytest.fixture()
def settingsClient(tmp_path, monkeypatch):
    """真路由 + admin 身份。`_default_settings` 是**模块级可变字典**，用完必须复原，
    否则本档写进去的脏值会活到下一个文件（跨用例顺序敏感那一族）。"""
    snapshot = dict(SETTINGS._default_settings)
    monkeypatch.setattr(APPS, "_settings_path", lambda path=None: tmp_path / "app_settings.json")
    app = FastAPI()
    app.include_router(SETTINGS.router, prefix="/api")
    overrideIdentity(app, dict(ADMIN))
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    SETTINGS._default_settings.clear()
    SETTINGS._default_settings.update(snapshot)


class TestTheDefaultTablesLoseTheKey:
    def testGeneralDefaultsNoLongerCarryLanguage(self):
        assert "language" not in APPS.GENERAL_DEFAULTS, (
            "全局默认表里还留着 `language`：它就是那四份「某人默认看什么语言」的第一份")
        assert APPS.GENERAL_DEFAULTS.get("app_name") == "Neurova", "邻座被一起删了"

    def testFlatDefaultsNoLongerCarryLanguage(self):
        assert "language" not in SETTINGS._default_settings, (
            "同一个面的第二个同名键还在——`GET /settings` 一次回显两遍 `language`"
            "（顶层与 general 各一份），两份漂移时没人知道自己读的是哪份")
        assert "theme" in SETTINGS._default_settings, "整张表被顺手清空了：本批只摘那一格"

    def testNoDefaultTableAnywhereStillSeedsTheKey(self):
        hits = _languageDefaultEntries(DEFAULT_TABLE_FILES)

        assert hits == [], "这四张表里还有地方把 `language` 默认成一个串：%s" % hits


class TestTheFaceRefusesTheRetiredKey:
    def testMergedReadoutCarriesNoLanguageEvenWhenPlantedOnDisk(self, settingsClient, tmp_path):
        residue: Dict[str, Any] = {
            "general": {"app_name": "Neurova", "language": "zh-CN"},
            "flat": {"theme": "light", "language": "fr"},
        }
        (tmp_path / "app_settings.json").write_text(json.dumps(residue), encoding="utf-8")

        body = settingsClient.get(BASE).json()["settings"]

        assert "language" not in body, list(body.keys())
        assert "language" not in (body.get("general") or {}), (
            "盘上残留的旧键被原样回显＝假装这条词汇还活着（教义第 2 条）——"
            "下一个接线的人会把它当成真在用的东西")
        assert body["general"]["app_name"] == "Neurova", "摘键摘到了邻座"
        assert body["theme"] == "light", "flat 面被一起拒了：本批拒的只是那一格"

    def testReadingTheFileDoesNotRewriteIt(self, settingsClient, tmp_path):
        """只读的回显不许顺手"清理"别人的盘——那是把读操作变成一次不可逆的写。"""
        residue = {"general": {"app_name": "Neurova", "language": "zh-CN"}}
        path = tmp_path / "app_settings.json"
        path.write_text(json.dumps(residue), encoding="utf-8")
        before = path.read_bytes()

        settingsClient.get(BASE)

        assert path.read_bytes() == before, "GET 改写了数据根里的文件"

    def testPutGeneralSectionWithLanguageIsRejectedWithAPointer(self, settingsClient):
        r = settingsClient.put(BASE, json={"settings": {
            "general": {"app_name": "Neurova", "language": "en"}}})

        assert r.status_code == 400, r.text
        assert "/api/v1/language" in r.json()["detail"], (
            "拒了却没给去处：旧调用方只会重试，不会知道自己该改指哪里")

    def testPutFlatLanguageIsRejected(self, settingsClient):
        r = settingsClient.put(BASE, json={"settings": {"language": "en-US"}})

        assert r.status_code == 400, r.text
        assert "/api/v1/language" in r.json()["detail"]

    def testPutSingleKeyLanguageIsRejected(self, settingsClient):
        r = settingsClient.put(f"{BASE}/language", json={"value": "en-US"})

        assert r.status_code == 400, r.text
        assert "/api/v1/language" in r.json()["detail"], (
            "同根因的三个写口要一并拒（教义第 5 条）：漏一个，旧键就从那里活回来")

    def testReadingTheRetiredKeySaysNotFoundNotSilentlyEmpty(self, settingsClient):
        r = settingsClient.get(f"{BASE}/language")

        assert r.status_code == 404, r.text

    def testNeighbouringKeysStillWrite(self, settingsClient):
        r = settingsClient.put(BASE, json={"settings": {
            "general": {"app_name": "Renamed"}, "theme": "dark"}})

        assert r.status_code == 200, r.text
        assert "language" not in r.json()["settings"], list(r.json()["settings"].keys())

    def testNothingWasPersistedForTheRejectedWrites(self, settingsClient, tmp_path):
        """拒收那三次不许改写盘。

        先做一次**合法**写入把文件建出来，再拿字节比对——如果只断"盘上没有 language"，
        文件根本不存在时那条断言也成立，就成了恒绿的弱判据（排除型断言在功能缺失时
        自动成立那一族，§6-166 记过）。
        """
        accepted = settingsClient.put(BASE, json={"settings": {"theme": "dark"}})
        assert accepted.status_code == 200, accepted.text
        path = tmp_path / "app_settings.json"
        assert path.exists(), "合法写入没建出文件，下面那条字节比对就没有基线"
        before = path.read_bytes()

        settingsClient.put(BASE, json={"settings": {"language": "en"}})
        settingsClient.put(f"{BASE}/language", json={"value": "en"})
        settingsClient.put(BASE, json={"settings": {"general": {"language": "en"}}})

        assert path.read_bytes() == before, (
            "回了 400 却把状态写进盘——报错与变更分家（教义第 1 条的反面）")


class TestTheSecondAndThirdImplementationsDisappear:
    def testSettingsManagerHasNoUserLanguageApi(self):
        for name in ("get_user_language", "set_user_language"):
            assert not hasattr(SM.SettingsManager, name), (
                f"`settings_manager.{name}` 还在：它是同一件事的第二套词汇而生产零消费者，"
                "留着就是下一个接线的人会误用的那条路")

    def testSettingsManagerWhitelistsDropLanguage(self, tmp_path):
        manager = SM.SettingsManager(config={"data_dir": str(tmp_path / "sm")})

        assert "language" not in manager.get_all_settings("u-1"), (
            "`get_all_settings` 还在给每人算一份语言默认：那是第二个按人读面")
        manager.update_settings({"language": "en-US", "theme": "dark"}, user_id="u-1")
        assert "language" not in manager.get_all_settings("u-1"), (
            "白名单里还留着 `language`：批量更新能把它写回去，退役就只是文案")

    def testUserWorkspaceDefaultConfigDropsLanguage(self, tmp_path):
        workspace = UW.UserWorkspace(user_id="u-1", base_path=tmp_path)
        defaults = workspace._get_default_config()

        assert "language" not in defaults, "工作区默认配置还带 language：那是第四份字面量"
        assert "timezone" in defaults, "邻座被一起删了"


class TestTheScannerHasTeeth:
    def testMutationControlCatchesASecondDefaultTable(self, tmp_path):
        """上一组格若抓不住"加回去"，它就是恒绿。"""
        (tmp_path / "a.py").write_text(
            'GENERAL_DEFAULTS = {"app_name": "N", "language": "zh-CN"}\n', encoding="utf-8")
        (tmp_path / "b.py").write_text(
            'd = {}\nd["language"] = "en"\n', encoding="utf-8")
        # 这两种形态**不该**被抓：拒收面自己的键名常量、以及别的用途的 language 字段
        (tmp_path / "c.py").write_text(
            'RETIRED_LANGUAGE_KEY = "language"\n', encoding="utf-8")
        (tmp_path / "d.py").write_text(
            'NODE = {"language": runtime_language_var}\n', encoding="utf-8")

        hits = _languageDefaultEntries([tmp_path / n for n in ("a.py", "b.py", "c.py", "d.py")])

        assert len(hits) == 2, (
            "形状探测器要么漏了字典/下标两形之一，要么把拒收面自己的常量也算进来了：%s" % hits)
