# -*- coding: utf-8 -*-
"""语言层的「开箱默认」一格（用户 2026-10-12 裁「先取长补短再退役」，台账 §6-167）。

## 这一档在合并的是哪几件事

仓内曾有四份「某人默认看什么语言」的定义（逐条 file:line 见台账正文）：

- 全局默认（结构化 section）：`core/app_settings.py` 的 `GENERAL_DEFAULTS["language"]`
  ——生产读者 **0 处**，只被 `GET /settings` 回显；
- 全局默认（平铺 legacy 键）：`api/endpoints/settings.py` 的 `_default_settings["language"]`
  ——同一次回显里的**第二个**同名键，读者同样 0 处；
- 按人（第二套词汇）：`core/settings_manager.py` 的 `get/set_user_language`——生产 0 处；
- 按人（工作区配置）：`core/user_workspace.py` 默认配置里的 `"language"`——生产 0 处；
- 按人（选定单点）：`language/manager.py` + `language_api.py`（§6-160 刚落的那层），
  前端 `setLocale`／`syncLocaleFromServer` 真在消费。

这几份里唯一**不可替代**的东西是第一份的那个语义：**管理员可以替「还没表达过偏好的人」
定一个起点**。按教义第 7 条不能一删了事，也不能两边都留着再加个同步脚本，所以本批把它
**取进选定单点**（同一份存储的一个可选 `default` 键 ＋ 一条仅管理员的写面），
其余三份同批退役（退役面见 `tests/unit/api/testRetiredGlobalLanguageDefault.py`）。

## 三条不放宽的口径

1. **`configured` 只能说「这个人自己做过这个决定」**：管理员设了开箱默认之后，
   未表达过偏好的用户 `configured` 仍是 `False`，只是 `source` 从 `builtin` 变成
   `out_of_box`。把别人的决定报成本人的决定，是 §6-160 那条「如实标未审」的同族。
2. **来源词汇只有一处定义**：`LanguageManager.EFFECTIVE_SOURCES`，解析面与 HTTP 面都取它。
   第二份字面量一旦长出，先漂移的一定是没人对着读的那份——按文件面钉住并带变异对照。
3. **存储版本不抬**：新增的是一个**可选键**，旧文件读出来只是「没人设过开箱默认」。
   把 `PREFERENCES_STORE_VERSION` 抬到 2，等于让今天已落盘的每条按人偏好被自己的
   版本隔离逻辑改名隔离——那不是兼容，是凭空丢掉真数据。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests import ast_scan as astScan
from neurova.api import auth as authModule
from neurova.language import manager as languageManagerModule
from neurova.language.manager import LanguageManager
from neurova.language.models import Language, UserLanguagePreference

BASE = "/api/v1/language"
USER = {"user_id": "u-1", "username": "u1", "role": "user", "neuser_id": "u-1"}
ADMIN = {"user_id": "admin-1", "username": "root", "role": "admin", "neuser_id": "admin-1"}

#: `neurova/` 根——按**包根**取而不是数目录层级，挪文件不会让扫描面悄悄变窄。
NEUROVA_ROOT = Path(languageManagerModule.__file__).resolve().parent.parent

#: 那条保留属主名：它只活在内存里的那条「默认条目」上，永远不该进 `preferences` 表。
SENTINEL_OWNER = "__defaults__"


def _manager(tmp_path: Path) -> LanguageManager:
    return LanguageManager(data_dir=str(tmp_path / "language"))


def _default(primary: Language, **kwargs: Any) -> UserLanguagePreference:
    return UserLanguagePreference(user_id=SENTINEL_OWNER, primary_language=primary, **kwargs)


def _app(monkeypatch, tmp_path: Path, identity=None):
    from neurova.api.endpoints import language_api

    manager = _manager(tmp_path)
    # 走单例的既有复位路径（`lazySingleton` 的缓存就是本模块那个全局名），
    # 而不是把端点里的取用函数换掉——换函数等于绕过生产装配点。
    monkeypatch.setattr(languageManagerModule, "_language_manager", manager)

    app = FastAPI()
    app.include_router(language_api.router, prefix=BASE, tags=["Language API"])
    app.dependency_overrides[authModule.get_current_user] = lambda: dict(identity or USER)
    return app, manager


@pytest.fixture()
def client(monkeypatch, tmp_path):
    _app_obj, manager = _app(monkeypatch, tmp_path)
    with TestClient(_app_obj) as c:
        c.manager = manager
        yield c


@pytest.fixture()
def adminClient(monkeypatch, tmp_path):
    _app_obj, manager = _app(monkeypatch, tmp_path, identity=ADMIN)
    with TestClient(_app_obj) as c:
        c.manager = manager
        yield c


def _filesContaining(literal: str, root: Path) -> List[str]:
    """`root` 下把这个串当**字符串常量**用到的文件（按 AST，不按文本包含）。

    文本包含会把自己那句断言算进命中面（§6-162 记过的那枚形态），所以只认
    `ast.Constant` 的 str 值；注释与 docstring 里的提到不算定义。

    取数走共享解析预算 `tests/ast_scan`（Issue #148：私有 `rglob + ast.parse`
    会把「解析量」绑成「代码总量」，与其余受保护文件共享机器时撞 30s 墙钟）。
    `literal` 是判据的**充分条件**——连这个串都没出现的文件不可能命中，
    故预筛不改变判定，只把解析面收到命中面。判据会重复扫（两格用例各调一次、
    且 `root` 可能是临时目录），故用保留型 `sourceRefsUnder` + 文本预筛：
    临时目录那一格的文件同样按内容戳缓存，不重复读盘。
    """
    hits: List[str] = []
    for ref in astScan.sourceRefsUnder(root, hints=(literal,)):
        try:
            tree = astScan._cachedParse(ref.stamp, ref.code)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == literal:
                hits.append(ref.path.relative_to(root).as_posix())
                break
    return hits


class TestOutOfBoxDefaultResolution:
    """取进来的那一格：解析链是 本人偏好 → 开箱默认 → 枚举级 last resort。"""

    def testWithNothingAnywhereResolutionIsBuiltinAndNamed(self, tmp_path):
        manager = _manager(tmp_path)

        preference, source = manager.resolvePreference("nobody")

        assert source == "builtin", (
            "谁都没设过时来源必须是 builtin——不点名来源，「开箱默认到底生效了没」"
            "就只能靠猜，而这条链今天正是靠猜活着的")
        assert preference.primary_language is manager.default_language

    def testAdminSetDefaultAppliesToSomeoneWithNoPreference(self, tmp_path):
        manager = _manager(tmp_path)

        assert manager.setOutOfBoxDefault(_default(Language.ENGLISH, auto_detect=False)) is True

        preference, source = manager.resolvePreference("nobody")
        assert source == "out_of_box"
        assert preference.primary_language is Language.ENGLISH

    def testExplicitPreferenceBeatsTheOutOfBoxDefault(self, tmp_path):
        manager = _manager(tmp_path)
        manager.setOutOfBoxDefault(_default(Language.ENGLISH))
        manager.set_user_preference("u-9", UserLanguagePreference(
            user_id="u-9", primary_language=Language.JAPANESE))

        preference, source = manager.resolvePreference("u-9")

        assert source == "user"
        assert preference.primary_language is Language.JAPANESE, (
            "开箱默认压过了本人选的语言——这一层就从「偏好」变成了「强制」，语义不同")

    def testDefaultSurvivesARebuiltManagerFromDisk(self, tmp_path):
        first = _manager(tmp_path)
        first.setOutOfBoxDefault(_default(Language.FRENCH))
        first.set_user_preference("u-3", UserLanguagePreference(
            user_id="u-3", primary_language=Language.KOREAN))

        second = _manager(tmp_path)

        resolvedDefault = second.resolvePreference("nobody")
        assert resolvedDefault[1] == "out_of_box"
        assert resolvedDefault[0].primary_language is Language.FRENCH
        assert second.resolvePreference("u-3")[0].primary_language is Language.KOREAN, (
            "重建时只读回开箱默认、丢了按人偏好——两份读面又不同源了")

    def testTheDefaultIsNotStoredAsAUserRow(self, tmp_path):
        manager = _manager(tmp_path)
        manager.setOutOfBoxDefault(_default(Language.GERMAN))

        assert manager.get_user_preference(SENTINEL_OWNER) is None, (
            "开箱默认被当成一条**用户**偏好存了：它会混进「多少人设过偏好」的计数里")
        payload = json.loads(Path(manager.preferences_path).read_text(encoding="utf-8"))
        assert SENTINEL_OWNER not in (payload.get("preferences") or {})


class TestPersistenceHonesty:
    def testWriteFailureRollsBackAndReportsFalse(self, tmp_path, monkeypatch):
        manager = _manager(tmp_path)

        def boom(*args, **kwargs):
            raise OSError("disk refuses")

        monkeypatch.setattr(languageManagerModule, "atomic_write_text", boom)

        assert manager.setOutOfBoxDefault(_default(Language.SPANISH)) is False
        assert manager.resolvePreference("nobody")[1] == "builtin", (
            "盘没写成却把内存留着：下一次读会拿到一个盘上不存在、却已经生效的默认值")

    def testAnOldFileWithoutTheDefaultKeyStillLoads(self, tmp_path):
        """向后兼容：§6-160 那批落盘的文件没有 `default` 键，抬版本会让它们全被隔离。"""
        first = _manager(tmp_path)
        first.set_user_preference("u-7", UserLanguagePreference(
            user_id="u-7", primary_language=Language.ENGLISH))
        path = Path(first.preferences_path)
        legacy: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        legacy.pop("default", None)
        assert legacy["version"] == languageManagerModule.PREFERENCES_STORE_VERSION
        path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

        second = _manager(tmp_path)

        assert second.getOutOfBoxDefault() is None
        assert second.resolvePreference("u-7")[0].primary_language is Language.ENGLISH
        assert second.resolvePreference("nobody")[1] == "builtin"

    def testStoreKeepsOneVersionAndOnePreferencesMap(self, tmp_path):
        manager = _manager(tmp_path)
        manager.set_user_preference("u-1", UserLanguagePreference(
            user_id="u-1", primary_language=Language.CHINESE))
        manager.setOutOfBoxDefault(_default(Language.RUSSIAN))

        payload = json.loads(Path(manager.preferences_path).read_text(encoding="utf-8"))

        assert payload["version"] == languageManagerModule.PREFERENCES_STORE_VERSION, (
            "新增一个可选键不该抬版本：抬了就是让今天已落盘的每条按人偏好被自己的"
            "版本隔离逻辑改名隔离")
        assert set(payload.keys()) == {"version", "default", "preferences"}, payload.keys()


class TestSourceVocabularyHasOneHome:
    def testTheClosedSetIsDefinedOnceAndUsedByEveryLayer(self):
        sources = set(LanguageManager.EFFECTIVE_SOURCES)

        assert sources == {"user", "out_of_box", "builtin"}, (
            "来源词汇漂移了：HTTP 面的读数与前端的分支是按这一组值写的，"
            "多一个少一个都会让某一层把未知来源当成已知")

        hits = _filesContaining("out_of_box", NEUROVA_ROOT)
        assert hits == ["language/manager.py"], (
            "`out_of_box` 这个字面量在 %s 都出现了——第二份词汇表长出来了（教义第 6 条）" % hits)

    def testTheScannerReallyCatchesASecondHome(self, tmp_path):
        """变异对照：探测器必须抓得住「第二处」，否则上一格是恒绿的空转。"""
        (tmp_path / "language").mkdir()
        (tmp_path / "other").mkdir()
        (tmp_path / "language" / "a.py").write_text('X = "out_of_box"\n', encoding="utf-8")
        (tmp_path / "other" / "b.py").write_text('Y = "out_of_box"\n', encoding="utf-8")
        (tmp_path / "other" / "c.py").write_text(
            "# 注释里提到 out_of_box 不该算定义\nZ = 1\n", encoding="utf-8")

        assert _filesContaining("out_of_box", tmp_path) == ["language/a.py", "other/b.py"], (
            "探测器要么没抓到第二处，要么把注释里的提到也算成了定义")


class TestDefaultOverHttp:
    def testGetDefaultWithNothingSetSaysNotConfiguredAndWritesNothing(self, client):
        r = client.get(f"{BASE}/preferences/default")

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["configured"] is False
        assert data["source"] == "builtin"
        assert not Path(client.manager.preferences_path).exists(), (
            "一次 GET 就在盘上留下文件——「多少人设过默认」会被读操作自己灌大")

    def testOnlyAdminMaySetTheOutOfBoxDefault(self, client):
        r = client.put(f"{BASE}/preferences/default",
                       json={"primary_language": "en", "auto_detect": False})

        assert r.status_code == 403, (
            "普通用户也能改所有人的起点？这一格写的是「别人还没选」的那部分人。%s" % r.text)

    def testAdminPutThenANewUserReadsItThroughMine(self, adminClient):
        put = adminClient.put(f"{BASE}/preferences/default",
                              json={"primary_language": "pt-BR", "auto_detect": False})

        assert put.status_code == 200, put.text
        assert put.json()["data"]["primary_language"] == "pt", (
            "UI 那一族的区域码要在面这一侧归一（单点仍是 Language.normalizeTag）")

        got = adminClient.get(f"{BASE}/preferences/mine").json()["data"]
        assert got["source"] == "out_of_box"
        assert got["primary_language"] == "pt"
        assert got["configured"] is False, (
            "`configured` 说的是「这个人自己选过」——管理员替他选了不算他选过")
        assert adminClient.get(f"{BASE}/preferences/default").json()["data"]["configured"] is True

    def testUnrecognizedTagIsRejectedByNameingIt(self, adminClient):
        r = adminClient.put(f"{BASE}/preferences/default", json={"primary_language": "klingon"})

        assert r.status_code == 400, r.text
        assert "klingon" in r.json()["detail"]

    def testAutoIsRejectedAsABadTagNotAsAFiveHundred(self, adminClient):
        r = adminClient.put(f"{BASE}/preferences/default", json={"primary_language": "auto"})

        assert r.status_code == 400, (
            "`auto` 在构造点被拒是 400；让它冒成 500 就是把契约问题伪装成运行时故障：%s" % r.text)
        assert "auto" in r.json()["detail"]

    def testBodyCannotNameTheOwnerItWritesTo(self, adminClient):
        r = adminClient.put(f"{BASE}/preferences/default",
                            json={"primary_language": "en", "user_id": "victim"})

        assert r.status_code == 422, (
            "写默认也能指定属主＝第二个「替他人绑」的入口（与 §6-160 的 mine 同口径）：%s" % r.text)

    def testDiskRefusalIsReportedAsFiveHundredNotTwoHundred(self, adminClient, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("disk refuses")

        monkeypatch.setattr(languageManagerModule, "atomic_write_text", boom)

        r = adminClient.put(f"{BASE}/preferences/default", json={"primary_language": "de"})

        assert r.status_code == 500, (
            "盘没写成却回 200：管理员会以为所有人的起点已经改了，而重启后它并不是：%s" % r.text)
        assert adminClient.get(f"{BASE}/preferences/default").json()["data"]["configured"] is False
