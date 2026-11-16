# -*- coding: utf-8 -*-
"""S2→S1 移交悬空 R6：install_from_zip 落盘名随机化（教义第 1 条根因修复）。

skill_pool_api.install_from_zip 曾用 `file.filename` 直接拼 zip_path
（`os.path.join(tmpdir, file.filename)`）——文件名由客户端任意控制：
1. 路径逃逸面：filename 含 `..` / 路径分隔符时 os.path.join 让落盘写出
   tmpdir（写进服务端任意可写路径）；
2. 可预测路径面：同名并发上传互踩、落盘路径可被预先猜测。

修复判据：服务端落盘名一律 uuid 随机（对照同文件 install-from-url 与
用户私库创建技能的 uuid sid 用法），客户端 filename 只允许进 skill_id
命名（且经 basename 提取，不得携带路径成分）。
"""
import asyncio
import io
import os
from unittest.mock import MagicMock

import pytest
from fastapi import UploadFile

import neurova.api.endpoints.skill_pool_api as skillPoolModule


@pytest.fixture()
def capturedService(monkeypatch):
    """装桩 _pool_service，捕获 install_skill 收到的 skill_path / skill_id。"""
    service = MagicMock()
    service.install_skill.return_value = {"success": True, "skill_id": "x"}
    monkeypatch.setattr(skillPoolModule, "_pool_service", lambda *a, **kw: service)
    return service


def _upload(filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(b"PK\x03\x04 zip-bytes"), filename=filename)


def _runInstall(filename: str, capturedService):
    current_user = {"user_id": "u1"}
    asyncio.run(skillPoolModule.install_from_zip(
        file=_upload(filename), target="", current_user=current_user))
    capturedService.install_skill.assert_called_once()
    return capturedService.install_skill.call_args.kwargs


def testZipDiskNameIsRandomizedNotClientControlled(capturedService):
    """普通上传名：落盘路径不得携带客户端提供的文件名。"""
    kwargs = _runInstall("evil-name.zip", capturedService)
    skill_path = str(kwargs["skill_path"])
    disk_name = os.path.basename(skill_path)
    assert disk_name != "evil-name.zip", "落盘名仍是客户端可控的 file.filename"
    assert "evil-name" not in skill_path, f"落盘路径含客户端可控成分: {skill_path}"


def testZipPathTraversalInFilenameCannotEscapeTmpdir(capturedService):
    """恶意上传名（`..` + 路径分隔符）：落盘路径不得携带路径跳转成分。"""
    kwargs = _runInstall("../../evil.zip", capturedService)
    skill_path = str(kwargs["skill_path"])
    assert ".." not in skill_path, f"落盘路径未消除路径逃逸面: {skill_path}"
    assert os.path.basename(skill_path) != "evil.zip"


def testZipSkillIdNamingCarriesNoPathComponents(capturedService):
    """skill_id 命名来自 filename，但不得把路径成分带进技能身份。"""
    kwargs = _runInstall("../../evil.zip", capturedService)
    skill_id = str(kwargs.get("skill_id") or "")
    assert "/" not in skill_id and "\\" not in skill_id and ".." not in skill_id
