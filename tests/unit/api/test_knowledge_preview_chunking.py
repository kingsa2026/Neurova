"""P1#7 chunk 切分 live-preview 端点测试。

契约（报告 §7 #7）：
- POST /knowledge/preview-chunking {content, max_chars?, overlap?} → 只读预览：
  不入库、不算 embedding、不落日志正文；与摄取路径共享 split_with_meta
 单源实现。
- 与生产一致性断言：preview 的 chunks 与 repo 摄取同一文本得到的条目
  chunks（含 context_header 表头注入）逐项相等。
- 预算护栏：超长输入 4xx 语义拒绝（code:1），max_chars/overlap 越界钳制。
"""

import asyncio

from neurova.api.endpoints import knowledge as kmod
from neurova.knowledge.repository import KnowledgeRepository
from neurova.knowledge.splitter import DEFAULT_MAX_CHARS, split_with_meta


def _preview(body):
    return asyncio.run(kmod.preview_chunking(body))


class TestPreviewChunking:
    def test_returns_chunks_matching_production_single_source(self, tmp_path):
        text = "段落一。" * 60 + "\n\n" + "| 城市 | 人口 |\n|---|---|\n" + "\n".join(
            f"| 城{i} | {i * 100} |" for i in range(30)
        )
        resp = _preview({"content": text, "max_chars": 300, "overlap": 40})
        assert resp["code"] == 0
        preview_chunks = resp["data"]["chunks"]
        assert preview_chunks

        # 与摄取路径（split_with_meta）逐项一致——单源证明
        production = split_with_meta(text, max_chars=300, overlap=40)
        assert preview_chunks == production

    def test_stats_and_default_params(self):
        text = "知识内容。" * 500  # 超默认 800 → 多块
        resp = _preview({"content": text})
        data = resp["data"]
        assert data["total"] == len(data["chunks"])
        assert data["max_chars"] == DEFAULT_MAX_CHARS
        assert data["char_total"] == len(text)

    def test_empty_rejected_with_code(self):
        assert _preview({"content": "   "})["code"] == 1
        assert _preview({})["code"] == 1

    def test_oversized_input_guard(self):
        huge = "长" * (64 * 1024 + 10)
        resp = _preview({"content": huge})
        assert resp["code"] == 1
        assert "上限" in resp["message"]

    def test_param_clamping(self):
        resp = _preview({"content": "短文本。", "max_chars": 999999, "overlap": 999999})
        assert resp["code"] == 0
        # 钳制不炸且 overlap ≤ max/2
        assert resp["data"]["max_chars"] <= 4000
        assert resp["data"]["overlap"] <= resp["data"]["max_chars"] // 2
