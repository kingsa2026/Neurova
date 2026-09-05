@echo off
rem Neurova WPF installer shell build (net48 via in-box csc, no SDK needed)
rem NOTE: keep this file ASCII-only (cmd reads it in the ANSI codepage)
rem Usage:
rem   build.cmd                          - shell only (sidecar kernel mode)
rem   build.cmd <kernel.exe> [icon.png]  - embed kernel (+icon) as resources
rem                                        -> single-file installer mode
rem Embed uses csc /resource (no IL merge needed: kernel extracted at runtime).

setlocal
set OUTDIR=%~dp0bin
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
  echo [error] csc.exe not found
  exit /b 1
)

set GAC=%WINDIR%\Microsoft.NET\assembly\GAC_MSIL
set GAC64=%WINDIR%\Microsoft.NET\assembly\GAC_64

set PF=%GAC%\PresentationFramework\v4.0_4.0.0.0__31bf3856ad364e35\PresentationFramework.dll
set PC=%GAC64%\PresentationCore\v4.0_4.0.0.0__31bf3856ad364e35\PresentationCore.dll
set WB=%GAC%\WindowsBase\v4.0_4.0.0.0__31bf3856ad364e35\WindowsBase.dll
set SX=%GAC%\System.Xaml\v4.0_4.0.0.0__b77a5c561934e089\System.Xaml.dll

for %%A in ("%PF%" "%PC%" "%WB%" "%SX%") do (
  if not exist %%A (
    echo [error] missing reference: %%A
    exit /b 1
  )
)

rem NOTE: do NOT self-reference %RESOURCES%/%ICON% inside a parenthesized
rem block — cmd expands them at parse time (pre-block values). Keep appends
rem outside blocks.
set RESOURCES=
set ICON=
if not "%~1"=="" (
  set RESOURCES=/resource:"%~1",Neurova.Installer.kernel-setup.exe
  set ICON=%~2
)
if "%ICON%"=="" set ICON=%~dp0..\icons\icon.ico
if exist "%ICON%" set RESOURCES=%RESOURCES% /resource:"%ICON%",Neurova.Installer.neurova-logo.png
if not "%~1"=="" (
  echo [info] embed mode: kernel=%~1 icon=%ICON%
) else (
  echo [info] sidecar mode: no kernel embedded
)

"%CSC%" /nologo /target:winexe /platform:anycpu /optimize+ ^
  /langversion:5 ^
  /out:"%OUTDIR%\installer-shell.exe" ^
  /win32icon:..\icons\icon.ico ^
  /r:"%PF%" /r:"%PC%" /r:"%WB%" /r:"%SX%" ^
  /r:System.dll /r:System.Core.dll /r:System.Drawing.dll /r:System.Windows.Forms.dll ^
  %RESOURCES% ^
  App.cs MainWindow.cs

if errorlevel 1 (
  echo [error] compile failed
  exit /b 1
)
echo [ok] %OUTDIR%\installer-shell.exe
endlocal
