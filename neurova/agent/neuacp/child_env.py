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


def buildChildEnvironment(env_extra: Optional[dict] = None) -> dict:
    env = {}
    for key in _BASE_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            env[key] = value
    env["PYTHONIOENCODING"] = "utf-8"
    for key, value in (env_extra or {}).items():
        env[key] = value
    return env
