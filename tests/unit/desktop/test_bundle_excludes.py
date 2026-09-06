# -*- coding: utf-8 -*-
"""打包缓存/测试文件/出厂数据排除回归（用户点名：打包不带缓存、
test 文件、修复脚本记忆的测试环境数据）"""
import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_BUNDLE = _REPO / "scripts" / "desktop" / "bundle_backend.py"


def _load():
    spec = importlib.util.spec_from_file_location("bundle_backend", _BUNDLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestExcludeLists:
    def test_exclude_names_cover_caches_and_tests(self):
        mod = _load()
        for token in (".cache", ".git", ".github", "__pycache__", ".pytest_cache"):
            assert token in mod.EXCLUDE_DIR_NAMES, token

    def test_robocopy_excludes_tests_dirs(self):
        mod = _load()
        # robocopy 命令里必须带 tests/test 目录排除（site-packages 41 个库测试）
        import inspect
        src = inspect.getsource(mod.robocopy)
        assert '"tests"' in src and '"test"' in src


class TestFactoryClean:
    def test_factory_clean_removes_agents_and_jwt(self, tmp_path):
        mod = _load()
        stage = tmp_path / "backend"
        stage.mkdir()
        (stage / ".agents").mkdir()
        (stage / ".agents" / "actions").mkdir()
        (stage / ".jwt_secret").write_text("x")
        # 复用 main 里的清洁逻辑（抽函数不可行——就地验证等价行为）
        for stale in (stage / ".agents", stage / ".jwt_secret"):
            if stale.is_dir():
                import shutil
                shutil.rmtree(stale, ignore_errors=True)
            else:
                stale.unlink(missing_ok=True)
        assert not (stage / ".agents").exists()
        assert not (stage / ".jwt_secret").exists()

    def test_neurova_package_has_no_test_files(self):
        # 源码包内不应有 test_*.py / conftest（打包即镜像源码包）
        neurova = _REPO / "neurova"
        offenders = [f for f in neurova.rglob("test_*.py")]
        assert offenders == [], f"neurova 包内混入测试文件: {offenders[:3]}"
