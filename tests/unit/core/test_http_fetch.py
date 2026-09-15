"""neurova.http_fetch 共享阻塞抓取层单测（curl_cffi 浏览器 TLS 指纹）。

根因契约：urllib 暴露 Python TLS 指纹（JA3），反爬层（Cloudflare 等）按
指纹直接 403。共享层优先用 curl_cffi 以浏览器身份握手指纹；curl_cffi
缺失时回落 urllib（安装可选，不炸主流程）。
行为契约：
- 浏览器系 UA（Mozilla 开头）→ 走 impersonate 伪装；
- 非浏览器 UA（如 wttr.in 要求的 curl/8.5.0）→ 调用方 UA 原样保留（BUGFIX 语义）；
- HTTP >= 400 抛错（对齐 urllib HTTPError 的"错误可见"语义，不静默返回错误页）；
- 解码维持 utf-8 + errors=replace。
两咽喉点（web_reach._http_get_text / tool_executor._blocking_fetch）委托本层，
SSRF/协议守卫仍在咽喉点处先行执行。
"""

import sys
import types
from unittest.mock import patch

import pytest

from neurova import http_fetch


class _FakeResp:
    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content
        self.status_code = status_code


def _install_fake_curl(monkeypatch, calls, resp=None):
    """注入假 curl_cffi 模块，记录 requests.get 的 kwargs（CA 探测不打真环境）。"""
    curl = types.ModuleType("curl_cffi")
    requests_mod = types.ModuleType("curl_cffi.requests")

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        return resp if resp is not None else _FakeResp()

    requests_mod.get = _get
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)


# ── fetch_text 本体 ──


def test_browser_ua_uses_impersonate_and_utf8_decode(monkeypatch):
    calls = []
    _install_fake_curl(monkeypatch, calls, _FakeResp(content="你好".encode("utf-8")))
    text = http_fetch.fetch_text("https://example.com/a", "Mozilla/5.0", 10)
    assert text == "你好"
    url, kwargs = calls[0]
    assert url == "https://example.com/a"
    assert kwargs.get("impersonate") == "chrome"
    assert kwargs.get("timeout") == 10
    # 防回归（live-verify 抓到的降级）：浏览器系 UA 也必须原样透传，层不得替换
    assert kwargs["headers"]["User-Agent"] == "Mozilla/5.0"


def test_non_browser_ua_preserves_ua_without_impersonate(monkeypatch):
    calls = []
    _install_fake_curl(monkeypatch, calls)
    http_fetch.fetch_text("https://wttr.in/x", "curl/8.5.0", 10)
    _, kwargs = calls[0]
    assert kwargs.get("impersonate") in (None, "curl")
    headers = kwargs.get("headers") or {}
    assert headers.get("User-Agent") == "curl/8.5.0"


def test_falls_back_to_urllib_when_curl_cffi_missing(monkeypatch):
    # sys.modules 置 None → from curl_cffi import ... 抛 ImportError
    monkeypatch.setitem(sys.modules, "curl_cffi", None)

    class _Ctx:
        def read(self):
            return "fb".encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Ctx()) as m:
        assert http_fetch.fetch_text("https://example.com/b", "Mozilla/5.0", 5) == "fb"
        assert m.called


def test_http_error_status_raises(monkeypatch):
    calls = []
    _install_fake_curl(monkeypatch, calls, _FakeResp(content=b"", status_code=403))
    with patch("urllib.request.urlopen") as fb:
        with pytest.raises(Exception, match="403"):
            http_fetch.fetch_text("https://blocked.example", "Mozilla/5.0", 10)
        # HTTP 4xx/5xx = 服务端策略判定，不重复打下一个客户端（只出现一次请求）
        assert len(calls) == 1
        fb.assert_not_called()


def test_curl_network_error_falls_back_to_urllib(monkeypatch):
    """curl 引擎连接层单点故障（curl 56 等）→ urllib 兜底，能力不降级。"""
    import types as _t

    curl = _t.ModuleType("curl_cffi")
    requests_mod = _t.ModuleType("curl_cffi.requests")

    def _boom(url, **kwargs):
        raise ConnectionError("curl: (56) Connection closed abruptly")

    requests_mod.get = _boom
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)

    class _Ctx:
        def read(self):
            return b"from-urllib"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Ctx()):
        assert http_fetch.fetch_text("https://flaky.example", "curl/8.5.0", 10) == "from-urllib"


