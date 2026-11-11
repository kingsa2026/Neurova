"""Web Reach 实现：平台直达读取（零配置路径路由）。

安全边界：
- URL 仅接受 http/https（file/ftp 等本地协议在入口拒绝）
- _http_get_text 在请求前解析目标主机并阻断私网/环回/链路本地/保留段/
  组播地址（SSRF 防护：防内网、云元数据、本机服务探测）
- YouTube 字幕仅限 youtube 域名；社交平台渐进式暴露，不自动登录
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser

from neurova import http_fetch
from neurova.core.logger import get_logger

logger = get_logger(__name__)

_USER_AGENT = "Mozilla/5.0 (Neurova; agent-reach/1.5.0)"
_DEFAULT_TIMEOUT = 20.0
_YTDLP_TIMEOUT = 90.0

# 社交平台 → doctor channel 名（渐进式暴露；不自动登录、不碰用户浏览器）
_SOCIAL_CHANNELS = {
    "twitter": "twitter",
    "reddit": "reddit",
    "xiaohongshu": "xiaohongshu",
    "facebook": "facebook",
    "instagram": "instagram",
    "linkedin": "linkedin",
}


# P0-1：SSRF 边界实现抽取至 neurova.security.url_guard（供 MCP http 配置门、
# P1-7 全局出网层复用）。以下保留原名字与语义做委托，兼容既有调用与测试 patch。
from neurova.security.url_guard import BLOCKED_NETS as _URL_GUARD_BLOCKED_NETS
from neurova.security.url_guard import assert_public_url as _url_guard_assert_public

_BLOCKED_NETS = _URL_GUARD_BLOCKED_NETS


from neurova.core.text_encoding import utf8ChildEnv


def _check_scheme(url: str) -> Optional[str]:
    """协议校验（仅 http/https），非法返回错误消息"""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        return f"仅支持 http/https 协议（收到 {scheme or '空'}）"
    return None


def _assert_public_host(url: str) -> None:
    """解析目标主机并阻断私网/环回/链路本地地址（SSRF 防护）。

    实现见 neurova.security.url_guard.assert_public_url（含 scheme 校验）。
    """
    _url_guard_assert_public(url)


def _validateHopUrl(url: str) -> None:
    """逐跳 SSRF 复核（P1-3）：重定向每一跳都过与首跳同一道门。"""
    scheme_err = _check_scheme(url)
    if scheme_err:
        raise ValueError(scheme_err)
    _assert_public_host(url)


def _http_get_text(url: str, timeout: float) -> str:
    """GET 请求并返回 UTF-8 文本（请求前做 SSRF 主机边界校验）。

    TLS 指纹走共享层 neurova.http_fetch（curl_cffi 浏览器指纹优先，urllib 兜底）。
    重定向不交引擎自动跟随：每一跳都过 _validateHopUrl 同一道门（P1-3）——
    只守首跳时，公网 URL 可 302 跳进环回/云元数据。
    """
    scheme_err = _check_scheme(url)
    if scheme_err:
        raise ValueError(scheme_err)
    _assert_public_host(url)
    return http_fetch.fetch_text(url, _USER_AGENT, timeout, url_validator=_validateHopUrl)


def _error(msg: str, **extra) -> Dict[str, Any]:
    return {"success": False, "error": msg, **extra}


def _ok(data: Any, source: str, **extra) -> Dict[str, Any]:
    return {"success": True, "data": data, "source": source, **extra}


# ══════════════════════════════════════════════════════════════
# V2EX 热门（官方公开 API，零配置）
# ══════════════════════════════════════════════════════════════


def v2ex_hot(limit: int = 10) -> Dict[str, Any]:
    """V2EX 热门帖子列表"""
    try:
        text = _http_get_text("https://www.v2ex.com/api/topics/hot.json", _DEFAULT_TIMEOUT)
        topics = json.loads(text)
        data = [
            {
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "replies": t.get("replies", 0),
                "member": (t.get("member") or {}).get("username", ""),
            }
            for t in topics[: max(1, int(limit))]
        ]
        return _ok(data, source="v2ex")
    except Exception as e:  # noqa: BLE001 - 工具层兜底
        logger.error("v2ex_hot 失败: %s", e)
        return _error(f"V2EX 读取失败: {e}", source="v2ex")


# ══════════════════════════════════════════════════════════════
# 通用网页阅读（Jina Reader，零配置）
# ══════════════════════════════════════════════════════════════


def web_read(url: str, timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """阅读任意网页（Jina Reader 转为可读文本/Markdown）"""
    if not url or not url.strip():
        return _error("缺少 URL")
    try:
        text = _http_get_text(f"https://r.jina.ai/{url}", timeout)
        return _ok(text, source="jina")
    except ValueError as e:
        return _error(str(e), source="jina")
    except Exception as e:  # noqa: BLE001
        logger.error("web_read 失败: %s", e)
        return _error(f"网页读取失败: {e}", source="jina")


# ══════════════════════════════════════════════════════════════
# RSS / Atom（feedparser，零配置）
# ══════════════════════════════════════════════════════════════


def rss_read(url: str, limit: int = 10, timeout: float = _DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """阅读 RSS/Atom 源"""
    if not url or not url.strip():
        return _error("缺少 URL")
    try:
        # 经共享层抓取：feedparser 传 URL 会内建裸 urllib 连接（绕过 TLS 指纹层，
        # 且连接错误被其 bozo 吞成空结果）。传原始字节保留其编码自动探测。
        _check_scheme(url)
        _assert_public_host(url)
        raw = http_fetch.fetch_bytes(url, _USER_AGENT, timeout, url_validator=_validateHopUrl)
        parsed = feedparser.parse(raw)
        if parsed.get("bozo") and not parsed.get("entries"):
            return _error(f"RSS 解析失败: {parsed.get('bozo_exception')}")
        data = [
            {
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "summary": (e.get("summary") or "")[:300],
            }
            for e in parsed.entries[: max(1, int(limit))]
        ]
        return _ok(data, source="rss")
    except ValueError as e:
        return _error(str(e), source="rss")
    except Exception as e:  # noqa: BLE001
        logger.error("rss_read 失败: %s", e)
        return _error(f"RSS 读取失败: {e}", source="rss")


# ══════════════════════════════════════════════════════════════
# YouTube 字幕（yt-dlp，零配置；仅限 youtube 域名）
# ══════════════════════════════════════════════════════════════


def _is_youtube_url(url: str) -> bool:
    lowered = url.lower()
    return "youtube.com/watch" in lowered or "youtu.be/" in lowered


def youtube_transcript(url: str, timeout: float = _YTDLP_TIMEOUT) -> Dict[str, Any]:
    """提取 YouTube 视频字幕/自动字幕文本（yt-dlp）"""
    if not url or not _is_youtube_url(url):
        return _error("仅支持 YouTube 视频链接（youtube.com/watch 或 youtu.be/）")

    workdir = None
    try:
        # 实现要点（实测沉淀）：
        # - sys.executable -m yt_dlp：与 venv 绑定（PATH 中无 yt-dlp.exe 仍可用）
        # - --js-runtimes node：新版 yt-dlp 解签名需要 JS 运行时（默认只启用 deno）
        # - 字幕写临时目录后读取（-o - 只作用于视频流，字幕始终落独立文件）
        workdir = tempfile.mkdtemp(prefix="neurova_yt_")
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--js-runtimes",
            "node",
            "--write-sub",
            "--write-auto-sub",
            "--skip-download",
            "--sub-langs",
            "zh.*,en.*",
            "--sub-format",
            "json3",
            "-o",
            str(Path(workdir) / "sub"),
            url,
        ]
        run = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=utf8ChildEnv(),
            errors="replace",
            timeout=timeout,
        )
        # 非零退出不立即放弃：多语言下载时部分语言可能 429 失败，但
        # 已写入的字幕文件仍可用（实测：zh-Hans 成功、后续语言 429 →
        # exit 1，但 sub.*.json3 已在目录中）
        text = _read_json3_dir(workdir)
        if text:
            return _ok(text, source="yt-dlp")
        if run.returncode != 0:
            return _error(f"yt-dlp 提取失败: {(run.stderr or '')[:300]}")
        return _error("未找到可用字幕（该视频可能无字幕）")
    except subprocess.TimeoutExpired:
        return _error(f"yt-dlp 提取超时（{timeout}s）")
    except FileNotFoundError:
        return _error("yt-dlp 未安装（pip install yt-dlp）")
    except Exception as e:  # noqa: BLE001
        logger.error("youtube_transcript 失败: %s", e)
        return _error(f"字幕提取失败: {e}")
    finally:
        if workdir:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)


def _read_json3_dir(workdir: str) -> str:
    """读取临时目录里的 json3 字幕文件（按语言优先级），压成纯文本"""
    candidates = sorted(
        Path(workdir).glob("sub*.json3"),
        key=lambda p: (0 if ".zh" in p.name else 1, str(p)),
    )
    texts: List[str] = []
    for path in candidates[:2]:  # 最多取两个语言文件（原字幕+自动字幕）
        try:
            with open(path, encoding="utf-8") as fh:
                texts.append(_flatten_json3(fh.read()))
        except Exception as e:  # noqa: BLE001 - 单文件损坏跳过
            logger.debug("字幕文件读取失败 %s: %s", path, e)
    return " ".join(t for t in texts if t)


def _flatten_json3(stdout: str) -> str:
    """把 yt-dlp json3 字幕（可能多个文件连串）压成纯文本"""
    texts: List[str] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(stdout):
        chunk = stdout[idx:].lstrip()
        if not chunk.startswith("{"):
            break
        try:
            obj, consumed = decoder.raw_decode(chunk)
        except json.JSONDecodeError:
            break
        idx += len(stdout[idx:]) - len(chunk) + consumed
        for ev in obj.get("events", []):
            segs = ev.get("segs") or []
            line = "".join(s.get("utf8", "") for s in segs).strip()
            if line and line != "\n":
                texts.append(line)
    return " ".join(texts)


# ══════════════════════════════════════════════════════════════
# B 站搜索（yt-dlp 的 bilisearch 前缀，无需登录）
# ══════════════════════════════════════════════════════════════


def bilibili_search(query: str, limit: int = 5, timeout: float = _YTDLP_TIMEOUT) -> Dict[str, Any]:
    """B 站视频搜索（yt-dlp bilisearch 前缀；不依赖 bili-cli 外部安装）。

    B 站风控对搜索接口有概率性 412（Precondition Failed），内置一次退避
    重试（失败退避）。
    """
    if not query or not query.strip():
        return _error("缺少搜索关键词")

    def _run_once() -> subprocess.CompletedProcess:
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "-J",
            "--flat-playlist",
            f"bilisearch{int(limit)}:{query}",
        ]
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=utf8ChildEnv(),
            errors="replace",
            timeout=timeout,
        )

    try:
        run = _run_once()
        if run.returncode != 0 and "412" in (run.stderr or ""):
            # B 站风控概率性拦截，退避后重试一次
            time.sleep(2)
            run = _run_once()
        if run.returncode != 0:
            return _error(f"B 站搜索失败: {(run.stderr or '')[:300]}")
        payload = json.loads(run.stdout or "{}")
        data = []
        for e in payload.get("entries") or []:
            url = e.get("url") or ""
            if not url:
                continue
            # flat 模式条目无 title，用 id（BV/av 号）兜底
            title = e.get("title") or e.get("id") or url
            data.append({"title": title, "url": url})
        if not data:
            return _error("搜索无结果")
        return _ok(data, source="bilibili")
    except subprocess.TimeoutExpired:
        return _error(f"B 站搜索超时（{timeout}s）")
    except FileNotFoundError:
        return _error("yt-dlp 不可用（pip install yt-dlp）")
    except Exception as e:  # noqa: BLE001
        logger.error("bilibili_search 失败: %s", e)
        return _error(f"B 站搜索失败: {e}")


# ══════════════════════════════════════════════════════════════
# 社交平台（渐进式暴露：doctor 查后端状态，未配置返回引导）
# ══════════════════════════════════════════════════════════════


def run_doctor() -> Dict[str, Any]:
    """运行 agent-reach 体检（渠道状态；只读配置，不执行渠道探测）。

    集成面收口（教义第 6/7 条）：旧实现 import agent_reach.core／
    agent_reach.config——PyPI 0.1.0 与源码仓 main 都没有这两个模块，
    该门今天必然落 except（死门）。现改走 CLI 面唯一集成点
    ``agent_reach_cli.runDoctor``；成功**原样**交回上游体检读数（不污染
    字段），失败点名原因（未装→安装指引；其余→CLI 错误码透传）——
    「不可得」与「未接入」两种读数保持互不同形。
    """
    from neurova.web_reach.agent_reach_cli import runDoctor

    result = runDoctor()
    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error") or "agent-reach doctor 不可得",
            **({"not_installed": True} if result.get("not_installed") else {}),
        }
    return result.get("data") or {}


def social_search(
    platform: str,
    query: str,
    limit: int = 10,
) -> Dict[str, Any]:
    """社交平台搜索（渐进式暴露 + CLI 渠道动作真实执行）。

    读数阶梯（三种失败形态互不同形，不自动登录、不碰用户浏览器）：
    - CLI 不可得 → backend_unavailable 点名 + 安装指引
    - 渠道未接入/待配置 → needs_setup 引导（agent-reach add …；带上游 problems/hint）
    - 渠道就绪 → ``agent-reach <platform> search <query>`` 真实执行；
      NEED_LOGIN → needs_login 引导（agent-reach login …）
    登录态归上游 CLI 自己的浏览器会话管理；本模块不保存凭据、不读凭据桶。
    """
    platform_key = (platform or "").strip().lower()
    if platform_key not in _SOCIAL_CHANNELS:
        return _error(
            f"不支持的平台: {platform}（支持: {'/'.join(sorted(_SOCIAL_CHANNELS))}）"
        )

    from neurova.web_reach.agent_reach_cli import doctorChannels, runChannelAction, runDoctor

    doctor = runDoctor()
    if not doctor.get("success"):
        return {
            "success": False,
            "backend_unavailable": True,
            "error": doctor.get("error") or "agent-reach CLI 不可得",
            "guide": doctor.get("error") or "agent-reach CLI 不可得",
            "platform": platform_key,
        }
    channel = doctorChannels(doctor.get("data")).get(platform_key) or {}
    status = channel.get("status")
    hint = channel.get("hint")
    if status == "not_added":
        guide = f"{platform_key} 渠道未接入：运行 agent-reach add {platform_key}"
        return {
            "success": False,
            "needs_setup": True,
            # error 键承载指引原文：咽喉/API 的成败映射只取 error，
            # 缺了它指引会被塌缩成笼统「工具执行失败」
            "error": guide,
            "guide": guide,
            "hint": hint,
            "platform": platform_key,
        }
    if status == "needs_setup":
        problems = "；".join(channel.get("problems") or [])
        guide = (
            f"{platform_key} 渠道待配置：{problems or f'运行 agent-reach add {platform_key}'}"
        )
        return {
            "success": False,
            "needs_setup": True,
            "error": guide,
            "guide": guide,
            "hint": hint,
            "platform": platform_key,
        }

    # 渠道就绪（或未验证）→ 真实执行；登录态缺失等由上游错误码引导
    result = runChannelAction(platform_key, "search", target=query, limit=max(1, int(limit)))
    if not result.get("success") and result.get("code") == "NEED_LOGIN":
        guide = f"{platform_key} 渠道需要登录态：运行 agent-reach login {platform_key}"
        return {
            "success": False,
            "needs_login": True,
            "error": guide,
            "guide": guide,
            "hint": result.get("hint"),
            "platform": platform_key,
        }
    return {**result, "platform": platform_key, "query": query}
