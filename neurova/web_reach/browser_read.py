"""browser_read —— JS 渲染页面 → 干净文本/Markdown 读取。

与 web_reach.web_read（Jina Reader 转文本）互补：web_read 覆盖静态页，
browser_read 通过 Playwright 驱动真实浏览器，处理 SPA / 客户端渲染 / 反爬
轻量页面，并把 DOM 提取为 Markdown 风格文本供 LLM 使用。

安全边界（与 reach.py 一致）：
- 仅 http/https；请求前经 url_guard 阻断私网/环回/链路本地/保留段/元数据 IP
- 浏览器无状态：每次调用独立 headless 实例，关闭即释放
- 续读零网络：传 session_id 时从内存缓存切片，不开浏览器、不做 URL 校验

续读游标（对标 Dokobot canContinue/sessionId）：
- 首读超过 chunk（默认 _MAX_TEXT=60k，与既有契约一致）→ 建 ReadSession，
  返回首片 + session_id + can_continue + next_offset，全文缓存在会话里
- 续读：browser_read(session_id=..., offset=?) → 纯内存切片，可循环读完全文

依赖：playwright（已在 requirements.txt，浏览器二进制需 `playwright install
chromium` 一次；未安装时返回明确引导错误，不影响其他 web_reach 工具）。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from playwright.async_api import async_playwright

from neurova.core.logger import get_logger
from neurova.core.read_sessions import get_read_session_store
from neurova.web_reach.reach import _assert_public_host, _error, _ok

logger = get_logger(__name__)

# 页内提取脚本：块级元素 → Markdown 风格文本（标题/段落/列表/代码/引用），
# 跳过脚本、导航/页脚/侧栏/弹窗等非内容区（按标签与 class 启发式）。
_MARKDOWN_JS = """() => {
  const SKIP_TAG = /^(script|style|noscript|iframe|svg|canvas|template|nav|footer|aside|button)$/i;
  const SKIP_CLASS = new Set(["nav","menu","footer","sidebar","cookie","advert","ad-","banner","modal","popup","toast"]);
  const out = [];
  const walk = (node) => {
    const tag = node.tagName ? node.tagName.toLowerCase() : '';
    if (!tag || SKIP_TAG.test(tag)) return;
    const cls = (node.className && typeof node.className === 'string') ? node.className : '';
    if (cls) {
      const tokens = cls.split(/\\s+/);
      for (const t of tokens) {
        if (SKIP_CLASS.has(t)) return;
      }
    }
    if (/^h[1-6]$/.test(tag)) {
      const t = (node.innerText || '').trim();
      if (t) out.push('\\n' + '#'.repeat(+tag[1]) + ' ' + t + '\\n');
      return;
    }
    if (tag === 'p' || (tag === 'div' && node.childElementCount === 0)) {
      const t = (node.innerText || '').trim();
      if (t) out.push(t + '\\n\\n');
      return;
    }
    if (tag === 'li') {
      const t = (node.innerText || '').trim();
      if (t) out.push('- ' + t);
      return;
    }
    if (tag === 'pre' || tag === 'code') {
      const t = (node.innerText || '').trim();
      if (t) out.push('\\n```\\n' + t + '\\n```\\n');
      return;
    }
    if (tag === 'blockquote') {
      const t = (node.innerText || '').trim();
      if (t) out.push('\\n> ' + t.replace(/\\n/g, '\\n> ') + '\\n');
      return;
    }
    if (tag === 'table') {
      const t = (node.innerText || '').trim();
      if (t) out.push('\\n' + t + '\\n');
      return;
    }
    for (const child of node.children || []) walk(child);
  };
  walk(document.body);
  return { title: document.title, text: out.join('\\n').replace(/\\n{3,}/g, '\\n\\n').trim() };
}"""

# 单次返回的文本上限（保护上下文长度）
_MAX_TEXT = 60_000


async def _safe_evaluate(page, timeout: float) -> Dict[str, Any]:
    """在页面加载引发的导航后安全提取（执行上下文可能被销毁，重试数次）。"""
    last: Dict[str, Any] = {"title": "", "text": ""}
    for _ in range(3):
        try:
            result = await page.evaluate(_MARKDOWN_JS)
            if isinstance(result, dict):
                last = result
                if result.get("text") or result.get("title"):
                    return result
        except Exception as e:  # noqa: BLE001 - 导航竞态则等待后重试
            if "Execution context was destroyed" not in str(e):
                raise
            await page.wait_for_timeout(500)
    return last


async def _browser_read_async(url: str, timeout: float) -> Dict[str, Any]:
    """启动 headless 浏览器导航并提取页面。

    等待策略：load（等待所有资源加载完成，包括脚本） + 沉淀（2s）。
    相比 networkidle（广告轮询/长连接易超时）和 domcontentloaded（SPA 水合不足）
    更均衡——实测通过维基百科（富内容）与 Vue.js 文档（SPA 水合后渲染）。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=int(timeout * 1000))
            # 给 SPA 水合与懒加载模块留出执行时间
            await page.wait_for_timeout(2000)
            result = await _safe_evaluate(page, timeout)
        finally:
            await browser.close()
    return result if isinstance(result, dict) else {"title": "", "text": ""}


