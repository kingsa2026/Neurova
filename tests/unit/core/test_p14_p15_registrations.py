# -*- coding: utf-8 -*-
"""DATA-P1-4 / DATA-P1-5（审计 2026-09-11）回归。

- P1-4: is_model_available 存在性 + 非空双判（0 字节截断文件不再通过）；
- P1-5: MoE 索引状态作用域键含 agent_id（同 persist 库路径的多 agent 不再互踩）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from neurova import mem_core as mc
from neurova.tts.model_downloader import ModelDownloader, MODEL_REGISTRY


@pytest.fixture()
def downloader(tmp_path: Path) -> ModelDownloader:
    return ModelDownloader(base_dir=str(tmp_path))


def _touch(model_dir: Path, name: str, size: int = 10) -> None:
    f = model_dir / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"x" * size)


@pytest.mark.parametrize("model_name", list(MODEL_REGISTRY.keys())[:1])
def test_zero_byte_required_file_fails_availability(downloader, tmp_path, model_name):
    """required_files 任一为 0 字节 → 不可用（触发重下自愈）。"""
    d = downloader.get_model_dir(model_name)
    for f in MODEL_REGISTRY[model_name]["required_files"]:
        _touch(d, f, size=0)
    assert downloader.is_model_available(model_name) is False

    for f in MODEL_REGISTRY[model_name]["required_files"]:
        _touch(d, f, size=64)
    assert downloader.is_model_available(model_name) is True


def test_moe_scope_key_includes_agent_id():
    class _Mgr:
        _persist_db_path = "/x/neurova_memories_persist.db"

    class _Cfg:
        agent_id = "agent-b"

    class _SysA:
        agent_id = "agent-a"

        class config:
            agent_id = "agent-a"

        memory_manager = _Mgr()

    class _SysB:
        config = _Cfg

        class memory_manager:
            _persist_db_path = "/x/neurova_memories_persist.db"

    ka = mc._moe_scope_key(_SysA())
    kb = mc._moe_scope_key(_SysB())
    assert "agent-a" in ka
    assert "agent-b" in kb
    assert ka != kb, "同 persist 库路径的两个 agent 必须得到不同作用域键"
