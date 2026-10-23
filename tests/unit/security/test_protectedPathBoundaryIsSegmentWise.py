# -*- coding: utf-8 -*-
r"""受保护路径按**路径段**判，不按字符前缀——两侧判据同一份口径。

根因（2026-10-24 实测）：`/root` 在受保护清单里，而"在它下面"此前用
`norm.startswith(protected)` 判。两个后果，一个是放过、一个是过拦：

    过拦  file_read {"file_path": "/root/agent_workspaces/x"}  -> protected_path HIGH 阻断
          （容器与 root 跑测环境下 HOME 就是 /root ⇒ 这台机器上每一条正常文件读写都被拦）
    过拦  /rootfs/data/x.txt、/rooted/app/x.txt                 -> 同样被当成"在 /root 之下"
    该拦  /etc/passwdX                                          -> 按字符前缀也算"在 /etc/passwd 之下"，
          而它根本不是那个文件（反过来同样成立：保护面被前缀写法放大或缩窄）

同一份清单在**两个地方**各写过一套判据：命令文本那一侧早已按段边界
（`(?<![\w./\\-])…(?![\w.\-])`），路径值这一侧还在按字符前缀。一处清单两套判据，
必然一版对一版错——本档把它收成一处（`FilePathGuardian._isUnderProtected`），
并逐形钉住两侧。

本档只管**判据形状**：它不主张 `/root` 该不该留在清单里（那是部署面的事，
容器里 HOME=/root 时"整个家目录 = 受保护区"本身值得另裁）。
"""

from __future__ import annotations

import os

from neurova.security.tool_guard import FilePathGuardian

_sep = "/"


def _isUnder(path: str, protected: str) -> bool:
    """与 `FilePathGuardian` 同口径的段边界判定——本档同时是它的**形状**说明。

    实现搬进生产代码前，这七格逐条复述判据；实现搬进去后由
    `test_implementationMatchesThisJudgment` 反向咬合，两处不许各走各的。
    """
    normPath = path.replace("\\", _sep).rstrip(_sep) or _sep
    normProtected = protected.replace("\\", _sep).rstrip(_sep)
    if os.name == "nt":
        normPath, normProtected = normPath.lower(), normProtected.lower()
    if normPath == normProtected:
        return True
    prefix = normProtected if normProtected.endswith(_sep) else normProtected + _sep
    return normPath.startswith(prefix)


class TestSegmentBoundary:
    def test_descendantIsUnder(self):
        assert _isUnder("/root/agent_workspaces/x.txt", "/root") is True
        assert _isUnder("/etc/ssh/sshd_config", "/etc/ssh") is True

    def test_selfIsUnder(self):
        assert _isUnder("/root", "/root") is True
        assert _isUnder("/root/", "/root") is True

    def test_siblingWithSameNamePrefixIsNotUnder(self):
        """`/rootfs` `/rooted` 不是 `/root` 的另一处——字符前缀会把它们一起拦下。"""
        assert _isUnder("/rootfs/data/x.txt", "/root") is False
        assert _isUnder("/rooted/app/x.txt", "/root") is False

    def test_lookalikeFileIsNotUnder(self):
        assert _isUnder("/etc/passwdX", "/etc/passwd") is False
        assert _isUnder("/etc/shadow.bak", "/etc/shadow") is False

    def test_windowsSeparatorsAreNormalized(self):
        """反斜杠先归一再比段——否则 `\\root\\x` 在 Linux 侧根本认不出来。"""
        assert _isUnder("/root\\x", "/root") is True
        assert _isUnder("\\root\\x", "/root") is True  # 归一后就是 /root/x


class TestBothSidesShareOneJudgment:
    """清单只有一份，判据也只能有一套：命令文本侧与路径值侧对同一批形态给同一答案。"""

    def test_pathSideReportsProtectedHit(self):
        found = [f.rule_id for f in FilePathGuardian()._checkOnePath("/etc/shadow")]
        assert "protected_path" in found, found

    def test_pathSideDoesNotInflateTheProtectedFace(self):
        """`/rootfs/x` 与 `/rooted/x` 不是受保护区里的事——不该被 `protected_path` 拦。"""
        for path in ("/rootfs/data/x.txt", "/rooted/app/x.txt"):
            found = [f.rule_id for f in FilePathGuardian()._checkOnePath(path)]
            assert "protected_path" not in found, f"{path} 被当成受保护路径拦下了：{found}"


class TestImplementationMatchesThisJudgment:
    """本档那七格是判据的**形状**说明；生产实现必须与它逐形同答。"""

    def test_implementationMatchesThisJudgment(self):
        impl = FilePathGuardian._isUnderProtected
        cases = [
            ("/root/agent_workspaces/x.txt", "/root"),
            ("/etc/ssh/sshd_config", "/etc/ssh"),
            ("/root", "/root"),
            ("/root/", "/root"),
            ("/rootfs/data/x.txt", "/root"),
            ("/rooted/app/x.txt", "/root"),
            ("/etc/passwdX", "/etc/passwd"),
            ("/etc/shadow.bak", "/etc/shadow"),
            ("/root\\x", "/root"),
            ("\\root\\x", "/root"),
        ]
        for path, protected in cases:
            assert impl(path, protected) is _isUnder(path, protected), (
                f"生产实现与本档判据在 {path!r} vs {protected!r} 上给了两个答案")
