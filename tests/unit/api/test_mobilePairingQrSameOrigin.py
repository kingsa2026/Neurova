"""移动端配对二维码：凭据不出本机 + 渲染只剩一处（§6-172 批 25；浏览器验收撞出的第二形）。

来历：给手机扫码的那张图，**今天有三条互不相容的实现**，而现役那条是错的：

1. `POST /pairing/generate` 回的 `qr_code_url` 指向 `https://api.qrserver.com/...&data=<ws 地址>`
   （`mobile_pairing.py:596`）——把 6 位配对码连同 ws 地址一起交给外部渲染服务。
   配对码是本仓**唯一的认证凭据**（`_generate_pairing_code` 的 docstring 自己就这么写，
   P3-18 为此换成 CSPRNG），确认后那条设备就挂到账号名下。凭据外泄不是"风格问题"。
2. 自家的 `GET /pairing/qrcode/{code}` 用 `import qrcode`，而 `qrcode` **不在依赖清单里**
   （清单里声明的是 `segno`，`requirements.txt:107`）⇒ 这条 `try` 恒定走 `ImportError` 分支。
3. `ImportError` 分支回的那张 `_generate_svg_qrcode` 图**不是二维码**：一个方框里写着
   "配对码: 123456 / 请使用手机 App 扫描"。手机扫它扫不出任何东西，而端点的 docstring
   写着"获取配对二维码图片（PNG）"——名实不符，且失败被一张看着像成功的图盖住了。

按教义第 7 条（比-取-接-退）：仓内已有一条**在跑的**渲染实现——
`channels/qrcode_auth.generate_qrcode_image()`（segno，已声明依赖，失败显式 500），
渠道扫码登录今天就是用它。本批把配对面接到它那一份上，退役 `qrcode` 那条从未生效的路
与那张假图；发出去的 URL 改成同源（Starlette `url_for`，路由表是路径的唯一事实源，
不在端点里另抄一遍 `/api/v1/mobile/…`）。

判据（行为面先，形状面后）：
1. `generate` 回的 `qr_code_url` 与请求同源，路径落在自家 `/pairing/qrcode/<code>`；
2. 拿这条 URL 直接 GET（同一进程内 app）⇒ 200 + `image/png` + PNG 魔数；
3. 图的**实质**：served bytes == 「用生产渲染器渲染生产 ws 地址」——即它是那张能扫出
   配对地址的真图，不是占位框；
4. 渲染失败时必须显式 5xx，不许回一张写着配对码的文字图；
5. 形状面：`mobile_pairing` 不再 import 未声明的 `qrcode`；`_generate_svg_qrcode` 全仓不存在；
   生产池零外部二维码渲染域名；`segno.make` 全仓恰一处。
6. 反空转：上面三形态的"复活样本"喂给探测器必须各自命中（排除型断言在功能缺失时会自动成立）。
"""
import ast
import base64
import functools
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_qr_0123456789")

from neurova.api.endpoints import mobile_pairing as MP
from neurova.channels.qrcode_auth import generate_qrcode_image
from neurova.tunnel import protocol
from tests.ast_scan import parseSource

REPO = Path(__file__).resolve().parents[3]
CALLER = {"sub": "kai", "username": "kai"}
#: 同源判据的参照点写死：`base_url.netloc` 在这个 httpx 版本里是 **bytes**，
#: 拿去拼期望串会得到 `b'testserver'`——断言与 PNG 内容两头一起飘。
HOST = "testserver"

#: 外部二维码渲染服务（把凭据交给第三方就是本批要断的东西）
_QR_SAAS_HOSTS = ("api.qrserver.com", "quickchart.io", "chart.googleapis.com", "goqr.me")


