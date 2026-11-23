# -*- coding: utf-8 -*-
"""外部数据集转换器落点判据：会话文件必须落
`<数据根>/training_datasets/<source>/sessions/`，不得在数据根顶层建目录。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "training" / "convert_external_datasets.py"


@pytest.fixture()
def converter():
    spec = importlib.util.spec_from_file_location("convert_external_datasets", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_write_session_lands_under_training_datasets(tmp_path, converter):
    count = converter._writeSession(
        tmp_path, "agentcompany", "s1",
        [{"role": "user", "content": "hello", "timestamp": "t"}],
        {"source": "theagentcompany"},
    )
    assert count == 1
    target = tmp_path / "training_datasets" / "agentcompany" / "sessions" / "session_s1.json"
    assert target.exists(), "转换产物必须落 training_datasets 命名空间"
    assert not (tmp_path / "agentcompany").exists(), "不得再在数据根顶层建 source 目录"
