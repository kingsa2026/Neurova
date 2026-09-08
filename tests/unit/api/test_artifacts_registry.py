"""artifact 注册服务单元测试。

锁定契约：
- register_artifact：路径解析 + kind 映射 + 同路径幂等（sha1 去重）；
- 归属：user_id/agent_id 记录，非属主 404（_get_owned_artifact 语义）；
- 读取白名单：工作区根（_WORKSPACE_ROOT）内路径放行；
  %TEMP%/neurova_tts/（TTS 音频）放行；白名单外路径拒绝注册。
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neurova.api.endpoints import artifacts_api


class TestArtifactKindMapping(unittest.TestCase):
    def test_markdown_html_image_audio_text(self):
        cases = [
            ("report.md", "markdown"),
            ("page.HTML", "html"),
            ("shot.png", "image"),
            ("pic.svg", "image"),
            ("tts.wav", "audio"),
            ("tts.mp3", "audio"),
            ("data.json", "text"),
            ("notes.txt", "text"),
            ("bin.bin", "text"),
        ]
        for name, expected in cases:
            self.assertEqual(artifacts_api._artifact_kind(name), expected, name)


class TestRegisterArtifact(unittest.TestCase):
    def setUp(self):
        artifacts_api._artifacts_store.clear()
        self.tmp = tempfile.mkdtemp(prefix="nr_art_")
        self._root_patch = mock.patch.object(artifacts_api, "_WORKSPACE_ROOT", Path(self.tmp))
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.ws = Path(self.tmp) / "ag1"
        self.ws.mkdir(parents=True, exist_ok=True)
        self.md_path = self.ws / "report.md"
        self.md_path.write_text("# hello", encoding="utf-8")

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_register_returns_metadata(self):
        art = artifacts_api.register_artifact(
            str(self.md_path), agent_id="ag1", user_id="u1"
        )
        self.assertTrue(art["artifact_id"])
        self.assertEqual(art["kind"], "markdown")
        self.assertEqual(art["name"], "report.md")
        self.assertEqual(art["agent_id"], "ag1")
        self.assertEqual(art["user_id"], "u1")
        self.assertEqual(art["size"], 7)
        # 同路径幂等：再次注册返回同一 id
        art2 = artifacts_api.register_artifact(str(self.md_path), "ag1", "u1")
        self.assertEqual(art["artifact_id"], art2["artifact_id"])

    def test_register_outside_allowed_roots_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            p = Path(outside) / "evil.md"
            p.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                artifacts_api.register_artifact(str(p), "ag1", "u1")

    def test_register_tts_tempdir_allowed(self):
        d = Path(tempfile.gettempdir()) / "neurova_tts"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "tts_test.wav"
        p.write_bytes(b"RIFFxxxx")
        art = artifacts_api.register_artifact(str(p), "ag1", "u1")
        self.assertEqual(art["kind"], "audio")

    def test_missing_file_rejected(self):
        with self.assertRaises(ValueError):
            artifacts_api.register_artifact(
                str(self.ws / "nope.md"), "ag1", "u1"
            )


class TestArtifactEndpointAuth(unittest.TestCase):
    """端点级归属校验（IDOR 防护语义）."""

    def setUp(self):
        artifacts_api._artifacts_store.clear()

    def tearDown(self):
        artifacts_api._artifacts_store.clear()

    def test_get_owned_artifact_404_for_non_owner(self):
        artifacts_api._artifacts_store["a1"] = {
            "artifact_id": "a1",
            "user_id": "owner",
            "path": "/tmp/x.md",
        }
        with self.assertRaises(Exception):
            artifacts_api._get_owned_artifact("a1", {"user_id": "other"})

    def test_get_owned_artifact_ok_for_owner(self):
        artifacts_api._artifacts_store["a1"] = {
            "artifact_id": "a1",
            "user_id": "owner",
            "path": "/tmp/x.md",
        }
        info = artifacts_api._get_owned_artifact("a1", {"user_id": "owner"})
        self.assertEqual(info["artifact_id"], "a1")


if __name__ == "__main__":
    unittest.main()
