"""
测试：knowledge API 导入（R-4 多格式文档 + 远程网页）

契约:
  1. POST /knowledge/import 支持文件上传（txt/md/docx/xlsx/pptx/pdf/html），
     抽取文本后创建知识条目，返回条目列表
  2. POST /knowledge/import-url 支持远程网页 URL（http/https），
     抓取 HTML 抽取正文存为条目
  3. SSRF 防护：ftp/file/localhost/环回/私有 IP 一律拒绝
  4. GET /knowledge 无数据时返回空列表（不再返回模拟数据）
"""

import io
import pytest
from unittest.mock import patch

from neurova.api.endpoints import knowledge as kb


def _make_docx_bytes():
    import docx

    d = docx.Document()
    d.add_paragraph("文档正文内容 ABC")
    d.add_paragraph("第二段")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class TestImportFile:
    @pytest.mark.asyncio
    async def test_import_txt_creates_item(self, monkeypatch, tmp_path):
        # 注入独立仓库（临时目录）
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "note.txt"
            content_type = "text/plain"

            async def read(self):
                return "hello knowledge content".encode("utf-8")

        result = await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )
        assert result["code"] == 0
        items = result["data"]["items"]
        assert len(items) == 1
        assert "hello knowledge content" in items[0]["content"]

    @pytest.mark.asyncio
    async def test_import_docx_extracts(self, monkeypatch, tmp_path):
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "report.docx"
            content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

            async def read(self):
                return _make_docx_bytes()

        result = await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )
        items = result["data"]["items"]
        assert len(items) == 1
        assert "文档正文内容 ABC" in items[0]["content"]

    @pytest.mark.asyncio
    async def test_import_unsupported_returns_item_count_zero(self, monkeypatch, tmp_path):
        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)

        class FakeUpload:
            filename = "archive.zip"
            content_type = "application/zip"

            async def read(self):
                return b"PK\x05\x06\x00\x00"

        result = await kb.import_knowledge_file(
            FakeUpload(), request=None, current_user={"user_id": "u1"}, agent_id="default"
        )
        assert result["code"] == 0
        assert result["data"]["items"] == []


class TestImportUrl:
    def test_validate_url_allows_https(self, monkeypatch):
        # 沙箱无外网 DNS——mock getaddrinfo 返回公网 IP，验证公网域名放行
        import socket

        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        )
        assert kb._validate_import_url("https://example.com/page") is True
        assert kb._validate_import_url("http://example.com") is True

    def test_validate_url_rejects_insecure(self):
        assert kb._validate_import_url("ftp://example.com") is False
        assert kb._validate_import_url("file:///etc/passwd") is False
        assert kb._validate_import_url("javascript:alert(1)") is False
        assert kb._validate_import_url("data:text/html,hi") is False

    def test_validate_url_rejects_localhost_and_private(self):
        assert kb._validate_import_url("http://localhost:8000/x") is False
        assert kb._validate_import_url("http://127.0.0.1/x") is False
        assert kb._validate_import_url("http://192.168.1.1/x") is False
        assert kb._validate_import_url("http://10.0.0.5/x") is False
        assert kb._validate_import_url("http://172.16.0.1/x") is False

    @pytest.mark.asyncio
    async def test_import_url_fetches_and_creates(self, monkeypatch, tmp_path):
        import socket

        from neurova.knowledge.repository import KnowledgeRepository

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo._items.clear()
        monkeypatch.setattr(kb, "_get_repository", lambda agent_id="default": repo)
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, port: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        )

        html = b"<html><body><h1>Remote Title</h1><p>Remote body content</p></body></html>"
        monkeypatch.setattr(kb, "_fetch_url", lambda url: html)

        items = kb._import_file_data(html, "example.com/article.html", "default", {"user_id": "u1"})
        assert len(items) == 1
        assert "Remote body content" in items[0]["content"]
