# -*- coding: utf-8 -*-
"""live-verify（Issue #289 · 开发环境）：自定义开发环境声明与三面口径对齐。

用**真文件**复演「点云原生开发按钮后会发生什么」，不用桩：

- 解释器：开发环境与生产镜像（`Dockerfile` 的 `FROM python:`）必须同版本，
  且不低于 `scripts/config.py` 的 `MIN_PYTHON_VERSION`；
- Node 大版本：开发环境 / CI（`.github/workflows/ci.yml` 的 `node-version`）/
  compose 前端镜像三者同源；
- 单容器模式：官方口径是「容器中装了 code-server ⇒ 单容器」，故判定取**真安装
  指令**（执行 code-server 官方 install.sh 的那条 `RUN`），不取字符串出现在注释
  里的形态；
- SSH：VSCode / Cursor / CodeBuddy 客户端接入前提是 `openssh-server` 真装在
  apt 安装面里；
- 依赖来源：预装取自既有锁/清单（`requirements-ci.lock` / `NeurUI/package.json`），
  不在 stages 里另列包名。

跑法：`python tests/manual/dev_environment_289.py`
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _read(name: str) -> str:
    return io.open(PROJECT_ROOT / name, encoding="utf-8").read()


def _aptPackages(dockerfile_text: str) -> set:
    """`apt-get install` 调用面里真被点名的包名（跳过注释行）。"""
    packages: set = set()
    lines = dockerfile_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.search(r"apt-get\s+install\b", line) and not line.lstrip().startswith("#"):
            chunk = [line.split("install", 1)[1]]
            while chunk[-1].rstrip().endswith("\\") and index + 1 < len(lines):
                index += 1
                chunk.append(lines[index])
            for token in re.split(r"[\s\\]+", " ".join(chunk)):
                token = token.strip()
                if token and not token.startswith("-") and not token.startswith("$"):
                    packages.add(token)
        index += 1
    return packages


def main() -> int:
    failures = []

    prod = _read("Dockerfile")
    ide = _read(".ide/Dockerfile")
    ci = _read(".github/workflows/ci.yml")

    # ── [1] 解释器三面对齐 ────────────────────────────────────────────
    prod_python = set(re.findall(r"^FROM\s+python:(\d+\.\d+)", prod, re.M))
    ide_python = set(re.findall(r"^FROM\s+python:(\d+\.\d+)", ide, re.M))
    print(f"[1] 生产解释器={sorted(prod_python)}  开发环境解释器={sorted(ide_python)}")
    if prod_python != ide_python:
        failures.append("开发环境解释器与生产镜像不同版本")

    min_python = re.search(
        r"MIN_PYTHON_VERSION\s*=\s*\((\d+),\s*(\d+)\)", _read("scripts/config.py")
    )
    floor = (int(min_python.group(1)), int(min_python.group(2)))
    actual = tuple(int(p) for p in ide_python.pop().split("."))
    print(f"[1b] 下限 MIN_PYTHON_VERSION={floor}  开发环境={actual}  达标={actual >= floor}")
    if actual < floor:
        failures.append("开发环境解释器低于项目最低版本")

    # ── [2] Node 大版本三面同源 ───────────────────────────────────────
    ci_node = re.search(r'node-version:\s*"(\d+)"', ci).group(1)
    ide_node = sorted(set(re.findall(r"deb\.nodesource\.com/setup_(\d+)\.x", ide)))
    compose = yaml.safe_load(_read("docker-compose.yml"))
    frontend_image = str(compose["services"]["frontend"]["image"])
    compose_node = re.match(r"^node:(\d+)", frontend_image).group(1)
    print(
        f"[2] CI node={ci_node}  开发环境 node={ide_node}  "
        f"compose 前端={frontend_image}（node={compose_node}）"
    )
    if ide_node != [ci_node] or compose_node != ci_node:
        failures.append("Node 大版本在开发环境 / CI / compose 之间分叉")

    # ── [3] 单容器模式判定 ───────────────────────────────────────────
    install_directive = re.search(r"^RUN\b.*code-server\.dev/install\.sh", ide, re.M)
    print(
        f"[3] code-server 真安装指令={'存在' if install_directive else '缺失'}  "
        f"⇒ 平台模式={'单容器' if install_directive else '双容器'}"
    )
    if not install_directive:
        failures.append("未真正安装 code-server，平台会回落到双容器模式")

    # ── [4] SSH 服务 ─────────────────────────────────────────────────
    packages = _aptPackages(ide)
    has_ssh = "openssh-server" in packages
    print(f"[4] apt 真安装面包数={len(packages)}  含 openssh-server={has_ssh}")
    if not has_ssh:
        failures.append("apt 安装面缺 openssh-server，客户端远程连接不可用")

    # ── [5] 依赖来源是既有锁 ─────────────────────────────────────────
    cnb = yaml.safe_load(_read(".cnb.yml"))
    vscode = cnb["$"]["vscode"][0]
    scripts = "\n".join(str(stage.get("script", "")) for stage in vscode["stages"])
    uses_lock = "requirements-ci.lock" in scripts
    uses_npm = "npm ci" in scripts
    print(f"[5] stages 引 requirements-ci.lock={uses_lock}  引 npm ci={uses_npm}")
    if not (uses_lock and uses_npm):
        failures.append("预装未取自既有锁/清单")

    # ── [6] 事件挂载点与接线面 ───────────────────────────────────────
    on_fallback = "vscode" in cnb["$"]
    build = (vscode.get("docker") or {}).get("build")
    fallback_image = (vscode.get("docker") or {}).get("image")
    services = vscode.get("services") or []
    print(
        f"[6] 挂在 $ 兜底块={on_fallback}  build={build}  "
        f"回退镜像={fallback_image}  services={services}"
    )
    if not on_fallback or build != ".ide/Dockerfile" or not fallback_image:
        failures.append("vscode 事件接线不完整")
    if sorted(services) != ["docker", "vscode"]:
        failures.append("services 未同时声明 vscode 与 docker")

    # ── [7] 启动按钮 ─────────────────────────────────────────────────
    settings = yaml.safe_load(_read(".cnb/settings.yml"))
    launch = settings["workspace"]["launch"]
    print(
        f"[7] 按钮名={launch['button']['name']!r}  cpus={launch['cpus']}  "
        f"autoOpenWebIDE={launch['autoOpenWebIDE']}  NPC 角色数={len(settings['npc']['roles'])}"
    )

    if failures:
        print("\nLIVE-VERIFY FAILED / Issue #289 · 开发环境")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nLIVE-VERIFY PASSED / Issue #289 · 开发环境")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
