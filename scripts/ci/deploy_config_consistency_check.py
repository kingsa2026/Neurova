#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""部署配置一致性门禁（Dockerfile ↔ docker-compose ↔ Helm ↔ 依赖声明）。

为什么要这个门禁：同一套服务的三种交付形态（镜像 / compose / Helm）各写各的
配置，且**没有一条自动化检查**把它们对齐。于是"改了一处忘了另外两处"导致的
漂移只能等上线才暴露，典型形态：

- 端口/健康检查契约各不相同（Dockerfile HEALTHCHECK 30s 周期 vs Helm 10s）；
- compose 里写了资源限制而 Helm 没有（或反之），扩缩容行为不一致；
- 环境变量名写错（如 configmap 写 DATABASE_PATH、应用读 NEUROVA_DB_PATH），
  值看起来设了、其实应用从未读到 —— 最隐蔽的一类；
- 镜像落不到 CI 实测的 Python/Node 版本上；
- 生产声明的硬依赖（裸 import 无降级）没进 requirements.txt，镜像能起来但
  功能路径 import 即崩。

门禁内容是**跨文件不变量**，不是单文件 lint：

R1 端口一致性      Dockerfile EXPOSE / start_server 默认端口 / compose 映射 /
                   Helm service+targetPort+env+configmap 必须同一个值
R2 健康检查一致性  Dockerfile HEALTHCHECK / compose healthcheck / Helm 基础
                   values.healthCheck（探针契约同源）
R3 资源限制一致性  compose deploy.resources 与 Helm backend.resources 精确相等
                   （cpu 归一到 millicore、memory 归一到 byte 后比较）
R4 镜像与版本      Dockerfile 基础镜像 Python 版本 ∈ CI 实测矩阵且 ≥ 项目最低
                   版本；compose 前端 Node 版本 == CI node 版本；Chart appVersion
                   == neurova.__version__；镜像 tag 不得写死 latest
R5 环境变量可读    三种交付形态声明的环境变量必须真被应用读取（源码扫描）
R6 持久化接线      persistence.enabled 时数据卷必须是 PVC，不得退化为 emptyDir
R7 鉴权密钥注入    后端必须支持 NEUROVA_JWT_SECRET 注入（多副本/生产前提）
R8 依赖声明包含    生产镜像声明的硬依赖必须同时进 CI 硬依赖表（反之亦然）
R9 门禁自身接线    两侧 CI（cnb + GitHub）都跑本脚本，且 cnb 有周级 crontab 巡检
R10 镜像内配置资产 应用运行时从 config/ 读的文件必须真被打进镜像（.dockerignore
                   不得把它们排除掉，否则容器里静默走内置默认值）
R11 Helm values 引用 模板引用的每个 .Values 路径必须在 values.yaml 定义（否则渲染成
                   <no value>，配置静默失效且 Helm 不报错）
R12 镜像内 config 遮蔽 Helm 不得用 ConfigMap 卷挂到 /app/config（会整体盖掉镜像内
                   config/cors.json 与 config/llm_presets/，与 R10 同类故障）

用法：
    python scripts/ci/deploy_config_consistency_check.py          # 人读报告
    python scripts/ci/deploy_config_consistency_check.py --json   # 机器可读
退出码：0 = 全部通过（可有 WARN）；1 = 存在 ERROR。
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import re
import sys

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECK_CMD = "scripts/ci/deploy_config_consistency_check.py"

# 生产镜像（Dockerfile + requirements.txt）必须声明的硬依赖：裸 import 无降级，
# 缺席即对应功能路径 import 崩（与 tests/unit/test_ci_thin_env_guards.py 同源口径）。
# 注：不要把"try/except ImportError 降级"的包放进来——mcp 即属此类
# （neurova/tool_layers/mcp_client.py 缺席时 _SDK_AVAILABLE=False，功能降级不崩），
# CI 精简集仍按测试需要声明它，但生产镜像不强制。
HARD_DEPS = ("apscheduler", "feedparser", "segno", "prometheus_client")

# R5 只扫"应用运行时环境变量声明面"（compose environment + helm values.backend.env +
# configmap）；Helm deployment 模板里的 secret 注入面（LLM_API_KEY 等）不在扫描范围，
# 因为那是"给 operator 预留的键位"，不随源码读取面收敛。

# 非 NEUROVA_ 前缀但确属运行时的标准环境变量（Python/时区），白名单保持最小。
ENV_ALLOWLIST = {"PYTHONUNBUFFERED", "PYTHONUTF8", "PYTHONIOENCODING", "TZ", "LC_ALL", "LANG"}

