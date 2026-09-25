# -*- coding: utf-8 -*-
"""agent 工作区根的下游消费端必须认单源解析器。

覆盖两个漏网面：
- scripts/import_kai_to_neurova.py 的目标目录（原先拼字面 agent_workspaces，
  换根/桌面版布局后会把记忆灌进一个运行时根本不读的目录）；
- scripts/desktop/bundle_backend.py 预建的 stage/agent_workspaces（那是安装包
  布局而非运行时根，但目录名必须与解析器默认根同名，否则装完两套目录互看不见）。
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script(alias: str, rel_path: str):
    """按路径加载脚本；脚本不在仓库里（如被 gitignore 的一次性导入器）则跳过。"""
    script_path = REPO_ROOT / rel_path
    if not script_path.exists():
        pytest.skip(f"脚本不在工作树中: {rel_path}")
    spec = importlib.util.spec_from_file_location(alias, script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_kai_target_honors_injected_root(tmp_path, monkeypatch):
    script = _load_script("import_kai_env", "scripts/import_kai_to_neurova.py")
    monkeypatch.setenv("NEUROVA_AGENT_WORKSPACES_DIR", str(tmp_path / "wsRoot"))

    target = script.resolve_agent_memory_dir(tmp_path / "install", "kai")

    assert target == tmp_path / "wsRoot" / "kai" / "memory"


def test_import_kai_target_falls_back_to_given_root(tmp_path, monkeypatch):
    """脚本可指向另一套安装（--neurova-root）：未注入 env 时按该根拼。"""
    script = _load_script("import_kai_fallback", "scripts/import_kai_to_neurova.py")
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)

    target = script.resolve_agent_memory_dir(tmp_path / "install", "kai")

    assert target == tmp_path / "install" / "agent_workspaces" / "kai" / "memory"


def test_bundled_layout_name_matches_resolver_default(tmp_path, monkeypatch):
    bundle = _load_script("bundle_backend_layout", "scripts/desktop/bundle_backend.py")
    stage = tmp_path / "stage"
    stage.mkdir()
    monkeypatch.delenv("NEUROVA_AGENT_WORKSPACES_DIR", raising=False)

    from neurova.core.agent_workspaces import get_agent_workspaces_root

    bundle.ensure_runtime_dirs(stage)

    assert (stage / get_agent_workspaces_root().name / "default").is_dir()
