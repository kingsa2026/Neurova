"""渠道域"依赖缺失却报成功"全族扫荡（审计 §6-8，第 5 条全命中点）。

先例是 `test_b3_sip_honest_no_fakesuccess.py`（B-3 对 sip.py 的收口），本文件把同一条契约
推广到整个渠道域：`if not <X>_AVAILABLE:` 的分支**不得产出真值/成功结构**，必须按该函数
自己的契约返回失败值，并 warning 点名缺哪个依赖。

原报告只记了三处（discord / qclaw / qclaw_service）。按 AST 复扫实为 26 处、跨 10 个文件，
另有 3 处（`telegram_api_client._api_request`、`wechat_auth._api_request`、`qqbot._api_request`）
本来就返回该文件自己的失败结构（`ok:False` / `errcode:-1` / `retcode:1`）——**那三处是对的，
本批改一个字都不行**，所以判据按"返回值语义"分类而不是按返回值类型分类。

最硬的一条是 MQTT：本机 venv 就没装 paho，`MQTT_AVAILABLE` 现值为 False，于是
`_init_connection()` 今天**真的**在置 `_initialized=True` 并 `return True`——不是潜在问题，
是当前可达的假成功。
"""

from __future__ import annotations

import ast
import io
import logging
import os

import pytest

import neurova.channels.discord as discord_module
import neurova.channels.mqtt as mqtt_module
import neurova.channels.qclaw_service as qclaw_service_module
from neurova.channels.discord import DiscordAdapter
from neurova.channels.mqtt import MQTTAdapter
from neurova.channels.qclaw_service import QClawService


def _channelsRoot() -> str:
    import neurova.channels as channels_pkg
    return os.path.dirname(os.path.abspath(channels_pkg.__file__))


@pytest.fixture(autouse=True)
def _isolateDataRoot(tmp_path, monkeypatch):
    """构造真适配器会开自己的库（`QClawService` → `data/qclaw_bindings.db`）。

    走 `NEUROVA_DATA_DIR` 这条显式注入口，绝不让判据自己变成 §6-29 点名的那类污染。
    """
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    return tmp_path



def _isSuccessValue(node: ast.expr) -> bool:
    """把"返回真值/成功结构"判出来；None、False、以及带失败标记的结构都不算。

    分类按**语义**而非返回值类型：渠道里三处（telegram / wechat_auth / qqbot 的
    `_api_request`）返回的是字典，但那是该文件自己的失败结构（`ok:False` /
    `errcode:-1` / `retcode:1`），动一个字都不行。
    """
    if node is None:
        return False
    if isinstance(node, ast.Constant) and node.value in (None, False):
        return False
    if isinstance(node, ast.Dict):
        # 字符串键要取字面值再比，直接 ast.unparse 会连引号一起带进来
        pairs = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                pairs[k.value] = ast.unparse(v)
        for flag in ("ok", "success", "valid"):
            if pairs.get(flag) == "True":
                return True
        for flag in ("ok", "success", "valid"):
            if pairs.get(flag) == "False":
                return False
        for code in ("errcode", "retcode", "code"):
            literal = pairs.get(code)
            if literal is not None and literal not in ("0", "-0"):
                return False
        return True     # 认不出失败标记的字典按"未如实报错"处理，逼显式化
    if isinstance(node, ast.Name) and node.id == "True":
        return True
    # 其余一律视为"造了个成功的假象"：字符串（含 f-string 的 mock id）、bytes、True、变量名
    return True



def testDependencyMissingBranchNeverReturnsSuccessValue():
    """全族判据：`if not X_AVAILABLE:` 分支内不得 return 真值/成功结构。"""
    offenders = []
    root = _channelsRoot()
    for name in sorted(os.listdir(root)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(root, name)
        tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for stmt in ast.walk(fn):
                if not isinstance(stmt, ast.If):
                    continue
                test = stmt.test
                if not (isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not)
                        and isinstance(test.operand, ast.Name)
                        and test.operand.id.endswith("AVAILABLE")):
                    continue
                for ret in [n for n in ast.walk(stmt) if isinstance(n, ast.Return)]:
                    if _isSuccessValue(ret.value):
                        offenders.append("%s:%d %s() [%s] -> %s" % (
                            name, stmt.lineno, fn.name, test.operand.id,
                            ast.unparse(ret.value)[:60]))
    assert not offenders, (
        "依赖缺失分支仍报成功（%d 处）：\n  %s" % (len(offenders), "\n  ".join(offenders))
    )


def testMqttInitConnectionWithoutPahoIsHonestFailure(caplog):
    """本机就没装 paho：`_init_connection()` 今天真的 return True —— 当前可达的假成功。"""
    assert mqtt_module.MQTT_AVAILABLE is False, (
        "本条断言的前提是「当前环境确实缺 paho」；若依赖已装上，请改用 monkeypatch 强制置 False"
    )
    adapter = MQTTAdapter()
    with caplog.at_level(logging.WARNING):
        assert adapter._init_connection() is False, "paho 缺失却报初始化成功"
    assert adapter._initialized is False, "未真实初始化却置 _initialized=True"
    assert any("paho-mqtt" in r.message or "未安装" in r.message for r in caplog.records), \
        "诚实失败必须点名缺哪个依赖"


def testDiscordVerifyTokenWithoutRequestsIsHonestFailure(monkeypatch, caplog):
    """`_verify_token()` 不得因 requests 缺失就宣称 Token 有效并置 _initialized。"""
    monkeypatch.setattr(discord_module, "REQUESTS_AVAILABLE", False)
    adapter = DiscordAdapter()
    with caplog.at_level(logging.WARNING):
        assert adapter._verify_token() is False
    assert adapter._initialized is False
    assert any("requests" in r.message for r in caplog.records)


def testQclawVerifyCredentialsWithoutRequestsIsNotValid(monkeypatch, caplog):
    """`{"valid": True, "qclaw_user_id": "mock_user_…"}` 是"凭证有效"的谎报。"""
    monkeypatch.setattr(qclaw_service_module, "REQUESTS_AVAILABLE", False)
    service = QClawService()
    with caplog.at_level(logging.WARNING):
        result = service.verify_credentials("app_id_12345678", "secret")
    assert result["valid"] is False, "依赖缺失时不得宣称凭证有效：%s" % result
    assert result.get("error"), "必须给出可归因的失败原因：%s" % result
    assert "mock_user" not in str(result), "不得编造 qclaw_user_id：%s" % result


def testQclawGetAccessTokenWithoutRequestsCachesNothing(monkeypatch):
    """mock token 会被写进 `token_cache`，之后即使依赖补上也照用假 token 两小时。"""
    monkeypatch.setattr(qclaw_service_module, "REQUESTS_AVAILABLE", False)
    service = QClawService()
    token = service.get_access_token("app_id_12345678", "secret")
    assert not token, "依赖缺失不得返回一个 accessToken：%r" % token
    assert "app_id_12345678" not in service.token_cache, (
        "假 token 不得进缓存（缓存键会跨依赖恢复而残留）：%s" % list(service.token_cache)
    )


def testQclawSendMessageWithoutRequestsIsHonestFailure(monkeypatch):
    """发送结果必须如实反映——这里此前是 `{"success": True, "message_id": "mock_msg_…"}`。"""
    monkeypatch.setattr(qclaw_service_module, "REQUESTS_AVAILABLE", False)
    service = QClawService()
    result = service.send_message("app_id_12345678", "secret", "chat-1", "hello")
    assert result["success"] is False, "依赖缺失却报发送成功：%s" % result
    assert result.get("error"), "发送失败必须可归因：%s" % result
