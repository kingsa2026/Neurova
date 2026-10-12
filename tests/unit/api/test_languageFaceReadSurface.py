# -*- coding: utf-8 -*-
"""语言面的 HTTP 读面（台账 §6-145 裁定乙：先接读面 + 补落盘，**不引入审批**）。

## 这批要接的是哪两条断链

1. `UserLanguagePreference` 只写内存（`manager.py:58` 那个字典），仓内**没有任何 HTTP 消费者**
   ——`get_language_manager()`/`init_language()` 全仓零调用点（§6-145 复算），
   所以「用户选了什么语言」这件事在后台既不存在也留不住。
2. `save_external_translations()` 写进去的条目一律 `is_approved=False`（`manager.py:232/279`），
   而 `get_translation()` 只回 `is_approved` 的条目（`:328`）——写完没人读得出来。
   用户 2026-10-11 裁「不引入审批」，所以这一格的正解**不是**补一个审批动作，
   而是给这批内容另开一条**如实标未审**的读面：覆盖层（overlay）。
   内置那条读路的门一寸不放宽（第 10 格专门钉这件事）。

## 三条不放宽的口径，逐条有格

- **语言码只有单点**：面这一侧不许再写一刀 `split("-")`（§6-145 刚拆掉的那份私藏口径）。
  第 16 格按 AST 钉住，第 11 格按读数钉住。
- **属主只从登录态取**：请求体里没有 `user_id` 这个口（第 6、7 格）——
  与渠道身份那条「面板没有替他人绑的入口」同一口径。
- **不识别的码必须点名**：第 4、12、14 格。回 200 空列表是最坏形态：
  打错一个字母的人永远看不见自己打错了。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as authModule
from neurova.api.deps import require_admin  # noqa: F401  （只用它的存在性做门，见 fixture）
from neurova.language import manager as languageManagerModule

BASE = "/api/v1/language"
USER = {"user_id": "u-1", "username": "u1", "role": "user", "neuser_id": "u-1"}
ADMIN = {"user_id": "admin-1", "username": "root", "role": "admin", "neuser_id": "admin-1"}


def _app(monkeypatch, tmp_path, identity=None):
    from neurova.api.endpoints import language_api
    from neurova.language.manager import LanguageManager

    manager = LanguageManager(data_dir=str(tmp_path / "language"))
    # 走单例的既有复位路径（`lazySingleton` 的缓存就是本模块那个全局名），
    # 而不是把端点里的取用函数换掉——换函数等于绕过生产装配点。
    monkeypatch.setattr(languageManagerModule, "_language_manager", manager)

    app = FastAPI()
    app.include_router(language_api.router, prefix="/api/v1/language", tags=["Language API"])
    app.dependency_overrides[authModule.get_current_user] = lambda: dict(identity or USER)
    return app, manager


@pytest.fixture()
def client(monkeypatch, tmp_path):
    app, manager = _app(monkeypatch, tmp_path)
    with TestClient(app) as c:
        c.manager = manager
        yield c


class TestPreferenceReadFace:
    def testGetMineWithNothingSavedSaysNotConfiguredAndWritesNothing(self, client):
        r = client.get(f"{BASE}/preferences/mine")

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["configured"] is False, (
            "没设过偏好却报 configured=True——读面把默认值冒充成用户做过的决定")
        assert data["source"] == "default"
        assert not Path(client.manager.preferences_path).exists(), (
            "一次 GET 就在盘上留下文件：那会让「多少人设过偏好」被读操作自己灌大")

    def testPutThenGetReturnsTheNormalizedTag(self, client):
        put = client.put(f"{BASE}/preferences/mine",
                         json={"primary_language": "zh-CN", "auto_detect": False})

        assert put.status_code == 200, put.text
        # 请求里给的是 UI 那一族的区域码，回读必须是归一后的真实语言码，且把来路一起给出
        assert put.json()["data"]["requested_tag"] == "zh-CN"
        assert put.json()["data"]["primary_language"] == "zh"

        got = client.get(f"{BASE}/preferences/mine").json()["data"]
        assert got["configured"] is True
        assert got["primary_language"] == "zh"
        assert got["auto_detect"] is False

    def testSavedPreferenceSurvivesAFreshManager(self, tmp_path, monkeypatch):
        """端点背后必须是**盘**，不是某个实例的字典。"""
        from neurova.language.manager import LanguageManager

        app, manager = _app(monkeypatch, tmp_path)
        with TestClient(app) as c:
            assert c.put(f"{BASE}/preferences/mine",
                         json={"primary_language": "ja-JP"}).status_code == 200

        restarted = LanguageManager(data_dir=str(tmp_path / "language"))
        monkeypatch.setattr(languageManagerModule, "_language_manager", restarted)
        app2, _ = _app(monkeypatch, tmp_path)
        with TestClient(app2) as c2:
            data = c2.get(f"{BASE}/preferences/mine").json()["data"]

        assert data["configured"] is True and data["primary_language"] == "ja", (
            "偏好只在原来那个实例里活着——重启即全失，HTTP 面写的就不是「用户的设置」")

    def testUnknownLanguageTagIsRefusedAndNamed(self, client):
        r = client.put(f"{BASE}/preferences/mine", json={"primary_language": "klingon"})

        assert r.status_code == 400, r.text
        assert "klingon" in r.text, f"拒因没点名坏值，调用方只能猜：{r.text}"
        assert client.get(f"{BASE}/preferences/mine").json()["data"]["configured"] is False, (
            "被拒的写入仍然落了盘")

    def testAutoIsRefusedAsPrimaryThroughHttp(self, client):
        """`auto` 是「自动检测」，那一层已有 `auto_detect` 布尔承载；
        让它当首选语言＝把 §6-140 刚拆掉的共用值在新字段上重建一遍。"""
        r = client.put(f"{BASE}/preferences/mine", json={"primary_language": "auto"})

        assert r.status_code == 400, r.text
        assert "auto_detect" in r.text or "自动检测" in r.text, r.text

    def testIdentityCannotBeSuppliedInTheBody(self, client):
        """属主只从登录态取——请求体里不许有 `user_id` 这个口（同渠道面板「没有替他人绑」）。"""
        r = client.put(f"{BASE}/preferences/mine",
                       json={"primary_language": "en-US", "user_id": "someone-else"})

        assert r.status_code in (400, 422), f"多余的 user_id 被无声收下：{r.text}"
        assert client.get(f"{BASE}/preferences/mine").json()["data"]["user_id"] == "u-1"

    def testOneUserCannotRewriteAnother(self, tmp_path, monkeypatch):
        appA, managerA = _app(monkeypatch, tmp_path, identity=USER)
        with TestClient(appA) as ca:
            assert ca.put(f"{BASE}/preferences/mine",
                          json={"primary_language": "en-US"}).status_code == 200

        appB, _ = _app(monkeypatch, tmp_path,
                       identity={"user_id": "u-2", "username": "u2",
                                 "role": "user", "neuser_id": "u-2"})
        with TestClient(appB) as cb:
            data = cb.get(f"{BASE}/preferences/mine").json()["data"]

        assert data["configured"] is False, (
            "另一个登录身份读到了 u-1 的偏好——按人隔离没做（managerA=%r）" % managerA)

    def testNoCredentialIs401(self, tmp_path, monkeypatch):
        """401/404 校准格：先证「这条入口真的存在」，再证「没凭证是被拒而不是找不到」。

        路由表形状读数读不到 include 进来的 router，而把「入口不存在」读成 404 也会
        把 405 那族放过——所以用行为读数，并配一格真的不存在路径。
        """
        from neurova.api.endpoints import language_api

        app = FastAPI()
        app.include_router(language_api.router, prefix="/api/v1/language")
        with TestClient(app) as c:
            assert c.get(f"{BASE}/preferences/mine").status_code == 401
            assert c.put(f"{BASE}/preferences/mine",
                         json={"primary_language": "en"}).status_code == 401
            assert c.get(f"{BASE}/this-route-does-not-exist").status_code == 404


class TestOverlayReadFace:
    """覆盖层：外部/用户上传的译文——裁定「不引入审批」的正解是**如实读出未审状态**。

    读数口径（写在这里是因为它会决定判据形状）：`/overlay` 给的是"这个命名空间 +
    这门语言在 manager 里的全部条目，逐条带 `approved`/`translator` 状态"，
    而不是"只给未审的那批"。理由是读的人要的是一条规则，而不是两次不同过滤——
    若这里只给未审的、`get_translation()` 只给已审的，同一份库就有两条各自裁剪的读路，
    以后加第三种状态时没人会想起来改两处。判据因此按 key 取用那一条，
    不断"整个列表只有我写的这一条"（内置 `ui` 命名空间本来就有 login/logout/settings）。
    """

    def _seed(self, client):
        return client.manager.save_external_translations(
            "ui", {"save": {"zh-CN": "保存一下", "en-US": "Save it"}})

    def _entry(self, data, key):
        matches = [e for e in data["entries"] if e["key"] == key]
        assert matches, "%r 读不出来（§6-145 那条「写完没人读」）：%r" % (key, data)
        return matches[0]

    def testOverlayReadsBackWhatTheWriterWrote(self, client):
        assert self._seed(client) is True

        r = client.get(f"{BASE}/overlay", params={"namespace": "ui", "language": "zh-CN"})

        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["resolved_language"] == "zh"
        assert data["requested_tag"] == "zh-CN"
        assert self._entry(data, "save")["value"] == "保存一下"

    def testOverlaySaysOutLoudThatItIsUnapproved(self, client):
        """不引入审批 ≠ 把未审说成已审：`approved` 必须如实为 False 并给出计数。"""
        self._seed(client)
        # 同时放一条内置的进来对照：同一张表里两种状态并存时，读数要分得开
        builtin = self._entry(client.get(
            f"{BASE}/overlay", params={"namespace": "ui", "language": "zh"}).json()["data"],
            "login")
        assert builtin["approved"] is True and builtin["translator"] == "builtin", (
            "内置条目被标成未审——那等于把已审的内容降级，状态这个字段就没人能信了")

        data = client.get(f"{BASE}/overlay",
                          params={"namespace": "ui", "language": "zh"}).json()["data"]
        entry = self._entry(data, "save")

        assert entry["approved"] is False
        assert entry["translator"] == "user"
        assert data["unapproved_count"] == sum(1 for e in data["entries"] if not e["approved"])
        assert data["unapproved_count"] >= 1

    def testTheBuiltinReadFaceStillRefusesUnapprovedEntries(self, client):
        """新读面不许把内置那条门的口径带松：`get_translation()` 仍然不认未审条目。"""
        from neurova.language.models import Language

        self._seed(client)

        assert client.manager.get_translation("save", Language.CHINESE, namespace="ui") != "保存一下", (
            "为了给覆盖层让路，把内置读面的 `is_approved` 门放宽了——"
            "那是把「未经确认的文案」送进所有读路径，裁定里没有这一条")

    def testOverlayForARegionTaggedLanguageResolves(self, client):
        self._seed(client)

        for tag in ("zh-CN", "zh_CN", "ZH-cn", "zh"):
            data = client.get(f"{BASE}/overlay",
                              params={"namespace": "ui", "language": tag}).json()["data"]
            assert data["resolved_language"] == "zh", tag
            assert data["entries"], tag

    def testUnknownOverlayLanguageTagIsNamedNotAnsweredWithAnEmptyList(self, client):
        self._seed(client)

        r = client.get(f"{BASE}/overlay", params={"namespace": "ui", "language": "klingon"})

        assert r.status_code == 400, r.text
        assert "klingon" in r.text, (
            "打错语言码的人收到的是一份**空覆盖层**加 200——他会以为这套语言没文案")

    def testOverlayWriteIsAdminOnlyAndReadsBackImmediately(self, tmp_path, monkeypatch):
        appU, _ = _app(monkeypatch, tmp_path, identity=USER)
        with TestClient(appU) as cu:
            denied = cu.put(f"{BASE}/overlay/ui",
                            json={"translations": {"cancel": {"zh-CN": "算了"}}})
        assert denied.status_code == 403, (
            "覆盖层写面是**未审内容进 UI**的入口，普通用户可写＝任意人给所有人改文案")

        appA, managerA = _app(monkeypatch, tmp_path, identity=ADMIN)
        with TestClient(appA) as ca:
            ok = ca.put(f"{BASE}/overlay/ui",
                        json={"translations": {"cancel": {"zh-CN": "算了"}}})
            assert ok.status_code == 200, ok.text
            got = ca.get(f"{BASE}/overlay",
                         params={"namespace": "ui", "language": "zh-CN"}).json()["data"]

        assert {"key": "cancel", "value": "算了", "approved": False,
                "translator": "user"} in got["entries"], (
            "写端点回 200 却读不回来——写面与读面不同源（manager=%r）" % managerA)

    def testOverlayWriteRefusalNamesTheBadCodeThroughTheSameSinglePoint(self, tmp_path, monkeypatch):
        """400 的拒因来自 manager 那一份校验，不是端点自己又写了一遍。

        自证方式是把那份校验桩成「全通过」：端点因此不再回 400，而 manager 自己仍拒收 ⇒
        读数变成 500（"你说没有坏码，可盘上没写成"）。桩掉之后读数确实变了 ⇒
        原来那条 400 不是恒绿的空壳；同时验它没往内存里半写。
        """
        from neurova.language.manager import LanguageManager
        from neurova.language.models import Language

        app, manager = _app(monkeypatch, tmp_path, identity=ADMIN)
        original = LanguageManager.rejectedLanguageTags

        with TestClient(app) as client:
            refusal = client.put(f"{BASE}/overlay/ui",
                                 json={"translations": {"delete": {"klingon": "x"}}})
            assert refusal.status_code == 400 and "klingon" in refusal.text, refusal.text

            monkeypatch.setattr(LanguageManager, "rejectedLanguageTags",
                                lambda self, translations: [], raising=True)
            stubbed = client.put(f"{BASE}/overlay/ui",
                                 json={"translations": {"delete": {"klingon": "x"}}})
            assert stubbed.status_code == 500, (
                "桩掉 manager 的校验后端点仍回 400 ⇒ 那份拒因是端点自己另写的第二处实现：%s"
                % stubbed.text)
            assert [e.key for e in manager.overlayEntries("ui", Language.CHINESE)
                    if e.key == "delete"] == [], (
                "校验被绕过时内存里已经半写了那条坏码——落盘失败却把脏值留在了库里")

            monkeypatch.setattr(LanguageManager, "rejectedLanguageTags", original)
            after = client.put(f"{BASE}/overlay/ui",
                               json={"translations": {"delete": {"klingon": "x"}}})
            assert after.status_code == 400, (
                "还原校验后不再回 400 ⇒ 上面那格的 500 是从别处来的，本格的对照没咬住")

    def testEncodedNamespaceTraversalNeverBecomesAFile(self, tmp_path, monkeypatch):
        """两种形态都要钉：路由层就挡下的（404）与进到处理器里的（400）。

        实测裸 `../` 与编码 `%2e%2e%2f` 都到不了处理器（Starlette 在匹配前规范化了路径），
        但"到不了"是路由层此刻的行为，不是这条防线该指望的东西——处理器里那道
        `_safeNamespace` 必须自己就拒，所以另按**解码后的串**直接验一次，
        并把 HTTP 面那一侧的读数收成"不许是 200"。
        """
        from fastapi import HTTPException as FastAPIHTTPException

        from neurova.api.endpoints import language_api

        app, manager = _app(monkeypatch, tmp_path, identity=ADMIN)
        with TestClient(app) as client:
            for bad in ("%2e%2e%2f%2e%2e%2fetc%2fpasswd", "%2e%2e", "%2e"):
                r = client.put(f"{BASE}/overlay/{bad}",
                               json={"translations": {"k": {"zh-CN": "v"}}})
                assert r.status_code in (400, 404), (
                    "命名空间 %r 的写请求回了 %s：它可能被当成文件名用了" % (bad, r.status_code))

        for escape in ("../../etc/passwd", "a/b", "..", ".", ".hidden", ""):
            with pytest.raises(FastAPIHTTPException) as caught:
                language_api._safeNamespace(escape)
            assert caught.value.status_code == 400, escape

        root = Path(manager.data_dir).parent
        assert not (root.parent / "passwd").exists()

    def testPlainDotSegmentsDoNotReachTheWriter(self, client):
        """裸点段在路由层就被规范化掉——405/404 也是"没进写面"，但必须不是 200。

        （把"入口不存在"一律读成 404 会漏掉 Starlette 报 405 那一族，所以两种都收，
        唯独不收 200：那才是真穿过来了。）
        """
        for bad in ("..", ".", "a/b"):
            r = client.put(f"{BASE}/overlay/{bad}",
                           json={"translations": {"k": {"zh-CN": "v"}}})
            assert r.status_code in (400, 404, 405), (
                "命名空间 `%s` 的写请求回了 %r——它被当成文件名用了" % (bad, r.status_code))


class TestTheFaceDoesNotOwnASecondNormalization:
    def testEndpointModuleHasNoPrivateLanguageTagSlicing(self):
        """§6-145 刚拆掉「枚举侧不认、装载侧私藏一刀」那份平行口径，别在新面上长回来。"""
        from neurova.api.endpoints import language_api

        source = Path(language_api.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("split", "lower", "replace"):
                offenders.append("%s@%s" % (node.attr, node.lineno))
        assert not offenders, (
            "端点里自己动语言码（%s）——归一口径就有了第二份，"
            "必须走 Language.normalizeTag / Language.from_str" % offenders)

    def testEveryLanguageCodeInTheFaceGoesThroughTheModelSinglePoint(self):
        """正向格：归一确实发生在面上（不是整档没引用而假绿）。"""
        from neurova.api.endpoints import language_api

        source = Path(language_api.__file__).read_text(encoding="utf-8")
        assert "normalizeTag" in source, "面上根本没走单点归一，上一条守卫就成了没人走的空档"

    def testResponseEnvelopeKeysAreTheRealModelKeys(self, client):
        """判据按**真产物键集合**核，不按 dataclass 字段名的想象写（§6-145 那格教训）。"""
        client.put(f"{BASE}/preferences/mine", json={"primary_language": "en-US"})

        data = client.get(f"{BASE}/preferences/mine").json()["data"]

        assert set(data) >= {"user_id", "primary_language", "secondary_languages",
                             "fallback_language", "auto_detect", "configured", "source"}, sorted(data)
