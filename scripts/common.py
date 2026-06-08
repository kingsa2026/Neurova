"""
Neurova 共享工具模块
提供颜色、Logo、进度条、终端检测等共享功能
"""

import sys
import time
import threading
import re
from typing import Optional

# ANSI 颜色码
class Colors:
    """ANSI 颜色码常量"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"
    BG_RED = "\033[41m"
    # 天蓝色 / Sky Blue
    SKY_BLUE = "\033[38;5;117m"
    SKY_BLUE_BRIGHT = "\033[38;5;159m"
    SKY_BLUE_BG = "\033[48;5;117m"


# Spinner 动画字符集
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
# 进度条填充字符
PROGRESS_FILL = "█"
PROGRESS_EMPTY = "░"

# 天蓝色 NEUROVA ASCII Logo
LOGO_ART = r"""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║                                                                   ║
    ║   ███╗   ██╗███████╗██╗   ██╗██████╗  ██████╗ ██╗   ██╗  █████╗   ║
    ║   ████╗  ██║██╔════╝██║   ██║██╔══██╗██╔═══██╗██║   ██║ ██╔══██╗  ║
    ║   ██╔██╗ ██║█████╗  ██║   ██║██████╔╝██║   ██║██║   ██║ ███████║  ║
    ║   ██║╚██╗██║██╔══╝  ██║   ██║██╔══██╗██║   ██║╚██╗ ██╔╝ ██╔══██║  ║
    ║   ██║ ╚████║███████╗╚██████╔╝██║  ██║╚██████╔╝ ╚████╔╝  ██║  ██║  ║
    ║   ╚═╝  ╚═══╝╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝   ╚═══╝   ╚═╝  ╚═╝  ║
    ║                                                                   ║
    ║       {subtitle:^51}  ║
    ╚═══════════════════════════════════════════════════════════════════╝
