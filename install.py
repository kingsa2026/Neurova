#!/usr/bin/env python3
"""
Neurova 一键安装脚本 / One-Click Install / 一键インストール / Одностраничная установка
===================

自动完成以下步骤：
1. 选择语言 (中文/English/日本語/Русский)
2. 检查 Python 版本 (>= 3.10)
3. 创建虚拟环境 (.venv)
4. 安装 Python 依赖
5. 安装前端依赖 (npm)
6. 下载 MOSS-TTS 模型
7. 下载 Embedding 模型 (bge-small-zh-v1.5)

使用方式:
    python install.py              # 完整安装
    python install.py --skip-models  # 跳过模型下载
    python install.py --skip-frontend  # 跳过前端安装
    python install.py --lang zh      # 直接指定语言 (跳过选择)
"""

import argparse
import os
import re
import subprocess
import sys
import shutil
import threading
import time
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.resolve()
VENV_DIR = ROOT_DIR / ".venv"
FRONTEND_DIR = ROOT_DIR / "neuUI"
MODELS_DIR = ROOT_DIR / "models"

# Python 版本要求
MIN_PYTHON_VERSION = (3, 10)

# ==================== 进度条 / Progress Bar ====================

# ANSI 颜色码
class Colors:
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
    ║            {subtitle:^51}  ║
    ╚═══════════════════════════════════════════════════════════════════╝
"""


def print_logo(subtitle: str = None, double_subtitle: str = None):
    """
    以天蓝色打印 NEUROVA logo。

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
            "║            {subtitle:^51}  ║",
            f"║            {subtitle:^51}  ║\n    ║            {double_subtitle:^51}  ║",
        )
    print(c(out, Colors.SKY_BLUE_BRIGHT))


def _supports_color():
    """检测终端是否支持 ANSI 颜色。"""
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


_USE_COLOR = _supports_color()


def c(text, color):
    """给文本添加颜色（如果终端支持）。"""
    if not _USE_COLOR:
        return text
    return f"{color}{text}{Colors.RESET}"


