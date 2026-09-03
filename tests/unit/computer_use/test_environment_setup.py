"""电脑控制 / 浏览器自动化 后端环境集成测试

验证 Neurova 的 Computer Use 能力栈（Pillow 截图、pyautogui 鼠标键盘、
Playwright 浏览器）在当前解释器中可用，且相关检测/安装机制正确。
"""

import importlib.util
import inspect
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"


def _spec(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


class TestDependencyDeclaration:
    """依赖清单必须声明 Computer Use 能力栈"""

    def test_requirements_declare_computer_use_stack(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        for pkg in ("Pillow", "pyautogui", "playwright"):
            pattern = rf"(?im)^\s*{pkg}\s*[><=~^]"
            assert re.search(pattern, text), f"requirements.txt 缺少 {pkg}"


class TestHealthCheckIntegration:
    """start.py --check 的依赖体检应覆盖 Computer Use 能力栈"""

    def test_check_dependencies_reports_computer_use(self):
        from scripts.health_check import check_dependencies

        deps = check_dependencies()
        for key in ("PIL", "pyautogui", "playwright"):
            assert key in deps, f"check_dependencies 未覆盖 {key}"
            # 报告结果必须与真实探测一致
            assert deps[key] == _spec(key), f"{key} 状态与实际不符"

    def test_reported_state_matches_interpreter(self):
        from scripts.health_check import check_dependencies

        deps = check_dependencies()
        assert deps["fastapi"] is True


class TestInterpreterConsistency:
    """桌面操作必须走进程内实现：

    1) 不允许裸 'python' 起子进程 —— 可能指向另一个无依赖的解释器
       （本机实测：venv 为 3.12 装全套依赖，PATH 上却是 3.15alpha）
    2) 不允许 shell=True / 拼 -c 源码 —— 外部输入拼源码是注入向量，
       shlex.quote 只防 shell 语义防不住 Python 语法层
    """

    def test_no_bare_python_subprocess(self):
        import neurova.computer_use as cu

        src = inspect.getsource(cu)
        assert '"python"' not in src, "存在裸 'python' 子进程调用"

    def test_no_shell_true_or_dash_c_interpolation(self):
        import neurova.computer_use as cu

        src = inspect.getsource(cu)
        assert "shell=True" not in src
        # 禁止把外部输入拼进 python -c 源码（shlex.quote 防不住语法层注入）；
        # ["cmd.exe","/c",cmd] / ["/bin/sh","-c",cmd] 这类固定解释器 argv 形式不受限
        assert 'executable, "-c"' not in src
        assert "'-c', code" not in src

    def test_desktop_ops_are_in_process(self):
        from neurova.computer_use import ComputerUseManager

        assert "import pyautogui" in inspect.getsource(ComputerUseManager.click)
        assert "ImageGrab" in inspect.getsource(ComputerUseManager.screenshot)

    def test_screenshot_prefers_in_process_pil(self):
        if not _spec("PIL"):
            return  # 未安装环境下跳过能力断言（一致性由其他测试覆盖）
        from neurova.computer_use import reset_computer_use_manager, get_computer_use_manager

        reset_computer_use_manager()
        manager = get_computer_use_manager()
        assert manager._screenshot_backend == "PIL"


class TestBrowserBackendAvailability:
    """装好 playwright 后 BrowserManager 应自动注册 playwright 后端"""

    def test_flag_matches_environment(self):
        from neurova.computer_use import browser_manager

        assert browser_manager.HAS_PLAYWRIGHT == _spec("playwright")

    def test_status_lists_playwright_when_available(self):
        from neurova.computer_use.browser_manager import BrowserManager

        status = BrowserManager().get_status()
        if _spec("playwright"):
            assert "playwright" in status["available_backends"]
            assert status["has_playwright"] is True


class TestChromiumProbe:
    """setup 脚本需能探测 Chromium 二进制是否就绪"""

    def test_probe_functions_exist_and_run(self):
        import scripts.setup_computer_use as setup_cu

        caps = setup_cu.probe_capabilities()
        assert {"pillow", "pyautogui", "playwright", "chromium"} <= set(caps.keys())
        assert caps["pillow"] == _spec("PIL")
        assert caps["playwright"] == _spec("playwright")
        # chromium 探测返回布尔且不抛异常
        assert isinstance(caps["chromium"], bool)

    def test_missing_packages_listed_by_checker(self):
        import scripts.setup_computer_use as setup_cu

        missing = setup_cu.missing_packages()
        assert isinstance(missing, list)
        # 一致性：探测为 False 的包必须在缺失列表里
        caps = setup_cu.probe_capabilities()
        for pkg in ("pillow", "pyautogui", "playwright"):
            if not caps[pkg]:
                assert pkg in missing
