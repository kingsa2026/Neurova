@echo off
REM ============================================================================
REM Neurova 一键重启脚本 (Windows)
REM 自动提升管理员权限，杀掉旧进程，重新启动
REM ============================================================================

cd /d "%~dp0"

REM 检查是否以管理员运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 正在请求管理员权限...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && python start.py --restart --backend --yes' -Verb RunAs"
    exit /b
)

REM 已经是管理员，直接重启（--yes 跳过交互确认）
python start.py --restart --backend --yes
