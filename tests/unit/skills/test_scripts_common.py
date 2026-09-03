"""
Neurova 共享工具模块测试
测试 common.py 中的颜色、Logo、进度条等功能
"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

# 导入被测模块
from scripts.common import (
    Colors, _supports_color, c, print_logo, ProgressBar,
    run_with_progress, install_with_progress, SPINNER_FRAMES,
    PROGRESS_FILL, PROGRESS_EMPTY, LOGO_ART
)


class TestColors:
    """测试颜色常量"""
    
    def test_colors_exist(self):
        """测试颜色常量是否存在"""
        assert hasattr(Colors, 'RESET')
        assert hasattr(Colors, 'BOLD')
        assert hasattr(Colors, 'RED')
        assert hasattr(Colors, 'GREEN')
        assert hasattr(Colors, 'YELLOW')
        assert hasattr(Colors, 'BLUE')
        assert hasattr(Colors, 'MAGENTA')
        assert hasattr(Colors, 'CYAN')
        assert hasattr(Colors, 'WHITE')
        assert hasattr(Colors, 'SKY_BLUE')
        assert hasattr(Colors, 'SKY_BLUE_BRIGHT')
    
    def test_colors_are_strings(self):
        """测试颜色常量是否为字符串"""
        assert isinstance(Colors.RESET, str)
        assert isinstance(Colors.RED, str)
        assert isinstance(Colors.GREEN, str)
    
    def test_colors_contain_ansi_codes(self):
        """测试颜色常量是否包含 ANSI 转义码"""
        assert '\033[' in Colors.RESET
        assert '\033[' in Colors.RED
        assert '\033[' in Colors.GREEN


class TestSupportsColor:
    """测试颜色支持检测"""
    
    def test_supports_color_returns_bool(self):
        """测试 _supports_color 返回布尔值"""
        result = _supports_color()
        assert isinstance(result, bool)
    
    @patch('sys.stdout.isatty', return_value=False)
    def test_supports_color_no_tty(self, mock_isatty):
        """测试非 TTY 终端不支持颜色"""
        assert _supports_color() == False
    
    @patch('sys.stdout.isatty', return_value=True)
    @patch('sys.platform', 'linux')
    def test_supports_color_linux_tty(self, mock_isatty):
        """测试 Linux TTY 终端支持颜色"""
        assert _supports_color() == True


class TestColorFunction:
    """测试颜色函数"""
    
    def test_c_adds_color(self):
        """测试 c 函数添加颜色"""
        with patch('scripts.common._USE_COLOR', True):
            result = c("test", Colors.RED)
            assert result == f"{Colors.RED}test{Colors.RESET}"
    
    def test_c_no_color(self):
        """测试 c 函数在无颜色支持时返回原文"""
        with patch('scripts.common._USE_COLOR', False):
            result = c("test", Colors.RED)
            assert result == "test"


class TestPrintLogo:
    """测试 Logo 打印"""
    
    def test_print_logo_default(self, capsys):
        """测试默认 Logo 打印"""
        print_logo()
        captured = capsys.readouterr()
        assert "NEUROVA" in captured.out or "╗" in captured.out
    
    def test_print_logo_with_subtitle(self, capsys):
        """测试带副标题的 Logo 打印"""
        print_logo(subtitle="测试副标题")
        captured = capsys.readouterr()
        assert "测试副标题" in captured.out
    
    def test_print_logo_with_double_subtitle(self, capsys):
        """测试带双副标题的 Logo 打印"""
        print_logo(subtitle="第一行", double_subtitle="第二行")
        captured = capsys.readouterr()
        assert "第一行" in captured.out
        assert "第二行" in captured.out


class TestProgressBar:
    """测试进度条"""
    
    def test_progress_bar_init(self):
        """测试进度条初始化"""
        pb = ProgressBar("测试", total=100)
        assert pb.description == "测试"
        assert pb.total == 100
        assert pb.current == 0
    
    def test_progress_bar_context_manager(self, capsys):
        """测试进度条上下文管理器"""
        with ProgressBar("测试", total=10) as pb:
            for i in range(10):
                pb.update(i + 1)
                time.sleep(0.01)
        captured = capsys.readouterr()
        # 进度条应该输出一些内容
        assert len(captured.out) > 0
    
    def test_progress_bar_update(self):
        """测试进度条更新"""
        pb = ProgressBar("测试", total=100)
        pb.start()
        pb.update(50)
        assert pb.current == 50
        pb.finish()
    
    def test_progress_bar_indeterminate(self, capsys):
        """测试不确定进度模式"""
        pb = ProgressBar("测试", total=100)
        pb.start()
        pb.set_indeterminate("加载中...")
        time.sleep(0.2)
        pb.finish()
        captured = capsys.readouterr()
        # 应该有一些输出
        assert len(captured.out) > 0


class TestRunWithProgress:
    """测试带进度条的命令执行"""
    
    def test_run_with_progress_success(self):
        """测试成功执行命令"""
        if sys.platform == "win32":
            cmd = ["cmd", "/c", "echo", "hello"]
        else:
            cmd = ["echo", "hello"]
        
        rc, stdout, stderr = run_with_progress("测试命令", cmd)
        assert rc == 0
        assert "hello" in stdout.lower()
    
    def test_run_with_progress_failure(self):
        """测试失败执行命令"""
        cmd = ["nonexistent_command_12345"]
        rc, stdout, stderr = run_with_progress("测试命令", cmd)
        assert rc != 0


class TestInstallWithProgress:
    """测试带进度条的安装"""
    
    def test_install_with_progress_success(self):
        """测试成功安装"""
        if sys.platform == "win32":
            cmd = ["cmd", "/c", "echo", "installed"]
        else:
            cmd = ["echo", "installed"]
        
        result = install_with_progress("测试安装", cmd)
        assert result == True
    
    def test_install_with_progress_failure(self):
        """测试失败安装"""
        cmd = ["nonexistent_command_12345"]
        result = install_with_progress("测试安装", cmd)
        assert result == False


class TestConstants:
    """测试常量"""
    
    def test_spinner_frames(self):
        """测试 Spinner 帧列表"""
        assert isinstance(SPINNER_FRAMES, list)
        assert len(SPINNER_FRAMES) > 0
        for frame in SPINNER_FRAMES:
            assert isinstance(frame, str)
    
    def test_progress_chars(self):
        """测试进度条字符"""
        assert isinstance(PROGRESS_FILL, str)
        assert isinstance(PROGRESS_EMPTY, str)
        assert len(PROGRESS_FILL) == 1
        assert len(PROGRESS_EMPTY) == 1
    
    def test_logo_art(self):
        """测试 Logo 艺术字"""
        assert isinstance(LOGO_ART, str)
        assert "NEUROVA" in LOGO_ART or "╗" in LOGO_ART


class TestEdgeCases:
    """测试边界情况"""
    
    def test_progress_bar_zero_total(self):
        """测试总进度为零的情况"""
        pb = ProgressBar("测试", total=0)
        assert pb.total == 1.0  # 应该被修正为 1.0
    
    def test_progress_bar_negative_total(self):
        """测试负总进度的情况"""
        pb = ProgressBar("测试", total=-10)
        assert pb.total == 1.0  # 应该被修正为 1.0
    
    def test_progress_bar_update_beyond_total(self):
        """测试更新超过总进度的情况"""
        pb = ProgressBar("测试", total=100)
        pb.start()
        pb.update(150)
        assert pb.current == 100  # 应该被限制为 100
        pb.finish()
    
    def test_progress_bar_finish_twice(self):
        """测试重复完成的情况"""
        pb = ProgressBar("测试", total=100)
        pb.start()
        pb.update(50)
        pb.finish()
        pb.finish()  # 应该不会出错


if __name__ == "__main__":
    pytest.main([__file__, "-v"])