# 应用运行时会从 config/ 目录读取的文件（reader 见注释）。镜像缺它们时不会报错，
# 只会静默回落到内置默认值——比崩溃更难发现。
RUNTIME_CONFIG_ASSETS = {
    "config/cors.json": "neurova/api/middleware.py（CORS 来源清单）",
    "config/llm_presets/defaults.json": "neurova/llm/presets.py（模型预设）",
}

# 最小调度间隔由平台限制（5 分钟）；周级 cadence 的判据见 _check_ci_wiring。
WEEKLY_CRON = re.compile(r"^crontab:\s*(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*$")

class Finding:
    __slots__ = ("level", "rule", "message")

    def __init__(self, level: str, rule: str, message: str) -> None:
        self.level = level
        self.rule = rule
        self.message = message

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "rule": self.rule, "message": self.message}


def _read(*parts: str) -> str:
    return io.open(PROJECT_ROOT.joinpath(*parts), encoding="utf-8").read()


def _load_yaml(*parts: str) -> Any:
    return yaml.safe_load(_read(*parts))


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
_CPU_RE = re.compile(r"^(\d+(?:\.\d+)?)(m?)$")
_MEM_RE = re.compile(r"^(\d+(?:\.\d+)?)([a-zA-Z]*)$")
# 单位口径（跨形态比较的前提，别想当然）：
#   Docker/compose 的 k/m/g 是 **1024 进制**（--memory=512m 即 512MiB）；
#   Kubernetes 的 Ki/Mi/Gi 同为 1024 进制，而 K/M/G（大写）才是 1000 进制。
# 故裸 k/m/g 按 1024 归一，才能与 k8s 的 Mi/Gi 正确相等。
_MEM_UNITS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "m": 1024**2,
    "g": 1024**3,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "ki": 1024,
    "kib": 1024,
    "mi": 1024**2,
    "mib": 1024**2,
    "gi": 1024**3,
    "gib": 1024**3,
}


def cpu_millicores(value: Any) -> int | None:
    """cpu 归一到 millicore：`2` / `2.0` / `2000m` → 2000。"""
    if value is None:
        return None
    m = _CPU_RE.match(str(value).strip())
    if not m:
        return None
    number = float(m.group(1))
    # "2000m" 已是 millicore；"2" / "2.0"（compose cpus 写法的核数）才需 ×1000
    return int(round(number)) if m.group(2) == "m" else int(round(number * 1000))


def memory_bytes(value: Any) -> int | None:
    """memory 归一到 byte，支持 Kubernetes（Gi/Mi）与 compose（g/m）两种记法。"""
    if value is None:
        return None
    m = _MEM_RE.match(str(value).strip())
    if not m:
        return None
    unit = m.group(2).lower()
    if unit not in _MEM_UNITS:
        return None
    return int(round(float(m.group(1)) * _MEM_UNITS[unit]))


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def parse_dockerfile() -> Dict[str, Any]:
    text = _read("Dockerfile")
    stages = re.findall(r"^FROM\s+(\S+)(?:\s+[aA][sS]\s+(\S+))?", text, re.M)
    expose = [int(p) for p in re.findall(r"^EXPOSE\s+(\d+)", text, re.M)]
    health = None
    # HEALTHCHECK 是**多行**指令（`--interval=... \` 换行后接 CMD curl ...：
    # 只截首行会漏掉 URL，path/port 静默变成 None，健康检查路径的比较等于没做）。
    m = re.search(r"^HEALTHCHECK\b((?:.*\\\n)*.*)$", text, re.M)
    if m:
        flags = m.group(1)
        url = re.search(r"http://localhost:(\d+)(/[^\s,]+)", flags)
        health = {
            "interval": _flag(flags, "interval"),
            "timeout": _flag(flags, "timeout"),
            "start_period": _flag(flags, "start-period"),
            "retries": _flag(flags, "retries"),
            "port": int(url.group(1)) if url else None,
            "path": url.group(2) if url else None,
        }
    cmd = re.search(r"^CMD\s+(\[.*\])", text, re.M)
    return {
        "stages": stages,
        "base_images": [s[0] for s in stages],
        "expose": expose,
        "healthcheck": health,
        "cmd": cmd.group(1) if cmd else None,
    }


def _flag(flags: str, name: str) -> int | None:
    # 时长类（interval/timeout/start-period）带 s 后缀，retries 是纯数字 ——
    # 只认带 s 的写法会把 retries 静默读成 None（等于漏比一项）。
    m = re.search(rf"--{re.escape(name)}=(\d+)s?", flags)
    return int(m.group(1)) if m else None


