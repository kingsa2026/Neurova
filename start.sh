#!/usr/bin/env bash
# ============================================================================
# Neurova 一键启动脚本 (Linux/macOS)
# ============================================================================
#
# 使用方式:
#   ./start.sh              # 同时启动前后端
#   ./start.sh --backend    # 仅启动后端
#   ./start.sh --frontend   # 仅启动前端
#   ./start.sh --cli        # 启动后端 + CLI 聊天
#   ./start.sh --chat       # 启动前后端 + 自动打开浏览器
#   ./start.sh --check      # 检查服务状态
#   ./start.sh --skip-install  # 跳过自动环境检查
#
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 查找 Python 3.10+
PYTHON_CMD=""
for cmd in python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

# 如果没找到合适的 Python，尝试使用 venv 中的
if [ -z "$PYTHON_CMD" ] && [ -x ".venv/bin/python" ]; then
    version=$(".venv/bin/python" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
    if [ "$version" -ge 10 ] 2>/dev/null; then
        PYTHON_CMD=".venv/bin/python"
    fi
fi

if [ -z "$PYTHON_CMD" ]; then
    echo ""
    echo "  ✗ 未找到 Python 3.10 或更高版本"
    echo "  请安装 Python 3.10+ 后重试"
    echo "  下载地址: https://www.python.org/downloads/"
    echo ""
    exit 1
fi

# 运行 start.py，传递所有参数
exec "$PYTHON_CMD" start.py "$@"
