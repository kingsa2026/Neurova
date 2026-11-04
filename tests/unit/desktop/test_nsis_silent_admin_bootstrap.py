# -*- coding: utf-8 -*-
"""NSIS 静默模式下的首装管理员凭据通道必须仍然成立。

为什么要有本守卫（实测断裂，且是"构建物不对"的真根因）：

`NeurUI/src-tauri/installer-wpf/MainWindow.cs` 段二以
`Process.Start(kernel, "/S /D=<dir>")` 启动 NSIS 内核——**静默模式**。
而 NSIS 对 `Page custom` 的语义是：`/S` 下**整个自定义页回调（含 PRE /
显示 / LEAVE）一律不执行**。

原 `PageAdminAccount` 把"无历史安装才建 ini"写成了页面函数体里的 `Abort`
分支——它只在**交互式双击**内核时成立。经 WPF 壳调用时页面根本不进，
`$AdminWritten` 永远停在 `.onInit` 的 "0"，安装段 `$AdminWritten == "1"`
判据不成立，于是：

- 安装**成功**（`/S` 退出码 0），
- WPF 完成页照常显示「安装完成」，
- 但 `<安装目录>\\backend\\data\\bootstrap_admin.ini` **根本没有生成**，
- 用户设的管理员账号被静默丢弃，首启无管理员。

真机自证（wine 无 X 驱动，与 CI 容器同条件）：

```
$ wine poc.exe /S /D=C:\\out          # 自定义页内写 C:\\pageA-ran.txt 作探针
$ ls C:\\pageA-ran.txt                 # → 不存在：页面回调一次都没进
$ cat C:\\out\\out.txt                 # → u=[]：页面里 StrCpy 的值也没生效
```

所以凭据**不能**只能由页面回调产生——必须有一条不经页面的通道。
本守卫钉住这条通道：`.onInit` 从内核同目录的 `bootstrap_admin.cred`
（`[bootstrap] username/password`）读凭据，读完即删；WPF 不再把
用户名/密码拼进命令行（P2-4：命令行可被同机进程经 WMI 读取）。
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_NSI = _REPO / "NeurUI" / "src-tauri" / "nsis" / "installer.nsi"
_WPF = _REPO / "NeurUI" / "src-tauri" / "installer-wpf" / "MainWindow.cs"


def _source() -> str:
    return _NSI.read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> str:
    """截取 Function <name> … FunctionEnd 的函数体（不匹配时返回空串）。"""
    m = re.search(
        r"^Function\s+" + re.escape(name) + r"\s*$(.*?)^FunctionEnd\s*$",
        src,
        flags=re.M | re.S,
    )
    return m.group(1) if m else ""


def testOnInitReadsAdminCredentialFromKernelDirIni():
    """静默通道：.onInit 从 $EXEDIR 的临时 INI 读取用户名/密码并立即删除。

    凭据不得走 /NU= /NP= 命令行开关——那会被同机进程经 WMI Win32_Process
    读到明文。
    """
    body = _function_body(_source(), ".onInit")
    assert body, "installer.nsi 缺少 .onInit 函数"
    assert '"$EXEDIR\\bootstrap_admin.cred"' in body, (
        ".onInit 未从内核同目录读取 bootstrap_admin.cred——静默安装拿不到凭据"
    )
    for key in ("username", "password"):
        assert re.search(
            rf'ReadINIStr\s+\$Admin\w+\s+"\$EXEDIR\\bootstrap_admin\.cred"\s+"bootstrap"\s+"{key}"',
            body,
        ), f".onInit 未读取 bootstrap_admin.cred 的 {key} 键"
    assert re.search(r'Delete\s+"\$EXEDIR\\bootstrap_admin\.cred"', body), (
        "读取凭据后必须立即删除临时文件"
    )
    for opt in ("/NU=", "/NP="):
        assert f'"{opt}"' not in body, (
            f".onInit 仍在解析命令行开关 {opt}——凭据会出现在进程 CommandLine 里"
        )


def testWpfNeverPutsCredentialsOnCommandLine():
    """WPF 只能写临时凭据文件；命令行里只允许 /S 与 /D。"""
    src = _WPF.read_text(encoding="utf-8")
    assert "bootstrap_admin.cred" in src, "WPF 未使用临时凭据文件通道"
    assert "Encoding.Unicode" in src, "凭据文件需按 NSIS Unicode 读取的 UTF-16 写入"
    assert re.search(r'Arguments\s*=\s*"/S\s*/D="\s*\+\s*targetDir', src), (
        "WPF 启动内核的命令行应只含 /S 与 /D"
    )
    assert "TryDeleteAdminCredentialFile" in src, "WPF 未在进程退出/启动失败时兜底清理凭据文件"
    for opt in ("/NU=", "/NP="):
        assert f'"{opt}"' not in src, f"WPF 仍把 {opt} 拼进命令行"


def testSilentPathMarksAdminWrittenWithoutPageCallback():
    """静默分支必须自己置 $AdminWritten——不得依赖页面回调链。"""
    body = _function_body(_source(), ".onInit")
    assert body, "installer.nsi 缺少 .onInit 函数"
    silent_marker = re.search(
        r"IfSilent\s+(\w+)", body
    )
    assert silent_marker, (
        ".onInit 未用 IfSilent 区分静默/交互——两种模式下凭据来源不同，"
        "必须显式分叉，不能只靠页面回调"
    )
    label = silent_marker.group(1)
    # 静默分支标签之后必须出现 $AdminWritten 赋值
    tail = body[body.index(label):] if label in body else ""
    assert re.search(r'StrCpy\s+\$AdminWritten\s+"?1"?', tail), (
        f"IfSilent 跳到的分支 {label}: 中没有置 $AdminWritten=1。"
        "安装段判据是 $AdminWritten == \"1\"，不置位则 ini 不写、"
        "安装却报成功——用户设的账号被静默丢弃"
    )


def testPageLeaveStillOwnsInteractiveCredentialContract():
    """交互路径不能被静默通道顶掉：页面回调仍需校验并置位。"""
    body = _function_body(_source(), "PageLeaveAdminAccount")
    assert body, "installer.nsi 缺少 PageLeaveAdminAccount"
    assert re.search(r'StrCpy\s+\$AdminWritten\s+"?1"?', body), (
        "PageLeaveAdminAccount 不再置 $AdminWritten——交互安装的凭据会丢失"
    )
    assert "ValidateAdminUsername" in body, (
        "PageLeaveAdminAccount 丢掉了用户名合法性校验"
    )
