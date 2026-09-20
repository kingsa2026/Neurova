"""
打包脚本 agent_workspaces 预创建回归（安装版 2026-09-04 启动崩溃第二道防线）

根因：bundle_backend.py 只复制 neurova/models/config/start_server.py，
从不创建 agent_workspaces/。干净安装机上该目录天然不存在，
后端 _load_saved_agents 曾因 os.listdir 缺目录直接崩（已由
test_load_saved_agents_missing_dir.py 根治启动崩溃）。

本测试锁定打包侧不变量：bundle 结束后暂存区必须有
agent_workspaces/default/，消除"后端运行时自建目录"这个单点依赖。
"""
import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_BUNDLE = _REPO / "scripts" / "desktop" / "bundle_backend.py"


def _load_bundle_module():
    spec = importlib.util.spec_from_file_location("bundle_backend", _BUNDLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBundleCreatesWorkspaces:
    def test_ensure_runtime_dirs_creates_default_workspace(self, tmp_path):
        mod = _load_bundle_module()
        stage = tmp_path / "backend"
        stage.mkdir()
        mod.ensure_runtime_dirs(stage)
        assert (stage / "agent_workspaces" / "default").is_dir()

    def test_ensure_runtime_dirs_idempotent(self, tmp_path):
        mod = _load_bundle_module()
        stage = tmp_path / "backend"
        stage.mkdir()
        mod.ensure_runtime_dirs(stage)
        mod.ensure_runtime_dirs(stage)  # 幂等：重复调用不抛异常
        assert (stage / "agent_workspaces" / "default").is_dir()

    def test_ensure_runtime_dirs_missing_stage_raises(self, tmp_path):
        mod = _load_bundle_module()
        with pytest.raises(Exception):
            mod.ensure_runtime_dirs(tmp_path / "nonexistent")

    def test_main_wires_ensure_runtime_dirs(self, tmp_path, monkeypatch):
        """main() 必须接线 ensure_runtime_dirs（防实现漂移）。"""
        mod = _load_bundle_module()
        called = []
        monkeypatch.setattr(mod, "ensure_runtime_dirs", lambda stage: called.append(stage))
        # main 的其他步骤依赖真实仓库树，直接 stub 全部重活
        monkeypatch.setattr(mod, "copy_tree_light", lambda *a, **k: None)
        monkeypatch.setattr(mod, "STAGE", tmp_path / "stage", raising=False)
        monkeypatch.setattr(mod, "MANIFEST", tmp_path / "stage" / "MANIFEST.json", raising=False)
        monkeypatch.setattr("sys.argv", ["bundle_backend.py"])
        rc = mod.main()
        assert rc == 0
        assert len(called) == 1
        assert called[0] == tmp_path / "stage"

    def test_route_b_never_packages_python_runtime(self):
        """路线 B 契约：bundle_backend.py 不得再打包 Python/Node 运行时
        （体积红线由 package_installer_zip.validate_lean_backend 兜底）。"""
        src = _BUNDLE.read_text(encoding="utf-8")
        for dead in ("ensure_standalone_python", "copy_venv_site_packages"):
            assert dead not in src, f"{dead} 应随路线 B 删除"

    def test_main_purges_stale_python_stage(self, tmp_path, monkeypatch):
        """main() 必须清理暂存区残留 python/（上一轮路线 A 的遗留）。"""
        mod = _load_bundle_module()
        monkeypatch.setattr(mod, "copy_tree_light", lambda *a, **k: None)
        monkeypatch.setattr(mod, "ensure_runtime_dirs", lambda stage: None)
        monkeypatch.setattr(mod, "STAGE", tmp_path / "stage", raising=False)
        monkeypatch.setattr(mod, "MANIFEST", tmp_path / "stage" / "MANIFEST.json", raising=False)
        monkeypatch.setattr("sys.argv", ["bundle_backend.py"])
        (tmp_path / "stage" / "python" / "python.exe").parent.mkdir(parents=True)
        (tmp_path / "stage" / "python" / "python.exe").write_bytes(b"x")
        assert mod.main() == 0
        assert not (tmp_path / "stage" / "python").exists()