@functools.lru_cache(maxsize=1)
def _productionSources() -> dict:
    """生产池：`neurova/**/*.py` 的原文（一次扫，两格共用）。"""
    out = {}
    for path in sorted((REPO / "neurova").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        out[path.relative_to(REPO).as_posix()] = path.read_text(encoding="utf-8")
    return out



@pytest.fixture()
def app_client():
    """真挂载：与注册表同一前缀 `/api` + `/v1/mobile`（`endpoints/__init__.py:292`）。"""
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()   # 在册设备是持久权威，清空靠释放单例（库已由 conftest 指向 tmp）
    app = FastAPI()
    app.include_router(MP.router, prefix="/api/v1/mobile")
    app.dependency_overrides[MP._get_current_user_id] = lambda: "kai"
    with TestClient(app, base_url=f"http://{HOST}", raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()
    MP._pairing_codes.clear()
    MP.resetDeviceRegistry()


def _pathOf(url: str) -> str:
    """把发出去的同源 URL 换回进程内可 GET 的路径（读的就是自己给出去那条）。"""
    parts = urlsplit(url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _generate(c) -> dict:
    r = c.post("/api/v1/mobile/pairing/generate", json={"device_name": "probe", "device_type": "mobile"})
    assert r.status_code == 200, r.text
    return r.json()


class TestQrUrlStaysOnOrigin:
    def test_generated_qr_url_is_same_origin(self, app_client):
        body = _generate(app_client)
        url = body["qr_code_url"]
        parts = urlsplit(url)
        assert parts.netloc == HOST, f"二维码地址不是同源（凭据要出门）：{url}"
        assert parts.path.endswith(f"/pairing/qrcode/{body['code']}"), (
            f"同源却没落在自家渲染端点上：{url}")
        assert not any(host in url for host in _QR_SAAS_HOSTS), (
            f"配对码被交给外部渲染服务：{url}")

    def test_that_very_url_serves_a_real_png(self, app_client):
        body = _generate(app_client)
        r = app_client.get(_pathOf(body["qr_code_url"]))
        assert r.status_code == 200, f"发出去的地址自家读不到：{r.status_code} {r.text}"
        assert r.headers.get("content-type", "").startswith("image/png"), r.headers.get("content-type")
        assert r.content[:4] == b"\x89PNG", "回的不是 PNG——端点承诺的就是 PNG"
        assert len(r.content) > 100, f"图太小，不像是真二维码：{len(r.content)} 字节"

    def test_served_image_is_the_qr_of_the_pairing_payload(self, app_client):
        """实质判据：那张图必须**就是**配对载荷的二维码（同一渲染器、同一文本）。

        S1b 起文本从"含 host 的回连地址"改成 `neurova://pair?ref=…`（§3.4：
        「谁」与「在哪」分离，地址漂移不得让已发的码作废）。本格的职责没变——
        仍是"served 字节 == 生产渲染器渲染生产载荷"，只是被渲染的那串换了。
        期望值由生产那两处自己算（`protocol.pairingQrPayload` + `generate_qrcode_image`），
        测试不复刻渲染逻辑——复刻过的桩件会与被审那行犯同一个错。
        """
        body = _generate(app_client)
        expected = base64.b64decode(
            generate_qrcode_image(protocol.pairingQrPayload(body["ref"])))

        served = app_client.get(_pathOf(body["qr_code_url"])).content
        assert served == expected, (
            f"served {len(served)}B ≠ 渲染器给的 {len(expected)}B——图与配对载荷不同源，"
            "手机扫到的不是那条 ref")


class TestFailureIsHonest:
    def test_render_failure_surfaces_5xx_not_a_text_box(self, app_client, monkeypatch):
        """缺依赖/渲染抛错时必须是显式失败。

        原先这里回一张「方框 + 配对码文字」的 SVG：看着像成功，手机却扫不出任何东西，
        故障被盖在一张图后面（教义第 2 条禁止的形态）。
        """
        import neurova.channels.qrcode_auth as QA

        def boom(_scan_url):
            from fastapi import HTTPException
            raise HTTPException(status_code=500, detail="QR code image generation failed: forced")

        monkeypatch.setattr(QA, "generate_qrcode_image", boom)
        body = _generate(app_client)
        r = app_client.get(_pathOf(body["qr_code_url"]))
        assert r.status_code >= 500, (
            f"渲染失败却回 {r.status_code}：{r.text[:120]}——失败必须点名，不许降级成假图")
        assert "svg" not in r.headers.get("content-type", "").lower(), (
            "回的还是那张占位 SVG")


class TestDetectorsAreNotVacuous:
    """排除型断言在功能缺失时会自动成立——先证明这些探测器看得见它要排除的形态。"""

    def test_qr_saas_detector_hits_a_revived_line(self):
        revived = ('qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/'
                   '?size=200x200&data={ws_url}"')
        hits = [host for host in _QR_SAAS_HOSTS if host in revived]
        assert hits, "探测器连旧那行都认不出——第 5c 格是恒真的空守卫"

    def test_undeclared_qrcode_import_detector_hits_a_revived_import(self):
        revived = "import qrcode\nfrom qrcode import QRCode\n"
        assert _undeclaredQrcodeImports(revived), (
            "import 探测器认不出复活样本——第 5a 格是恒真的空守卫")

    def test_fake_qr_placeholder_detector_hits_a_revived_def(self):
        revived = "def _generate_svg_qrcode(code):\n    return '<svg/>'\n"
        assert _placeholderDefs(revived), (
            "假图探测器认不出复活样本——第 5b 格是恒真的空守卫")


def _undeclaredQrcodeImports(source: str) -> list:
    """AST 里 import 名恰为 `qrcode` 的节点（`qrcode_auth` 这种模块名不算——按整名比，不按片段）。"""
    hits = []
    for node in ast.walk(parseSource(source)):
        if isinstance(node, ast.Import):
            hits += [a.name for a in node.names if a.name.split(".")[0] == "qrcode"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "qrcode":
                hits.append(node.module)
    return hits


def _placeholderDefs(source: str) -> list:
    r"""按**定义行**认那张假图（不整档 ast.parse：生产池里有文件的 docstring 带 `\w`
    这类序列，逐档解析会刷一屏 SyntaxWarning，把真正的读数淹掉）。"""
    return re.findall(r"^\s*def\s+_generate_svg_qrcode\b", source, re.MULTILINE)


class TestSingleSourceShape:
    def test_mobile_pairing_no_longer_imports_the_undeclared_library(self):
        src = (REPO / "neurova/api/endpoints/mobile_pairing.py").read_text(encoding="utf-8")
        assert not _undeclaredQrcodeImports(src), (
            "`qrcode` 又回来了——它不在依赖清单里，那条 try 只会恒定走降级分支")

    def test_placeholder_image_is_gone_repo_wide(self):
        offenders = {rel for rel, src in _productionSources().items() if _placeholderDefs(src)}
        assert not offenders, f"写着配对码的假二维码又出现了：{sorted(offenders)}"

    def test_no_production_line_hands_credentials_to_a_qr_saas(self):
        offenders = []
        for rel, src in _productionSources().items():
            for host in _QR_SAAS_HOSTS:
                if host in src:
                    offenders.append(f"{rel}:{host}")
        assert not offenders, (
            f"生产池里出现外部二维码渲染服务（凭据外泄面复活）：{offenders}")

    def test_qr_rendering_lives_in_exactly_one_place(self):
        """教义第 6 条：渲染口径单源——第二份 `segno.make` 就是下一次漂移的起点。"""
        hits = sorted(rel for rel, src in _productionSources().items() if "segno.make" in src)
        assert hits == ["neurova/channels/qrcode_auth.py"], (
            f"二维码渲染出现第二处实现（应只走渠道那一份）：{hits}")