def parse_compose() -> Dict[str, Any]:
    doc = _load_yaml("docker-compose.yml") or {}
    services = doc.get("services") or {}

    def env_of(svc: Dict[str, Any]) -> Dict[str, str]:
        raw = svc.get("environment")
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        out: Dict[str, str] = {}
        for item in raw or []:
            key, _, value = str(item).partition("=")
            out[key.strip()] = value.strip()
        return out

    def port_of(svc: Dict[str, Any]) -> int | None:
        for entry in svc.get("ports") or []:
            m = re.match(r"^(\d+):(\d+)$", str(entry))
            if m:
                return int(m.group(1))
        return None

    return {name: {"env": env_of(svc), "port": port_of(svc), "raw": svc} for name, svc in services.items()}


def parse_helm() -> Dict[str, Any]:
    base = _load_yaml("helm", "neurova", "values.yaml") or {}
    envs = {
        name: _load_yaml("helm", "neurova", f"values-{name}.yaml") or {}
        for name in ("development", "production")
    }
    return {
        "base": base,
        "development": envs["development"],
        "production": envs["production"],
        "chart": _load_yaml("helm", "neurova", "Chart.yaml") or {},
        "deployment": _read("helm", "neurova", "templates", "deployment-backend.yaml"),
        "secret": _read("helm", "neurova", "templates", "secret.yaml"),
        "configmap": _read("helm", "neurova", "templates", "configmap.yaml"),
        "pvc": _read("helm", "neurova", "templates", "pvc.yaml"),
    }


# 后端直读面（os.environ / config.get）
BACKEND_ENV_READ = re.compile(
    r"(?:os\.environ\.get|os\.getenv|getenv|config\.get|config\.get_int"
    r"|config\.get_bool|config\.get_list)\(\s*[\"']([A-Z][A-Z0-9_]+)[\"']"
)
# 前端编译期注入面（Vite：import.meta.env.VITE_*）
FRONTEND_ENV_READ = re.compile(r"import\.meta\.env\.([A-Z][A-Z0-9_]+)")


def parse_app_read_env_keys() -> set:
    """真被读取的环境变量名（后端直读面 + 前端 Vite 注入面）。

    只扫 neurova/ 会误报 VITE_*（它们由 NeurUI 在构建/开发服务器上读取），
    故前端源码一并纳入读取面。
    """
    keys = set()
    for path in PROJECT_ROOT.joinpath("neurova").rglob("*.py"):
        keys.update(BACKEND_ENV_READ.findall(path.read_text(encoding="utf-8", errors="ignore")))
    # 仓库根启动脚本（start_server.py 是生产容器入口，读 NEUROVA_LOG_LEVEL /
    # NEUROVA_HOST / NEUROVA_PORT）与 scripts/ 一并纳入扫描面
    for name in ("start_server.py", "start.py", "cli.py", "install.py"):
        target = PROJECT_ROOT / name
        if target.exists():
            keys.update(BACKEND_ENV_READ.findall(target.read_text(encoding="utf-8", errors="ignore")))
    for path in PROJECT_ROOT.joinpath("scripts").rglob("*.py"):
        keys.update(BACKEND_ENV_READ.findall(path.read_text(encoding="utf-8", errors="ignore")))
    for suffix in ("*.ts", "*.js", "*.vue", "*.mjs"):
        for path in PROJECT_ROOT.joinpath("NeurUI", "src").rglob(suffix):
            keys.update(FRONTEND_ENV_READ.findall(path.read_text(encoding="utf-8", errors="ignore")))
    return keys


def parse_requirements() -> Dict[str, set]:
    def names(name: str) -> set:
        out = set()
        for raw in _read(name).splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            out.add(re.split(r"[>=<!\[;~ ]", line)[0].strip().lower().replace("-", "_"))
        return out

    return {"prod": names("requirements.txt"), "ci": names("requirements-ci.txt")}


