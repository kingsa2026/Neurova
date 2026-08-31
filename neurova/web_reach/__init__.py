"""Web Reach —— 互联网平台直达读取能力（对标 Agent-Reach 方案 B）

路由选型对齐 Panniantong/Agent-Reach 的零配置路径：
- 网页阅读: Jina Reader（r.jina.ai 前缀，免费无 Key）
- V2EX: 官方公开 API
- RSS/Atom: feedparser
- YouTube 字幕: yt-dlp（仅限 youtube 域名）
- B 站搜索: yt-dlp 的 bilisearch 前缀（bili-cli 的 yt-dlp 等价物）
- 社交平台（Twitter/小红书等）: 渐进式暴露——查 doctor 后端状态，
  未配置返回引导，不自动登录、不碰用户浏览器（安全边界同上游）

凭据与运行时状态归上游工具（~/.agent-reach/），本模块不保存任何凭据。
"""

from neurova.web_reach.reach import (
    bilibili_search,
    social_search,
    rss_read,
    v2ex_hot,
    web_read,
    youtube_transcript,
)

__all__ = [
    "bilibili_search",
    "social_search",
    "rss_read",
    "v2ex_hot",
    "web_read",
    "youtube_transcript",
]
