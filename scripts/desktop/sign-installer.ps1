# Neurova 安装包签名（自签名证书；指纹见 desktop/ 签名记录）
# 用法: powershell -File scripts/desktop/sign-installer.ps1 -Path <installer>
param(
  [Parameter(Mandatory = $true)][string]$Path,
  [string]$Thumbprint = "11F098DB1C2E2EB47BD74CF82059A81A046A8757",
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$signtool = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
if (-not $signtool) { throw "signtool.exe 未找到（需 Windows SDK）" }
& $signtool sign /fd SHA256 /td SHA256 /tr $TimestampUrl /sha1 $Thumbprint $Path
& $signtool verify /pa /all $Path
