#!/usr/bin/env python3
"""
Neurova 一键安装脚本 / One-Click Install / 一键インストール / Одностраничная установка
===================

自动完成以下步骤：
1. 检查 Python 版本 (>= 3.10)
2. 创建虚拟环境 (.venv)
3. 安装 Python 依赖（清单 single source: requirements.txt）
4. 安装前端依赖 (npm ci，判据与 start.py 同契约)
5. 安装浏览器内核 (Playwright Chromium，browser_read / computer_use 依赖)
6. 安装本地 ASR 引擎包（可选，由 --with-local-asr 显式开启）
7. 下载模型（按 models/MANIFEST.json 逐件走真下载器）
8. 验证安装（探针面与模型就绪判据都取自供给清单）

使用方式:
    python install.py                 # 完整安装
    python install.py --skip-models   # 跳过模型下载
    python install.py --skip-frontend # 跳过前端安装
    python install.py --with-local-asr # 同时装本地 ASR 引擎（funasr/whisper，体积大）
    python install.py --verify-only   # 只做安装后验证
    python install.py --lang zh       # 直接指定语言 (跳过选择)

设计要点（三条都是实测踩过的断链，改前先读）：

1. **所有重活都在 .venv 解释器里跑**。`install.py` 本身由宿主机 Python 执行，
   宿主机没有 huggingface_hub / modelscope / whisper；在宿主进程内下载模型
   必然 ImportError，旧版把它吞成「[WARN] 下载失败 + 将使用后备」，用户看到
   安装成功而模型根本不存在。模型下载因此走 `--model-worker` 子进程（同一份
   代码、同一套真下载器），退出码即事实。

2. **依赖与模型只有一处声明**。基础依赖 = `requirements.txt`；模型 id / 仓库 /
   引擎包 = `models/MANIFEST.json`（Windows 首启链路 `src-tauri/src/lib.rs`
   读的同一份）。本脚本不新造名单，只消费它们。

3. **失败必须诚实**。模型下载失败就报 WARN + 点名原因与后续取法，不用空目录
   冒充 OK（旧版 `download_asr_model` 只 mkdir 就打印「[OK] FunASR 模型」）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# 项目根（本脚本可能被任意解释器等 cwd 调用，一切相对路径都锚在它上面）
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.common import (  # noqa: E402
    Colors,
    c,
    print_logo,
    run_with_progress as _run_with_progress,
)
from scripts.config import (  # noqa: E402
    FRONTEND_DIR,
    MIN_PYTHON_VERSION,
    VENV_DIR,
    get_venv_python,
)

# 供给清单：Windows 首启链路（src-tauri/src/lib.rs）与本脚本共用的唯一声明源
SUPPLY_MANIFEST = PROJECT_ROOT / "models" / "MANIFEST.json"
REQUIREMENTS_FILE = "requirements.txt"


def runWithProgress(description, cmd, cwd=None, env=None, indeterminateMsg=None):
    """带进度条执行命令（多语言完成文案由共享模块统一渲染）。"""
    return _run_with_progress(
        description, cmd, cwd=cwd, env=env, indeterminate_msg=indeterminateMsg
    )


def installWithProgress(description, cmd, cwd=None, env=None):
    """带进度条执行安装命令，返回是否成功。"""
    rc, _, _ = runWithProgress(description, cmd, cwd=cwd, env=env)
    return rc == 0


# ==================== 多语言支持 ====================

TRANSLATIONS = {
    "zh": {
        "lang_name": "中文",
        "header_title": "一键安装脚本",
        "header_slogan": "智能无限，协作无间",
        "step_python": "检查 Python 版本",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] 需要 Python {min}+，当前版本: {current}",
        "step_venv": "创建虚拟环境",
        "venv_exists": "[OK] 虚拟环境已存在: {path}",
        "venv_created": "[OK] 虚拟环境创建成功",
        "venv_error": "[ERROR] 创建虚拟环境失败: {error}",
        "step_deps": "安装 Python 依赖",
        "deps_index": "    索引源 {index}",
        "deps_ok": "[OK] Python 依赖安装完成（探针 {probe} 均可导入）",
        "deps_probe_fail": "[ERROR] 依赖装完但探针导入失败: {probe}",
        "deps_error": "[ERROR] 全部索引源均失败: {error}",
        "deps_missing_file": "[ERROR] 依赖清单缺失: {path}",
        "step_frontend": "安装前端依赖",
        "frontend_skip": "[SKIP] 前端目录不可用: {path}",
        "frontend_exists": "[OK] 前端依赖已就绪（vite 可执行文件在位）",
        "frontend_ok": "[OK] 前端依赖安装完成",
        "frontend_error": "[ERROR] 安装前端依赖失败: {error}",
        "step_browser": "安装浏览器内核",
        "browser_skip": "[SKIP] playwright 未安装，跳过浏览器内核",
        "browser_exists": "[OK] Chromium 内核已存在",
        "browser_ok": "[OK] Chromium 内核安装完成",
        "browser_warn": "[WARN] 浏览器内核安装失败: {error}",
        "browser_hint": "[INFO] browser_read / computer_use 需要它，可稍后执行: {cmd}",
        "step_engines": "安装本地 ASR 引擎包",
        "engines_skip": "[SKIP] 未开启本地 ASR 引擎（加 --with-local-asr 可安装）",
        "engines_plan": "    待安装引擎包: {packages}",
        "engines_ok": "[OK] 本地 ASR 引擎包已安装: {packages}",
        "engines_warn": "[WARN] 引擎包安装失败: {error}",
        "engines_weights_note": "[INFO] FunASR 中文权重由引擎首次调用时自动下载（无需本脚本预置）",
        "step_models": "下载模型",
        "model_start": "    {name}（{size}MB，来源 {source}）",
        "model_ok": "[OK] {name} -> {path}",
        "model_skip": "[SKIP] {name} 已就绪",
        "model_warn": "[WARN] {name} 下载失败: {error}",
        "model_engine_missing": "[SKIP] {name} 需要引擎包 {spec}（未安装，跳过权重下载；加 --with-local-asr 可一并安装）",
        "model_hint": "[INFO] 可在应用内「模型管理」重试，或稍后重跑: python install.py",
        "models_none": "[OK] 供给清单未声明任何模型",
        "step_verify": "验证安装",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] 部分组件验证失败，安装可继续，但上述功能会降级",
        "verify_model_ok": "[OK] 模型就绪: {name}",
        "verify_model_fail": "[FAIL] 模型缺失: {name}（必需项）",
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
        "manifest_error": "[ERROR] 供给清单不可用: {error}",
        "lang_prompt": "请选择语言 / Select language / 言語を選択 / Выберите язык:",
    },
    "en": {
        "lang_name": "English",
        "header_title": "One-Click Install",
        "header_slogan": "Intelligent Infinity, Seamless Collaboration",
        "step_python": "Checking Python version",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}+ required, found: {current}",
        "step_venv": "Creating virtual environment",
        "venv_exists": "[OK] Virtual environment exists: {path}",
        "venv_created": "[OK] Virtual environment created",
        "venv_error": "[ERROR] Failed to create virtual environment: {error}",
        "step_deps": "Installing Python dependencies",
        "deps_index": "    index source {index}",
        "deps_ok": "[OK] Python dependencies installed (probes importable: {probe})",
        "deps_probe_fail": "[ERROR] Install finished but probes fail: {probe}",
        "deps_error": "[ERROR] All index sources failed: {error}",
        "deps_missing_file": "[ERROR] Requirements file missing: {path}",
        "step_frontend": "Installing frontend dependencies",
        "frontend_skip": "[SKIP] Frontend directory unavailable: {path}",
        "frontend_exists": "[OK] Frontend dependencies ready (vite executable present)",
        "frontend_ok": "[OK] Frontend dependencies installed",
        "frontend_error": "[ERROR] Failed to install frontend dependencies: {error}",
        "step_browser": "Installing browser engine",
        "browser_skip": "[SKIP] playwright not installed, skipping browser engine",
        "browser_exists": "[OK] Chromium engine already present",
        "browser_ok": "[OK] Chromium engine installed",
        "browser_warn": "[WARN] Browser engine install failed: {error}",
        "browser_hint": "[INFO] browser_read / computer_use need it; run later: {cmd}",
        "step_engines": "Installing local ASR engine packages",
        "engines_skip": "[SKIP] Local ASR engines disabled (add --with-local-asr)",
        "engines_plan": "    engine packages: {packages}",
        "engines_ok": "[OK] Local ASR engine packages installed: {packages}",
        "engines_warn": "[WARN] Engine package install failed: {error}",
        "engines_weights_note": "[INFO] FunASR Chinese weights are fetched on first use by the engine",
        "step_models": "Downloading models",
        "model_start": "    {name} ({size}MB, source {source})",
        "model_ok": "[OK] {name} -> {path}",
        "model_skip": "[SKIP] {name} already present",
        "model_warn": "[WARN] {name} download failed: {error}",
        "model_engine_missing": "[SKIP] {name} needs engine package {spec} (not installed; skipping weights, add --with-local-asr)",
        "model_hint": "[INFO] Retry from the in-app model manager, or re-run: python install.py",
        "models_none": "[OK] Supply manifest declares no models",
        "step_verify": "Verifying installation",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] Some components failed verification; affected features degrade",
        "verify_model_ok": "[OK] Model ready: {name}",
        "verify_model_fail": "[FAIL] Required model missing: {name}",
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
        "manifest_error": "[ERROR] Supply manifest unavailable: {error}",
        "lang_prompt": "Select language / 选择语言 / 言語を選択 / Выберите язык:",
    },
    "ja": {
        "lang_name": "日本語",
        "header_title": "ワンクリックインストール",
        "header_slogan": "無限の知性、シームレスなコラボレーション",
        "step_python": "Python バージョンを確認",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Python {min}以上が必要です。現在: {current}",
        "step_venv": "仮想環境を作成",
        "venv_exists": "[OK] 仮想環境が存在します: {path}",
        "venv_created": "[OK] 仮想環境を作成しました",
        "venv_error": "[ERROR] 仮想環境の作成に失敗: {error}",
        "step_deps": "Python 依存関係をインストール",
        "deps_index": "    インデックス {index}",
        "deps_ok": "[OK] Python 依存関係をインストールしました（探針 {probe}）",
        "deps_probe_fail": "[ERROR] インストール後の探針インポートに失敗: {probe}",
        "deps_error": "[ERROR] 全インデックスが失敗: {error}",
        "deps_missing_file": "[ERROR] 依存関係ファイルが見つかりません: {path}",
        "step_frontend": "フロントエンド依存関係をインストール",
        "frontend_skip": "[SKIP] フロントエンドが利用できません: {path}",
        "frontend_exists": "[OK] フロントエンド依存関係は準備済み（vite 実行ファイルあり）",
        "frontend_ok": "[OK] フロントエンド依存関係をインストールしました",
        "frontend_error": "[ERROR] フロントエンド依存関係のインストールに失敗: {error}",
        "step_browser": "ブラウザエンジンをインストール",
        "browser_skip": "[SKIP] playwright 未インストールのためブラウザエンジンを省略",
        "browser_exists": "[OK] Chromium エンジンは既に存在します",
        "browser_ok": "[OK] Chromium エンジンをインストールしました",
        "browser_warn": "[WARN] ブラウザエンジンのインストールに失敗: {error}",
        "browser_hint": "[INFO] browser_read / computer_use に必要。後で実行: {cmd}",
        "step_engines": "ローカル ASR エンジンをインストール",
        "engines_skip": "[SKIP] ローカル ASR は無効（--with-local-asr で有効化）",
        "engines_plan": "    対象パッケージ: {packages}",
        "engines_ok": "[OK] ローカル ASR エンジンをインストールしました: {packages}",
        "engines_warn": "[WARN] エンジンのインストールに失敗: {error}",
        "engines_weights_note": "[INFO] FunASR 中国語重みは初回呼び出し時に自動取得されます",
        "step_models": "モデルをダウンロード",
        "model_start": "    {name}（{size}MB、ソース {source}）",
        "model_ok": "[OK] {name} -> {path}",
        "model_skip": "[SKIP] {name} は既に準備済み",
        "model_warn": "[WARN] {name} のダウンロードに失敗: {error}",
        "model_engine_missing": "[SKIP] {name} にはエンジン {spec} が必要（未導入のため重みを省略。--with-local-asr で導入可）",
        "model_hint": "[INFO] アプリ内のモデル管理で再試行、または再実行: python install.py",
        "models_none": "[OK] 供給マニフェストにモデル宣言がありません",
        "step_verify": "インストールを検証",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] 一部の検証に失敗しましたが続行します（該当機能は低下）",
        "verify_model_ok": "[OK] モデル準備完了: {name}",
        "verify_model_fail": "[FAIL] 必須モデルがありません: {name}",
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
        "manifest_error": "[ERROR] 供給マニフェストを利用できません: {error}",
        "lang_prompt": "言語を選択 / Select language / 选择语言 / Выберите язык:",
    },
    "ru": {
        "lang_name": "Русский",
        "header_title": "Установка в один клик",
        "header_slogan": "Бесконечный интеллект, бесшовное сотрудничество",
        "step_python": "Проверка версии Python",
        "python_ok": "[OK] Python {version}",
        "python_error": "[ERROR] Требуется Python {min}+, найдено: {current}",
        "step_venv": "Создание виртуального окружения",
        "venv_exists": "[OK] Виртуальное окружение существует: {path}",
        "venv_created": "[OK] Виртуальное окружение создано",
        "venv_error": "[ERROR] Ошибка создания виртуального окружения: {error}",
        "step_deps": "Установка зависимостей Python",
        "deps_index": "    индекс {index}",
        "deps_ok": "[OK] Зависимости установлены (проверка импорта: {probe})",
        "deps_probe_fail": "[ERROR] Установка завершена, но проверка импорта не прошла: {probe}",
        "deps_error": "[ERROR] Все источники индекса не удались: {error}",
        "deps_missing_file": "[ERROR] Файл зависимостей отсутствует: {path}",
        "step_frontend": "Установка зависимостей фронтенда",
        "frontend_skip": "[SKIP] Каталог фронтенда недоступен: {path}",
        "frontend_exists": "[OK] Зависимости фронтенда готовы (есть исполняемый файл vite)",
        "frontend_ok": "[OK] Зависимости фронтенда установлены",
        "frontend_error": "[ERROR] Ошибка установки зависимостей фронтенда: {error}",
        "step_browser": "Установка браузерного движка",
        "browser_skip": "[SKIP] playwright не установлен, браузерный движок пропущен",
        "browser_exists": "[OK] Движок Chromium уже есть",
        "browser_ok": "[OK] Движок Chromium установлен",
        "browser_warn": "[WARN] Ошибка установки браузерного движка: {error}",
        "browser_hint": "[INFO] Нужен для browser_read / computer_use; выполните позже: {cmd}",
        "step_engines": "Установка локальных движков ASR",
        "engines_skip": "[SKIP] Локальный ASR отключён (включите --with-local-asr)",
        "engines_plan": "    пакеты движков: {packages}",
        "engines_ok": "[OK] Локальные движки ASR установлены: {packages}",
        "engines_warn": "[WARN] Ошибка установки пакетов движков: {error}",
        "engines_weights_note": "[INFO] Веса FunASR загружаются движком при первом вызове",
        "step_models": "Загрузка моделей",
        "model_start": "    {name}（{size}MB, источник {source}）",
        "model_ok": "[OK] {name} -> {path}",
        "model_skip": "[SKIP] {name} уже готова",
        "model_warn": "[WARN] Ошибка загрузки {name}: {error}",
        "model_engine_missing": "[SKIP] {name} требует пакет движка {spec} (не установлен; веса пропущены, добавьте --with-local-asr)",
        "model_hint": "[INFO] Повторите в менеджере моделей приложения или: python install.py",
        "models_none": "[OK] В манифесте нет объявленных моделей",
        "step_verify": "Проверка установки",
        "verify_ok": "[OK] {name}",
        "verify_fail": "[FAIL] {name}",
        "verify_warn": "[WARN] Часть компонентов не прошла проверку, продолжаем",
        "verify_model_ok": "[OK] Модель готова: {name}",
        "verify_model_fail": "[FAIL] Обязательная модель отсутствует: {name}",
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
        "manifest_error": "[ERROR] Манифест поставки недоступен: {error}",
        "lang_prompt": "Выберите язык / Select language / 选择语言 / 言語を選択:",
    },
}

# 当前语言 (默认中文)
currentLang = "zh"


def t(key, **kwargs):
    """获取翻译文本"""
    text = TRANSLATIONS[currentLang].get(key, key)
    if kwargs:
        return text.format(**kwargs)
    return text


def selectLanguage():
    """交互式语言选择"""
    global currentLang

    print_logo(subtitle="Neurova Installer")

    print("    " + c(t("lang_prompt"), Colors.SKY_BLUE) + "\n")
    print("    " + c("[1]", Colors.SKY_BLUE_BRIGHT) + " 中文 (Chinese)")
    print("    " + c("[2]", Colors.SKY_BLUE_BRIGHT) + " English")
    print("    " + c("[3]", Colors.SKY_BLUE_BRIGHT) + " 日本語 (Japanese)")
    print("    " + c("[4]", Colors.SKY_BLUE_BRIGHT) + " Русский (Russian)\n")

    while True:
        try:
            choice = input("    " + c("1-4:", Colors.SKY_BLUE) + " ").strip()
            if choice in ("1", "2", "3", "4"):
                currentLang = {"1": "zh", "2": "en", "3": "ja", "4": "ru"}[choice]
                break
            print("    " + c("1-4", Colors.YELLOW))
        except (EOFError, KeyboardInterrupt):
            # 非交互模式，默认中文
            currentLang = "zh"
            break

    print(f"\n    {c('->', Colors.SKY_BLUE)} {c(TRANSLATIONS[currentLang]['lang_name'], Colors.SKY_BLUE_BRIGHT + Colors.BOLD)}\n")


def printHeader():
    """打印安装头信息"""
    print_logo(subtitle=t("header_slogan"), double_subtitle=t("header_title"))


# ==================== 供给清单（单源消费） ====================


def loadSupplyManifest() -> dict:
    """读取 models/MANIFEST.json（与 Windows 首启链路同一份）。

    解析失败与文件缺失都点名抛出：字段对不上时表现也是「清单不存在」，
    排查会被引向文件缺失而非契约错位。
    """
    if not SUPPLY_MANIFEST.exists():
        raise RuntimeError(f"{SUPPLY_MANIFEST} 不存在")
    try:
        return json.loads(SUPPLY_MANIFEST.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{SUPPLY_MANIFEST} 解析失败: {e}") from e


def pipIndexCandidates(manifest: dict) -> list:
    """pip 索引候选（镜像在前、官方兜底）——与首启链路同一份声明。"""
    pip = (manifest.get("runtime") or {}).get("pip") or {}
    urls = pip.get("indexUrls") or []
    if not urls:
        raise RuntimeError("清单缺少 runtime.pip.indexUrls")
    return list(urls)


def probeModules(manifest: dict) -> list:
    """依赖就绪探针的 import 面——清单声明，不在这里再抄一份。"""
    pip = (manifest.get("runtime") or {}).get("pip") or {}
    probe = pip.get("probe") or []
    if not probe:
        raise RuntimeError("清单缺少 runtime.pip.probe")
    return list(probe)


def manifestModels(manifest: dict) -> list:
    """模型清单项（缺失即空列表，不伪造默认项）。"""
    return list(manifest.get("models") or [])


def enginePackages(manifest: dict) -> list:
    """本地 ASR 引擎包声明（清单 runtime.asr.enginePackages）。

    spec = pip 规格串，import = 就绪探针名；两者同源，install.py 不另抄名单。
    """
    asr = (manifest.get("runtime") or {}).get("asr") or {}
    return list(asr.get("enginePackages") or [])


# ==================== 步骤实现 ====================


def checkPythonVersion() -> bool:
    """检查 Python 版本"""
    current = sys.version_info[:2]
    if current < MIN_PYTHON_VERSION:
        print(t("python_error", min=f"{MIN_PYTHON_VERSION[0]}.{MIN_PYTHON_VERSION[1]}", current=f"{current[0]}.{current[1]}"))
        return False
    print(t("python_ok", version=f"{current[0]}.{current[1]}"))
    return True


def createVenv() -> bool:
    """创建虚拟环境"""
    if get_venv_python().exists():
        print(t("venv_exists", path=str(VENV_DIR)))
        return True
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
            cwd=str(PROJECT_ROOT),
        )
        print(t("venv_created"))
        return True
    except subprocess.CalledProcessError as e:
        print(t("venv_error", error=str(e)))
        return False


def installPythonDeps(manifest: dict) -> bool:
    """安装 Python 依赖：按清单索引候选依次回退，装完用清单探针验证。"""
    venvPython = get_venv_python()
    if not venvPython.exists():
        print(t("deps_error", error=f"Python not found: {venvPython}"))
        return False

    req = PROJECT_ROOT / REQUIREMENTS_FILE
    if not req.exists():
        print(t("deps_missing_file", path=str(req)))
        return False

    probes = probeModules(manifest)
    failures = []
    for index in pipIndexCandidates(manifest):
        print(t("deps_index", index=index))
        ok = installWithProgress(
            t("step_deps"),
            [
                str(venvPython), "-m", "pip", "install",
                "--disable-pip-version-check", "--index-url", index, "-r", str(req),
            ],
            cwd=str(PROJECT_ROOT),
        )
        if not ok:
            failures.append(index)
            continue
        probe = subprocess.run(
            [str(venvPython), "-c", f"import {', '.join(probes)}"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
        )
        if probe.returncode == 0:
            print(t("deps_ok", probe=", ".join(probes)))
            return True
        print(t("deps_probe_fail", probe=", ".join(probes)))
        print(probe.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or "")
        return False

    print(t("deps_error", error=" | ".join(failures)))
    return False


def frontendViteBin() -> Path:
    """前端就绪判据：vite 可执行文件在场（半损坏 node_modules 会骗过目录存在性）。"""
    return FRONTEND_DIR / "node_modules" / ".bin" / (
        "vite.cmd" if sys.platform == "win32" else "vite"
    )


def installFrontendDeps() -> bool:
    """安装前端依赖：判据与 start.py 同契约（vite 在位 + lock 优先 npm ci）。"""
    if not (FRONTEND_DIR / "package.json").exists():
        print(t("frontend_skip", path=str(FRONTEND_DIR)))
        return True
    if frontendViteBin().exists():
        print(t("frontend_exists"))
        return True

    lock = FRONTEND_DIR / "package-lock.json"
    cmd = ["npm", "ci"] if lock.exists() else ["npm", "install"]
    if not installWithProgress(t("step_frontend"), cmd, cwd=str(FRONTEND_DIR)):
        print(t("frontend_error", error=" ".join(cmd)))
        return False
    print(t("frontend_ok"))
    return True


def installBrowserEngine() -> bool:
    """安装 Playwright Chromium 内核（browser_read / computer_use 的运行时依赖）。

    非致命：装不上只降级浏览器类工具，不影响后端与界面。
    """
    venvPython = get_venv_python()
    probe = subprocess.run(
        [str(venvPython), "-c", "import playwright"], capture_output=True
    )
    if probe.returncode != 0:
        print(t("browser_skip"))
        return True

    from scripts.setup_computer_use import chromium_installed

    if chromium_installed():
        print(t("browser_exists"))
        return True

    if installWithProgress(
        t("step_browser"), [str(venvPython), "-m", "playwright", "install", "chromium"]
    ):
        print(t("browser_ok"))
        return True

    print(t("browser_warn", error="playwright install chromium"))
    print(t("browser_hint", cmd=f"{venvPython} -m playwright install chromium"))
    return True


def installAsrEnginePackages(manifest: dict) -> bool:
    """安装模型声明的本地 ASR 引擎包（默认不装：体积大且属可选能力）。"""
    entries = enginePackages(manifest)
    if not entries:
        print(t("engines_skip"))
        return True

    specs = [e["spec"] for e in entries]
    probes = [e["import"] for e in entries]
    print(t("engines_plan", packages=", ".join(specs)))
    venvPython = get_venv_python()
    index = pipIndexCandidates(manifest)[0]
    ok = installWithProgress(
        t("step_engines"),
        [str(venvPython), "-m", "pip", "install", "--disable-pip-version-check",
         "--index-url", index, *specs],
        cwd=str(PROJECT_ROOT),
    )
    if not ok:
        print(t("engines_warn", error=", ".join(specs)))
        return True  # 非致命：ASR 是可选能力，其余功能不受影响

    # 装完按声明探针复核（不是"pip 返回 0 就算装好"）
    probe = subprocess.run(
        [str(venvPython), "-c", f"import {', '.join(probes)}"], capture_output=True
    )
    if probe.returncode != 0:
        detail = probe.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        print(t("engines_warn", error=", ".join(probes) + " " + " ".join(detail)))
        return True

    print(t("engines_ok", packages=", ".join(specs)))
    if any(s.startswith("funasr") for s in specs):
        print(t("engines_weights_note"))
    return True


def entryFor(manifest: dict, modelId: str) -> Optional[dict]:
    """按 id 取清单模型项（找不到返回 None，不伪造默认项）。"""
    for entry in manifestModels(manifest):
        if entry["id"] == modelId:
            return entry
    return None


def engineSpecFor(manifest: dict, modelId: str) -> Optional[str]:
    """模型 → 其权重加载所依赖的引擎包规格（清单声明，无依赖返回 None）。

    模型项只按名引用引擎（`engineImport`），规格文本只在 `runtime.asr.
    enginePackages` 声明一处——两处都写规格串就是第二份定义。
    """
    entry = entryFor(manifest, modelId)
    engineImport = (entry or {}).get("engineImport")
    if not engineImport:
        return None
    for pkg in enginePackages(manifest):
        if pkg["import"] == engineImport:
            return pkg["spec"]
    return None


def modelWorker(modelId: str) -> int:
    """在 venv 解释器内下载单个模型（由 install.py 自身以子进程方式调用）。

    退出码即事实：0 = 模型真的就绪。这里绝不伪造成功。
    """
    from neurova.asr.model_downloader import ASR_MODEL_REGISTRY, ensure_model as ensureAsrModel
    from neurova.tts.model_downloader import MODEL_REGISTRY, get_model_downloader

    if modelId in MODEL_REGISTRY:
        path = get_model_downloader().ensure_model(modelId)
        print(f"[worker] {modelId} -> {path}")
        return 0

    if modelId in ASR_MODEL_REGISTRY:
        engineSpec = engineSpecFor(loadSupplyManifest(), modelId)
        try:
            model = ensureAsrModel(modelId.split("-", 1)[1])
        except ImportError as e:
            print(
                f"[worker] {modelId} 需要引擎包 {engineSpec or e.name}，"
                f"当前解释器未安装。安装后重试: "
                f"python install.py --with-local-asr",
                file=sys.stderr,
            )
            return 1
        if model is None:
            print(f"[worker] {modelId} 权重下载失败（whisper.load_model 返回 None）", file=sys.stderr)
            return 1
        print(f"[worker] {modelId} -> {ASR_MODEL_REGISTRY[modelId]['download_root']}")
        return 0

    print(f"[worker] 未知模型: {modelId}", file=sys.stderr)
    return 1


def engineImportable(venvPython: Path, manifest: dict, modelId: str) -> bool:
    """模型声明的引擎包在该解释器里是否可导入（不导入即权重也拿不到）。"""
    engineImport = (entryFor(manifest, modelId) or {}).get("engineImport")
    if not engineImport:
        return True
    probe = subprocess.run(
        [str(venvPython), "-c", f"import {engineImport}"], capture_output=True
    )
    return probe.returncode == 0


def downloadModels(manifest: dict, includeAsr: bool) -> bool:
    """按清单逐件下载模型（每件走 venv 子进程的真下载器）。"""
    # ASR 权重即「依赖引擎包才拿得到的那批」——按清单声明判定，不按来源字符串
    entries = [
        e for e in manifestModels(manifest)
        if not e.get("engineImport") or includeAsr
    ]
    if not entries:
        print(t("models_none"))
        return True

    venvPython = get_venv_python()
    allOk = True
    for entry in entries:
        name = entry["id"]
        # 权重加载依赖引擎包时，引擎缺席就跳过（不是失败）——否则默认安装会为
        # 一个用户没选择安装的可选能力报 WARN，把噪音当故障
        engineSpec = engineSpecFor(manifest, name)
        if engineSpec and not engineImportable(venvPython, manifest, name):
            print(t("model_engine_missing", name=name, spec=engineSpec))
            continue
        print(t("model_start", name=name, size=entry.get("size_mb", "?"), source=entry.get("source", "?")))
        ok = installWithProgress(
            t("step_models"),
            [str(venvPython), str(Path(__file__).resolve()), "--model-worker", name,
             "--lang", currentLang],
            cwd=str(PROJECT_ROOT),
        )
        if ok:
            print(t("model_ok", name=name, path=str(PROJECT_ROOT / entry["path"])))
        else:
            print(t("model_warn", name=name, error=f"worker exit != 0（见上方日志）"))
            print(t("model_hint"))
            allOk = False
    return allOk


def verifyInstallation(manifest: dict) -> bool:
    """验证安装：依赖探针来自清单，模型就绪判据来自真交付物。"""
    venvPython = get_venv_python()
    if not venvPython.exists():
        print(t("verify_fail", name=str(venvPython)))
        return False

    allOk = True
    for module in probeModules(manifest):
        probe = subprocess.run(
            [str(venvPython), "-c", f"import {module}"], capture_output=True
        )
        if probe.returncode == 0:
            print(t("verify_ok", name=module))
        else:
            print(t("verify_fail", name=module))
            allOk = False

    ok, failed = probeModels(venvPython, manifest)
    if failed:
        allOk = False
    for name in ok:
        print(t("verify_model_ok", name=name))
    for name in failed:
        print(t("verify_model_fail", name=name))
    return allOk


# 模型就绪探针：只在 venv 子进程里跑（宿主解释器没有下载器依赖，进程内判会假失败）
_MODEL_PROBE_SCRIPT = (
    "import json,sys\n"
    "from neurova.tts.model_downloader import MODEL_REGISTRY, get_model_downloader\n"
    "from neurova.asr.model_downloader import ASR_MODEL_REGISTRY, is_model_ready\n"
    "downloader = get_model_downloader()\n"
    "ready = []\n"
    "for modelId in json.loads(sys.argv[1]):\n"
    "    if modelId in MODEL_REGISTRY:\n"
    "        ok = downloader.is_model_available(modelId)\n"
    "    elif modelId in ASR_MODEL_REGISTRY:\n"
    "        ok = is_model_ready(modelId.split('-', 1)[1])\n"
    "    else:\n"
    "        ok = False\n"
    "    if ok:\n"
    "        ready.append(modelId)\n"
    "print(json.dumps(ready))\n"
)


def probeModels(venvPython: Path, manifest: dict) -> tuple:
    """在 venv 内探测模型就绪。

    Returns:
        (全部就绪的模型名, 必需项缺失的模型名)；探针不可用时把全部必需项计为缺失
        （宁可报缺，不可谎报就绪）。
    """
    entries = manifestModels(manifest)
    required = [e["id"] for e in entries if e.get("required")]
    probe = subprocess.run(
        [str(venvPython), "-c", _MODEL_PROBE_SCRIPT,
         json.dumps([e["id"] for e in entries])],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
    )
    if probe.returncode != 0:
        return [], required

    ready = set(json.loads(probe.stdout.decode("utf-8", "replace").strip().splitlines()[-1]))
    return sorted(ready), sorted(set(required) - ready)


# ==================== 主流程 ====================


def buildSteps(args, manifest: dict) -> list:
    """按参数装配步骤表（顺序即依赖顺序：deps 需要解释器，模型需要依赖）。"""
    steps = [("python", checkPythonVersion), ("venv", createVenv)]
    if not args.skip_deps:
        steps.append(("deps", lambda: installPythonDeps(manifest)))
    if not args.skip_frontend:
        steps.append(("frontend", installFrontendDeps))
    if not args.skip_browser:
        steps.append(("browser", installBrowserEngine))
    if args.with_local_asr:
        steps.append(("engines", lambda: installAsrEnginePackages(manifest)))
    if not args.skip_models:
        steps.append(("models", lambda: downloadModels(manifest, includeAsr=not args.skip_asr)))
    return steps


def printCompletion() -> None:
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


def main() -> int:
    global currentLang

    parser = argparse.ArgumentParser(description="Neurova One-Click Install")
    parser.add_argument("--skip-models", action="store_true", help="Skip model download")
    parser.add_argument("--skip-asr", action="store_true", help="Skip ASR model download")
    parser.add_argument("--skip-frontend", action="store_true", help="Skip frontend install")
    parser.add_argument("--skip-browser", action="store_true", help="Skip Playwright Chromium install")
    parser.add_argument("--skip-deps", action="store_true", help="Skip Python dependency install")
    parser.add_argument("--with-local-asr", action="store_true",
                        help="Install local ASR engine packages (funasr/whisper, large)")
    parser.add_argument("--verify-only", action="store_true", help="Only run the verification step")
    parser.add_argument("--model-worker", metavar="MODEL_ID",
                        help="Internal: download one model in the current interpreter")
    parser.add_argument("--lang", choices=["zh", "en", "ja", "ru"], help="Language (skip selection)")
    args = parser.parse_args()

    # 语言选择（--model-worker 是内部子进程调用，跳过交互与横幅）
    if args.lang:
        currentLang = args.lang
    elif args.model_worker is None:
        selectLanguage()

    if args.model_worker:
        return modelWorker(args.model_worker)

    printHeader()

    try:
        manifest = loadSupplyManifest()
    except RuntimeError as e:
        print(t("manifest_error", error=str(e)))
        return 1

    if args.verify_only:
        return 0 if verifyInstallation(manifest) else 1

    steps = buildSteps(args, manifest)
    total = len(steps)
    for i, (name, func) in enumerate(steps, 1):
        print(f"\n[{i}/{total}] {t('step_' + name)}...")
        try:
            if not func():
                print(f"\n{t('error_install', name=name)}")
                return 1
        except KeyboardInterrupt:
            print(t("error_cancel"))
            return 1
        except Exception as e:  # noqa: BLE001 - 逐步报错并点名步骤
            print(t("error_generic", name=name, error=str(e)))
            return 1

    print(f"\n[{total + 1}/{total + 1}] {t('step_verify')}...")
    if not verifyInstallation(manifest):
        print(f"\n{t('verify_warn')}")

    printCompletion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
