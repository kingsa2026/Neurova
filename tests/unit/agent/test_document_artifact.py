# -*- coding: utf-8 -*-
"""文档型回复 → Markdown 工件（产出物面）单元测试。

锁定契约（2026-11-14 产品口径：产出物面展示文档型成果，命名=任务内容+日期）：
- 文档型回复（够长＋含 Markdown 标题）落成
  `<工作区>/documents/<标题>_<YYYY-MM-DD>.md` 并注册 kind=markdown 工件；
- 标题取回复第一个 Markdown 标题（去标记符/emoji/非法文件名字符）；
  清洗后为空则回退用户输入前 24 字；
- 短回复 / 无标题 → 不产出（宁缺勿滥，不给每轮长答案都造文件）；
- env NEUROVA_DOC_ARTIFACT=0 整体关闭（逃生开关）；
- 同名文件自动 _2/_3 递增，不覆盖既有产物。
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from neurova.agent.document_artifact import capture_document_artifact
from neurova.core.agent_workspaces import get_agent_workspace_dir


def _long_body(chars: int = 900) -> str:
    return "这是一段足够长的探索结论正文，用于越过文档判定阈值。" * (chars // 30 + 1)


class TestDocumentArtifactCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nr_docart_")
        self._root_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.ws = get_agent_workspace_dir("kai")
        self.ws.mkdir(parents=True, exist_ok=True)
        self.today = time.strftime("%Y-%m-%d")

    def test_document_like_reply_captured_as_md(self):
        reply = "# Neurova 探索报告\n\n" + _long_body()
        ev = capture_document_artifact(
            user_input="凯 你来探索一下neurova", reply=reply,
            agent_id="kai", user_id="3",
        )
        self.assertIsNotNone(ev)
        self.assertEqual(ev["type"], "artifact")
        self.assertEqual(ev["kind"], "markdown")
        self.assertTrue(ev["name"].startswith("Neurova 探索报告_"), ev["name"])
        self.assertIn(self.today, ev["name"])
        self.assertTrue(ev["path"].endswith(".md"))
        self.assertTrue(Path(ev["path"]).exists())
        self.assertEqual(Path(ev["path"]).read_text(encoding="utf-8"), reply)
        # 落点在工作区 documents/ 目录下
        self.assertIn("documents", str(Path(ev["path"]).parent.name))

    def test_short_reply_not_captured(self):
        reply = "# 标题\n\n太短了。"
        self.assertIsNone(
            capture_document_artifact(user_input="问", reply=reply,
                                      agent_id="kai", user_id="3"))

    def test_no_heading_not_captured(self):
        reply = "没有标题的一大段文字。" * 200
        self.assertIsNone(
            capture_document_artifact(user_input="问", reply=reply,
                                      agent_id="kai", user_id="3"))

    def test_env_disabled(self):
        reply = "# 报告\n\n" + _long_body()
        with mock.patch.dict(os.environ, {"NEUROVA_DOC_ARTIFACT": "0"}):
            self.assertIsNone(
                capture_document_artifact(user_input="问", reply=reply,
                                          agent_id="kai", user_id="3"))

    def test_title_falls_back_to_user_input_when_heading_cleans_empty(self):
        reply = "### 🧬\n\n" + _long_body()
        ev = capture_document_artifact(
            user_input="凯 你来探索一下neurova", reply=reply,
            agent_id="kai", user_id="3",
        )
        self.assertIsNotNone(ev)
        self.assertTrue(ev["name"].startswith("凯 你来探索一下neurova"[:12]), ev["name"])

    def test_duplicate_name_dedup(self):
        reply = "# 同名报告\n\n" + _long_body()
        first = capture_document_artifact(user_input="问", reply=reply,
                                          agent_id="kai", user_id="3")
        second = capture_document_artifact(user_input="问", reply=reply,
                                           agent_id="kai", user_id="3")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first["path"], second["path"])
        self.assertIn("_2", second["name"])

    def test_illegal_filename_chars_stripped(self):
        reply = "# 探索:报告/第二批?<2026>\n\n" + _long_body()
        ev = capture_document_artifact(user_input="问", reply=reply,
                                       agent_id="kai", user_id="3")
        self.assertIsNotNone(ev)
        for ch in '<>:"/\\|?*':
            self.assertNotIn(ch, ev["name"])


if __name__ == "__main__":
    unittest.main()
