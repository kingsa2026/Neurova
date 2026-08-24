"""
网络搜索 Skill Executor（同步版）

语义与 neurova.skill_system.WebSearchSkill 一致：成功即返回
SkillResult(success=True)，网络失败时把错误信息放进 output 而不
抛异常（与 WebSearchSkill 的容错行为保持一致）。

从 Bug W-4 修复逻辑对齐 tool_executor._execute_web_search，使用
urllib 直接发起搜索请求，保证该路径独立可用。解析结果受 max_results
参数控制（默认 5）。
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from neurova.skills.executor import BaseSkillExecutor, SkillResult


class WebSearchSkillExecutor(BaseSkillExecutor):
    """网络搜索执行器：query 搜索"""

    def __init__(self, timeout: float = 10.0) -> None:
        super().__init__(skill_id="web_search", skill_name="网络搜索技能")
        self.timeout = timeout

    def execute(self, params: Dict[str, Any]) -> SkillResult:
        query = params.get("query", "")
        max_results = int(params.get("max_results", 5))
        try:
            results = self._search(query, max_results=max_results)
        except Exception as exc:  # 与 WebSearchSkill 一致：失败也视为成功并附错误信息
            results = [{"query": query, "error": f"搜索失败: {exc}"}]
        return SkillResult(success=True, output=results)

    def _search(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        if not query:
            return []
        try:
            q = urllib.parse.quote(query)
            url = f"https://www.bing.com/search?q={q}"
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (compatible; Neurova/1.0)"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            snippets: List[str] = []
            idx = 0
            while len(snippets) < max_results:
                pos = html.find("</p>", idx)
                if pos == -1:
                    break
                snippet = html[max(0, pos - 200):pos].strip()
                if snippet:
                    snippets.append(snippet)
                idx = pos + 4

            if not snippets:
                return [
                    {
                        "query": query,
                        "url": url,
                        "snippet": f"搜索 '{query}' 完成，但未能提取摘要。",
                    }
                ]

            return [
                {"query": query, "url": url, "snippet": re.sub(r"\s+", " ", s).strip()}
                for s in snippets[:max_results]
            ]
        except Exception as exc:
            return [{"query": query, "error": f"搜索失败: {exc}"}]
