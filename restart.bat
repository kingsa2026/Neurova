@echo off
REM ============================================================================
REM Neurova 一键重启脚本 (Windows)
REM 自动提升管理员权限，杀掉旧进程，重新启动前后端
REM ============================================================================

cd /d "%~dp0"

REM 检查是否以管理员运行
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 正在请求管理员权限...
    REM 提权路径同样 venv 优先 + 窗口驻留：与 start.bat 2026-09-16 闪退修复同款。
    REM 旧版此处跑裸 python（落到 PATH 上 ABI 不可控的解释器），且报错随
    REM /c 窗口关闭即灭，故障现场不可读。
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe start.py --restart --yes) else (python start.py --restart --yes) & echo [诊断驻留] start.py 已退出，完整日志见 logs\launcher.log & pause' -Verb RunAs"
    exit /b
)

REM 已经是管理员，直接重启（--yes 跳过交互确认）
REM venv 优先：与 start.bat 同判据，PATH 上的 python 在本机不可控
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe start.py --restart --yes
) else (
    python start.py --restart --yes
)
REM 驻留窗口：start.py 快速退出路径（启动失败/异常）下，不让错误文本随窗口
REM 关闭而灭；输出同时镜像在 logs\launcher.log
echo.
echo [诊断驻留] start.py 已退出，窗口保持打开以便查看错误；完整日志: logs\launcher.log
pause
