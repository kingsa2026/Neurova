@echo off
REM Neurova Helm Chart 部署脚本 (Windows)

setlocal enabledelayedexpansion

REM 颜色代码
set "RED=[91m"
set "GREEN=[92m"
set "YELLOW=[93m"
set "BLUE=[94m"
set "NC=[0m"

REM 打印带颜色的消息
echo %BLUE%[INFO]%NC% Neurova Helm Chart 部署脚本
echo.

REM 检查 Helm 是否安装
where helm >nul 2>nul
if %errorlevel% neq 0 (
    echo %RED%[ERROR]%NC% Helm 未安装
    echo %BLUE%[INFO]%NC% 请先安装 Helm: https://helm.sh/docs/intro/install/
    pause
    exit /b 1
)

echo %GREEN%[SUCCESS]%NC% Helm 已安装
echo.

REM 解析参数
set "COMMAND="
set "ENVIRONMENT=development"
set "NAMESPACE=neurova"
set "RELEASE_NAME=neurova"

:parse_args
if "%~1"=="" goto :check_args
if "%~1"=="deploy" (
    set "COMMAND=deploy"
    shift
    goto :parse_args
)
if "%~1"=="lint" (
    set "COMMAND=lint"
    shift
    goto :parse_args
)
if "%~1"=="status" (
    set "COMMAND=status"
    shift
    goto :parse_args
)
if "%~1"=="uninstall" (
    set "COMMAND=uninstall"
    shift
    goto :parse_args
)
if "%~1"=="template" (
    set "COMMAND=template"
    shift
    goto :parse_args
)
if "%~1"=="-e" (
    set "ENVIRONMENT=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="--environment" (
    set "ENVIRONMENT=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="-n" (
    set "NAMESPACE=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="--namespace" (
    set "NAMESPACE=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="-r" (
    set "RELEASE_NAME=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="--release" (
    set "RELEASE_NAME=%~2"
    shift
    shift
    goto :parse_args
)
if "%~1"=="-h" goto :show_help
if "%~1"=="--help" goto :show_help

echo %RED%[ERROR]%NC% 未知参数: %~1
goto :show_help

:check_args
if "%COMMAND%"=="" goto :show_help

REM 执行命令
if "%COMMAND%"=="lint" goto :lint
if "%COMMAND%"=="deploy" goto :deploy
if "%COMMAND%"=="status" goto :status
if "%COMMAND%"=="uninstall" goto :uninstall
if "%COMMAND%"=="template" goto :template

:lint
echo %BLUE%[INFO]%NC% 检查 Helm Chart 语法...
cd neurova
helm lint
if %errorlevel% equ 0 (
    echo %GREEN%[SUCCESS]%NC% Helm Chart 语法检查通过
) else (
    echo %RED%[ERROR]%NC% Helm Chart 语法检查失败
    cd ..
    pause
    exit /b 1
)
cd ..
pause
exit /b 0

:deploy
echo %BLUE%[INFO]%NC% 部署到 %ENVIRONMENT% 环境...

REM 创建命名空间
kubectl get namespace %NAMESPACE% >nul 2>nul
if %errorlevel% neq 0 (
    echo %BLUE%[INFO]%NC% 创建命名空间: %NAMESPACE%
    kubectl create namespace %NAMESPACE%
)

REM 构建 Helm 命令
set "HELM_CMD=helm upgrade --install %RELEASE_NAME% neurova --namespace %NAMESPACE%"

REM 根据环境选择配置文件
if "%ENVIRONMENT%"=="production" (
    set "HELM_CMD=!HELM_CMD! -f neurova/values-production.yaml"
) else if "%ENVIRONMENT%"=="prod" (
    set "HELM_CMD=!HELM_CMD! -f neurova/values-production.yaml"
) else if "%ENVIRONMENT%"=="development" (
    set "HELM_CMD=!HELM_CMD! -f neurova/values-development.yaml"
) else if "%ENVIRONMENT%"=="dev" (
    set "HELM_CMD=!HELM_CMD! -f neurova/values-development.yaml"
) else (
    echo %YELLOW%[WARNING]%NC% 未知环境: %ENVIRONMENT%，使用默认配置
)

REM 执行部署
echo %BLUE%[INFO]%NC% 执行部署命令...
!HELM_CMD!

if %errorlevel% equ 0 (
    echo %GREEN%[SUCCESS]%NC% 部署成功！
    echo %BLUE%[INFO]%NC% 查看部署状态:
    echo   kubectl get pods -n %NAMESPACE% -l app.kubernetes.io/name=neurova
    echo   helm status %RELEASE_NAME% -n %NAMESPACE%
) else (
    echo %RED%[ERROR]%NC% 部署失败
    pause
    exit /b 1
)
pause
exit /b 0

:status
echo %BLUE%[INFO]%NC% 查看部署状态...
helm status %RELEASE_NAME% -n %NAMESPACE%
kubectl get pods -n %NAMESPACE% -l app.kubernetes.io/name=neurova
pause
exit /b 0

:uninstall
echo %BLUE%[INFO]%NC% 卸载应用...
helm uninstall %RELEASE_NAME% -n %NAMESPACE%
echo %GREEN%[SUCCESS]%NC% 应用已卸载
pause
exit /b 0

:template
echo %BLUE%[INFO]%NC% 渲染模板...
helm template %RELEASE_NAME% neurova -n %NAMESPACE%
pause
exit /b 0

:show_help
echo Neurova Helm Chart 部署脚本
echo.
echo 使用方法:
echo   %~nx0 [命令] [选项]
echo.
echo 命令:
echo   deploy      部署应用
echo   lint        检查 Helm Chart 语法
echo   status      查看部署状态
echo   uninstall   卸载应用
echo   template    渲染模板（不部署）
echo.
echo 选项:
echo   -e, --environment  环境 (production/development) [默认: development]
echo   -n, --namespace    命名空间 [默认: neurova]
echo   -r, --release      Release 名称 [默认: neurova]
echo   -h, --help         显示此帮助信息
echo.
echo 示例:
echo   %~nx0 deploy -e production -n neurova-prod
echo   %~nx0 lint
echo   %~nx0 status -n neurova
echo   %~nx0 uninstall -n neurova
echo.
pause
exit /b 0