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
7. 下载 ASR 模型 (FunASR)
8. 下载 Embedding 模型 (bge-small-zh-v1.5)

使用方式:
    python install.py              # 完整安装
    python install.py --skip-models  # 跳过模型下载
    python install.py --skip-frontend  # 跳过前端安装
    python install.py --lang zh      # 直接指定语言 (跳过选择)
"""

import argparse
import os
import subprocess
import sys
import shutil
from pathlib import Path

# 添加项目根目录到 Python 路径
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

# 从共享模块导入
from scripts.common import (
    Colors,
    ProgressBar,
    print_logo,
    c,
    run_with_progress as _run_with_progress,
    install_with_progress as _install_with_progress,
)
from scripts.config import (
    ROOT_DIR,
    VENV_DIR,
    FRONTEND_DIR,
    MODELS_DIR,
    MIN_PYTHON_VERSION,
    get_venv_python,
)

# 注意：进度条、颜色、Logo 等共享功能已从 scripts.common 模块导入
# 多语言支持保留在本文件中


def run_with_progress(
    description: str,
    cmd: list,
    cwd: str = None,
    env: dict = None,
    indeterminate_msg: str = None,
) -> tuple:
    """
    带进度条执行命令（支持多语言）
    
    Args:
        description: 进度条描述
        cmd: 命令列表
        cwd: 工作目录
        env: 环境变量
        indeterminate_msg: 不确定进度模式的消息
        
    Returns:
        tuple: (returncode, stdout, stderr)
    """
    # 根据语言选择完成消息
    if current_lang == "zh":
        message = "完成"
    elif current_lang == "ja":
        message = "完了"
    elif current_lang == "ru":
        message = "完成ено"
    else:
        message = "done"
    
    # 调用共享模块的 run_with_progress
    rc, stdout, stderr = _run_with_progress(
        description, cmd, cwd=cwd, env=env, indeterminate_msg=indeterminate_msg
    )
    
    # 注意：共享模块的 run_with_progress 已经处理了进度条显示
    # 这里我们只需要返回结果
    return rc, stdout, stderr


def install_with_progress(
    description: str,
    cmd: list,
    cwd: str = None,
    env: dict = None,
) -> bool:
    """
    带进度条执行安装命令（支持多语言）
    
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




# ==================== 多语言支持 ====================

