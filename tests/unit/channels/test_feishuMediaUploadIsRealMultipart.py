# -*- coding: utf-8 -*-
"""飞书媒体上传今天发不出去（§6-168 顺带发现的缺陷，单列先立红灯）。

实况：`MediaMixin.upload_file:118` 与 `upload_image:66` 都把 `files=` 传给
`AuthMixin._feishu_request`——该 helper 的签名不收 `files`，且恒带
`Content-Type: application/json; charset=utf-8`。于是任何一次调用都是
`TypeError: _feishu_request() got an unexpected keyword argument 'files'`，
即使签名收下了，JSON 头也会让 multipart 体被平台拒收。

为什么今天没人在身上撞见：这个 Mixin 是孤儿——`FeishuAdapter` 只继承了 `AuthMixin`
（`feishu.py:38`），全仓对 `upload_file`/`upload_image` 的生产调用为零（`feishu_ai.py:134`
那处属遗留字节工厂路径，不在渠道链上）。所以坏形状自 `feishu_media.py` 落地起从未执行过；
它不是"看着能用"，是"从没被调用过"（与 §6-157 记的"曾被消费可能是一次假接线"同一族：
要先验"当时能不能调用成功"）。

本批要接语音出站，飞书是唯一"入站语音已真能跑"的渠道之一，上传这一层是它的必经路径——
所以必须在接线之前按根修好（不修就是在一条必抛的方法上叠新功能，§6-166 刚记的那形）。

判据用**本地回环真 HTTP 桩**收请求：不是 monkeypatch `requests`，
因为要验的恰恰是"发出去的字节形状"（multipart 还是 JSON）与"文件内容真到了对岸"。
全程 127.0.0.1，不开外网、不碰飞书域名、不花任何服务商额度。
"""

import asyncio
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from neurova.channels.feishu_auth import AuthMixin
from neurova.channels.feishu_media import MediaMixin
from tests.ast_scan import parseSource


class _Stub(BaseHTTPRequestHandler):
    """记录最近一次请求的头与体，回一个飞书形状的成功响应。"""

    captured = {}

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        type(self).captured = {
            "path": self.path,
            "content_type": self.headers.get("Content-Type") or "",
            "auth": self.headers.get("Authorization") or "",
            "body": raw,
        }
        payload = b'{"code": 0, "data": {"file_key": "fk_1", "image_key": "ik_1"}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 静音
        pass


@pytest.fixture()
def stub():
    _Stub.captured = {}
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class _Uploader(MediaMixin, AuthMixin):
    """真 Mixin 组合（MediaMixin + AuthMixin），只把凭据换成桩——
    基址与 token 走 AuthMixin 的真路径，不重写它们。"""

    def __init__(self, api_base: str):
        self.api_base = api_base
        self._tenant_access_token = "t-tokens"
        self._token_expires_at = 4e12  # 永不过期：不触发取 token 的网络分支
        self._token_lock = threading.Lock()


def _wav(path: pathlib.Path) -> pathlib.Path:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x20\x01" * 800)
    return path


class TestUploadActuallyReachesTheWire:
    def test_uploadFileSendsMultipartAndReturnsKey(self, stub, tmp_path):
        target = _wav(tmp_path / "tts_sess-1_1700000000.wav")
        up = _Uploader(stub)

        key = asyncio.run(up.upload_file(str(target), file_type="stream"))

        assert key == "fk_1", f"上传没拿到 file_key（返回 {key!r}）——多半根本没发出去"
        got = _Stub.captured
        assert got["path"].startswith("/im/v1/files"), got["path"]
        assert got["content_type"].startswith("multipart/form-data"), (
            f"上传必须是 multipart，实得 Content-Type={got['content_type']!r}"
        )
        assert target.read_bytes()[:64] in got["body"], "文件字节没进请求体（空 form 也算‘成功’就是谎报）"

    def test_uploadImageSendsMultipartAndReturnsKey(self, stub, tmp_path):
        """同根第二处（教义第 5 条）：`upload_image` 犯的是同一个错，不能只修被点名的那条。"""
        png = tmp_path / "shot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1234")
        up = _Uploader(stub)

        key = asyncio.run(up.upload_image(str(png)))

        assert key == "ik_1", f"图片上传没拿到 image_key（返回 {key!r}）"
        got = _Stub.captured
        assert got["path"].startswith("/im/v1/images"), got["path"]
        assert got["content_type"].startswith("multipart/form-data"), got["content_type"]
        assert b"1234" in got["body"]

    def test_missingFileIsNotSentAndNotReportedAsSuccess(self, stub, tmp_path):
        """文件不在位：不发请求、返回 None（不拿假 key 糊下一步）。"""
        up = _Uploader(stub)
        key = asyncio.run(up.upload_file(str(tmp_path / "absent.wav")))
        assert key is None
        assert _Stub.captured == {}, "文件不存在却仍发出了上传请求"


class TestUploadDoesNotBlockTheEventLoop:
    def test_uploadsDispatchThroughToThread(self):
        """同步 requests 必须下沉到工作线程（P1-6 同族：协程内阻塞子进程/网络）。"""
        import ast

        src = pathlib.Path("neurova/channels/feishu_media.py").read_text(encoding="utf-8")
        tree = parseSource(src)
        offenders = []
        for cls in [node for node in tree.body if isinstance(node, ast.ClassDef)]:
            for fn in [m for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
                posts = [c for c in calls if getattr(c.func, "attr", "") in ("_feishu_multipart", "_feishu_post")]
                toThread = [c for c in calls if getattr(c.func, "attr", "") == "to_thread"]
                if posts and not toThread:
                    offenders.append(fn.name)
        assert offenders == [], f"上传走同步请求、把事件循环堵住：{offenders}"

    def test_detectorIsNotBlind(self):
        """反向对照：探测器不是恒绿——把 to_thread 摘掉就必须报出来。"""
        import ast

        bad = parseSource(
            "class C:\n"
            "    async def upload_x(self):\n"
            "        return self._feishu_multipart('/p', {}, {})\n"
        )
        fn = bad.body[0].body[0]
        calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
        posts = [c for c in calls if getattr(c.func, "attr", "") in ("_feishu_multipart", "_feishu_post")]
        toThread = [c for c in calls if getattr(c.func, "attr", "") == "to_thread"]
        assert posts and not toThread