class ProgressBar:
    """
    进度条 - 支持动画、百分比、ETA、下载速度。
    
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
    
    def start(self):
        """开始进度条（启动动画线程）。"""
        self.start_time = time.time()
        self.last_update_time = time.time()
        self._anim_stop.clear()
        self._anim_thread = threading.Thread(target=self._animate, daemon=True)
        self._anim_thread.start()
    
    def _animate(self):
        """动画线程 - 在不确定模式下旋转 spinner。"""
        while not self._anim_stop.is_set():
            with self._lock:
                if not self._indeterminate:
                    return
                self._render(animated_only=True)
            self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)
            self._anim_stop.wait(0.1)
    
    def update(self, current: float, total: float = None):
        """更新进度。"""
        with self._lock:
            if total is not None:
                self.total = max(total, 1.0)
            self.current = max(0.0, min(current, self.total))
            self._indeterminate = False
            self._render()
    
    def set_indeterminate(self, message: str = ""):
        """切换为不确定进度模式（旋转 spinner）。"""
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
        """格式化字节数。"""
        for unit in ["B", "KB", "MB", "GB"]:
            if n < 1024.0:
                return f"{n:.1f}{unit}"
            n /= 1024.0
        return f"{n:.1f}TB"
    
    def _format_time(self, seconds: float) -> str:
        """格式化时间。"""
        if seconds < 0 or seconds == float("inf"):
            return "--:--"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    
    def _render(self, animated_only: bool = False):
        """渲染进度条到终端。"""
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
    
    def finish(self, success: bool = True, message: str = None):
        """完成进度条。"""
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
                line = f"  {symbol} {c(self.description, Colors.BOLD)} {c(message or ('完成' if current_lang == 'zh' else 'done'), Colors.DIM)}"
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
            import re
            plain_len = len(re.sub(r"\033\[[0-9;]*m", "", line))
            sys.stdout.write(line + " " * max(0, self._last_line_len - plain_len) + "\n")
            sys.stdout.flush()
            self._last_line_len = 0


def run_with_progress(
    description: str,
    cmd: list,
    cwd: str = None,
    env: dict = None,
    indeterminate_msg: str = None,
) -> tuple:
    """
    在子进程中执行命令，并实时解析输出更新进度条。
    
    Returns:
        (returncode, stdout, stderr)
    """
    import re as _re
    
    pb = ProgressBar(description, total=100.0, show_eta=True)
    pb.start()
    pb.set_indeterminate(indeterminate_msg or description)
    
    # 正则: 匹配 pip 的下载/安装进度
    # 例如: "Downloading numpy-1.26.0.whl (14.7 MB)"
    #       "  ━━━━━━━━━━━━━━━━━━━━━━ 14.7/14.7 MB 2.4 MB/s eta 0:00:00"
    file_re = _re.compile(r"^\s*(?:Downloading|Collecting|Installing)\s+([^\s(]+).*?\(?([\d.]+)\s*(KB|MB|GB|B)?\)?", _re.IGNORECASE)
    bar_re = _re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB|B)?", _re.IGNORECASE)
    
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
        elif line.strip().startswith("Downloading ") and "━━━━━━━━━━━━━━━━━━━━" in line:
            # 进度条字符 - 表示下载中
            pass
    
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
            # 简单策略：files_done * 1.0 + file_progress，再映射到 5-95%
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
    cwd: str = None,
    env: dict = None,
) -> bool:
    """带进度条地执行命令。"""
    rc, _, _ = run_with_progress(description, cmd, cwd=cwd, env=env)
    return rc == 0




# ==================== 多语言支持 ====================

TRANSLATIONS = {
    "zh": {
        "lang_name": "中文",
        "header_title": "一键安装脚本",
        "header_slogan": "智能无限，协作无间",
        "step_python": "[1/7] 检查 Python 版本...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] 需要 Python {min}+，当前版本: {current}",
        "step_venv": "[2/7] 创建虚拟环境...",
        "venv_exists": "[OK] 虚拟环境已存在: {path}",
        "venv_created": "[OK] 虚拟环境创建成功",
        "venv_error": "[ERROR] 创建虚拟环境失败: {error}",
        "step_deps": "[3/7] 安装 Python 依赖...",
        "deps_upgrading": "    升级 pip...",
        "deps_install": "    安装依赖包...",
        "deps_ok": "[OK] Python 依赖安装完成",
        "deps_error": "[ERROR] 安装 Python 依赖失败: {error}",
        "step_frontend": "[4/7] 安装前端依赖...",
        "frontend_skip": "[SKIP] 前端目录不存在: {path}",
        "frontend_exists": "[OK] 前端依赖已存在",
        "frontend_ok": "[OK] 前端依赖安装完成",
        "frontend_error": "[ERROR] 安装前端依赖失败: {error}",
        "step_tts": "[5/7] 下载 MOSS-TTS 模型...",
        "tts_downloading": "    下载 moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTS 模型下载失败: {error}",
        "tts_fallback": "[INFO] 将使用 edge-tts 作为后备",
        "step_embed": "[6/7] 下载 Embedding 模型 (bge-small-zh-v1.5)...",
        "embed_downloading": "    下载 bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embedding 模型下载失败: {error}",
        "embed_fallback": "[INFO] 将使用 TF-IDF 作为后备",
        "step_verify": "[7/7] 验证安装...",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] 部分组件验证失败，但安装继续",
        "complete_title": "安装完成！",
        "complete_start": "启动方式:",
        "complete_win": "  Windows:  start.bat",
        "complete_linux": "  Linux/Mac: python start.py",
        "complete_venv": "  或:       .venv/bin/python start.py",
        "complete_options": "更多选项:",
        "complete_help": "  python start.py --help",
        "error_install": "[ERROR] 安装失败: {name}",
        "error_cancel": "\n\n安装已取消",
        "error_generic": "[ERROR] 安装失败: {name} - {error}",
        "lang_prompt": "请选择语言 / Select language / 言語を選択 / Выберите язык:",
    },
    "en": {
        "lang_name": "English",
        "header_title": "One-Click Install",
        "header_slogan": "Intelligent Infinity, Seamless Collaboration",
        "step_python": "[1/7] Checking Python version...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}+ required, found: {current}",
        "step_venv": "[2/7] Creating virtual environment...",
        "venv_exists": "[OK] Virtual environment exists: {path}",
        "venv_created": "[OK] Virtual environment created",
        "venv_error": "[ERROR] Failed to create virtual environment: {error}",
        "step_deps": "[3/7] Installing Python dependencies...",
        "deps_upgrading": "    Upgrading pip...",
        "deps_install": "    Installing packages...",
        "deps_ok": "[OK] Python dependencies installed",
        "deps_error": "[ERROR] Failed to install Python dependencies: {error}",
        "step_frontend": "[4/7] Installing frontend dependencies...",
        "frontend_skip": "[SKIP] Frontend directory not found: {path}",
        "frontend_exists": "[OK] Frontend dependencies exist",
        "frontend_ok": "[OK] Frontend dependencies installed",
        "frontend_error": "[ERROR] Failed to install frontend dependencies: {error}",
        "step_tts": "[5/7] Downloading MOSS-TTS model...",
        "tts_downloading": "    Downloading moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTS model download failed: {error}",
        "tts_fallback": "[INFO] Will use edge-tts as fallback",
        "step_embed": "[6/7] Downloading Embedding model (bge-small-zh-v1.5)...",
        "embed_downloading": "    Downloading bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embedding model download failed: {error}",
        "embed_fallback": "[INFO] Will use TF-IDF as fallback",
        "step_verify": "[7/7] Verifying installation...",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] Some components failed verification, continuing",
        "complete_title": "Installation Complete!",
        "complete_start": "How to start:",
        "complete_win": "  Windows:  start.bat",
        "complete_linux": "  Linux/Mac: python start.py",
        "complete_venv": "  Or:       .venv/bin/python start.py",
        "complete_options": "More options:",
        "complete_help": "  python start.py --help",
        "error_install": "[ERROR] Installation failed: {name}",
        "error_cancel": "\n\nInstallation cancelled",
        "error_generic": "[ERROR] Installation failed: {name} - {error}",
        "lang_prompt": "Select language / 选择语言 / 言語を選択 / Выберите язык:",
    },
    "ja": {
        "lang_name": "日本語",
        "header_title": "ワンクリックインストール",
        "header_slogan": "無限の知性、シームレスなコラボレーション",
        "step_python": "[1/7] Pythonバージョンを確認中...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}以上が必要です。現在: {current}",
        "step_venv": "[2/7] 仮想環境を作成中...",
        "venv_exists": "[OK] 仮想環境が存在します: {path}",
        "venv_created": "[OK] 仮想環境を作成しました",
        "venv_error": "[ERROR] 仮想環境の作成に失敗: {error}",
        "step_deps": "[3/7] Python依存関係をインストール中...",
        "deps_upgrading": "    pipをアップグレード中...",
        "deps_install": "    パッケージをインストール中...",
        "deps_ok": "[OK] Python依存関係のインストール完了",
        "deps_error": "[ERROR] Python依存関係のインストールに失敗: {error}",
        "step_frontend": "[4/7] フロントエンド依存関係をインストール中...",
        "frontend_skip": "[SKIP] フロントエンドディレクトリが見つかりません: {path}",
        "frontend_exists": "[OK] フロントエンド依存関係が存在します",
        "frontend_ok": "[OK] フロントエンド依存関係のインストール完了",
        "frontend_error": "[ERROR] フロントエンド依存関係のインストールに失敗: {error}",
        "step_tts": "[5/7] MOSS-TTSモデルをダウンロード中...",
        "tts_downloading": "    moss-tts-nanoをダウンロード中...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTSモデルのダウンロードに失敗: {error}",
        "tts_fallback": "[INFO] edge-ttsをフォールバックとして使用",
        "step_embed": "[6/7] Embeddingモデルをダウンロード中 (bge-small-zh-v1.5)...",
        "embed_downloading": "    bge-small-zh-v1.5をダウンロード中 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embeddingモデルのダウンロードに失敗: {error}",
        "embed_fallback": "[INFO] TF-IDFをフォールバックとして使用",
        "step_verify": "[7/7] インストールを検証中...",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] 一部のコンポーネントの検証に失敗しましたが、続行します",
        "complete_title": "インストール完了！",
        "complete_start": "起動方法:",
        "complete_win": "  Windows:  start.bat",
        "complete_linux": "  Linux/Mac: python start.py",
        "complete_venv": "  または:   .venv/bin/python start.py",
        "complete_options": "その他のオプション:",
        "complete_help": "  python start.py --help",
        "error_install": "[ERROR] インストール失敗: {name}",
        "error_cancel": "\n\nインストールがキャンセルされました",
        "error_generic": "[ERROR] インストール失敗: {name} - {error}",
        "lang_prompt": "言語を選択 / Select language / 选择语言 / Выберите язык:",
    },
    "ru": {
        "lang_name": "Русский",
        "header_title": "Одностраничная установка",
        "header_slogan": "Бесконечный интеллект, бесшовное сотрудничество",
        "step_python": "[1/7] Проверка версии Python...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Требуется Python {min}+, найдено: {current}",
        "step_venv": "[2/7] Создание виртуального окружения...",
        "venv_exists": "[OK] Виртуальное окружение существует: {path}",
        "venv_created": "[OK] Виртуальное окружение создано",
        "venv_error": "[ERROR] Ошибка создания виртуального окружения: {error}",
        "step_deps": "[3/7] Установка зависимостей Python...",
        "deps_upgrading": "    Обновление pip...",
        "deps_install": "    Установка пакетов...",
        "deps_ok": "[OK] Зависимости Python установлены",
        "deps_error": "[ERROR] Ошибка установки зависимостей Python: {error}",
        "step_frontend": "[4/7] Установка зависимостей фронтенда...",
        "frontend_skip": "[SKIP] Каталог фронтенда не найден: {path}",
        "frontend_exists": "[OK] Зависимости фронтенда существуют",
        "frontend_ok": "[OK] Зависимости фронтенда установлены",
        "frontend_error": "[ERROR] Ошибка установки зависимостей фронтенда: {error}",
        "step_tts": "[5/7] Загрузка модели MOSS-TTS...",
        "tts_downloading": "    Загрузка moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] Ошибка загрузки модели TTS: {error}",
        "tts_fallback": "[INFO] Будет использован edge-tts как запасной вариант",
        "step_embed": "[6/7] Загрузка модели Embedding (bge-small-zh-v1.5)...",
        "embed_downloading": "    Загрузка bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Ошибка загрузки модели Embedding: {error}",
        "embed_fallback": "[INFO] Будет использован TF-IDF как запасной вариант",
        "step_verify": "[7/7] Проверка установки...",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] Некоторые компоненты не прошли проверку, продолжаем",
        "complete_title": "Установка завершена!",
        "complete_start": "Способы запуска:",
        "complete_win": "  Windows:  start.bat",
        "complete_linux": "  Linux/Mac: python start.py",
        "complete_venv": "  Или:      .venv/bin/python start.py",
        "complete_options": "Другие опции:",
        "complete_help": "  python start.py --help",
        "error_install": "[ERROR] Ошибка установки: {name}",
        "error_cancel": "\n\nУстановка отменена",
        "error_generic": "[ERROR] Ошибка установки: {name} - {error}",
        "lang_prompt": "Выберите язык / Select language / 选择语言 / 言語を選択:",
    },
}

# 当前语言 (默认中文)
current_lang = "zh"


def t(key, **kwargs):
    """获取翻译文本"""
    text = TRANSLATIONS[current_lang].get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def select_language():
    """交互式语言选择"""
    global current_lang
    
    print_logo(subtitle="Neurova Installer")
    
    print("    " + c("请选择语言 / Select language / 言語を選択 / Выберите язык:", Colors.SKY_BLUE) + "\n")
    print("    " + c("[1]", Colors.SKY_BLUE_BRIGHT) + " 中文 (Chinese)")
    print("    " + c("[2]", Colors.SKY_BLUE_BRIGHT) + " English")
    print("    " + c("[3]", Colors.SKY_BLUE_BRIGHT) + " 日本語 (Japanese)")
    print("    " + c("[4]", Colors.SKY_BLUE_BRIGHT) + " Русский (Russian)\n")
    
    while True:
        try:
            choice = input("    " + c("输入数字 (1-4):", Colors.SKY_BLUE) + " ").strip()
            if choice == "1":
                current_lang = "zh"
                break
            elif choice == "2":
                current_lang = "en"
                break
            elif choice == "3":
                current_lang = "ja"
                break
            elif choice == "4":
                current_lang = "ru"
                break
            else:
                print("    " + c("无效选择，请输入 1-4 / Invalid choice, enter 1-4", Colors.YELLOW))
        except (EOFError, KeyboardInterrupt):
            # 非交互模式，默认中文
            current_lang = "zh"
            break
    
    print(f"\n    {c('->', Colors.SKY_BLUE)} {c(TRANSLATIONS[current_lang]['lang_name'], Colors.SKY_BLUE_BRIGHT + Colors.BOLD)}\n")


def print_header():
    """打印安装头信息"""
    print_logo(subtitle=t('header_slogan'), double_subtitle=t('header_title'))


def check_python_version():
    """检查 Python 版本"""
    print(t("step_python"))
    
    current = sys.version_info[:2]
    if current < MIN_PYTHON_VERSION:
        print(t("python_error", min=f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}", current=f"{current[0]}.{current[1]}"))
        sys.exit(1)
    
    print(t("python_ok", version=f"{current[0]}.{current[1]}"))
    return True


def create_venv():
    """创建虚拟环境"""
    print(t("step_venv"))
    
    if VENV_DIR.exists():
        print(t("venv_exists", path=str(VENV_DIR)))
        return True
    
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
            cwd=ROOT_DIR,
        )
        print(t("venv_created"))
        return True
    except subprocess.CalledProcessError as e:
        print(t("venv_error", error=str(e)))
        return False


def get_venv_python():
    """获取虚拟环境的 Python 路径"""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    else:
        return VENV_DIR / "bin" / "python"


def install_python_deps():
    """安装 Python 依赖"""
    print(t("step_deps"))
    
    venv_python = get_venv_python()
    if not venv_python.exists():
        print(t("deps_error", error=f"Python not found: {venv_python}"))
        return False
    
    try:
        # 升级 pip
        print(t("deps_upgrading"))
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            cwd=ROOT_DIR,
            capture_output=True,
        )
        
        # 安装依赖
        print(t("deps_install"))
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", "requirements.txt"],
            check=True,
            cwd=ROOT_DIR,
        )
        
        print(t("deps_ok"))
        return True
    except subprocess.CalledProcessError as e:
        print(t("deps_error", error=str(e)))
        return False


def install_frontend_deps():
    """安装前端依赖"""
    print(t("step_frontend"))
    
    if not FRONTEND_DIR.exists():
        print(t("frontend_skip", path=str(FRONTEND_DIR)))
        return True
    
    node_modules = FRONTEND_DIR / "node_modules"
    if node_modules.exists():
        print(t("frontend_exists"))
        return True
    
    try:
        subprocess.run(
            ["npm", "install"],
            check=True,
            cwd=FRONTEND_DIR,
            shell=True,
        )
        print(t("frontend_ok"))
        return True
    except subprocess.CalledProcessError as e:
        print(t("frontend_error", error=str(e)))
        return False


def download_tts_model():
    """下载 MOSS-TTS 模型"""
    print(t("step_tts"))
    
    try:
        from neurova.tts.model_downloader import get_model_downloader
        
        downloader = get_model_downloader()
        
        # 下载 moss-tts-nano
        print(t("tts_downloading"))
        path = downloader.ensure_model("moss-tts-nano")
        print(t("tts_ok", path=str(path)))
        
        return True
    except Exception as e:
        print(t("tts_warn", error=str(e)))
        print(t("tts_fallback"))
        return True  # 非致命错误


def download_embedding_model():
    """下载 Embedding 模型"""
    print(t("step_embed"))
    
    try:
        from neurova.tts.model_downloader import get_model_downloader
        
        downloader = get_model_downloader()
        
        # 下载 bge-small-zh-v1.5
        print(t("embed_downloading"))
        path = downloader.ensure_model("bge-small-zh-v1.5")
        print(t("embed_ok", path=str(path)))
        
        return True
    except Exception as e:
        print(t("embed_warn", error=str(e)))
        print(t("embed_fallback"))
        return True  # 非致命错误


def verify_installation():
    """验证安装"""
    print(f"\n{t('step_verify')}")
    
    venv_python = get_venv_python()
    
    checks = [
        ("FastAPI", "import fastapi"),
        ("Uvicorn", "import uvicorn"),
        ("ONNX Runtime", "import onnxruntime"),
        ("Sentence Transformers", "import sentence_transformers"),
        ("HuggingFace Hub", "import huggingface_hub"),
        ("Tokenizers", "import tokenizers"),
    ]
    
    all_ok = True
    for name, import_stmt in checks:
        try:
            subprocess.run(
                [str(venv_python), "-c", import_stmt],
                check=True,
                capture_output=True,
            )
            print(t("verify_ok", name=name))
        except subprocess.CalledProcessError:
            print(t("verify_fail", name=name))
            all_ok = False
    
    return all_ok


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Neurova One-Click Install")
    parser.add_argument("--skip-models", action="store_true", help="Skip model download")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend install")
    parser.add_argument("--lang", choices=["zh", "en", "ja", "ru"], help="Language (skip selection)")
    args = parser.parse_args()
    
    # 语言选择
    if args.lang:
        current_lang = args.lang
    else:
        select_language()
    
    print_header()
    
    steps = [
        ("python", check_python_version),
        ("venv", create_venv),
        ("deps", install_python_deps),
    ]
    
    if not args.skip_frontend:
        steps.append(("frontend", install_frontend_deps))
    
    if not args.skip_models:
        steps.append(("tts", download_tts_model))
        steps.append(("embed", download_embedding_model))
    
    # 执行安装步骤
    for i, (name, func) in enumerate(steps, 1):
        try:
            if not func():
                print(f"\n{t('error_install', name=name)}")
                sys.exit(1)
        except KeyboardInterrupt:
            print(t("error_cancel"))
            sys.exit(1)
        except Exception as e:
            print(t("error_generic", name=name, error=str(e)))
            sys.exit(1)
    
    # 验证安装
    if not verify_installation():
        print(f"\n{t('verify_warn')}")
    
    print("\n" + "=" * 60)
    print(t("complete_title"))
    print("=" * 60)
    print(f"\n{t('complete_start')}")
    print(t("complete_win"))
    print(t("complete_linux"))
    print(t("complete_venv"))
    print(f"\n{t('complete_options')}")
    print(t("complete_help"))
    print("=" * 60)


if __name__ == "__main__":
    main()
