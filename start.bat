@echo off
REM ============================================================================
REM Neurova 一键启动脚本 (Windows)
REM ============================================================================

cd /d "%~dp0"

REM 如果传了 --restart 或 --restart --backend，需要管理员权限
echo %* | findstr /i "restart" >nul
if %errorLevel% equ 0 (
    net session >nul 2>&1
    if %errorLevel% neq 0 (
        echo 正在请求管理员权限以重启服务...
        REM 提权路径同样 venv 优先：旧版跑裸 python，在本机会落到 PATH 上
        REM ABI 不稳定的 alpha 解释器；& pause 驻留窗口（2026-09-16 闪退排查）
        powershell -Command "Start-Process cmd -ArgumentList '/c cd /d \"%~dp0\" && if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe start.py %* --yes) else (python start.py %* --yes) & echo [诊断驻留] start.py 已退出，完整日志见 logs\launcher.log & pause' -Verb RunAs"
        exit /b
    )
    REM 已经是管理员，加上 --yes 跳过确认
    if exist ".venv\Scripts\python.exe" (
        .venv\Scripts\python.exe start.py %* --yes
    ) else (
        python start.py %* --yes
    )
    REM 驻留窗口：start.py 快速退出路径（无服务直接启动/启动失败）下
    REM 不让错误文本随 cmd 窗口关闭而灭；输出同时镜像在 logs\launcher.log
    echo.
    echo [诊断驻留] start.py 已退出，窗口保持打开以便查看错误；完整日志: logs\launcher.log
    pause
) else (
    REM 非重启模式，正常启动
    if exist ".venv\Scripts\python.exe" (
        .venv\Scripts\python.exe start.py %*
    ) else (
        python start.py %*
    )
    REM 正常启动会阻塞在"按 Ctrl+C 停止所有服务"；走到这里说明发生了
    REM 快速退出（服务已在运行/启动失败/异常），驻留窗口让故障现场可读
    echo.
    echo [诊断驻留] start.py 已退出，窗口保持打开以便查看错误；完整日志: logs\launcher.log
    pause
)
