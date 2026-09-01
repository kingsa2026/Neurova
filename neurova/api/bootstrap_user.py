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

import os
from typing import List, Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

BOOTSTRAP_ENV = "NEUROVA_BOOTSTRAP_USER"

_user_model_loader = None  # 可注入（测试桩）


def _get_user_model():
    # 注意：不做模块级缓存——测试经 monkeypatch 替换本函数必须直接生效
    from neurova.api.endpoints.auth import _get_user_model as _loader

    return _loader()


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
