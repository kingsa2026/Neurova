"""console.py artifact SSE 事件提取 (extract_tool_artifacts / _extract_artifacts) 单元测试。

锁定契约：
- tool_result 完整文本中含 file_path/audio_path 的 dict
  → 注册 artifact 并返回 {"type": "artifact", ...} 事件列表；
- OutputRef 折叠引用（output_ref.path，tool_outputs/ 下的 ref_*.json）是
  上下文减负的**内部机制**，不是产出物——不注册（2026-11-14 产品口径：
  产出物面展示文档型成果，命名=任务内容+日期，而非工具内部引用）；
- 纯文本/无路径 dict → 空列表；
- env NEUROVA_ARTIFACT_EVENTS=0 → 空列表（逃生开关）；
- file_operation 读形态（含 content）不提取；写形态才提取。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neurova.api.endpoints import artifacts_api
from neurova.api.endpoints.artifacts_api import _extract_artifacts
from neurova.core.agent_workspaces import get_agent_workspace_dir


class TestExtractArtifacts(unittest.TestCase):
    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_art_")
        # 挂到 agent_workspaces 布局下以满足白名单
        self._root_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.ws = get_agent_workspace_dir("ag1")
        self.ws.mkdir(parents=True)
        self.md = self.ws / "report.md"
        self.md.write_text("# report", encoding="utf-8")

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_file_path_dict_extracts_artifact(self):
        raw = json.dumps({"success": True, "file_path": str(self.md)})
        events = _extract_artifacts(raw, agent_id="ag1", user_id="u1")
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["type"], "artifact")
        self.assertEqual(ev["kind"], "markdown")
        self.assertEqual(ev["name"], "report.md")
        self.assertTrue(ev["artifact_id"])

    def test_output_ref_folded_result_yields_no_artifact(self):
        """OutputRef 折叠引用不进产出物面。

        工具大输出折叠成 ref_*.json（tool_outputs/ 下）是上下文减负的内部
        机制——把它的落盘路径注册成 artifact，会让"本轮产出物"里出现
        ref_1794591986__file__read__e8ac.json 这类内部引用（2026-11-14
        kai 实测的产出物面污染）。产出物面应展示文档型成果。
        """
        out_dir = self.ws / "tool_outputs"
        out_dir.mkdir(exist_ok=True)
        ref_file = out_dir / "ref_1794591986_file__read_e8ac.json"
        ref_file.write_text("{}", encoding="utf-8")
        raw = json.dumps(
            {
                "success": True,
                "output_ref": {
                    "path": str(ref_file),
                    "size_bytes": 2,
                    "truncated": True,
                    "preview": "{}",
                },
                "note": "工具 file__read 输出超阈值，完整内容已落盘",
            }
        )
        self.assertEqual(_extract_artifacts(raw, agent_id="ag1", user_id="u1"), [])

    def test_tool_outputs_dir_file_path_yields_no_artifact(self):
        """即便路径经 file_path 字段给出，tool_outputs/ 下的引用文件也不算产出。"""
        out_dir = self.ws / "tool_outputs"
        out_dir.mkdir(exist_ok=True)
        ref_file = out_dir / "ref_123_file_read_abc.json"
        ref_file.write_text("{}", encoding="utf-8")
        raw = json.dumps({"success": True, "file_path": str(ref_file)})
        self.assertEqual(_extract_artifacts(raw, agent_id="ag1", user_id="u1"), [])

    def test_plain_text_returns_empty(self):
        self.assertEqual(_extract_artifacts("just text", agent_id="ag1", user_id="u1"), [])

    def test_no_path_dict_returns_empty(self):
        raw = json.dumps({"success": True, "stdout": "hello"})
        self.assertEqual(_extract_artifacts(raw, agent_id="ag1", user_id="u1"), [])

    def test_truncated_json_regex_fallback(self):
        raw = '{"success": true, "file_path": "' + str(self.md).replace("\\", "\\\\")
        events = _extract_artifacts(raw, agent_id="ag1", user_id="u1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "markdown")

    def test_audio_path_extracts_audio_kind(self):
        d = Path(tempfile.gettempdir()) / "neurova_tts"
        d.mkdir(parents=True, exist_ok=True)
        wav = d / "tts_evt.wav"
        wav.write_bytes(b"RIFFxxxx")
        raw = json.dumps({"success": True, "audio_path": str(wav)})
        events = _extract_artifacts(raw, agent_id="ag1", user_id="u1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "audio")

    def test_env_gate_disabled(self):
        raw = json.dumps({"success": True, "file_path": str(self.md)})
        with mock.patch.dict(os.environ, {"NEUROVA_ARTIFACT_EVENTS": "0"}):
            self.assertEqual(_extract_artifacts(raw, agent_id="ag1", user_id="u1"), [])

    def test_multiple_paths_multiple_events(self):
        d = Path(tempfile.gettempdir()) / "neurova_tts"
        d.mkdir(parents=True, exist_ok=True)
        wav = d / "tts_evt2.wav"
        wav.write_bytes(b"RIFFxxxx")
        raw = json.dumps({"file_path": str(self.md), "audio_path": str(wav)})
        events = _extract_artifacts(raw, agent_id="ag1", user_id="u1")
        self.assertEqual(len(events), 2)


class TestReadResultsAreNotArtifacts(unittest.TestCase):
    """读类结果不产 artifact（2026-09-08 产出物卡片前提契约）。

    file_operation 读取返回 {content, file_path}——file_path 是被读文件的
    回指而非本轮产出；写入返回 {success, file_path} 才是产出。
    误把读取当产出会让产出物卡片列出模型"看过"的文件（假产出）。
    """

    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_art_")
        self._root_patch = mock.patch.dict(
            os.environ, {"NEUROVA_AGENT_WORKSPACES_DIR": self.tmp}
        )
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.ws = get_agent_workspace_dir("ag1")
        self.ws.mkdir(parents=True)
        self.md = self.ws / "note.md"
        self.md.write_text("# note", encoding="utf-8")

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_file_operation_read_shape_yields_no_artifact(self):
        raw = json.dumps({"content": "# note", "file_path": str(self.md)})
        self.assertEqual(artifacts_api.extract_tool_artifacts("file_operation", raw, "ag1", "u1"), [])

    def test_file_operation_write_shape_yields_artifact(self):
        raw = json.dumps({"success": True, "file_path": str(self.md)})
        events = artifacts_api.extract_tool_artifacts("file_operation", raw, "ag1", "u1")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "note.md")

    def test_unknown_tool_still_extracts(self):
        """非 file_operation 工具的 file_path（如 run_code 产出）保持提取。"""
        raw = json.dumps({"success": True, "file_path": str(self.md)})
        events = artifacts_api.extract_tool_artifacts("run_code", raw, "ag1", "u1")
        self.assertEqual(len(events), 1)

    def test_unparseable_result_falls_through_to_extract(self):
        """非 JSON 文本不判读——按原通道提取（正则兜底兜半截 JSON）。"""
        raw = '{"file_path": "' + str(self.md).replace("\\", "\\\\")
        events = artifacts_api.extract_tool_artifacts("file_operation", raw, "ag1", "u1")
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()