def browser_read(
    url: str = "",
    timeout: float = 30.0,
    session_id: str = None,
    offset: int = None,
    chunk_size: int = None,
) -> Dict[str, Any]:
    """读取 JS 渲染页面为 Markdown 风格文本（同步入口，供工具线程调用）。

    首读传 url；长文自动建读取会话并返回游标字段。续读只传 session_id
    （可选 offset 显式回看），零浏览器开销。

    Returns:
        与 web_reach 契约一致的 _ok/_error 字典（success/data/source 或 error）。
    """
    # ── 续读路径：纯内存切片，不开浏览器、不做 URL 校验（零网络）──
    if session_id:
        store = get_read_session_store()
        chunk = store.read(session_id, offset=offset)
        if chunk is None:
            return _error(
                "读取会话不存在或已过期——请用 url 重新首读",
                source="browser_read",
            )
        if url and url != chunk["url"]:
            logger.debug("续读忽略传入 url %s（会话归属 %s）", url, chunk["url"])
        return _ok(chunk, source="browser_read")

    # ── 首读路径 ──
    if not url or not str(url).strip():
        return _error("缺少 url 参数（或传 session_id 续读）", source="browser_read")
    try:
        _assert_public_host(url)
    except ValueError as e:
        return _error(f"URL 校验失败: {e}", source="browser_read")
    try:
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_browser_read_async(url, float(timeout)))
        finally:
            loop.close()
    except Exception as e:  # noqa: BLE001 - 工具层兜底
        msg = str(e)
        if "executable doesn't exist" in msg.lower() or "playwright install" in msg.lower():
            return _error(
                "Playwright 浏览器未安装——先运行 playwright install chromium 一次",
                source="browser_read",
            )
        logger.error("browser_read 失败 %s: %s", url, e)
        return _error(f"浏览器读取失败: {e}", source="browser_read")

    text = (result or {}).get("text", "") or ""
    if not text.strip():
        return _error(
            "页面未提取到文本内容（可能为空页、登录墙或 JS 未渲染完成）",
            source="browser_read",
        )

    # 首片分片 + 全文入会话缓存（尾部不再丢弃）；短文（未超 chunk）不建会话，
    # 行为与既有契约完全一致
    effective_chunk = int(chunk_size) if chunk_size else _MAX_TEXT
    truncated = len(text) > effective_chunk
    data = {
        "title": (result or {}).get("title", ""),
        "text": text[:effective_chunk],
        "url": url,
        "text_length": len(text),
        "truncated": truncated,
        "can_continue": truncated,
        "next_offset": effective_chunk if truncated else None,
        "session_id": None,
        "total_length": len(text),
        "source": "browser_read",
    }
    if truncated:
        store = get_read_session_store()
        session = store.create(
            domain="browser_read", url=url,
            title=(result or {}).get("title", "") or "",
            text=text, chunk_size=effective_chunk,
            served=effective_chunk,  # 首片已直接返回，游标跳过它
        )
        data["session_id"] = session.session_id
    return _ok(data, source="browser_read")
