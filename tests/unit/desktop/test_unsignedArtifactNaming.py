# -*- coding: utf-8 -*-
"""安装包文件名里的 `_unsigned` 必须由**交付件实测**决定。

两处真实断裂（都不是假设）：
1. 旧写法 `signed = getattr(build_tauri, "last_signed", False) if not skip_tauri else None`
   配 `mark = "" if signed is not False else "_unsigned"`：走 `--skip-tauri` 时
   `signed` 是 None，`None is not False` ⇒ **不加标记**。实测
   `dist/installer/Neurova_Setup_1.0.0-beta7_20261103_x64.exe` 的
   `Get-AuthenticodeSignature` 状态是 NotSigned，而它顶着干净名字分发了出去。
2. 更根本的一层：交付件是 **WPF 壳**（`shutil.copy2(shell, out_path)`），
   tauri 签的是壳里嵌的 NSIS 内核，壳本身没有任何签名步骤
   （`installer-wpf/build.cmd` 里 grep 不到 sign）。按"内核签了没"给外壳命名，
   量的不是同一个对象——即便在有证书的机器上，也会产出一个未签名却叫
   `..._x64.exe` 的交付件。

枚举坑一并钉住：`Authenticode` 的 Status 取值是
NotSigned / Valid / HashMismatch / NotTrusted / UnknownError，**没有 "Signed"**。
按 "Signed" 比会永远判成未签名；反过来把"读不出"当成已签名是更坏的方向。
只有 Valid 算签过，其余一律点名。
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "desktop" / "package_installer_zip.py"
NOT_SIGNED_STATES = ["NotSigned", "HashMismatch", "NotTrusted",
                     "UnknownError", "ProbeFailed", "Empty", ""]


def _pkg():
    spec = importlib.util.spec_from_file_location("package_installer_zip", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("package_installer_zip", module)
    spec.loader.exec_module(module)
    return module


def testMarkFollowsMeasuredStateNotProcessFlag():
    """交付件名字的判定必须来自实测调用，不再来自进程内标志。

    守卫钉代码形态不钉词：早先按源码文本 grep 旧表达式，被我自己写在注释里的
    那句旧代码撞红——注释怎么改措辞都能把守卫弄红或放过，AST 不会。
    """
    pkg = _pkg()
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "package")
    marks = [n for n in ast.walk(fn)
             if isinstance(n, ast.Assign)
             and any(t.id == "mark" for t in n.targets if isinstance(t, ast.Name))]
    assert len(marks) == 2, f"单文件与 legacy zip 两条分支各需一次实测：{len(marks)}"
    for m in marks:
        assert isinstance(m.value, ast.Call) and             getattr(m.value.func, "id", "") == "mark_for",             "mark 仍由非实测来源决定"
        assert [a.id for a in m.value.args if isinstance(a, ast.Name)] == ["shell"],             "mark_for 必须量交付件本身（壳），不是内核也不是标志位"
    # Attribute 节点已覆盖 `getattr(x, "last_signed")` 之外的所有读法，
    # 属性名以字符串字面量传给 getattr 时另查一条
    flagged = [n for n in ast.walk(fn)
               if (isinstance(n, ast.Attribute) and n.attr == "last_signed")
               or (isinstance(n, ast.Constant) and n.value == "last_signed")]
    assert not flagged, "package() 仍在读进程内的签名标志属性"


@pytest.mark.parametrize("state", NOT_SIGNED_STATES)
def testAnythingButValidIsNamedUnsigned(tmp_path, monkeypatch, state):
    """读不出/链不过/哈希不符/探测失败 —— 一律点名。方向只能是宁可多标。"""
    pkg = _pkg()
    monkeypatch.setattr(pkg, "artifactSignatureState", lambda _p: state)
    shell = tmp_path / "shell.exe"
    shell.write_bytes(b"MZ")
    assert pkg.mark_for(shell) == "_unsigned", state


def testValidSignatureIsNotMarked(tmp_path, monkeypatch):
    pkg = _pkg()
    monkeypatch.setattr(pkg, "artifactSignatureState", lambda _p: "Valid")
    shell = tmp_path / "shell.exe"
    shell.write_bytes(b"MZ")
    assert pkg.mark_for(shell) == ""


@pytest.mark.skipif(os.name != "nt", reason="Authenticode 只在 Windows 上可测")
def testProbeReadsARealSignedBinary():
    """正向控制：系统自带的已签名二进制必须读出 Valid。

    这条专门防"枚举用错导致永远判未签名"——把 `Signed` 当取值就是这种错，
    它不会报错，只会让每一个包都带 _unsigned，看起来像保守其实是全错。
    """
    pkg = _pkg()
    assert pkg.artifactSignatureState(Path(r"C:\\Windows\\System32\\cmd.exe")) == "Valid"


@pytest.mark.skipif(os.name != "nt", reason="Authenticode 只在 Windows 上可测")
def testProbeDoesNotClaimSignatureForNonBinary(tmp_path):
    """反向控制：随便一个非 PE 文件绝不能被读成 Valid。"""
    pkg = _pkg()
    junk = tmp_path / "junk.exe"
    junk.write_bytes(b"not a portable executable at all")
    assert pkg.artifactSignatureState(junk) != "Valid"
