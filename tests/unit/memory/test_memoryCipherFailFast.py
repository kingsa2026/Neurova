"""§6-34：记忆层加密的降级门必须 fail-fast（红→绿）

现状（读码 + 本文件红灯实测）：
- `security.py:364-367` 在 `cryptography` 缺失时只 `logger.warning("…使用回退加密器")`
  就换成 `_FallbackCipher`——**重复密钥流 XOR**（`keystream = sha256(key)` 循环复用），
  与 P0-3 刚退役的凭据弱加密同族；
- `_FernetCipher.encrypt/decrypt` 与 `_FallbackCipher.decrypt` 全部把失败**改写成空串**
  （`return ""`）：写侧失败会落一条"加密成功的空记忆"，读侧失败让记忆看起来"没有内容"
  ——正是教义第 2 条禁止的形态（AGENTS.md §6-8 同族）。

取证结论（决定处置形态，不是猜的）：`encrypt_sensitive_content` / `decrypt_sensitive_content`
在 `7835c367`（pyc 骨架恢复）、`33b71a25`（桶层摘链）与 HEAD 三个版本上，**全仓命中文件
只有定义所在的 `security.py` 本身**——这条加解密链从未被任何调用方走过，因此盘上不存在
XOR 存量，可以直接 fail-fast 而不必先做 legacy 读回。"能力从未接线"这件事本身按核心原则
第 7 条另记台账（§6-37），本文件第 4 条判据把"零调用点"钉成会红的账。
"""

import ast
import pathlib

import pytest

import neurova.cognitive_layers.memory_layer.security as security
from tests import ast_scan

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _fernetConfig(**kwargs):
    return security.SecurityConfig(
        default_encryption=security.EncryptionMethod.FERNET, **kwargs
    )


def testMissingCryptographyFailsFastInsteadOfXor(monkeypatch):
    """依赖缺失必须点名拒绝，不得换一把弱钥匙继续写。"""
    monkeypatch.setattr(security, "HAS_CRYPTOGRAPHY", False)

    with pytest.raises(RuntimeError) as raised:
        security.MemorySecurity(_fernetConfig(encryption_key="whatever"))

    message = str(raised.value)
    assert "cryptography" in message, f"报错必须点名缺哪个依赖：{message}"


def testFallbackCipherRetired():
    """防回流：XOR 回退加密器整块必须消失。"""
    assert not hasattr(security, "_FallbackCipher"), (
        "重复密钥流 XOR 回来了——它既无完整性，也保不住'依赖缺失'时该红的那一刻"
    )


def testDecryptFailureIsNotRewrittenAsEmptyContent():
    """解不开必须抛出点名，不能返回空串把'坏数据'改写成'这条记忆没内容'。"""
    mem = security.MemorySecurity(_fernetConfig())

    with pytest.raises(Exception) as raised:
        mem.decrypt_sensitive_content(
            "not-a-fernet-token", security.EncryptionMethod.FERNET.value
        )

    assert not isinstance(raised.value, AssertionError), (
        f"应当是解密失败本身，拿到：{raised.value!r}"
    )


def testRoundTripStillWorks():
    """正对照：判据不得把能用的路径一起打死。"""
    mem = security.MemorySecurity(_fernetConfig())

    cipherText, used = mem.encrypt_sensitive_content("手机号 13800000000")
    assert used == security.EncryptionMethod.FERNET.value
    assert cipherText and cipherText != "手机号 13800000000"
    assert mem.decrypt_sensitive_content(cipherText, used) == "手机号 13800000000"


def testCipherChainHasZeroCallersAndThatIsPinned():
    """'敏感记忆落盘加密'从未接线——零调用点是**登记事实**，不是默认状态。

    接线它（或连同本文件一起退役它）都必须来改这条期望数，否则它就是一句没人读的注释。
    与 `tests/unit/collaboration/test_glance_yield_await_sites.py` 的双向钉法同形。
    """
    expectedCallers = 0
    hits = []
    # 本判据只扫一遍、不留常驻语法树，故走共享的一次性入口；顺带吃文本预筛——
    # 两个方法名都没出现的文件不可能有调用点（`tests/unit/test_ci_ast_scan_budget_guard.py`
    # 常驻拦「私有 rglob + ast.parse」的全仓扫描：判据成本不得随代码总量涨）。
    hints = ast_scan.textHints("encrypt_sensitive_content", "decrypt_sensitive_content")
    for path, node in ast_scan.transientNodes(REPO_ROOT / "neurova", hints=hints):
        if path.name == "security.py":
            continue  # 定义所在文件本身
        if isinstance(node, ast.Attribute) and node.attr in {
            "encrypt_sensitive_content",
            "decrypt_sensitive_content",
        }:
            hits.append(str(path.relative_to(REPO_ROOT)))

    assert len(hits) == expectedCallers, (
        f"敏感内容加解密的调用点数从 {expectedCallers} 变成 {len(hits)}：{sorted(set(hits))}。"
        "接线了就去台账 §6-37 记影响面并改这里；本模块的 fail-fast 判据同时才第一次真的护到人。"
    )
