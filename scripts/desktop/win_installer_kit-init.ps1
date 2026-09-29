# Neurova Windows 打包机初始化（Issue #332）
# 逐件装齐构建链：git / Node.js 20 / Rust(msvc) / NSIS / VS Build Tools(MSVC) / Python
# 任一步失败即中止（$ErrorActionPreference = "Stop"），不产来源不明的包。
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Step($name, $block) {
  Write-Host ""
  Write-Host "=== $name ===" -ForegroundColor Cyan
  & $block
  if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) { throw "$name 失败（exit $LASTEXITCODE）" }
}

Step "winget 可用性" {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget 缺席 —— 需要 Windows 10 1809+ / Windows 11，或手工装 App Installer"
  }
  winget --version
}

Step "git" {
  if (Get-Command git -ErrorAction SilentlyContinue) { git --version; return }
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
}

Step "Node.js 20" {
  if (Get-Command node -ErrorAction SilentlyContinue) { node -v; return }
  winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-package-agreements --accept-source-agreements
}

Step "Rust (msvc)" {
  if (Get-Command cargo -ErrorAction SilentlyContinue) { cargo --version; return }
  winget install --id Rustlang.Rustup -e --source winget --accept-package-agreements --accept-source-agreements
  # rustup 默认装的是 MSVC 目标；确认工具链
  & "$env:USERPROFILE\.cargo\bin\rustup.exe" default stable-msvc
}

Step "MSVC 生成工具（C++ 编译 tauri 原生部分所需）" {
  if (Get-Command cl.exe -ErrorAction SilentlyContinue) { cl; return }
  winget install --id Microsoft.VisualStudio.2022.BuildTools -e --source winget `
    --accept-package-agreements --accept-source-agreements `
    --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
}

Step "NSIS" {
  if (Get-Command makensis -ErrorAction SilentlyContinue) { makensis /VERSION; return }
  winget install --id NSIS.NSIS -e --source winget --accept-package-agreements --accept-source-agreements
}

Step "Python 3.12" {
  if (Get-Command python -ErrorAction SilentlyContinue) { python -V; return }
  winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
}

Write-Host ""
Write-Host "[ok] 工具链初始化完成。请重开一个 PowerShell（PATH 已更新），再跑：" -ForegroundColor Green
Write-Host "     python scripts\desktop\win_installer_kit.py run --repo <克隆目录>"
