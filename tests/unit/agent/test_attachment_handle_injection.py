"""T-02：附件抽取不到文本时，必须给出**原因 + 句柄 + 可用原语**并留痕。

事故（2026-09-24 取证）：用户上传 `memory.db`，注入文案只有
`[用户上传了文件 memory.db（file），无法解析文本内容]` ——
没有 `file_id`（agent 无从取用）、没有失败原因、也没有"该用哪个原语"，
且该失败被显式排除在日志之外（`:1513` 的 `unsupported_format` 分支），
启动/运行日志里搜不到这一轮的任何痕迹。

本文件钉四件事：
1. 经生产装配点（`_inject_attachments_into_input`）驱动，失败正文携带
   `file_id` 与 `status`；
2. 失败一律可观测（日志）；
3. 文案点名的原语必须是**真实注册名**，或如实说"当前无可用抽取原语"；
4. 安全（D1）：注入文案不含任何绝对路径。
"""

from __future__ import annotations

import logging

import pytest

from neurova.agent.chat_pipeline import ChatPipeline

_DB_BYTES = b"SQLite format 3\x00" + b"\x00" * 4080


def _make_pipeline(read_bytes):
    """生产构造点替身：只替换字节读取咽喉（附件域唯一咽喉）。"""
    pipeline = object.__new__(ChatPipeline)
    pipeline._read_attachment_bytes = lambda file_id: read_bytes
    return pipeline


def _db_attachment():
    """附件元数据形态取自上传面：含一条**只在服务端**用的绝对路径。"""
    return {
        "file_id": "file_abc123",
        "filename": "memory.db",
        "file_type": "file",
        "mime_type": "application/octet-stream",
        "size": len(_DB_BYTES),
        "path": "/srv/neurova/data/storage/users/1/agents/default/sessions/default/file/memory.db",
    }


class TestUnparseableAttachmentNotice:
    def test_injectsFileIdAndStatus(self):
        pipeline = _make_pipeline(_DB_BYTES)
        text, vision_parts = pipeline._inject_attachments_into_input("看看有什么信息", [_db_attachment()])

        assert vision_parts == []
        assert "file_abc123" in text, f"句柄未进正文：{text}"
        assert "unsupported_format" in text, f"失败原因未进正文：{text}"

    def test_unsupportedFormat_isObservable(self, caplog):
        pipeline = _make_pipeline(_DB_BYTES)
        with caplog.at_level(logging.WARNING, logger="neurova.agent.chat_pipeline"):
            pipeline._inject_attachments_into_input("看看有什么信息", [_db_attachment()])

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "memory.db" in joined, f"抽取失败没有留痕：{joined!r}"
        assert "unsupported_format" in joined, f"留痕里没有失败原因：{joined!r}"

    def test_injectedTextCarriesNoAbsolutePath(self):
        """D1：附件的取用凭证只有 `file_id`，不得把服务端路径写进历史。"""
        pipeline = _make_pipeline(_DB_BYTES)
        text, _ = pipeline._inject_attachments_into_input("看看有什么信息", [_db_attachment()])

        for leak in ("/srv/", "data/storage", "agent_workspaces", "users/1"):
            assert leak not in text, f"注入文案泄露了路径片段 {leak!r}：{text}"


class TestPrimitiveHintHonesty:
    def test_namedPrimitive_isReallyRegistered(self):
        """点名的原语必须真实存在（防合成幻名进用户面文案）。"""
        from neurova.builtin_tools import _BUILTIN_SCHEMAS

        pipeline = _make_pipeline(_DB_BYTES)
        text, _ = pipeline._inject_attachments_into_input("读取", [_db_attachment()])

        import re

        named = re.findall(r"`([a-z_]+)`", text)
        for name in named:
            assert name in _BUILTIN_SCHEMAS, f"文案点名了未注册的原语 {name!r}：{text}"

    def test_saysWhetherAPrimitiveExists(self):
        """二选一：点名真名，或如实说"当前无可用抽取原语" —— 不写假路标。"""
        from neurova.attachment_parser import suggestExtractionPrimitive

        candidates = [
            ("memory.db", "file"),
            ("notes.txt", "text"),
            ("report.pdf", "document"),
            ("archive.zip", "file"),
        ]
        for filename, file_type in candidates:
            hint = suggestExtractionPrimitive(filename, file_type)
            assert hint is None or hint in __import__(
                "neurova.builtin_tools", fromlist=["_BUILTIN_SCHEMAS"]
            )._BUILTIN_SCHEMAS, f"{filename} 的建议原语 {hint!r} 不是真实注册名"


class TestReverseLock:
    def test_removingHandleComposition_dropsFileId(self, monkeypatch):
        """反向锁：把通知文案的单源构造换成旧占位串 ⇒ 句柄必然消失。"""
        from neurova.agent import chat_pipeline as _cp

        monkeypatch.setattr(
            _cp,
            "composeUnparseableAttachmentNotice",
            lambda **kwargs: f"[用户上传了文件 {kwargs['filename']}，无法解析文本内容]",
        )
        pipeline = _make_pipeline(_DB_BYTES)
        text, _ = pipeline._inject_attachments_into_input("看看", [_db_attachment()])

        assert "file_abc123" not in text, f"反向锁不成立，句柄仍在：{text}"
        assert "unsupported_format" not in text
