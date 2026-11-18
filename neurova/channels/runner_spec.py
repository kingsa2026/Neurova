# -*- coding: utf-8 -*-
"""渠道 Runner 启动规格（QwenPaw 对照批 A1）。

把"一个渠道实例跑在独立子进程"所需的可信根信息收敛成一个显式规格：
解释器、代码根、入口点、源码版本与依赖清单。宿主拉起子进程前按它
核对，子进程握手时回带审计结果——两侧对不上就拒绝启动（fail-closed）。

设计边界（对齐 QwenPaw `process_supervisor.LaunchSpec` 的形制，实现为本仓自研）：
- 只声明"可信根"，不携带渠道密钥——密钥仍走既有 ChannelConfig，不经本规格扩散；
- `required_deps` 是该渠道适配器的**可导入依赖**清单，握手期逐个 import 实测；
- `source_revision` 供宿主核对"拉起来的代码就是我以为的代码"。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List


def defaultSourceRevision() -> str:
    """当前源码版本：优先显式环境变量（CI/部署注入），退回 git 短码；
    两者都不可得时如实写 unknown（握手核对跳过该项，但不假装一致）。"""
    explicit = os.environ.get("NEUROVA_SOURCE_REVISION", "").strip()
    if explicit:
        return explicit
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=defaultCodeRoot(),
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def defaultCodeRoot() -> str:
    """neurova 包的父目录——子进程把它插进 PYTHONPATH 即可 import 本仓。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class LaunchSpec:
    """渠道子进程启动规格（可信根）。"""

    channel_type: str
    #: 子进程入口适配器，形如 "module:qualname"；`builtin:echo` 为协议测试内置回显。
    entrypoint: str
    python_executable: str = ""
    code_root: str = ""
    source_revision: str = ""
    #: 渠道适配器的第三方依赖（按模块名，握手期逐个 import 实测）。
    required_deps: List[str] = field(default_factory=list)
    #: 允许透传给子进程的环境变量键（白名单；空＝只带基础项）。
    private_env_keys: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.python_executable:
            self.python_executable = sys.executable
        if not self.code_root:
            self.code_root = defaultCodeRoot()
        if not self.source_revision:
            self.source_revision = defaultSourceRevision()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_type": self.channel_type,
            "entrypoint": self.entrypoint,
            "python_executable": self.python_executable,
            "code_root": self.code_root,
            "source_revision": self.source_revision,
            "required_deps": list(self.required_deps),
            "private_env_keys": list(self.private_env_keys),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "LaunchSpec":
        return cls(
            channel_type=str(payload.get("channel_type") or ""),
            entrypoint=str(payload.get("entrypoint") or ""),
            python_executable=str(payload.get("python_executable") or ""),
            code_root=str(payload.get("code_root") or ""),
            source_revision=str(payload.get("source_revision") or ""),
            required_deps=[str(x) for x in (payload.get("required_deps") or [])],
            private_env_keys=[str(x) for x in (payload.get("private_env_keys") or [])],
        )

    @classmethod
    def from_json(cls, raw: str) -> "LaunchSpec":
        return cls.from_dict(json.loads(raw))
