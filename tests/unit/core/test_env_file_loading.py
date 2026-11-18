"""
.env 装配纪律守卫（移动端配对 ws_url 复发事故的根修判据）。

背景：NEUROVA_ADVERTISED_BASE_URL 只在 `app.run()` 里经 load_dotenv 装配，
而标准启动器 `start.py --backend` 走 `start_server.py`，后者从未加载 .env——
于是任何一次经 start.py 的重启都会把对外通告打回 ws://（80 口被 nginx 301），
鸿蒙 ohos websocket 握手必败（lws reason 46），移动端聊天空回复。
本档钉两件事：
  1. `config.loadEnvFile()` 功能可用（显式路径加载 .env 进 os.environ）；
  2. 两个进程入口（start_server.py / app.run）都必须经 loadEnvFile 装配。
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from neurova.core import config  # noqa: E402


def test_loadEnvFile_loads_explicit_path_into_environ(tmp_path, monkeypatch):
    """loadEnvFile(显式路径) 应把 .env 键值装入 os.environ（返回 True）。"""
    env_file = tmp_path / ".env"
    env_file.write_text("NEUROVA_ADVERTISED_BASE_URL=https://www.example.top\n", encoding="utf-8")
    probe_key = "NEUROVA_ADVERTISED_BASE_URL"
    monkeypatch.delenv(probe_key, raising=False)
    try:
        loaded = config.loadEnvFile(env_file)
        assert loaded is True
        assert os.environ.get(probe_key) == "https://www.example.top"
    finally:
        os.environ.pop(probe_key, None)


def test_loadEnvFile_missing_file_is_fail_soft(tmp_path):
    """路径不存在时不得抛异常（返回 False），入口装配失败不能炸启动。"""
    assert config.loadEnvFile(tmp_path / "no_such.env") is False


@pytest.mark.parametrize(
    "entry_relative, snippet",
    [
        ("start_server.py", "loadEnvFile("),
        ("neurova/api/app.py", "loadEnvFile("),
    ],
)
def test_process_entrypoints_load_env_file(entry_relative, snippet):
    """两个后端进程入口的源码都必须调用 loadEnvFile（防止再次绕过 .env）。"""
    source = (REPO_ROOT / entry_relative).read_text(encoding="utf-8")
    assert snippet in source, f"{entry_relative} 缺少 loadEnvFile 装配点"