def test_curl_and_urllib_both_fail_raises_original_curl_error(monkeypatch):
    """双引擎都失败时抛 curl 的第一手错误（不抹除、不替换成兜底引擎的次生报错）。"""
    import types as _t

    curl = _t.ModuleType("curl_cffi")
    requests_mod = _t.ModuleType("curl_cffi.requests")

    def _boom(url, **kwargs):
        raise ConnectionError("curl: (56) Connection closed abruptly")

    requests_mod.get = _boom
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)

    with patch("urllib.request.urlopen", side_effect=OSError("urllib also down")):
        with pytest.raises(ConnectionError, match="56"):
            http_fetch.fetch_text("https://down.example", "Mozilla/5.0", 10)


def test_decode_uses_replace_on_invalid_utf8(monkeypatch):
    calls = []
    _install_fake_curl(monkeypatch, calls, _FakeResp(content=b"caf\xe9"))
    assert http_fetch.fetch_text("https://example.com/c", "Mozilla/5.0", 10)  # 不抛异常


# ── ASCII CA 适配（Windows libcurl 读不了非 ASCII 路径 CA → curl 77） ──


def test_ascii_ca_copies_when_certifi_path_non_ascii(tmp_path, monkeypatch):
    import certifi

    fake_src = tmp_path / "项目目录" / "cacert.pem"
    fake_src.parent.mkdir()
    fake_src.write_bytes(b"FAKE-CA")
    monkeypatch.setattr(certifi, "where", lambda: str(fake_src))
    monkeypatch.setattr(http_fetch, "_ca_state", "")
    dest = http_fetch._ascii_ca()
    assert dest is not None
    dest.encode("ascii")  # 副本路径必须纯 ASCII（libcurl 硬约束）
    assert open(dest, "rb").read() == b"FAKE-CA"


def test_ascii_ca_none_when_path_already_ascii(tmp_path, monkeypatch):
    import certifi

    ascii_src = tmp_path / "ca.pem"
    ascii_src.write_bytes(b"CA")
    try:
        str(ascii_src).encode("ascii")
    except UnicodeEncodeError:
        pytest.skip("tempdir 含非 ASCII，无法构造 ASCII 场景")
    monkeypatch.setattr(certifi, "where", lambda: str(ascii_src))
    monkeypatch.setattr(http_fetch, "_ca_state", "")
    assert http_fetch._ascii_ca() is None


# ── fetch_bytes（feedparser 等需原始字节自行探测编码） ──


def test_fetch_bytes_returns_raw_bytes_without_decode(monkeypatch):
    calls = []
    _install_fake_curl(monkeypatch, calls, _FakeResp(content=b"caf\xe9"))
    assert http_fetch.fetch_bytes("https://example.com/f", "Mozilla/5.0", 10) == b"caf\xe9"


def test_fetch_bytes_network_error_falls_back_to_urllib(monkeypatch):
    import types as _t

    curl = _t.ModuleType("curl_cffi")
    requests_mod = _t.ModuleType("curl_cffi.requests")

    def _boom(url, **kwargs):
        raise ConnectionError("curl: (56) Connection closed abruptly")

    requests_mod.get = _boom
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)

    class _Ctx:
        def read(self):
            return b"raw-urllib"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("urllib.request.urlopen", return_value=_Ctx()):
        assert http_fetch.fetch_bytes("https://flaky.example/feed", "Mozilla/5.0", 10) == b"raw-urllib"


# ── 咽喉点委托 ──


def test_http_get_text_delegates_after_guards(monkeypatch):
    from neurova.web_reach import reach

    monkeypatch.setattr(reach, "_assert_public_host", lambda url: None)
    with patch("neurova.http_fetch.fetch_text", return_value="OK") as m:
        text = reach._http_get_text("https://example.com/d", 3.0)
    assert text == "OK"
    m.assert_called_once()
    assert m.call_args[0][0] == "https://example.com/d"


def test_http_get_text_still_blocks_private_before_fetch():
    from neurova.web_reach import reach

    with patch("neurova.http_fetch.fetch_text") as m:
        with pytest.raises(ValueError):
            reach._http_get_text("http://127.0.0.1:9527/admin", 3.0)
    m.assert_not_called()


def test_blocking_fetch_delegates():
    from neurova.tool_executor import ToolExecutor

    with patch("neurova.http_fetch.fetch_text", return_value="H") as m:
        out = ToolExecutor._blocking_fetch("https://example.com/e", "Mozilla/5.0", 7)
    assert out == "H"
    assert m.call_args[0][0] == "https://example.com/e"
    assert m.call_args[0][1] == "Mozilla/5.0"
