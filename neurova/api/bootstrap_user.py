# -*- coding: utf-8 -*-
"""
bootstrap 用户引导（遗留①）

NEUROVA_BOOTSTRAP_USER=username:password 配置时，create_app 启动期
若无任何用户则创建 admin 账号——e2e/CI/本地演示的登录入口。

语义：
- 幂等：已有任意用户 → 不动；同名用户已存在 → 跳过
- 未配置环境变量 → 什么都不做（生产默认路径）
- fail-open：任何异常只告警，绝不阻断应用启动
"""

from __future__ import annotations

import configparser
import os
from typing import List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

BOOTSTRAP_ENV = "NEUROVA_BOOTSTRAP_USER"

# 安装包首装向导凭据文件（NSIS 自定义页写入，后端启动消费后删除）
BOOTSTRAP_ADMIN_FILE = "data/bootstrap_admin.ini"

_user_model_loader = None  # 可注入（测试桩）


def _get_user_model():
    # 注意：不做模块级缓存——测试经 monkeypatch 替换本函数必须直接生效
    from neurova.api.endpoints.auth import _get_user_model as _loader

    return _loader()


def _read_ini_text(path: str) -> Optional[configparser.ConfigParser]:
    """多编码尝试读取 INI（NSIS Unicode 安装器写 UTF-16，普通场景 UTF-8/GBK）。"""
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "utf-16", "gbk"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        parser = configparser.ConfigParser()
        try:
            parser.read_string(text)
        except configparser.Error:
            continue
        return parser
    return None


def consume_bootstrap_admin_file(
    ini_path: Optional[str] = None,
    user_model=None,
) -> int:
    """消费安装包首装向导写入的管理员凭据文件。

    语义（与 ensure_bootstrap_user 一致，外加文件生命周期）：
    - 无文件 → no-op
    - 仅当系统中无任何用户时创建 admin（同名冲突跳过）
    - 文件无论成败一律删除（凭据不残留；删除失败仅告警）
    - fail-open：任何异常不阻断启动

    Returns:
        创建的用户数（0/1）
    """
    path = ini_path or BOOTSTRAP_ADMIN_FILE
    if not os.path.exists(path):
        return 0

    username = password = ""
    try:
        parser = _read_ini_text(path)
        if parser is not None and parser.has_section("bootstrap"):
            username = (parser.get("bootstrap", "username", fallback="") or "").strip()
            password = parser.get("bootstrap", "password", fallback="") or ""
    except Exception as e:
        logger.warning("bootstrap_admin.ini 读取失败（将删除）: %s", e)

    try:
        os.remove(path)
    except OSError as e:
        logger.warning("bootstrap_admin.ini 删除失败（不阻断启动）: %s", e)

    if not username or not password:
        logger.info("bootstrap_admin.ini 内容无效或为空，跳过管理员创建")
        return 0

    try:
        um = user_model if user_model is not None else _get_user_model()
        users: List = []
        if hasattr(um, "list_users"):
            users = um.list_users() or []
        if users:
            logger.info("系统已有用户，忽略安装包引导凭据")
            return 0

        from neurova.api.endpoints.auth import hash_password

        um.create_user(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            status="active",
        )
        logger.info("安装包引导管理员已创建: %s (admin)", username)
        return 1
    except ValueError as e:
        logger.warning("安装包引导管理员创建跳过: %s", e)
        return 0
    except Exception as e:
        logger.error("安装包引导管理员创建失败（不阻断启动）: %s", e)
        return 0


def ensure_bootstrap_user(
    env_value: Optional[str] = None,
    user_model=None,
) -> int:
    """按环境变量引导创建用户。

    Returns:
        创建的用户数（0/1）
    """
    value = env_value if env_value is not None else os.environ.get(BOOTSTRAP_ENV, "")
    value = (value or "").strip()
    if not value:
        return 0

    if ":" not in value:
        logger.warning("NEUROVA_BOOTSTRAP_USER 格式非法（应为 username:password），跳过")
        return 0

    username, password = value.split(":", 1)
    username = username.strip()
    if not username or not password:
        logger.warning("NEUROVA_BOOTSTRAP_USER 用户名或密码为空，跳过")
        return 0

    try:
        um = user_model if user_model is not None else _get_user_model()
        users: List = []
        if hasattr(um, "list_users"):
            users = um.list_users() or []
        # 已有任意用户 → 不引导（避免覆盖生产账号体系）
        if users:
            return 0

        from neurova.api.endpoints.auth import hash_password

        um.create_user(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            status="active",
        )
        logger.info("bootstrap 用户已创建: %s (admin)", username)
        return 1
    except ValueError as e:
        # 同名冲突等业务性失败：告警跳过
        logger.warning("bootstrap 用户创建跳过: %s", e)
        return 0
    except Exception as e:
        # fail-open：引导失败绝不阻断启动
        logger.error("bootstrap 用户引导失败（不阻断启动）: %s", e)
        return 0
