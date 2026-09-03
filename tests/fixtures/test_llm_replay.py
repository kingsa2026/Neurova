"""LLM 录制-回放夹具自身回归测试（防夹具腐化）。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from tests.fixtures.llm_replay import LlmReplayError, LlmRecorder, ReplayLlmClient


class _RealClient:
    """录制侧假真实 client。"""

    async def chat_stream_async(self, messages, **kwargs):
        for text in ("你好", "，世界"):
            yield _Chunk(text)


class _Chunk:
    def __init__(self, content: str):
        self.content = content
        self.role = "assistant"
        self.model = "real"
        self.done = False
        self.usage = {}

    def to_dict(self):
        return {"content": self.content, "role": self.role,
                "model": self.model, "done": self.done, "usage": self.usage}


_MSG = [{"role": "user", "content": "hi"}]


class TestLlmRecorder(unittest.TestCase):
    def test_record_save_load_roundtrip(self):
        recorder = LlmRecorder(_RealClient())
        consumed = []

        async def _run():
            async for chunk in recorder.chat_stream_async(_MSG):
                consumed.append(chunk.content)

        asyncio.run(_run())
        self.assertEqual(consumed, ["你好", "，世界"])
        self.assertEqual(len(recorder.calls), 1)

        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "script.json"
            recorder.save(path)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["version"], 1)
            loaded = LlmRecorder.load(path)
            self.assertEqual(loaded["calls"][0]["chunks"], data["calls"][0]["chunks"])

    def test_load_rejects_wrong_version(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text(json.dumps({"version": 99, "calls": []}), encoding="utf-8")
            with self.assertRaises(LlmReplayError):
                LlmRecorder.load(path)


class TestReplayLlmClient(unittest.TestCase):
    def _recorder_script(self):
        recorder = LlmRecorder(_RealClient())

        async def _record():
            async for _ in recorder.chat_stream_async(_MSG):
                pass

        asyncio.run(_record())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "s.json"
            recorder.save(path)
            return LlmRecorder.load(path)

    def test_replay_matches_recorded_contract(self):
        script = self._recorder_script()
        fake = ReplayLlmClient(script)

        async def _replay():
            return [c.content async for c in fake.chat_stream_async(_MSG)]

        self.assertEqual(asyncio.run(_replay()), ["你好", "，世界"])

    def test_fingerprint_drift_raises_in_strict_mode(self):
        script = self._recorder_script()
        fake = ReplayLlmClient(script)
        with self.assertRaises(LlmReplayError):
            asyncio.run(
                _consume(fake.chat_stream_async([{"role": "user", "content": "OTHER"}]))
            )

    def test_exhaustion_falls_back_in_non_strict_mode(self):
        script = self._recorder_script()
        fake = ReplayLlmClient(script, strict=False)

        async def _exhaust_and_call_again():
            async for _ in fake.chat_stream_async(_MSG):
                pass
            return [c.content async for c in fake.chat_stream_async(_MSG)]

        self.assertEqual(asyncio.run(_exhaust_and_call_again()), [""])

    def test_chat_merges_stream_to_single_response(self):
        script = self._recorder_script()
        fake = ReplayLlmClient(script)
        resp = fake.chat(_MSG)
        self.assertEqual(resp.content, "你好，世界")
        self.assertTrue(resp.done)


async def _consume(agen):
    return [c async for c in agen]


if __name__ == "__main__":
    unittest.main()
