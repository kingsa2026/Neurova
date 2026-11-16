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
#: 扫描根单点（必须是模块级：函数内的局部名会被面自证棘轮解成动态值，那档就静默掉出它的面）。
NEUROVA = REPO_ROOT / "neurova"


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


def testCipherChainCallersStayPinnedToTheSingleReadOutlet():
    """加解密链已接线（审计 3.3-5 拍板 + encrypt 读侧拍板 2026-11-17）——调用面只许收敛在唯一读出口。

    旧判据「零调用点」随接线被合法推翻：写侧走 manager.remember 咽喉的
    screenForStorage（其内部才触达 encrypt_sensitive_content，定义文件自身跳过）；
    读侧出口单点 = Memory.to_dict → plaintextContent（models.py）。
    本判据改钉**收敛面**：security.py 之外，这两个方法名的调用文件必须恰为
    models.py 一处——再有第三处绕过咽喉直调加解密即红。
    与 `tests/unit/collaboration/test_glance_yield_await_sites.py` 的双向钉法同形。
    """
    expectedCallerFiles = {
        "neurova/cognitive_layers/memory_layer/models.py",
    }
    hits = []
    # 本判据只扫一遍、不留常驻语法树，故走共享的一次性入口；顺带吃文本预筛——
    # 两个方法名都没出现的文件不可能有调用点（`tests/unit/test_ci_ast_scan_budget_guard.py`
    # 常驻拦「私有 rglob + ast.parse」的全仓扫描：判据成本不得随代码总量涨）。
    hints = ast_scan.textHints("encrypt_sensitive_content", "decrypt_sensitive_content")
    surface = len(ast_scan.filesUnder(NEUROVA))
    assert surface > 500, (
        f"扫描面现读 {surface} 档 .py（根＝{NEUROVA}，本判据的域＝生产源码）——"
        "预筛命中数不随根的大小变，「零调用点」得先证这条判据在看代码")
    for path, node in ast_scan.transientNodes(NEUROVA, hints=hints):
        if path.name == "security.py":
            continue  # 定义所在文件本身
        if isinstance(node, ast.Attribute) and node.attr in {
            "encrypt_sensitive_content",
            "decrypt_sensitive_content",
        }:
            hits.append(path.relative_to(REPO_ROOT).as_posix())

    assert set(hits) == expectedCallerFiles, (
        f"敏感内容加解密的调用文件现读 {sorted(set(hits))}，"
        f"期望只收敛在唯一读出口 {sorted(expectedCallerFiles)}——"
        "新消费方必须走 screenForStorage/明文读出口，不得各自直调加解密。"
    )
