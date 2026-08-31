"""Web Reach 实现：平台直达读取（路由选型对齐 Agent-Reach 零配置路径）。

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
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

import feedparser

from neurova.core.logger import get_logger
from neurova.web_reach.credentials import get_credential_store

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


def _http_get_text(url: str, timeout: float) -> str:
    """GET 请求并返回 UTF-8 文本（请求前做 SSRF 主机边界校验）"""
    scheme_err = _check_scheme(url)
    if scheme_err:
        raise ValueError(scheme_err)
    _assert_public_host(url)
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


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
        # feedparser 内部自建连接；SSRF 边界由前置解析校验兜底
        _check_scheme(url)
        _assert_public_host(url)
        parsed = feedparser.parse(url, request_headers={"User-Agent": _USER_AGENT})
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
    重试（对齐 Agent-Reach 的失败重试链设计）。
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
    """运行 agent-reach 体检（渠道后端状态；只读配置，不执行渠道探测）"""
    try:
        from agent_reach.core import AgentReach
        from agent_reach.config import Config

        eyes = AgentReach(Config(read_only=True))
        return eyes.doctor()
    except Exception as e:  # noqa: BLE001 - 未安装/版本不匹配时优雅降级
        logger.debug("agent-reach doctor 不可用: %s", e)
        return {}


def social_search(
    platform: str,
    query: str,
    limit: int = 10,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """社交平台搜索（渐进式暴露 + 按用户凭据真实执行）。

    隔离边界（对齐上游 Agent-Reach）：
    - 凭据按 user_id 分桶（UserCredentialStore，加密落盘），不共享、
      不自动登录、不碰用户浏览器
    - 后端就绪且该用户凭据齐备 → 凭据经子进程 env 注入执行上游 CLI
      （凭据只存在于子进程环境，不进返回值与日志）
    - 后端就绪但凭据缺失 → needs_setup 引导（不借用他人凭据）
    - 后端未激活 → needs_setup 引导
    """
    platform_key = (platform or "").strip().lower()
    if platform_key not in _SOCIAL_CHANNELS:
        return _error(
            f"不支持的平台: {platform}（支持: {'/'.join(sorted(_SOCIAL_CHANNELS))}）"
        )
    doctor = run_doctor()
    channels = doctor.get("channels") if isinstance(doctor, dict) else {}
    channel = (channels or {}).get(_SOCIAL_CHANNELS[platform_key], {})
    active = channel.get("active_backend") if isinstance(channel, dict) else None

    if not active:
        return {
            "success": False,
            "needs_setup": True,
            "guide": (
                f"{platform_key} 需要配置登录态后端。参考 Agent-Reach 引导："
                f"安装 OpenCLI（桌面，复用 Chrome 会话）或对应 CLI/Cookie，"
                f"配置后运行 agent-reach doctor --json 验证。"
            ),
            "platform": platform_key,
        }

    # 后端就绪 → 按用户凭据执行（凭据分桶；缺失则引导）
    uid = user_id or "default"
    creds = get_credential_store().platform_credentials(uid, platform_key)
    missing = [k for k, v in creds.items() if not v]

    if missing:
        return {
            "success": False,
            "needs_setup": True,
            "missing_keys": missing,
            "guide": (
                f"{platform_key} 后端已就绪（{active}），但当前用户缺少凭据: "
                f"{', '.join(missing)}。请在设置中提供对应 Cookie/Token，"
                f"或运行 agent-reach configure。"
            ),
            "platform": platform_key,
        }

    # 真实执行：上游 CLI + env 注入（凭据只在子进程环境中）
    from neurova.web_reach.social_exec import execute_social_search

    result = execute_social_search(
        platform=platform_key,
        query=query,
        limit=limit,
        credentials=creds,
        active_backend=active,
    )
    result.setdefault("platform", platform_key)
    return result
