# -*- coding: utf-8 -*-
"""收尾轮按名带挂既有产物——管线装配点回归测试。

锁定契约（2026-11-14 用户点单）：
- `_collect_round_artifacts(tool_msgs, reply=..., doc_event=...)` 是本轮
  产物装配入口：tool_result 提取＋文档工件＋回复点名带挂，经
  merge_round_artifacts 按 artifact_id 去重后随 assistant_metadata 落盘；
- 旧位置参数调用（仅 tool_msgs）保持兼容（A-03 回归同款形态）。
"""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from neurova.api.endpoints import artifacts_api
from neurova.core.agent_workspaces import get_agent_workspace_dir
from neurova.post_chat_pipeline import PostChatPipeline


def _make_pipe(agent) -> PostChatPipeline:
    pipe = PostChatPipeline.__new__(PostChatPipeline)
    pipe._agent = agent
    return pipe


class TestRoundArtifactAttach(unittest.TestCase):
    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_pipeatt_")
        self._env_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.ws = get_agent_workspace_dir("kai")
        self.ws.mkdir(parents=True)
        self.md = self.ws / "Neurova记忆系统要点报告.md"
        self.md.write_text("# 报告", encoding="utf-8")
        info = artifacts_api.register_artifact(str(self.md), agent_id="kai", user_id="3")
        self.known_id = info["artifact_id"]
        self.pipe = _make_pipe(
            SimpleNamespace(config=SimpleNamespace(agent_id="kai"), current_user_id="3")
        )

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_reply_mentioned_artifact_attached_to_round(self):
        """收尾轮回复点名既有产物 → 挂进本轮 artifacts。"""
        events = self.pipe._collect_round_artifacts(
            [], reply="任务收尾确认：产物 `Neurova记忆系统要点报告.md` 真实存在。"
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["artifact_id"], self.known_id)

    def test_tool_result_extraction_still_registered(self):
        """tool_result 写形态产物照旧注册（写进工作区的 pdf）。"""
        pdf = self.ws / "out.pdf"
        pdf.write_bytes(b"%PDF-1.7 fake")
        import json

        raw = json.dumps({"success": True, "file_path": str(pdf)})
        events = self.pipe._collect_round_artifacts(
            [{"type": "tool_result", "tool_name": "write_pdf", "result": raw}]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "pdf")

    def test_other_users_artifact_not_attached(self):
        """他人产物即使被点名也不挂（归属口径与读端一致）。"""
        artifacts_api._artifacts_store.clear()
        info = artifacts_api.register_artifact(str(self.md), agent_id="kai", user_id="9")
        events = self.pipe._collect_round_artifacts(
            [], reply="产物 `Neurova记忆系统要点报告.md` 已就绪。"
        )
        self.assertEqual([e for e in events if e.get("artifact_id") == info["artifact_id"]], [])


if __name__ == "__main__":
    unittest.main()
