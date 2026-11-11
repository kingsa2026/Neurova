"""Web Reach —— 互联网平台直达读取能力

零配置路径的路由选型：
- 网页阅读: Jina Reader（r.jina.ai 前缀，免费无 Key）
- 浏览器渲染页读取: browser_read（Playwright headless，JS 页 → Markdown 文本）
- V2EX: 官方公开 API
- RSS/Atom: feedparser
- YouTube 字幕: yt-dlp（仅限 youtube 域名）
- B 站搜索: yt-dlp 的 bilisearch 前缀（bili-cli 的 yt-dlp 等价物）
- 社交平台（Twitter/小红书等）: 渐进式暴露——查 doctor 渠道状态，
  未接入返回引导，不自动登录、不碰用户浏览器（安全边界同上游）

凭据与运行时状态归上游工具（~/.agent-reach/），本模块不保存任何凭据。

agent-reach 的集成面唯一收敛在 agent_reach_cli（CLI argv 直传 + JSON
envelope 归一）；reach.social_search 的渐进式暴露与渠道动作执行都走它。
"""

from neurova.web_reach import agent_reach_cli
from neurova.web_reach.reach import (
    bilibili_search,
    social_search,
    rss_read,
    v2ex_hot,
    web_read,
    youtube_transcript,
)
from neurova.web_reach.browser_read import browser_read

__all__ = [
    "agent_reach_cli",
    "bilibili_search",
    "browser_read",
    "social_search",
    "rss_read",
    "v2ex_hot",
    "web_read",
    "youtube_transcript",
]
