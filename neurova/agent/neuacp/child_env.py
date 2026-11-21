# -*- coding: utf-8 -*-
"""外部代理子进程环境装配单源（ACP 与插件形态共用）。

白名单式治理：只带运行必需键——宿主代理变量（HTTP_PROXY 等）天然被
排除（规避子进程代理坑），凭据按 env_extra 显式注入；UTF-8 双头钉。
"""
import os
from typing import Optional

_BASE_ENV_KEYS = (
    "PATH",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "USERPROFILE",
    "PROGRAMFILES",
    "ALLUSERSPROFILE",
    "HOME",
    "PYTHONIOENCODING",
)


def buildChildEnvironment(
    env_extra: Optional[dict] = None,
    run_credential_context: Optional[dict] = None,
) -> dict:
    """装配子进程环境（白名单式）。

    Args:
        env_extra: 显式追加的 env 键值（凭据类变量按既有惯例走这里）。
        run_credential_context: C4 run 级身份绑定——``{"run_id","tenant_id"}``。
            提供时注入 ``NEUROVA_RUN_CREDENTIAL``=<run 级范围凭据>（HMAC 绑定
            run+租户+过期，密钥单源 ``currentJwtSecretKey``）；``None`` 不注入
            （行为不变）。上下文缺参由签发侧诚实抛错（fail-closed，不静默
            放行无绑定进程）。该键只由此通道写入，``env_extra`` 不覆盖它。
    """
    env = {}
    for key in _BASE_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    for key, value in (env_extra or {}).items():
        env[key] = value
    if run_credential_context is not None:
        # 惰性 import：child_env 是被广泛复用的叶子模块，凭据签发链
        # （run_identity → api.auth → jwt/config）只在真正注入时才加载。
        from neurova.security.run_identity import issueRunCredential

        env["NEUROVA_RUN_CREDENTIAL"] = issueRunCredential(
            run_credential_context.get("run_id"),
            run_credential_context.get("tenant_id"),
        )
    return env