# ---------------------------------------------------------------------------
# 规则
# ---------------------------------------------------------------------------
def _check_ports(docker: Dict[str, Any], compose: Dict[str, Any], helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    base = helm["base"]
    # 入口脚本的默认端口两种写法都要认：`os.environ.get("NEUROVA_PORT", 9527)`
    # 与 `os.environ.get("NEUROVA_PORT", "9527")`。只认数字形态会静默漏比
    # （实测：改成字符串默认值后该项变成 None，被"过滤 None"逻辑悄悄放过）。
    start_server = re.search(r'NEUROVA_PORT"\s*,\s*"?([0-9]+)"?', _read("start_server.py"))
    if not start_server:
        out.append(
            Finding(
                "error",
                "R1-ports",
                "未能在 start_server.py 解析到 NEUROVA_PORT 默认端口——"
                "端口一致性比较会静默少一项（不要把该解析写成可选）",
            )
        )
    observed = {
        "Dockerfile EXPOSE": (docker["expose"] or [None])[0],
        "start_server 默认端口": int(start_server.group(1)) if start_server else None,
        "compose backend 端口映射": compose["backend"]["port"],
        "Helm backend.service.port": base["backend"]["service"]["port"],
        "Helm backend.service.targetPort": base["backend"]["service"]["targetPort"],
        "Helm backend.env NEUROVA_PORT": _env_value(base["backend"].get("env") or [], "NEUROVA_PORT"),
        "Helm configmap NEUROVA_PORT": _configmap_value(helm["configmap"], "NEUROVA_PORT", helm),
        "compose backend NEUROVA_PORT": compose["backend"]["env"].get("NEUROVA_PORT"),
    }
    distinct = {str(v) for v in observed.values() if v is not None}
    if len(distinct) != 1:
        out.append(
            Finding(
                "error",
                "R1-ports",
                "后端端口在交付形态间不一致：" + "，".join(f"{k}={v}" for k, v in observed.items()),
            )
        )
    if base["frontend"]["service"]["port"] != compose.get("frontend", {}).get("port"):
        out.append(
            Finding(
                "error",
                "R1-ports",
                f"前端端口不一致：Helm {base['frontend']['service']['port']} vs "
                f"compose {compose.get('frontend', {}).get('port')}",
            )
        )
    return out


def _check_health(docker: Dict[str, Any], compose: Dict[str, Any], helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    dhc = docker["healthcheck"] or {}
    chc = compose["backend"]["raw"].get("healthcheck") or {}
    hhc = helm["base"]["backend"].get("healthCheck") or {}
    pairs = (
        ("interval/periodSeconds", dhc.get("interval"), _seconds(chc.get("interval")), hhc.get("periodSeconds")),
        ("timeout/timeoutSeconds", dhc.get("timeout"), _seconds(chc.get("timeout")), hhc.get("timeoutSeconds")),
        ("start-period/initialDelaySeconds", dhc.get("start_period"), _seconds(chc.get("start_period")), hhc.get("initialDelaySeconds")),
        ("retries/failureThreshold", dhc.get("retries"), chc.get("retries"), hhc.get("failureThreshold")),
    )
    for label, dv, cv, hv in pairs:
        values = {str(v) for v in (dv, cv, hv) if v is not None}
        if len(values) != 1:
            out.append(
                Finding(
                    "error",
                    "R2-healthcheck",
                    f"健康检查 {label} 不一致：Dockerfile={dv}, compose={cv}, Helm={hv}",
                )
            )
    # 环境 overrides（values-development / values-production）里的 healthCheck
    # 同样要比对：base 对齐、override 漂移 = 生产探活仍是另一套口径。
    for env_name in ("development", "production"):
        override = ((helm[env_name].get("backend") or {}).get("healthCheck")) or {}
        for label, dv, hv in (
            ("periodSeconds", dhc.get("interval"), override.get("periodSeconds")),
            ("timeoutSeconds", dhc.get("timeout"), override.get("timeoutSeconds")),
            ("initialDelaySeconds", dhc.get("start_period"), override.get("initialDelaySeconds")),
            ("failureThreshold", dhc.get("retries"), override.get("failureThreshold")),
            ("path", (dhc.get("path") or "").split("?")[0] or None, override.get("path")),
        ):
            if hv is not None and str(hv) != str(dv):
                out.append(
                    Finding(
                        "error",
                        "R2-healthcheck",
                        f"values-{env_name}.yaml 的 healthCheck.{label}={hv} 与 "
                        f"Dockerfile/compose 的 {dv} 不一致（同一镜像两套探活口径）",
                    )
                )
    # readiness 探针参数必须走 values（可以刻意与 liveness 不同，但不能硬编码在
    # 模板里）：模板写死即"两处同源 + 一处隐形口径"，本规则只比 values 于是完全看不见。
    template = helm["deployment"]
    for probe in ("readinessProbe", "livenessProbe"):
        block = re.search(rf"{probe}:\n((?:\s+.*\n?)+)", template)
        if not block:
            continue
        for key in ("initialDelaySeconds", "periodSeconds", "timeoutSeconds", "failureThreshold"):
            m = re.search(rf"^\s+{key}:\s*(\S+)\s*$", block.group(1), re.M)
            if m and not m.group(1).startswith("{{"):
                out.append(
                    Finding(
                        "error",
                        "R2-healthcheck",
                        f"deployment-backend.yaml 的 {probe}.{key} 硬编码为 {m.group(1)}"
                        "（不走 values → 跨环境/跨形态无法对齐，门禁也看不见）",
                    )
                )
    path = (dhc.get("path") or "").split("?")[0]
    if path and hhc.get("path") != path:
        out.append(
            Finding(
                "error",
                "R2-healthcheck",
                f"健康检查路径不一致：Dockerfile={path}, Helm healthCheck.path={hhc.get('path')}",
            )
        )
    if dhc.get("port") and dhc["port"] != compose["backend"]["port"]:
        out.append(Finding("error", "R2-healthcheck", "compose 健康检查端口与 Dockerfile EXPOSE 不一致"))
    return out


def _seconds(value: Any) -> int | None:
    m = re.match(r"^(\d+)s$", str(value)) if value is not None else None
    return int(m.group(1)) if m else None


def _check_resources(compose: Dict[str, Any], helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    compose_res = ((compose["backend"]["raw"].get("deploy") or {}).get("resources")) or {}
    helm_res = helm["base"]["backend"].get("resources") or {}

    def get(block: Dict[str, Any], key: str) -> Any:
        entry = block.get(key) or {}
        return {"cpu": cpu_millicores(entry.get("cpu", entry.get("cpus"))), "memory": memory_bytes(entry.get("memory"))}

    if not compose_res:
        out.append(
            Finding(
                "error",
                "R3-resources",
                "compose backend 未声明 deploy.resources —— 与 Helm resources.requests/limits 无法对齐"
                "（同一镜像两种资源口径）",
            )
        )
        return out
    for key, helm_key in (("limits", "limits"), ("reservations", "requests")):
        c, h = get(compose_res, key), get(helm_res, helm_key)
        if c != h:
            out.append(
                Finding(
                    "error",
                    "R3-resources",
                    f"资源{helm_key}不一致：compose {key}={c} vs Helm {helm_key}={h}"
                    "（cpu 按 millicore、memory 按 byte 归一后比较）",
                )
            )
    return out


def _check_images(docker: Dict[str, Any], helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    ci = _read(".github", "workflows", "ci.yml")
    py_versions = set(re.findall(r'python-version:\s*"(\d+\.\d+)"', ci))
    py_min = re.search(r"MIN_PYTHON_VERSION\s*=\s*\((\d+),\s*(\d+)\)", _read("scripts", "config.py"))
    min_ver = f"{py_min.group(1)}.{py_min.group(2)}" if py_min else None

    for image in docker["base_images"]:
        m = re.match(r"^python:(\d+\.\d+)", image)
        if not m:
            out.append(Finding("warn", "R4-images", f"Dockerfile 基础镜像非 python:* 形态：{image}"))
            continue
        version = m.group(1)
        if version not in py_versions:
            out.append(
                Finding(
                    "error",
                    "R4-images",
                    f"Dockerfile 基础镜像 python:{version} 不在 CI 实测版本 {sorted(py_versions)} 内"
                    "（生产跑的是未经 CI 验证的解释器）",
                )
            )
        if min_ver and _ver_tuple(version) < _ver_tuple(min_ver):
            out.append(Finding("error", "R4-images", f"Dockerfile Python {version} < 项目最低 {min_ver}"))

    node = re.search(r'node-version:\s*"(\d+)"', ci)
    fe_image = ((compose_image := _load_yaml("docker-compose.yml") or {}).get("services", {})
                .get("frontend", {}).get("image"))
    if node and fe_image:
        m = re.match(r"^node:(\d+)", str(fe_image))
        if not m or m.group(1) != node.group(1):
            out.append(
                Finding(
                    "error",
                    "R4-images",
                    f"compose 前端镜像 {fe_image} 与 CI node-version {node.group(1)} 不一致"
                    "（本地 dev 与 CI 跑不同大版本 Node）",
                )
            )

    app_version = re.search(r'__version__\s*=\s*"([^"]+)"', _read("neurova", "__init__.py"))
    chart_version = str(helm["chart"].get("appVersion", ""))
    if app_version and chart_version != app_version.group(1):
        out.append(
            Finding(
                "error",
                "R4-images",
                f"Chart appVersion={chart_version} 与 neurova.__version__={app_version.group(1)} 不一致"
                "（部署产物版本与代码版本各说各话）",
            )
        )
    for env_name in ("base", "development", "production"):
        # frontend 一并查：只钉 backend 等于留了同一形态的后门（前端的 "latest"
        # 同样让同一份 values 在不同时刻拉到不同镜像）。
        for component in ("backend", "frontend"):
            tag = (((helm[env_name].get(component) or {}).get("image") or {}).get("tag"))
            if tag in ("latest", ":latest"):
                out.append(
                    Finding(
                        "error",
                        "R4-images",
                        f"Helm values({env_name}) 写死 {component}.image.tag=latest —— 部署不可复现，"
                        "请留空以跟随 Chart appVersion",
                    )
                )
    return out


def _ver_tuple(version: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def _check_env_keys(compose: Dict[str, Any], helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    read_keys = parse_app_read_env_keys()
    base = helm["base"]

    declared: Dict[str, str] = {}
    for key in compose["backend"]["env"]:
        declared.setdefault(key, "docker-compose.yml backend.environment")
    for key in compose.get("frontend", {}).get("env", {}):
        declared.setdefault(key, "docker-compose.yml frontend.environment")
    for entry in base["backend"].get("env") or []:
        declared.setdefault(entry["name"], "helm values.backend.env")
    for entry in _configmap_env_keys(helm["configmap"]):
        declared.setdefault(entry, "helm templates/configmap.yaml")

    for key, where in sorted(declared.items()):
        if key in ENV_ALLOWLIST or key in read_keys:
            continue
        out.append(
            Finding(
                "error",
                "R5-env",
                f"{where} 声明了 {key}，但应用源码从未读取该变量（值看起来设了、实际是死配置）",
            )
        )
    return out


def _configmap_value(template: str, key: str, helm: Dict[str, Any] | None = None) -> Any:
    """取 configmap 模板里某个键的字面值（纯 .Values 引用返回 None，交由其他规则校验）。"""
    m = re.search(rf"^\s{{2}}{re.escape(key)}:\s*(.+?)\s*$", template, re.M)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith("{{"):
        return None
    return raw.strip().strip('"')


def _configmap_env_keys(template: str) -> List[str]:
    keys = []
    for line in template.splitlines():
        m = re.match(r"^\s{2}([A-Z][A-Z0-9_]*):", line)
        if m:
            keys.append(m.group(1))
    return keys


def _volume_block(template: str, volume_name: str) -> str:
    """截取 `volumes:` 段里某个卷的 YAML 块（同名卷在 volumeMounts 也出现，取最后一段）。"""
    blocks = re.findall(
        rf"^\s*-\s*name:\s*{re.escape(volume_name)}\s*$\n((?:^\s+.*$\n?)+)",
        template, re.M,
    )
    return "\n".join(blocks)


def _check_persistence(helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    base = helm["base"]
    persistence = (base.get("database") or {}).get("persistence") or {}
    service = {
        "chart.svc": "helm/neurova/templates/pvc.yaml",
        "helm values": "helm/neurova/values.yaml",
    }
    deployment = helm["deployment"]
    if "persistentVolumeClaim" not in deployment:
        out.append(
            Finding(
                "error",
                "R6-persistence",
                "deployment-backend.yaml 未挂载 persistentVolumeClaim —— SQLite 数据随 Pod 重建丢失"
                f"（参考 {sorted(service.values())}）",
            )
        )
    # 判据看的是"data 卷块里有没有 persistentVolumeClaim 取值分支"，而不是
    # 全文有没有 emptyDir 字样——模板里 persistence.enabled=false 的 else 分支
    # 合法地写着 emptyDir（逐字匹配会把正常模板判红）。
    data_block = _volume_block(deployment, "data")
    if persistence.get("enabled") and "persistentVolumeClaim" not in data_block:
        out.append(
            Finding(
                "error",
                "R6-persistence",
                "persistence.enabled=true 但数据卷（name: data）无 persistentVolumeClaim 分支 "
                "—— SQLite 数据随 Pod 重建丢失",
            )
        )
    if persistence.get("enabled") and "-data" not in deployment:
        out.append(
            Finding(
                "error",
                "R6-persistence",
                "Chart 创建了 <fullname>-data PVC，但 deployment 未引用它（PVC 白建、数据无持久化）",
            )
        )
    return out


def _check_auth_secret(helm: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    if "NEUROVA_JWT_SECRET" not in helm["deployment"]:
        out.append(
            Finding(
                "error",
                "R7-auth",
                "deployment-backend.yaml 未注入 NEUROVA_JWT_SECRET —— 生产（NEUROVA_ENV=production）"
                "下每个副本各自随机生成密钥：跨副本 token 互不认可、重启即全员掉线",
            )
        )
    if "NEUROVA_JWT_SECRET" in helm["deployment"] and "jwt" not in helm["secret"].lower():
        out.append(Finding("error", "R7-auth", "secret.yaml 未提供 jwt-secret 键，注入面缺来源"))

    prod_replicas = (helm["production"].get("backend") or {}).get("replicaCount")
    base_replicas = (helm["base"].get("backend") or {}).get("replicaCount") or 1
    access_mode = str((helm["base"].get("database") or {}).get("persistence", {}).get("accessMode", ""))
    if (prod_replicas or base_replicas) > 1 and access_mode == "ReadWriteOnce":
        out.append(
            Finding(
                "warn",
                "R7-auth",
                f"副本数 >1 且持久卷 accessMode={access_mode}：嵌入式 SQLite 多进程同写风险，"
                "请确认单节点调度或改用外部数据库",
            )
        )
    return out


def _check_hard_deps(reqs: Dict[str, set]) -> List[Finding]:
    out: List[Finding] = []
    for dep in HARD_DEPS:
        if dep not in reqs["prod"]:
            out.append(
                Finding(
                    "error",
                    "R8-deps",
                    f"硬依赖 {dep} 未声明在 requirements.txt —— 生产镜像（Dockerfile 装 this）"
                    "相应功能路径 import 即崩",
                )
            )
        if dep not in reqs["ci"]:
            out.append(
                Finding(
                    "error",
                    "R8-deps",
                    f"硬依赖 {dep} 未声明在 requirements-ci.txt —— CI 薄环境导入巡检会漏掉它",
                )
            )
    return out


def _check_config_assets() -> List[Finding]:
    """R10：应用运行时读的 config/ 资产必须真进镜像。

    Dockerfile 有 `COPY config/ ./config/`，但 .dockerignore 里的 `config/*.json`
    会把 cors.json 挡在构建上下文之外 —— 构建成功、容器正常启动，只是 CORS
    来源静默回落到内置的 localhost/tauri 默认值（生产浏览器请求被拒，
    且日志里毫无线索）。
    """
    out: List[Finding] = []
    rules = [
        line.strip()
        for line in _read(".dockerignore").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    def ignored(path: str) -> bool:
        state = False
        for rule in rules:
            negate = rule.startswith("!")
            pattern = (rule[1:] if negate else rule).rstrip("/")
            matched = (
                fnmatch.fnmatch(path, pattern)
                or path.startswith(pattern + "/")
                or fnmatch.fnmatch(path.split("/")[-1], pattern)
            )
            if matched:
                state = not negate
        return state

    for asset, reader in RUNTIME_CONFIG_ASSETS.items():
        if ignored(asset):
            out.append(
                Finding(
                    "error",
                    "R10-config-assets",
                    f"{asset} 被 .dockerignore 排除，镜像内不存在（读取方：{reader}）"
                    "—— 构建/启动都正常，只是运行时静默走内置默认值",
                )
            )
    return out


def _check_helm_values_refs() -> List[Finding]:
    """Helm 模板引用的每个 .Values 路径必须在 values.yaml 有定义。

    `{{ .Values.foo.bar }}` 指向不存在的键时 Helm 不报错（渲染成 `<no value>`），
    出问题的往往是整段配置（如资源限制渲染成空 → 用集群默认值）。
    """
    out: List[Finding] = []
    import glob as _glob

    values = _load_yaml("helm", "neurova", "values.yaml") or {}

    def resolve(path: str) -> Any:
        cur: Any = values
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    refs: set = set()
    for path in _glob.glob(str(PROJECT_ROOT / "helm" / "neurova" / "templates" / "*")):
        text = io.open(path, encoding="utf-8").read()
        refs.update(
            m.group(1).rstrip(".")
            for m in re.finditer(r"(?:\$)?\.Values\.([A-Za-z0-9_.]+)", text)
        )
    missing = sorted(r for r in refs if resolve(r) is None)
    for ref in missing:
        out.append(
            Finding(
                "error",
                "R11-helm-values",
                f"模板引用了 values.yaml 中不存在的键 .Values.{ref}"
                "（Helm 渲染为 <no value> 不报错，该段配置静默失效）",
            )
        )
    return out


def _check_helm_config_shadow() -> List[Finding]:
    """R12：Helm 不得用卷挂载遮蔽镜像内的运行时 config 资产。

    R10 管的是"资产进没进镜像"（.dockerignore），本条管"进了镜像会不会被挂载遮蔽"：
    ConfigMap 卷挂在 /app/config 会把镜像内的 config/cors.json 与
    config/llm_presets/defaults.json 整体盖掉，而这些键在 ConfigMap 里根本没有
    （ConfigMap 装的是环境变量，已由 envFrom 注入）——于是运行时静默回落到内置
    默认值，与 R10 的故障表现完全一致，只是成因换到了 Helm 侧。
    """
    out: List[Finding] = []
    template = _read("helm", "neurova", "templates", "deployment-backend.yaml")
    # 收集模板里是 configMap 类型的卷名
    cm_volumes = set(re.findall(r"^\s*-\s*name:\s*(\S+)\s*$\n\s*configMap:", template, re.M))
    bodies = re.findall(r"volumeMounts:\n((?:\s+-.*\n(?:\s+.*\n?)*)+)", template)
    mount_paths = []
    for body in bodies:
        for m in re.finditer(
            r"-\s*name:\s*(\S+)\s*\n\s*mountPath:\s*([^\s]+)", body
        ):
            if m.group(1) in cm_volumes:
                mount_paths.append(m.group(2).strip())
    for mount_path in mount_paths:
        for asset in RUNTIME_CONFIG_ASSETS:
            # 资产在容器的位置是 /app/<asset>
            if asset.startswith("config/") and mount_path.rstrip("/") == "/app/config":
                out.append(
                    Finding(
                        "error",
                        "R12-config-shadow",
                        f"deployment-backend.yaml 把 ConfigMap 卷挂到 {mount_path}，"
                        f"整体遮蔽镜像内 {asset}（ConfigMap 里只有环境变量键）——"
                        "运行时静默回落内置默认值",
                    )
                )
    return out


def _check_ci_wiring() -> List[Finding]:
    out: List[Finding] = []
    cnb = _load_yaml(".cnb.yml") or {}
    ghw = _read(".github", "workflows", "ci.yml")
    main = cnb.get("main") or {}

    cnb_scripts = json.dumps(main.get("push") or [], ensure_ascii=False)
    if CHECK_CMD not in cnb_scripts:
        out.append(Finding("error", "R9-wiring", f".cnb.yml push 流水线未调用 {CHECK_CMD}"))
    if CHECK_CMD not in ghw:
        out.append(Finding("error", "R9-wiring", f".github/workflows/ci.yml 未调用 {CHECK_CMD}"))

    weekly = [
        key for key in main
        if isinstance(key, str) and key.startswith("crontab:")
        and WEEKLY_CRON.match(key)
        and WEEKLY_CRON.match(key).group(5) != "*"
        and CHECK_CMD in json.dumps(main[key], ensure_ascii=False)
    ]
    if not weekly:
        out.append(
            Finding(
                "error",
                "R9-wiring",
                "缺少周级 crontab 巡检流水线（形如 `main: \"crontab: 30 3 * * 1\"`，pipeline 内调用 "
                f"{CHECK_CMD}）——平台定时任务最小间隔 5 分钟，周级用第 5 段（星期）表达即可",
            )
        )
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _env_value(entries: Iterable[Dict[str, Any]], name: str) -> Any:
    for entry in entries:
        if entry.get("name") == name:
            return entry.get("value")
    return None


def run_checks() -> List[Finding]:
    docker = parse_dockerfile()
    compose = parse_compose()
    helm = parse_helm()
    findings: List[Finding] = []
    findings += _check_ports(docker, compose, helm)
    findings += _check_health(docker, compose, helm)
    findings += _check_resources(compose, helm)
    findings += _check_images(docker, helm)
    findings += _check_env_keys(compose, helm)
    findings += _check_persistence(helm)
    findings += _check_auth_secret(helm)
    findings += _check_hard_deps(parse_requirements())
    findings += _check_config_assets()
    findings += _check_helm_config_shadow()
    findings += _check_helm_values_refs()
    findings += _check_ci_wiring()
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="部署配置一致性门禁")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args()

    findings = run_checks()
    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warn"]

    if args.json:
        print(json.dumps(
            {"ok": not errors, "errors": [f.to_dict() for f in errors],
             "warnings": [f.to_dict() for f in warnings]},
            ensure_ascii=False, indent=2,
        ))
        return 1 if errors else 0

    print("=" * 72)
    print("部署配置一致性门禁：Dockerfile / docker-compose / Helm / requirements")
    print("=" * 72)
    if not findings:
        print("✅ 全部规则通过")
        return 0
    for finding in errors:
        print(f"❌ [{finding.rule}] {finding.message}")
    for finding in warnings:
        print(f"⚠️  [{finding.rule}] {finding.message}")
    print("-" * 72)
    print(f"ERROR {len(errors)} 项 / WARN {len(warnings)} 项")
    return 1 if errors else 0


if __name__ == "__main__":
    # 只在作为进程运行时重配控制台：本文件会被 `test_deploy_config_guard.py` 之类
    # 用 importlib 在 pytest 进程内加载，模块级 reconfigure 等于改宿主进程的捕获流。
    # 中文 Windows 的 cp936 编不出 ⚠️/🛑/→，`print` 会抛 UnicodeEncodeError 把门禁自己打死
    # （Linux CI 看不见这条）。同仓先例 scripts/ci_static_gate.py 是模块级——它不被 import。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
