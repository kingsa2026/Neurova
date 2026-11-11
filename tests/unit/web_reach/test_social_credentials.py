"""社交平台凭据切片退役守卫（§6-591，2026-11-12）。

背景：social_search 切 CLI 面（登录态归上游 agent-reach 浏览器会话）后，
社交平台凭据段失去唯一工具消费方——后端三端点、存储社交方法、前端
CredentialManager 社交段与 10 键 i18n 同批退役。本文件钉**缺席**：
路由表里不得再有 /social-credentials，credentials 模块不得再暴露社交
批量读写符号，平台键集注册表须为空（rdp 键集随 §6-592 RDP 授权面回填）。

仍活着的相邻面（不得误伤）：SSH 主机凭据（ssh_runner＋设置端点）、
RDP 直连凭据（§6-592 接通：rdp_provider → get_rdp_endpoint 专用访问器）、
通用桶 set/get/delete_credential。platform_credentials／PLATFORM_REQUIRED_KEYS
注册表随 §6-592 一并退役（RDP 换专用访问器后注册表零消费者）。
"""

import importlib

from neurova.api.endpoints import settings as settings_module

_RETIRED_SYMBOLS = (
    "set_platform_credentials",
    "platform_status",
    "clear_platform_credentials",
    "list_platforms",
    "_KEY_TO_PLATFORM",
    "PLATFORM_REQUIRED_KEYS",
    "platform_credentials",
)

_SOCIAL_PLATFORMS = ("twitter", "reddit", "xiaohongshu", "facebook", "instagram", "linkedin")


def test_settings路由表不得再有social_credentials端点():
    paths = {getattr(r, "path", "") for r in settings_module.router.routes}
    leaked = [p for p in paths if "social" in p.lower()]
    assert leaked == [], f"社交凭据端点未退役干净: {leaked}"


def test_settings命名空间不得再有SocialCredentialRequest模型():
    assert not hasattr(settings_module, "SocialCredentialRequest"), (
        "SocialCredentialRequest 模型未随端点退役"
    )


def test_credentials模块不得再暴露社交批量读写符号():
    creds = importlib.import_module("neurova.web_reach.credentials")
    leaked = [name for name in _RETIRED_SYMBOLS if hasattr(creds, name)] + [
        f"UserCredentialStore.{name}"
        for name in _RETIRED_SYMBOLS
        if hasattr(creds.UserCredentialStore, name)
    ]
    assert leaked == [], f"社交凭据切片符号未退役干净: {leaked}"


def test_平台键集注册表整体退役():
    """社交键集清空后注册表整体失去消费者（RDP 换专用访问器）⇒ 常量退役。"""
    creds = importlib.import_module("neurova.web_reach.credentials")
    assert not hasattr(creds, "PLATFORM_REQUIRED_KEYS"), (
        "PLATFORM_REQUIRED_KEYS 注册表在 RDP 换专用访问器后已零消费者，应随批退役"
    )
    assert not hasattr(creds, "platform_credentials"), (
        "platform_credentials 批量读在 RDP 换专用访问器后已零消费者，应随批退役"
    )


def test_相邻活面不得误伤():
    """SSH/RDP/通用桶三面仍在——退役刀口不得越过。"""
    creds = importlib.import_module("neurova.web_reach.credentials")
    store = creds.UserCredentialStore
    for name in (
        "set_credential",
        "get_credential",
        "delete_credential",
        "set_ssh_host",
        "get_ssh_host",
        "list_ssh_hosts",
        "delete_ssh_host",
        "set_rdp_endpoint",
        "get_rdp_endpoint",
        "rdp_status",
        "delete_rdp_endpoint",
    ):
        assert hasattr(store, name), f"相邻活面被误删: UserCredentialStore.{name}"
