"""LLM 录制-回放测试夹具（对齐 DeepSeek Harness 的 llm-replay 思路）。

背景：Neurova 测试债中 C 类失败源自 mock 缺口——每次改 LLM 接口都要
手搓 chunk 结构 mock，且 mock 与真实契约对不上（见 test_execute_with_stream
根因复盘）。本夹具把"录一次真实调用 → 回放保证 chunk 契约"固化。

用法（unittest / pytest 通用，纯标准库，不 import neurova）：

    from tests.fixtures.llm_replay import LlmRecorder, ReplayLlmClient

    # 1) 录制：包装真实 client 消费一次流
    recorder = LlmRecorder(real_client)
    async for chunk in recorder.chat_stream_async([{"role": "user", "content": "hi"}]):
        ...
    recorder.save("tests/fixtures/llm_chunk_contract.json")   # 落盘脚本

    # 2) 回放：测试里注入替身，chunk 契约与录制完全一致
    script = LlmRecorder.load("tests/fixtures/llm_chunk_contract.json")
    fake = ReplayLlmClient(script)
    async for chunk in fake.chat_stream_async([{"role": "user", "content": "hi"}]):
        assert chunk.content == 真实录制内容  # 契约验证

    # strict=False：脚本耗尽时返回占位空 chunk（供"先跑通再补录"）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

SCRIPT_VERSION = 1
_EMPTY_RESULT = {"content": "", "role": "assistant", "model": "replay", "done": True, "usage": {}}


class LlmReplayError(RuntimeError):
    """回放契约错误（strict 模式）或脚本格式错误。"""


@dataclass
class ReplayChunk:
    """回放 chunk：duck-type 对齐 LLMResponse 的流式片段主要契约。"""

    content: str = ""
    role: str = "assistant"
    model: str = "replay"
    done: bool = False
    usage: Dict[str, Any] = field(default_factory=dict)
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "role": self.role,
            "model": self.model,
            "done": self.done,
            "usage": self.usage,
        }


def _fingerprint(messages: List[Dict[str, str]]) -> str:
    """调用指纹：结构变化即回放失败（strict 契约核心）。

    采用消息 JSON 规整哈希——mock 缺口类回归（schema 漂移）靠它暴露，
    而不是靠手写断言去猜 chunk 结构。
    """
    try:
        payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError) as e:  # noqa: BLE001 - 不可序列化消息
        raise LlmReplayError(f"消息指纹失败（不可 JSON 序列化）: {e}") from e
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


class LlmRecorder:
    """包装真实 LLM client：透传调用并记录 chunk 序列到脚本 JSON。"""

    def __init__(self, real_client: Any) -> None:
        self.real_client = real_client
        self.calls: List[Dict[str, Any]] = []

    async def chat_stream_async(self, messages: List[Dict[str, str]], **kwargs):
        """消费真实流，边透传边录制（async 形态）。"""
        fp = _fingerprint(messages)
        recorded = []
        async for chunk in self.real_client.chat_stream_async(messages, **kwargs):
            item = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            recorded.append(item)
            yield chunk
        self.calls.append({"fingerprint": fp, "messages": messages,
                           "type": "stream", "chunks": recorded})

    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[Any]:
        """消费真实流，边透传边录制（同步形态）。"""
        fp = _fingerprint(messages)
        recorded = []
        for chunk in self.real_client.chat_stream(messages, **kwargs):
            item = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            recorded.append(item)
            yield chunk
        self.calls.append({"fingerprint": fp, "messages": messages,
                           "type": "stream", "chunks": recorded})

    def save(self, path: Path | str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"version": SCRIPT_VERSION, "calls": self.calls},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def load(path: Path | str) -> Dict[str, Any]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != SCRIPT_VERSION:
            raise LlmReplayError(
                f"脚本版本不符: {data.get('version')} != {SCRIPT_VERSION}")
        calls = data.get("calls", [])
        if not isinstance(calls, list):
            raise LlmReplayError("脚本 calls 字段必须是列表")
        return data


class ReplayLlmClient:
    """按脚本回放的 LLM client 替身（接口对齐 llm_client.LlmClient）。

    - strict=True（默认）：消息指纹必须匹配脚本中的下一次调用，
      否则立即报错——这是"契约测试"而非"宽松桩"。
    - strict=False：脚本耗尽时回退占位空结果（用于先接通测试再补录）。
    """

    def __init__(self, script: Dict[str, Any], *, strict: bool = True) -> None:
        self.script = script
        self.strict = strict
        self._cursor = 0

    @property
    def remaining(self) -> int:
        return len(self.script.get("calls", [])) - self._cursor

    def _next_call(self, messages: List[Dict[str, str]], expected_type: str) -> Dict[str, Any]:
        calls = self.script.get("calls", [])
        if self._cursor >= len(calls):
            if self.strict:
                raise LlmReplayError(
                    f"脚本耗尽（已重放 {self._cursor}/{len(calls)} 条调用）——"
                    "请重新录制或使用 strict=False")
            return {"type": expected_type, "chunks": [], "fingerprint": "empty",
                    "messages": messages}
        call = calls[self._cursor]

        fp = _fingerprint(messages)
        expected_fp = call.get("fingerprint")
        if expected_fp is not None and fp != expected_fp:
            raise LlmReplayError(
                f"调用指纹不匹配（第 {self._cursor + 1} 条）："
                f"期望 {expected_fp} 实际 {fp} —— 消息结构或契约已漂移，"
                "请重新录制")
        if call.get("type", "stream") != expected_type:
            raise LlmReplayError(
                f"调用类型不匹配（第 {self._cursor + 1} 条）："
                f"期望 {call.get('type')} 实际 {expected_type}")
        self._cursor += 1
        return call

    @staticmethod
    def _chunks_of(call: Dict[str, Any]) -> List[ReplayChunk]:
        chunks = call.get("chunks") or []
        return [ReplayChunk(**_pick(c, ("content", "role", "model",
                                        "done", "usage")))
                if isinstance(c, dict) else ReplayChunk(content=str(c))
                for c in chunks]

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> ReplayChunk:
        """非流式调用：返回整个响应（重放为单 chunk 形态）。"""
        call = self._next_call(messages, "stream")
        chunks = self._chunks_of(call)
        # 契约：chat() 返回完整内容；录制的是流时取其末条或合并
        if not chunks:
            return ReplayChunk(**_pick(_EMPTY_RESULT, ("content", "role", "model",
                                                       "done", "usage")))
        merged = "".join(c.content for c in chunks)
        return ReplayChunk(content=merged or chunks[-1].content,
                           role=chunks[-1].role or "assistant",
                           model=chunks[-1].model or "replay",
                           done=True,
                           usage=chunks[-1].usage or {})

    def chat_stream(self, messages: List[Dict[str, str]], **kwargs) -> Iterator[ReplayChunk]:
        """同步流式回放。"""
        call = self._next_call(messages, "stream")
        chunks = self._chunks_of(call)
        if not chunks and not self.strict:
            yield ReplayChunk(done=True, content="")
            return
        yield from chunks

    async def chat_stream_async(self, messages: List[Dict[str, str]], **kwargs):
        """异步流式回放（与 multi_model_client 契约对齐）。"""
        call = self._next_call(messages, "stream")
        chunks = self._chunks_of(call)
        if not chunks and not self.strict:
            yield ReplayChunk(done=True, content="")
            return
        for chunk in chunks:
            yield chunk


def _pick(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {k: d.get(k) for k in keys if k in d}
