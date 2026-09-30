# 把机器/用户级 PATH 合并进当前 PowerShell 进程（Issue #332 实机踩到）。
#
# 为什么每 stage 都要调（不是一次就够）：CNB 的流水线 stage **各自独立**起一个
# PowerShell 进程 —— 同 Runner，但环境不跨 stage 继承。把刷新只写在第一个 stage 里，
# 到第二个 stage 就失效：实测 `python` 在环境自证 stage 里解析成功
# （C:\Python312\python.exe），到 bundle_backend stage 立刻
# `无法将"python"项识别为 cmdlet`（CommandNotFoundException）。
#
# 为什么需要刷新本身：自托管 Runner 以**服务**形态常驻，进程环境在服务启动那一刻
# 定型。此后 `choco install python312` 之类往机器 PATH
# （HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment）写的新条目，
# 正在跑的 Runner 读不到 —— 只有重启服务才会重读。于是出现分裂事实：python.exe
# 在盘上（C:\Python312\python.exe、机器 PATH 里也有这一条），而 `Get-Command python`
# MISSING。失败形态是「工具链缺席」，看着像整机没装 —— 人会去重装、换机器，
# 打一场打不赢的仗，而根因只是环境没继承。
#
# 单一定义：本文件是刷新逻辑的唯一落点；各 stage 只写一行 dot-source，不手抄。

$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath;$env:Path"
Write-Host "[env] PATH 已合并机器/用户级条目（$($env:Path.Split(';').Count) 段）"
