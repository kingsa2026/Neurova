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

    # ── [5] 预装整装运行环境（用户诉求：不要默认镜像，装好运行环境）──────
    cnb = yaml.safe_load(_read(".cnb.yml"))
    vscode = cnb["$"]["vscode"][0]
    scripts = "\n".join(str(stage.get("script", "")) for stage in vscode["stages"])
    surface = ide + "\n" + scripts

    full_lock = re.search(r"requirements-full\.lock", surface)
    header = "\n".join(_read("requirements-full.lock").splitlines()[:4])
    same_source = "requirements.txt" in header
    print(
        f"[5a] 镜像装全量锁 requirements-full.lock={'存在' if full_lock else '缺失'}  "
        f"与 requirements.txt 同源={same_source}"
    )
    if not (full_lock and same_source):
        failures.append("开发环境未装全量运行依赖，或全量锁与 requirements.txt 不同源")

    # 判定只认真安装指令（`pip install ... -r <锁>`），不认注释里提到的文件名 ——
    # 否则注释会替安装发合格证（本仓在 code-server / openssh 上修过的同一形态）。
    installed_locks = set(
        re.findall(r"pip install[^\n]*?-r\s+\S*?(requirements[\w-]*\.lock)", ide)
    )
    print(f"[5b] 镜像真安装的锁={sorted(installed_locks)}")
    if not full_lock:
        failures.append("镜像未装 requirements-full.lock")
    if installed_locks and not any("full" in name for name in installed_locks):
        failures.append(f"镜像真安装的锁里没有全量锁：{sorted(installed_locks)}")

    pw = re.search(r"playwright[^\n]*install[^\n]*(--with-deps)", surface)
    pw_any = re.search(r"playwright[^\n]*install", surface)
    print(
        f"[5c] playwright 浏览器安装={'存在' if pw_any else '缺失'}  "
        f"带 --with-deps={'是' if pw else '否'}"
    )
    if not pw:
        failures.append("playwright 浏览器未装（或缺 --with-deps 的系统库）")

    uses_npm = re.search(r"npm\s+(ci|install)", surface)
    print(f"[5d] 前端依赖装法 npm ci={'存在' if uses_npm else '缺失'}")
    if not uses_npm:
        failures.append("前端依赖未安装")

    # ── [5f] 构建上下文可见性（.dockerignore 不得挡 COPY 源）─────────────
    ignores = [
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    def _excluded(path: str) -> bool:
        import re as _re

        def _match(pattern: str, candidate: str) -> bool:
            body = pattern.lstrip("/")
            variants = {body}
            if "**/" in body:
                variants.add(body.replace("**/", ""))
            for variant in variants:
                regex = _re.escape(variant).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
                if _re.fullmatch(regex, candidate) or _re.fullmatch(regex + "/.*", candidate):
                    return True
            return False

        flag = False
        for pattern in ignores:
            if pattern.startswith("!"):
                if _match(pattern[1:].lstrip("/"), path):
                    flag = False
            elif _match(pattern, path):
                flag = True
        return flag

    copied = re.findall(r"^COPY\s+(\S+)\s", ide, re.M)
    blocked = [src for src in copied if _excluded(src)]
    print(f"[5f] .ide/Dockerfile COPY 源={copied}  被 .dockerignore 挡={blocked}")
    if blocked:
        failures.append(f"COPY 源被 .dockerignore 挡：{blocked}（docker build 直接失败）")

    # 全量锁覆盖的运行依赖抽样（真解析锁文件，不手抄包名）
    lock_names = {
        line.split("==")[0].strip().lower().replace("-", "_")
        for line in _read("requirements-full.lock").splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    }
    probes = [
        "onnxruntime", "sentence_transformers", "transformers", "edge_tts",
        "playwright", "pyautogui", "jieba", "reportlab", "soundfile",
    ]
    hit = [name for name in probes if name in lock_names]
    print(f"[5e] 全量锁覆盖运行依赖抽样={len(hit)}/{len(probes)}  {sorted(hit)}")
    if len(hit) != len(probes):
        failures.append(f"全量锁缺运行依赖：{sorted(set(probes) - set(hit))}")

    # ── [5g] CodeBuddy Web 入口（codebuddy 命令 + 版本） ──────────────
    codebuddy = re.search(
        r"^\s*RUN\b[^\n]*npm[^\n]*@tencent-ai/codebuddy-code", ide, re.M
    )
    print(
        f"[5g] codebuddy 真装指令={'存在' if codebuddy else '缺失'}"
        "  ⇒ CodeBuddy Web 入口" + ("可见" if codebuddy else "不可见")
    )
    if not codebuddy:
        failures.append("镜像缺 codebuddy 命令，CodeBuddy Web 入口不展示")

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

    # ── [6b] 资源规格：流水线 runner.cpus 与按钮 cpus 同源 ─────────────
    pipeline_cpus = (vscode.get("runner") or {}).get("cpus")
    print(f"[6b] 流水线 runner.cpus={pipeline_cpus}")

    # ── [7] 启动按钮 ─────────────────────────────────────────────────
    settings = yaml.safe_load(_read(".cnb/settings.yml"))
    launch = settings["workspace"]["launch"]
    print(
        f"[7] 按钮名={launch['button']['name']!r}  cpus={launch['cpus']}  "
        f"autoOpenWebIDE={launch['autoOpenWebIDE']}  NPC 角色数={len(settings['npc']['roles'])}"
    )
    if pipeline_cpus != launch["cpus"]:
        failures.append(
            f"runner.cpus={pipeline_cpus} 与按钮 cpus={launch['cpus']} 分叉"
        )
    welcome = (vscode.get("env") or {}).get("CNB_WELCOME_CMD")
    print(f"[7b] CNB_WELCOME_CMD={'已声明' if welcome else '未声明'}")

    if failures:
        print("\nLIVE-VERIFY FAILED / Issue #289 · 开发环境")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nLIVE-VERIFY PASSED / Issue #289 · 开发环境")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