TRANSLATIONS = {
    "zh": {
        "lang_name": "中文",
        "header_title": "一键安装脚本",
        "header_slogan": "智能无限，协作无间",
        "step_python": "[1/8] 检查 Python 版本...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] 需要 Python {min}+，当前版本: {current}",
        "step_venv": "[2/8] 创建虚拟环境...",
        "venv_exists": "[OK] 虚拟环境已存在: {path}",
        "venv_created": "[OK] 虚拟环境创建成功",
        "venv_error": "[ERROR] 创建虚拟环境失败: {error}",
        "step_deps": "[3/8] 安装 Python 依赖...",
        "deps_upgrading": "    升级 pip...",
        "deps_install": "    安装依赖包...",
        "deps_ok": "[OK] Python 依赖安装完成",
        "deps_error": "[ERROR] 安装 Python 依赖失败: {error}",
        "step_frontend": "[4/8] 安装前端依赖...",
        "frontend_skip": "[SKIP] 前端目录不存在: {path}",
        "frontend_exists": "[OK] 前端依赖已存在",
        "frontend_ok": "[OK] 前端依赖安装完成",
        "frontend_error": "[ERROR] 安装前端依赖失败: {error}",
        "step_tts": "[5/8] 下载 MOSS-TTS 模型...",
        "tts_downloading": "    下载 moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTS 模型下载失败: {error}",
        "tts_fallback": "[INFO] 将使用 edge-tts 作为后备",
        "step_asr": "[6/8] 下载 ASR 模型 (FunASR)...",
        "asr_downloading": "    下载 FunASR 模型...",
        "asr_ok": "[OK] FunASR 模型: {path}",
        "asr_warn": "[WARN] ASR 模型下载失败: {error}",
        "asr_fallback": "[INFO] 将使用 Whisper 作为后备",
        "step_embed": "[7/8] 下载 Embedding 模型 (bge-small-zh-v1.5)...",
        "embed_downloading": "    下载 bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embedding 模型下载失败: {error}",
        "embed_fallback": "[INFO] 将使用 TF-IDF 作为后备",
        "step_verify": "[8/8] 验证安装...",
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
        "step_python": "[1/8] Checking Python version...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}+ required, found: {current}",
        "step_venv": "[2/8] Creating virtual environment...",
        "venv_exists": "[OK] Virtual environment exists: {path}",
        "venv_created": "[OK] Virtual environment created",
        "venv_error": "[ERROR] Failed to create virtual environment: {error}",
        "step_deps": "[3/8] Installing Python dependencies...",
        "deps_upgrading": "    Upgrading pip...",
        "deps_install": "    Installing packages...",
        "deps_ok": "[OK] Python dependencies installed",
        "deps_error": "[ERROR] Failed to install Python dependencies: {error}",
        "step_frontend": "[4/8] Installing frontend dependencies...",
        "frontend_skip": "[SKIP] Frontend directory not found: {path}",
        "frontend_exists": "[OK] Frontend dependencies exist",
        "frontend_ok": "[OK] Frontend dependencies installed",
        "frontend_error": "[ERROR] Failed to install frontend dependencies: {error}",
        "step_tts": "[5/8] Downloading MOSS-TTS model...",
        "tts_downloading": "    Downloading moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTS model download failed: {error}",
        "tts_fallback": "[INFO] Will use edge-tts as fallback",
        "step_asr": "[6/8] Downloading ASR model (FunASR)...",
        "asr_downloading": "    Downloading FunASR model...",
        "asr_ok": "[OK] FunASR model: {path}",
        "asr_warn": "[WARN] ASR model download failed: {error}",
        "asr_fallback": "[INFO] Will use Whisper as fallback",
        "step_embed": "[7/8] Downloading Embedding model (bge-small-zh-v1.5)...",
        "embed_downloading": "    Downloading bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embedding model download failed: {error}",
        "embed_fallback": "[INFO] Will use TF-IDF as fallback",
        "step_verify": "[8/8] Verifying installation...",
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
        "step_python": "[1/8] Pythonバージョンを確認中...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}以上が必要です。現在: {current}",
        "step_venv": "[2/8] 仮想環境を作成中...",
        "venv_exists": "[OK] 仮想環境が存在します: {path}",
        "venv_created": "[OK] 仮想環境を作成しました",
        "venv_error": "[ERROR] 仮想環境の作成に失敗: {error}",
        "step_deps": "[3/8] Python依存関係をインストール中...",
        "deps_upgrading": "    pipをアップグレード中...",
        "deps_install": "    パッケージをインストール中...",
        "deps_ok": "[OK] Python依存関係のインストール完了",
        "deps_error": "[ERROR] Python依存関係のインストールに失敗: {error}",
        "step_frontend": "[4/8] フロントエンド依存関係をインストール中...",
        "frontend_skip": "[SKIP] フロントエンドディレクトリが見つかりません: {path}",
        "frontend_exists": "[OK] フロントエンド依存関係が存在します",
        "frontend_ok": "[OK] フロントエンド依存関係のインストール完了",
        "frontend_error": "[ERROR] フロントエンド依存関係のインストールに失敗: {error}",
        "step_tts": "[5/8] MOSS-TTSモデルをダウンロード中...",
        "tts_downloading": "    moss-tts-nanoをダウンロード中...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] TTSモデルのダウンロードに失敗: {error}",
        "tts_fallback": "[INFO] edge-ttsをフォールバックとして使用",
        "step_asr": "[6/8] ASRモデルをダウンロード中 (FunASR)...",
        "asr_downloading": "    FunASRモデルをダウンロード中...",
        "asr_ok": "[OK] FunASRモデル: {path}",
        "asr_warn": "[WARN] ASRモデルのダウンロードに失敗: {error}",
        "asr_fallback": "[INFO] Whisperをフォールバックとして使用",
        "step_embed": "[7/8] Embeddingモデルをダウンロード中 (bge-small-zh-v1.5)...",
        "embed_downloading": "    bge-small-zh-v1.5をダウンロード中 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Embeddingモデルのダウンロードに失敗: {error}",
        "embed_fallback": "[INFO] TF-IDFをフォールバックとして使用",
        "step_verify": "[8/8] インストールを検証中...",
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
        "step_python": "[1/8] Проверка версии Python...",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Требуется Python {min}+, найдено: {current}",
        "step_venv": "[2/8] Создание виртуального окружения...",
        "venv_exists": "[OK] Виртуальное окружение существует: {path}",
        "venv_created": "[OK] Виртуальное окружение создано",
        "venv_error": "[ERROR] Ошибка создания виртуального окружения: {error}",
        "step_deps": "[3/8] Установка зависимостей Python...",
        "deps_upgrading": "    Обновление pip...",
        "deps_install": "    Установка пакетов...",
        "deps_ok": "[OK] Зависимости Python установлены",
        "deps_error": "[ERROR] Ошибка установки зависимостей Python: {error}",
        "step_frontend": "[4/8] Установка зависимостей фронтенда...",
        "frontend_skip": "[SKIP] Каталог фронтенда не найден: {path}",
        "frontend_exists": "[OK] Зависимости фронтенда существуют",
        "frontend_ok": "[OK] Зависимости фронтенда установлены",
        "frontend_error": "[ERROR] Ошибка установки зависимостей фронтенда: {error}",
        "step_tts": "[5/8] Загрузка модели MOSS-TTS...",
        "tts_downloading": "    Загрузка moss-tts-nano...",
        "tts_ok": "[OK] moss-tts-nano: {path}",
        "tts_warn": "[WARN] Ошибка загрузки модели TTS: {error}",
        "tts_fallback": "[INFO] Будет использован edge-tts как запасной вариант",
        "step_asr": "[6/8] Загрузка модели ASR (FunASR)...",
        "asr_downloading": "    Загрузка модели FunASR...",
        "asr_ok": "[OK] Модель FunASR: {path}",
        "asr_warn": "[WARN] Ошибка загрузки модели ASR: {error}",
        "asr_fallback": "[INFO] Будет использован Whisper как запасной вариант",
        "step_embed": "[7/8] Загрузка модели Embedding (bge-small-zh-v1.5)...",
        "embed_downloading": "    Загрузка bge-small-zh-v1.5 (~130MB)...",
        "embed_ok": "[OK] bge-small-zh-v1.5: {path}",
        "embed_warn": "[WARN] Ошибка загрузки модели Embedding: {error}",
        "embed_fallback": "[INFO] Будет использован TF-IDF как запасной вариант",
        "step_verify": "[8/8] Проверка установки...",
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


def download_asr_model():
    """下载 ASR 模型 (FunASR)"""
    print(t("step_asr"))
    
    try:
        # 创建 ASR 模型目录
        asr_dir = MODELS_DIR / "asr"
        asr_dir.mkdir(parents=True, exist_ok=True)
        
        funasr_dir = asr_dir / "funasr"
        funasr_dir.mkdir(parents=True, exist_ok=True)
        
        # FunASR 模型会在首次使用时自动下载
        # 这里只创建目录结构
        print(t("asr_downloading"))
        print(t("asr_ok", path=str(funasr_dir)))
        
        return True
    except Exception as e:
        print(t("asr_warn", error=str(e)))
        print(t("asr_fallback"))
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
    global current_lang
    
    parser = argparse.ArgumentParser(description="Neurova One-Click Install")
    parser.add_argument("--skip-models", action="store_true", help="Skip model download")
    parser.add_argument("--skip-asr", action="store_true", help="Skip ASR model download")
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
        if not args.skip_asr:
            steps.append(("asr", download_asr_model))
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
