# -*- coding: utf-8 -*-
"""A2：WAN 本地参考媒体百炼临时上传（台账 A2 第一波推进）。

契约事实源：dashscope-sdk-python `dashscope/utils/oss_utils.py`（官方实现）——
1. GET {api_root}/uploads?action=getPolicy&model=<m> → output{upload_host,
   upload_dir, oss_access_key_id, signature, policy, x_oss_object_acl,
   x_oss_forbid_overwrite}
2. POST upload_host multipart（OSSAccessKeyId/Signature/policy/key/
   x-oss-object-acl/x-oss-forbid-overwrite/success_action_status=200/
   x-oss-content-type/file）→ 200 → "oss://<key>"
3. 提交模型带 X-DashScope-OssResourceResolve: enable
本仓实现失败必须诚实抛错（不假提交、不静默回退公网 URL）。
"""
from __future__ import annotations

import pytest

from neurova.llm.generators.protocols import (
    ProtocolCredentials, dashscope_upload_file, submit_video,
)

pytestmark = pytest.mark.timeout(60)

CERT = {
    "request_id": "r0",
    "output": {
        "upload_host": "https://dashscope-file-mgr.oss-cn-beijing.aliyuncs.com",
        "upload_dir": "restful/data-proxy/abc",
        "oss_access_key_id": "AK",
        "signature": "SIG",
        "policy": "POL",
        "x_oss_object_acl": "private",
        "x_oss_forbid_overwrite": "true",
    },
}


class TestUploadFile:
    @pytest.mark.asyncio
    async def test_two_step_upload_returns_oss_ref(self, tmp_path, monkeypatch):
        got = tmp_path / "first.png"
        got.write_bytes(b"PNG")
        seen = {}

        async def fake_get(url, headers, timeout=30.0):
            seen["policy_url"] = url
            seen["auth"] = headers.get("Authorization")
            return 200, CERT

        async def fake_form(url, headers, fields, files, timeout=60.0):
            seen["host"] = url
            seen["key"] = fields["key"]
            seen["fields_ok"] = (fields["OSSAccessKeyId"] == "AK"
                                 and fields["policy"] == "POL"
                                 and fields["success_action_status"] == "200")
            seen["file"] = (files[0][0], files[0][1], files[0][2])
            return 200, {}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_get_json", fake_get)
        monkeypatch.setattr(p, "_post_form", fake_form)

        ref = await dashscope_upload_file("sk-x", "wan2.2-i2v", str(got),
                                          "https://dashscope.aliyuncs.com/api/v1")
        assert ref == f"oss://restful/data-proxy/abc/first.png"
        assert "action=getPolicy" in seen["policy_url"] and "model=wan2.2-i2v" in seen["policy_url"]
        assert seen["auth"] == "Bearer sk-x"
        assert seen["host"] == CERT["output"]["upload_host"] and seen["fields_ok"]
        assert seen["file"] == ("file", "first.png", b"PNG")

    @pytest.mark.asyncio
    async def test_policy_failure_raises_honest(self, tmp_path, monkeypatch):
        got = tmp_path / "f.png"; got.write_bytes(b"X")

        async def bad_get(url, headers, timeout=30.0):
            return 403, {"code": "AccessDenied", "message": "余额不足"}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_get_json", bad_get)
        with pytest.raises(RuntimeError, match="上传凭证"):
            await dashscope_upload_file("sk", "wanx", str(got), "https://d/api/v1")

    @pytest.mark.asyncio
    async def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            await dashscope_upload_file("sk", "wanx", "/no/such/file.png", "https://d/api/v1")


class TestSubmitVideoWanLocalUpload:
    @pytest.mark.asyncio
    async def test_local_ref_upgraded_to_oss_and_resolve_header(self, tmp_path, monkeypatch):
        frame = tmp_path / "a.png"; frame.write_bytes(b"F")
        captured = {}

        async def fake_upload(api_key, model, path, base_url):
            return "oss://dir/a.png"

        async def fake_post(url, headers, body, timeout=60.0):
            captured["headers"] = headers
            captured["body"] = body
            return 200, {"output": {"task_id": "t9"}}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "dashscope_upload_file", fake_upload)
        monkeypatch.setattr(p, "_post_json", fake_post)

        creds = ProtocolCredentials(api_key="k", base_url="https://d/api/v1",
                                    model="wan2.2-i2v", protocol="wan")
        out = await submit_video(creds, "p", ref_images=[str(frame)])
        assert out["task_id"] == "t9"
        assert captured["body"]["input"]["media"] == ["oss://dir/a.png"]
        assert captured["headers"].get("X-DashScope-OssResourceResolve") == "enable"

    @pytest.mark.asyncio
    async def test_public_url_skips_upload_no_header(self, monkeypatch):
        captured = {}

        async def fake_post(url, headers, body, timeout=60.0):
            captured["headers"] = headers; captured["body"] = body
            return 200, {"output": {"task_id": "t1"}}

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "_post_json", fake_post)
        creds = ProtocolCredentials(api_key="k", base_url="https://d/api/v1",
                                    model="wan", protocol="wan")
        await submit_video(creds, "p", ref_images=["https://cdn/x.png"])
        assert captured["body"]["input"]["media"] == ["https://cdn/x.png"]
        assert "X-DashScope-OssResourceResolve" not in captured["headers"]

    @pytest.mark.asyncio
    async def test_upload_failure_honest(self, tmp_path, monkeypatch):
        frame = tmp_path / "a.png"; frame.write_bytes(b"F")

        async def boom(api_key, model, path, base_url):
            raise RuntimeError("上传凭证获取失败: 403")

        from neurova.llm.generators import protocols as p
        monkeypatch.setattr(p, "dashscope_upload_file", boom)
        creds = ProtocolCredentials(api_key="k", base_url="https://d/api/v1",
                                    model="wan", protocol="wan")
        with pytest.raises(RuntimeError, match="403"):
            await submit_video(creds, "p", ref_images=[str(frame)])