"""


def _supports_color() -> bool:
    """
    检测终端是否支持 ANSI 颜色
    
    Returns:
        bool: 是否支持颜色
    """
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        # Windows 10+ 默认启用 ANSI
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x4
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return bool(mode.value & 0x4)
        except Exception:
            pass
    return True


# 全局颜色支持状态
_USE_COLOR = _supports_color()


def c(text: str, color: str) -> str:
    """
    给文本添加颜色（如果终端支持）
    
    Args:
        text: 要添加颜色的文本
        color: ANSI 颜色码
        
    Returns:
        str: 添加颜色后的文本
    """
    if not _USE_COLOR:
        return text
    return f"{color}{text}{Colors.RESET}"


def print_logo(subtitle: Optional[str] = None, double_subtitle: Optional[str] = None) -> None:
    """
    以天蓝色打印 NEUROVA logo
    
    Args:
        subtitle: 可选的第一行小标题（如 "智能无限，协作无间"）
        double_subtitle: 可选的第二行小标题（如 "一键安装脚本"）
    """
    if subtitle is None and double_subtitle is None:
        out = LOGO_ART.format(subtitle=" ")
    elif double_subtitle is None:
        out = LOGO_ART.format(subtitle=subtitle)
    else:
        # 双行小标题
        logo = LOGO_ART
        out = logo.replace(
            "║       {subtitle:^51}  ║",
            f"║       {subtitle:^51}  ║\n    ║       {double_subtitle:^51}  ║",
        )
    print(c(out, Colors.SKY_BLUE_BRIGHT))


class ProgressBar:
    """
    进度条 - 支持动画、百分比、ETA、下载速度
    
    Usage:
        with ProgressBar("Installing", total=100) as pb:
            for i in range(100):
                pb.update(i + 1)
    """
    
    def __init__(
        self,
        description: str = "",
        total: float = 100.0,
        unit: str = "",
        width: int = 30,
        show_speed: bool = False,
        show_eta: bool = True,
    ):
        self.description = description
        self.total = max(total, 1.0)
        self.current = 0.0
        self.unit = unit
        self.width = width
        self.show_speed = show_speed
        self.show_eta = show_eta
        self.start_time = time.time()
        self.last_update_time = 0.0
        self._finished = False
        self._lock = threading.Lock()
        self._last_line_len = 0
        self._anim_frame = 0
        self._anim_thread = None
        self._anim_stop = threading.Event()
        self._indeterminate = False
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.finish(success=exc_type is None)
        return False
    
    def start(self) -> None:
        """开始进度条（启动动画线程）"""
        self.start_time = time.time()
        self.last_update_time = time.time()
        self._anim_stop.clear()
        self._anim_thread = threading.Thread(target=self._animate, daemon=True)
        self._anim_thread.start()
    
    def _animate(self) -> None:
        """动画线程 - 在不确定模式下旋转 spinner"""
        while not self._anim_stop.is_set():
            with self._lock:
                if not self._indeterminate:
                    return
                self._render(animated_only=True)
            self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)
            self._anim_stop.wait(0.1)
    
    def update(self, current: float, total: Optional[float] = None) -> None:
        """更新进度"""
        with self._lock:
            if total is not None:
                self.total = max(total, 1.0)
            self.current = max(0.0, min(current, self.total))
            self._indeterminate = False
            self._render()
    
    def set_indeterminate(self, message: str = "") -> None:
        """切换为不确定进度模式（旋转 spinner）"""
        with self._lock:
            self._indeterminate = True
            if message:
                self.description = message
            if self._anim_thread is None or not self._anim_thread.is_alive():
                self._anim_stop.clear()
                self._anim_thread = threading.Thread(target=self._animate, daemon=True)
                self._anim_thread.start()
            self._render()
    
    def _format_bytes(self, n: float) -> str:
        """格式化字节数"""
        for unit in ["B", "KB", "MB", "GB"]:
            if n < 1024.0:
                return f"{n:.1f}{unit}"
            n /= 1024.0
        return f"{n:.1f}TB"
    
    def _format_time(self, seconds: float) -> str:
        """格式化时间"""
        if seconds < 0 or seconds == float("inf"):
            return "--:--"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    def _render(self, animated_only: bool = False) -> None:
        """渲染进度条到终端"""
        if self._finished:
            return
        
        elapsed = time.time() - self.start_time
        pct = (self.current / self.total) * 100.0
        
        if self._indeterminate:
            spinner = SPINNER_FRAMES[self._anim_frame]
            line = f"  {c(spinner, Colors.CYAN)} {c(self.description, Colors.BOLD)}"
        else:
            filled = int(self.width * self.current / self.total)
            empty = self.width - filled
            bar = c(PROGRESS_FILL * filled, Colors.GREEN) + c(PROGRESS_EMPTY * empty, Colors.DIM)
            pct_text = f"{pct:5.1f}%"
            
            extras = []
            if self.show_speed and elapsed > 0:
                speed = self.current / elapsed
                extras.append(self._format_bytes(speed) + "/s" if self.unit == "B" else f"{speed:.1f}{self.unit}/s")
            if self.show_eta and pct > 0 and pct < 100:
                eta = elapsed * (100.0 - pct) / pct
                extras.append(f"ETA {self._format_time(eta)}")
            if self.current > 0 and self.unit == "B":
                extras.append(f"{self._format_bytes(self.current)}/{self._format_bytes(self.total)}")
            elif self.current > 0 and self.unit:
                extras.append(f"{self.current:.0f}/{self.total:.0f}{self.unit}")
            
            extra_str = ("  " + c("│ ", Colors.DIM) + c(" ".join(extras), Colors.DIM)) if extras else ""
            line = f"  {c('▸', Colors.CYAN)} {c(self.description, Colors.BOLD):<28} {bar} {c(pct_text, Colors.GREEN)}{extra_str}"
        
        # 清除上一行
        if self._last_line_len > 0:
            sys.stdout.write("\r" + " " * self._last_line_len + "\r")
        sys.stdout.write(line)
        sys.stdout.flush()
        self._last_line_len = len(line)
    
    def finish(self, success: bool = True, message: Optional[str] = None) -> None:
        """完成进度条"""
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self._anim_stop.set()
            if self._anim_thread is not None:
                self._anim_thread.join(timeout=0.5)
            
            elapsed = time.time() - self.start_time
            if self._indeterminate:
                # 不确定进度 - 直接显示完成
                symbol = c("✔", Colors.GREEN) if success else c("✖", Colors.RED)
                line = f"  {symbol} {c(self.description, Colors.BOLD)} {c(message or 'done', Colors.DIM)}"
            else:
                # 100% 完成条
                filled = self.width
                bar = c(PROGRESS_FILL * filled, Colors.GREEN if success else Colors.RED)
                pct_text = "100.0%"
                symbol = c("✔", Colors.GREEN) if success else c("✖", Colors.RED)
                line = f"  {symbol} {c(self.description, Colors.BOLD):<28} {bar} {c(pct_text, Colors.GREEN)}  {c('✓ ' + self._format_time(elapsed), Colors.DIM)}"
            
            if self._last_line_len > 0:
                sys.stdout.write("\r" + " " * self._last_line_len + "\r")
            # 去掉 ANSI 码计算实际长度
            plain_len = len(re.sub(r"\033\[[0-9;]*m", "", line))
            sys.stdout.write(line + " " * max(0, self._last_line_len - plain_len) + "\n")
            sys.stdout.flush()
            self._last_line_len = 0


def run_with_progress(
    description: str,
    cmd: list,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    indeterminate_msg: Optional[str] = None,
) -> tuple:
    """
    在子进程中执行命令，并实时解析输出更新进度条
    
    Args:
        description: 进度条描述
        cmd: 命令列表
        cwd: 工作目录
        env: 环境变量
        indeterminate_msg: 不确定进度模式的消息
        
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    import subprocess
    
    pb = ProgressBar(description, total=100.0, show_eta=True)
    pb.start()
    pb.set_indeterminate(indeterminate_msg or description)
    
    # 正则: 匹配 pip 的下载/安装进度
    file_re = re.compile(r"^\s*(?:Downloading|Collecting|Installing)\s+([^\s(]+).*?\(?([\d.]+)\s*(KB|MB|GB|B)?\)?", re.IGNORECASE)
    bar_re = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|B)?", re.IGNORECASE)
    
    # 状态机
    current_file_size = 0.0
    files_done = 0
    files_total_estimate = 1
    file_progress = 0.0
    
    def parse_line(line: str):
        nonlocal current_file_size, file_progress, files_done
        
        # 匹配下载/安装的文件
        m = file_re.search(line)
        if m:
            try:
                size = float(m.group(2))
                unit = (m.group(3) or "B").upper()
                mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
                current_file_size = size * mult
                file_progress = 0.0
            except (ValueError, IndexError):
                pass
        
        # 匹配进度条数字
        m = bar_re.search(line)
        if m and current_file_size > 0:
            try:
                cur = float(m.group(1))
                tot = float(m.group(2))
                unit = (m.group(3) or "B").upper()
                mult = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}.get(unit, 1)
                # 把 KB/MB 单位换算成 B
                cur_b = cur * mult
                tot_b = tot * mult
                # 如果这是文件大小级别（tot 接近 current_file_size）
                if tot_b <= current_file_size * 1.1 and tot_b > 0:
                    file_progress = cur_b / tot_b
            except (ValueError, IndexError):
                pass
        
        # 匹配 "Successfully installed" 之类的完成标记
        if "Successfully installed" in line or "Successfully built" in line:
            files_done += 1
            file_progress = 1.0
    
    try:
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
        
        output_lines = []
        for line in process.stdout:
            output_lines.append(line)
            parse_line(line)
            # 估算总体进度
            overall = (files_done + file_progress) / max(files_total_estimate, 1)
            overall_pct = min(95.0, 5.0 + overall * 90.0)
            pb.update(overall_pct)
        
        process.wait()
        rc = process.returncode
        
        if rc == 0:
            pb.update(100.0)
        pb.finish(success=(rc == 0))
        return rc, "".join(output_lines), ""
    except Exception as e:
        pb.finish(success=False, message=str(e))
        return 1, "", str(e)


def install_with_progress(
    description: str,
    cmd: list,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> bool:
    """
    带进度条地执行命令
    
    Args:
        description: 进度条描述
        cmd: 命令列表
        cwd: 工作目录
        env: 环境变量
        
    Returns:
        bool: 命令是否成功
    """
    rc, _, _ = run_with_progress(description, cmd, cwd=cwd, env=env)
    return rc == 0