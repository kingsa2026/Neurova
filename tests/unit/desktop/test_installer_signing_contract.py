# -*- coding: utf-8 -*-
"""安装包签名契约：签名必须「可注入」，不得把构建机绑死在一台机器的证书库上（Issue #332）。

**为什么要有本守卫（实机踩到的真实断链）**：
`NeurUI/src-tauri/tauri.conf.json` 的 `bundle.windows.certificateThumbprint` 写死了
一枚**自签名证书指纹**。该证书只存在于原打包机的证书库里（私钥不进仓，这是对的）。
后果：换一台构建机（本轮的自托管节点 `orange-connector`）**连包都产不出来** ——

    Signing ... with identity "11F098DB1C2E2EB47BD74CF82059A81A046A8757"
    failed to bundle project: `failed to run ...\\signtool.exe`

Rust 侧编译早已成功（`app.exe` 已产出），卡在签名这一步。失败形态与「代码有 bug」
看着一模一样，而根因是**环境依赖被写进了产品配置**。

判据（两条，缺一不可）：
  1. 签名**可注入**：打包脚本必须能在「证书在位」时用它、在「证书缺席」时不因它
     硬失败，且这条判断写在**打包侧**（`--config` 覆盖），不靠人去改产品配置；
  2. **不得静默弱化**：不签名的产物必须**被点名**（日志 + 产物文件名/标记），
     不许装作签了。悄悄少签名 = 表面抹除（教义第 2 条）。
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_PKG_SCRIPT = _REPO / "scripts" / "desktop" / "package_installer_zip.py"
_TAURI_CONF = _REPO / "NeurUI" / "src-tauri" / "tauri.conf.json"


def _src() -> str:
    return _PKG_SCRIPT.read_text(encoding="utf-8")


def testSigningIsInjectableNotHardwired():
    """打包侧必须能按「证书是否在位」决定签名，不把失败留给 signtool。

    判据看**结构**：注入必须咬在 `build_tauri` 这条链上，而不是"文件里出现过
    某个字符串"。早先按字面量判，把注入删掉仍能过（`certificateThumbprint`
    在别的函数里也出现）—— 那是恒真断言，必须按调用链判。
    """
    import ast

    src = _src()
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "tauri_signing_args" in funcs, (
        "缺签名注入函数 —— 构建机会被绑死在写死指纹的那台机器上"
    )
    assert "cert_is_in_store" in funcs, (
        "必须查本机证书库有没有这枚证书（换机器时靠它决定签不签）"
    )
    body = ast.unparse(funcs["build_tauri"])
    assert "tauri_signing_args()" in body, (
        "签名注入必须在 build_tauri 里被调用（只定义不接线 = 死码）"
    )
    assert "--config" in src, (
        "签名必须经 tauri build --config 注入（不在产品配置里删指纹："
        "那台有证书的机器还要用它）"
    )


def testUnsignedBuildIsExplicitlyNamed():
    """不签名的产物必须被点名 —— 日志与产物名都要能看出来，不得装作签了。"""
    src = _src()
    assert "unsigned" in src.lower() or "未签名" in src, (
        "不签名的构建必须显式点名（日志/产物名），不得静默产出冒充已签名的包"
    )


def testProductConfigKeepsThumbprintForOwnedMachines():
    """产品配置里的指纹不删：有证书的机器仍按它签（那是签名事实源）。"""
    import json
    conf = json.loads(_TAURI_CONF.read_text(encoding="utf-8"))
    win = conf["bundle"]["windows"]
    assert win.get("certificateThumbprint"), (
        "tauri.conf.json 的 certificateThumbprint 是签名事实源，不得清空；"
        "换机器的问题在打包侧解决，不在产品配置里抹掉"
    )


def testUnsignedMarkerDoesNotEscapeArtifactDiscovery():
    """`_unsigned` 标记不得让产物从发现链上消失（同一根因的消费方扫荡）。

    产物名带标记后，凡按 `Neurova_Setup_*_x64.exe` 通配找产物的落点都会漏掉它 ——
    于是「不签名的包产出来了，却报产物缺席」，比不产还难查。消费方必须一并放宽：
      · `.cnb.yml` 的产物结构自证 stage；
      · `win_installer_kit.py` 的 `newest_installer`。
    单一定义的标记来自 `package_installer_zip.py`，此处只核「消费方都容得下」。
    """
    cnb = (_REPO / ".cnb.yml").read_text(encoding="utf-8")
    kit = (_REPO / "scripts" / "desktop" / "win_installer_kit.py").read_text(encoding="utf-8")
    assert "Neurova_Setup_*_x64*.exe" in cnb, (
        ".cnb.yml 的产物通配没容下 _unsigned 标记 —— 不签名的包会被判成缺席"
    )
    assert "Neurova_Setup_*_x64*.exe" in kit, (
        "win_installer_kit.py 的产物通配没容下 _unsigned 标记"
    )


def testSigningOverrideIsPassedAsFileNotInlineJson():
    """签名覆盖必须落**文件**再传路径 —— 内联 JSON 过 shell 会被剥掉引号。

    实机证据（2026-09-30，节点 orange-connector）：内联 `--config '{...}'` 经
    shell=True（cmd.exe/PowerShell）后引号被吃掉，tauri 收到的是
    `{bundle:{windows:{...}}}`，报
    `failed to parse config ... as JSON: key must be a string`。
    这与签名逻辑无关，是「把结构化数据塞进命令行」的固有缺陷：
    正确做法是写临时 json 文件、把**路径**交给 tauri（`--config` 支持路径）。
    """
    src = _src()
    assert "certificateThumbprint\":null" not in src.replace(" ", ""), (
        "内联 JSON 覆盖过 shell 会丢引号 —— 必须落文件传路径"
    )
    assert "write_text" in src, "签名覆盖应写成临时 json 文件"


def testBuildRedirectsLocalAppDataOffSystemProfile():
    """构建前必须把 LOCALAPPDATA 挪出 systemprofile（实机踩到的 0xC0000135）。

    实机证据（2026-09-30，节点 orange-connector，whoami=nt authority\\system）：
    自托管 Runner 以 SYSTEM 身份跑，`%LOCALAPPDATA%` 落在
    `C:\\WINDOWS\\system32\\config\\systemprofile\\AppData\\Local`。Tauri 的 NSIS 打包器
    把自带 makensis 解到那里，**该位置的可执行文件加载不了**：

        tauri\\NSIS\\Bin\\makensis.exe  → 0xC0000135 (STATUS_DLL_NOT_FOUND)
        同一份字节拷到 D:\\ci-localappdata\\tauri\\NSIS\\Bin → v3.13 正常
        系统 choco NSIS（C:\\Program Files (x86)\\NSIS）→ v3.13 正常

    于是 `tauri build` 在 bundler 最后一步报
    `Unable to start child process, error 0x2` / `Failed to bundle app with makensis`，
    看着像 NSIS 缺失或脚本有错，根因却是**缓存目录选在了不可执行的位置**。

    根修：构建前把 `LOCALAPPDATA` 指到一个普通目录（Tauri 据此决定 NSIS 缓存落点）。
    """
    import ast

    src = _src()
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "tauri_build_env" in funcs, (
        "缺 tauri_build_env()：SYSTEM 身份的 Runner 会让 Tauri 的 NSIS 落到 "
        "systemprofile，那是可执行文件加载不了的位置（0xC0000135）"
    )
    helper_src = ast.unparse(funcs["tauri_build_env"])
    assert "LOCALAPPDATA" in helper_src, "helper 必须改 LOCALAPPDATA"
    assert "systemprofile" in helper_src, "必须点名 systemprofile 这个根因"
    # 接线判据：`tauri build` 那条调用必须真带上 env（只定义不接线 = 死码）。
    body = ast.unparse(funcs["build_tauri"])
    assert "tauri_build_env()" in body, (
        "tauri_build_env() 没接进 build_tauri 的调用 —— 定义了却没用（死码）"
    )
