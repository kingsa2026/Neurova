# -*- coding: utf-8 -*-
"""generation 产物进产出物面 ＋ 收尾轮按名带挂 单元测试。

锁定契约（2026-11-14 产品口径，用户点单两项）：
- write_pdf/browser_pdf 等工具的"落产物目录"形态把 PDF 写进
  data/generations，结果 JSON 的 file_path 指向该目录——注册白名单
  必须收下它（此前被 _allowed_roots 拒掉，产出物面永远看不到 PDF）；
- 注册属主=轮次 sender；按名反查只回属主（或显式 shared）可见条目，
  文件已删除的条目不回（避免卡片挂出必 404 的死产物）；
- 回复点名带挂：收尾轮回复里点名的既有产物（反引号文件名 / 生成文件
  URL 两种形态）挂到当前轮 assistant_metadata.artifacts；
- merge_round_artifacts 是本轮产物装配单点：tool_result 提取＋文档
  工件＋回复带挂，按 artifact_id 去重保序。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neurova.api.endpoints import artifacts_api
from neurova.api.endpoints.artifacts_api import (
    artifact_names_from_reply,
    extract_tool_artifacts,
    find_artifacts_by_names,
    merge_round_artifacts,
)
from neurova.core.agent_workspaces import get_agent_workspace_dir


class TestGenerationArtifactSurface(unittest.TestCase):
    """data/generations 产物（PDF/图片/音频）注册进产出物面。"""

    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_genart_")
        self._env_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.ws = get_agent_workspace_dir("kai")
        self.ws.mkdir(parents=True)
        # generation 产物目录指进测试临时区（单一事实源常量的注入面）
        self.gen_dir = Path(self.tmp) / "generations"
        self.gen_dir.mkdir(parents=True, exist_ok=True)
        self._gen_patch = mock.patch(
            "neurova.llm.generators.runtime.GENERATION_OUTPUT_DIR", self.gen_dir
        )
        self._gen_patch.start()
        self.addCleanup(self._gen_patch.stop)
        self.pdf = self.gen_dir / "neurova-67c03017_0.pdf"
        self.pdf.write_bytes(b"%PDF-1.7 fake")

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_write_pdf_generations_result_registers_pdf_artifact(self):
        """write_pdf 无 path 形态：file_path 落 generations，须注册 kind=pdf。"""
        raw = json.dumps(
            {
                "bytes": 231125,
                "pages": 4,
                "file_name": self.pdf.name,
                "file_path": str(self.pdf),
                "download_url": f"/api/v1/generation/files/{self.pdf.name}",
            }
        )
        events = extract_tool_artifacts("write_pdf", raw, agent_id="kai", user_id="3")
        self.assertEqual(len(events), 1, "generations 产物必须注册（此前白名单拒收）")
        ev = events[0]
        self.assertEqual(ev["type"], "artifact")
        self.assertEqual(ev["kind"], "pdf")
        self.assertEqual(ev["name"], "neurova-67c03017_0.pdf")
        self.assertTrue(ev["artifact_id"])

    def test_registered_generation_artifact_owned_by_sender(self):
        """注册属主=轮次 sender；按名反查对他人不可见。"""
        raw = json.dumps({"file_path": str(self.pdf)})
        extract_tool_artifacts("write_pdf", raw, agent_id="kai", user_id="3")
        owned = find_artifacts_by_names([self.pdf.name], user_id="3")
        self.assertEqual(len(owned), 1)
        self.assertEqual(owned[0]["name"], self.pdf.name)
        self.assertEqual(find_artifacts_by_names([self.pdf.name], user_id="9"), [])


class TestReplyNameExtraction(unittest.TestCase):
    """回复正文点名产物的两种形态：反引号文件名 ＋ 生成文件 URL。"""

    def test_extracts_backtick_name_and_generation_url(self):
        reply = (
            "产物报告：\n- `Neurova记忆系统要点报告.md` — 完整结构化报告（8.3 kB），"
            "位于 data/kai/workspaces/\n- neurova-67c03017_0.pdf — 同内容 PDF 版，"
            "下载地址 /api/v1/generation/files/neurova-67c03017_0.pdf"
        )
        names = artifact_names_from_reply(reply)
        self.assertIn("Neurova记忆系统要点报告.md", names)
        self.assertIn("neurova-67c03017_0.pdf", names)

    def test_plain_words_and_versions_not_matched(self):
        self.assertEqual(artifact_names_from_reply("没有产物，见 3.5 节与 v1.2 说明。"), [])
        self.assertEqual(artifact_names_from_reply(""), [])
        self.assertEqual(artifact_names_from_reply(None), [])


class TestFindArtifactsByNames(unittest.TestCase):
    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_attach_")
        self._env_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.ws = get_agent_workspace_dir("kai")
        self.ws.mkdir(parents=True)
        self.md = self.ws / "报告.md"
        self.md.write_text("# 报告", encoding="utf-8")
        artifacts_api.register_artifact(str(self.md), agent_id="kai", user_id="3")

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_matches_by_exact_name_for_owner(self):
        found = find_artifacts_by_names(["报告.md", "不存在的.md"], user_id="3")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "报告.md")
        self.assertEqual(found[0]["type"], "artifact")

    def test_other_users_entry_not_visible(self):
        self.assertEqual(find_artifacts_by_names(["报告.md"], user_id="9"), [])

    def test_deleted_file_not_attached(self):
        info = next(iter(artifacts_api._artifacts_store.values()))
        Path(info["path"]).unlink()
        self.assertEqual(find_artifacts_by_names(["报告.md"], user_id="3"), [])


class TestMergeRoundArtifacts(unittest.TestCase):
    """merge_round_artifacts：tool_result 提取＋文档工件＋带挂，去重保序。"""

    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_merge_")
        self._env_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self.ws = get_agent_workspace_dir("kai")
        self.ws.mkdir(parents=True)
        self.md = self.ws / "报告.md"
        self.md.write_text("# 报告", encoding="utf-8")
        info = artifacts_api.register_artifact(str(self.md), agent_id="kai", user_id="3")
        self.known_id = info["artifact_id"]

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_dedupes_by_artifact_id_and_keeps_order(self):
        base = [
            {"type": "artifact", "artifact_id": self.known_id, "kind": "markdown",
             "name": "报告.md", "size": 6, "path": str(self.md)},
        ]
        doc_event = {"type": "artifact", "artifact_id": "doc1", "kind": "markdown",
                     "name": "任务_2026-11-14.md", "size": 10, "path": str(self.ws / "documents" / "任务_2026-11-14.md")}
        merged = merge_round_artifacts(base, reply="见 `报告.md`", user_id="3", doc_event=doc_event)
        ids = [e["artifact_id"] for e in merged]
        # base 在前、doc 次之；回复点名的 报告.md 与 base 同 id → 不重复
        self.assertEqual(ids, [self.known_id, "doc1"])

    def test_attaches_referenced_registered_artifact(self):
        merged = merge_round_artifacts([], reply="产物：`报告.md` 已就绪", user_id="3")
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["artifact_id"], self.known_id)

    def test_none_base_and_no_reply_yield_empty(self):
        self.assertEqual(merge_round_artifacts(None, reply="", user_id="3", doc_event=None), [])


if __name__ == "__main__":
    unittest.main()
