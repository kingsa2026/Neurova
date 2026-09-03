"""
测试：console 附件解析 helper（R-3 打通 file_ids）

背景根因（R-3）:
  console.ChatRequest 无 file_ids 字段，Pydantic 静默丢弃前端附件 ID，
  模型完全感知不到上传文件。

修复契约:
  1. attach_files(file_ids, user_id) 返回附件元数据列表
     （file_id/filename/file_type/mime_type/size/path，且仅属主可见）
  2. 无效/非属主 file_id 被跳过（不中断整轮对话）
  3. 结果是可 JSON 序列化的（供 metadata 落盘）
"""

import json

from neurova.api.endpoints import console


def test_attach_files_resolves_owned_files(monkeypatch):
    files_store = {}

    def fake_info(file_id, user_id):
        if file_id in files_store:
            meta = files_store[file_id]
            if meta["user_id"] == user_id:
                return dict(meta)
        return None

    import neurova.api.endpoints.files_api as files_api

    monkeypatch.setattr(files_api, "get_attachment_info", fake_info)

    files_store["f1"] = {
        "file_id": "f1",
        "filename": "报告.docx",
        "file_type": "document",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "size": 1024,
        "user_id": "u-1",
        "agent_id": "default",
        "path": "/tmp/report.docx",
    }
    files_store["f2"] = {
        "file_id": "f2",
        "filename": "pic.png",
        "file_type": "image",
        "mime_type": "image/png",
        "size": 2048,
        "user_id": "u-2",  # 另一用户 → 应被跳过
        "agent_id": "default",
        "path": "/tmp/pic.png",
    }

    # f1 属主，f2 非属主，f3 不存在
    result = console.attach_files(["f1", "f2", "f3"], "u-1")

    assert len(result) == 1
    assert result[0]["file_id"] == "f1"
    assert result[0]["file_type"] == "document"
    assert result[0]["filename"] == "报告.docx"


def test_attach_files_json_serializable(monkeypatch):
    def fake_info(file_id, user_id):
        return {
            "file_id": file_id,
            "filename": "x.txt",
            "file_type": "text",
            "mime_type": "text/plain",
            "size": 5,
            "user_id": user_id,
            "agent_id": "default",
            "path": "/tmp/x.txt",
        }

    import neurova.api.endpoints.files_api as files_api

    monkeypatch.setattr(files_api, "get_attachment_info", fake_info)

    result = console.attach_files(["a1"], "u-1")
    # 必须可 JSON 序列化（metadata 落盘依赖 _json_safe）
    json.dumps(result)
    assert json.loads(json.dumps(result))[0]["file_id"] == "a1"


def test_attach_files_empty_returns_empty_list():
    assert console.attach_files([], "u-1") == []
    assert console.attach_files(None, "u-1") == []
