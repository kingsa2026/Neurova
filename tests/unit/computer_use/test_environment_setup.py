"""电脑控制 / 浏览器自动化 后端环境集成测试

验证 Neurova 的 Computer Use 能力栈（Pillow 截图、pyautogui 鼠标键盘、
Playwright 浏览器）在当前解释器中可用，且相关检测/安装机制正确。
"""

import importlib.util
import inspect
import re
import sys
from pathlib import Path

import pytest

from scripts.health_check import PROBE_TIMEOUT_SECONDS

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"
_HEALTH_CHECK_SOURCE = PROJECT_ROOT / "scripts" / "health_check.py"

#: 体检探针那两格的父墙＝**子进程预算 ＋ 余量**，且预算从 `scripts/health_check.py` 取。
#:
#: 为什么这里必须显式声明：全局墙是 30s（`pyproject.toml` 的 `timeout = 30`），而探针子进程
#: 的预算是 120s；Windows 侧 pytest-timeout 没有 `SIGALRM` 可用、自动退回 **thread 法**，
#: 它的处理是「dump 全部线程栈后终止整个进程」。于是 30s 先到点时，报出来的不是"这一格红"，
#: 而是"整场跑测没了"——2026-10-24 实测 `pytest tests/unit` 在 33% 处就此消失，凶手正是
#: 下面 `test_check_dependencies_reports_computer_use` 那次探针调用（冷盘满载时整轮 import
#: 超过 30s；同机空载复算 7.9s，差的就是满载）。
#:
#: 这条不变量（父墙严格高于子墙）的常驻判据在
#: `tests/unit/ci/test_nestedPytestBudgetWallsAreOrdered.py`，而它把边界写明在两处：
#: 只认**嵌套 pytest** 的落点（跑别的命令不进账），且只认**同文件闭包**（`subprocess.run`
#: 落在别的模块的 helper 里时认不到）。这一格两条都不在它的范围内——预算在
#: `scripts/health_check.py`，跑的是解释器探针而非 pytest，所以闸绿着而场子被打死。
#: 处置：本格先按同一口径把两层的数接上（下面那条判据钉住"不得各写一个数"），
#: 跨模块与任意有界等待两面各自另立一票。
_HEALTH_PROBE_WALL = PROBE_TIMEOUT_SECONDS + 60


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

    @pytest.mark.timeout(_HEALTH_PROBE_WALL)
    def test_check_dependencies_reports_computer_use(self):
        from scripts.health_check import check_dependencies

        deps = check_dependencies()
        for key in ("PIL", "pyautogui", "playwright"):
            assert key in deps, f"check_dependencies 未覆盖 {key}"
            # 报告结果必须与真实探测一致
            assert deps[key] == _spec(key), f"{key} 状态与实际不符"

    @pytest.mark.timeout(_HEALTH_PROBE_WALL)
    def test_reported_state_matches_interpreter(self):
        from scripts.health_check import check_dependencies

        deps = check_dependencies()
        assert deps["fastapi"] is True

    def test_probeBudgetHasOneSourceAndBothWallsDeriveFromIt(self):
        """两层的数必须同源：子墙写在体检模块里一处，父墙由它导出，谁都不许再抄一个字面量。

        判据咬的是**形状**而不是秒数——机器快慢会变，「30s 先到、thread 法打死整场」这个
        机制只在"父墙不高于子墙"时成立。反向钉：`timeout=<字面量>` 回到体检模块、或本档
        的墙不再引用那个常量，即红。
        """
        source = _HEALTH_CHECK_SOURCE.read_text(encoding="utf-8")
        # 正检先行：锚必须真指得到，否则下面的"不得命中"是恒真断言
        assert re.search(r"^PROBE_TIMEOUT_SECONDS = \d+$", source, re.M), (
            "体检模块里再没有 `PROBE_TIMEOUT_SECONDS = <整数>` 这一行——预算换了出处，"
            "本档的父墙就是在对着一个不存在的数加余量"
        )
        from scripts.health_check import check_dependencies

        probeBody = inspect.getsource(check_dependencies)
        assert "timeout=PROBE_TIMEOUT_SECONDS" in probeBody, (
            "探针子进程不再引用那个常量——它回到自报一个数了，两层从此脱钩"
        )
        literalChild = re.findall(r"timeout\s*=\s*\d+", probeBody)
        assert not literalChild, (
            f"探针调用里又出现字面量子墙 {literalChild}——"
            "预算只许有 PROBE_TIMEOUT_SECONDS 一处出处，两处数字漂移时先到点的是错的那一层"
        )
        ownSource = Path(__file__).read_text(encoding="utf-8")
        assert re.search(r"_HEALTH_PROBE_WALL = PROBE_TIMEOUT_SECONDS \+ \d+", ownSource), (
            "本档的父墙不再由子墙预算导出（改成抄字面量了？）——两墙脱钩，全局 30s 又能先打死整场"
        )
        assert _HEALTH_PROBE_WALL > PROBE_TIMEOUT_SECONDS, (
            f"父墙 {_HEALTH_PROBE_WALL}s 未严格高于子墙 {PROBE_TIMEOUT_SECONDS}s（相等也是掷骰子）"
        )


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
