# -*- coding: utf-8 -*-
"""OPS-02 镜像交付面：运行时读的 config/ JSON 必须随镜像交付且解析得通。

审计 2026-11-25 批次 E 实测：`.dockerignore` 用 `config/*.json` 一刀切（只放行
cors.json 与 llm_presets/），而生产代码运行时会读四类 config 资产：

- `config/cors.json`（neurova/api/cors_policy.py）
- `config/llm_presets/*.json`（neurova/llm/presets.py）
- `config/llm_provider_templates.json`（neurova/llm/provider_manager.py）
- `config/evolution_settings.json`（neurova/evolution/evolution_settings.py）

后两项被挡在构建上下文之外 ⇒ `docker build` 全绿、容器能起，但服务商管理页
在第一次 `builtinProviderDefs()` 时抛 FileNotFoundError，进化设置静默回默认。
Compose 形态因 `./config:/app/config:ro` 挂载而看不出问题，独立镜像才暴露。

判据（不跑 docker build，按 Docker 语义模拟）：
1. 生产代码里的真解析点（resolver）逐一枚举 → 必须全部登记在门禁的
   `RUNTIME_CONFIG_ASSETS`（单源声明，防"新加读取方无人看守"）；
2. 按 Dockerfile 的 `COPY config/` 面 ∩ `.dockerignore` 规则算出的**假构建清单**
   → 每个声明资产都必须在清单里；
3. 把清单落盘成假镜像目录，用**真运行期解析器**读通（不是"文件存在"了事）；
4. 反向控制：模拟器对一条确实被排除的文件必须判排除（防"永远通过"）。
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "scripts" / "ci" / "deploy_config_consistency_check.py"
DOCKERFILE = REPO_ROOT / "Dockerfile"
CONFIG_ROOT = REPO_ROOT / "config"
WORKDIR = "/app"


def _loadGate():
    """按文件路径加载部署一致性门禁（取 RUNTIME_CONFIG_ASSETS 与 .dockerignore 实现）。"""
    spec = importlib.util.spec_from_file_location("neurova_deploy_gate_ops02", GATE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _relPosix(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


#: 在**干净子进程**里调用四个 reader 自己的落点解析函数，打印仓内相对路径 JSON。
#:
#: 必须另起进程：`tests/conftest.py` 的 autouse 夹具把 `cors_policy.configFile`
#: monkeypatch 到每测试临时目录（防测试写入仓库 config/cors.json），在 pytest
#: 进程内调用拿到的是 tmp 路径，相对化会直接 ValueError —— 那是隔离机制在
#: 正常工作，不是产品缺陷。子进程清掉进化设置的环境覆盖后读默认锚。
_RESOLVER_PROBE = r"""
import json
from pathlib import Path

from neurova.api import cors_policy
from neurova.evolution import evolution_settings
from neurova.llm import presets, provider_manager

registry = presets.LLMPresetRegistry.__new__(presets.LLMPresetRegistry)
assets = [
    str(cors_policy.configFile()),
    str(provider_manager._providerTemplatePath()),
    str(evolution_settings._settings_path()),
]
assets += [str(p) for p in Path(registry._get_presets_path()).glob("*.json")]
print(json.dumps(assets))
"""


def _runtimeConfigAssets() -> set:
    """生产代码真解析点枚举出的运行时 config 资产（仓内相对路径）。"""
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "NEUROVA_EVOLUTION_SETTINGS"}
    env["PYTHONIOENCODING"] = "utf-8"
    probe = subprocess.run(
        [sys.executable, "-c", _RESOLVER_PROBE],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    assert probe.returncode == 0, (
        "无法在干净进程里枚举运行期 config 资产（reader 解析点自身报错）：\n"
        f"{probe.stderr[-1200:]}"
    )
    paths = json.loads(probe.stdout.strip().splitlines()[-1])
    return {_relPosix(Path(path)) for path in paths}


#: Dockerfile 里把仓内目录搬进镜像的 COPY（排除 `COPY --from=` 的多阶段取件）
_CONFIG_COPY_RE = re.compile(r"^COPY\s+(?!--from)(\S+)\s+(\S+)\s*$", re.MULTILINE)


def _configCopyDirectives() -> list:
    """`COPY config/ <dest>` 指令表：[(仓内源前缀, 镜像内目标目录)]。"""
    text = DOCKERFILE.read_text(encoding="utf-8")
    directives = []
    for src, dest in _CONFIG_COPY_RE.findall(text):
        if not src.startswith("config/"):
            continue
        srcPrefix = src.rstrip("/") + "/"
        destNorm = dest.replace("\\", "/")
        while destNorm.startswith("./"):
            destNorm = destNorm[2:]
        destNorm = "/" + destNorm.strip("/")
        directives.append((srcPrefix, destNorm))
    return directives


def _imageConfigManifest() -> dict:
    """假构建清单：{仓内相对路径: 文件字节} —— Dockerfile COPY 面 ∩ .dockerignore 放行面。

    这是 `docker build` 对 config/ 的交付结果的最小可判据投影：
    - 不在 COPY 源目录下的文件进不了镜像；
    - 被 .dockerignore 命中的文件连构建上下文都进不去（Docker 以最后一条规则为准）。
    """
    gate = _loadGate()
    directives = _configCopyDirectives()
    assert directives, (
        "Dockerfile 里解析不到任何 `COPY config/ ...` —— 镜像根本不含 config 资产"
        "（判据会静默空转，禁止用「没找到就算过」短路）"
    )
    manifest: dict = {}
    for path in CONFIG_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = _relPosix(path)
        if gate.isDockerignored(rel):
            continue
        for srcPrefix, destDir in directives:
            if rel.startswith(srcPrefix):
                manifest[rel] = path.read_bytes()
                break
    return manifest


@pytest.fixture
def imageRoot(tmp_path) -> Path:
    """把假构建清单落盘成一个假镜像根（`<tmp>/app/config/...`）。"""
    root = tmp_path / "image"
    for rel, payload in _imageConfigManifest().items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


class TestDeclarationCoversProductionReaders:
    def test_everyResolvedRuntimeAssetIsDeclared(self):
        """生产代码读的每个 config 资产都必须登记在门禁的单源表里。

        表在 scripts/ci（R10 的判据面），resolver 在 neurova/（事实面）。
        此处把两者对齐：新增读取方只改 neurova 时，本判据红——不会出现
        「镜像缺文件但没有任何守卫看得见」的第三种状态。
        """
        gate = _loadGate()
        declared = set(gate.RUNTIME_CONFIG_ASSETS)
        resolved = _runtimeConfigAssets()
        missing = sorted(resolved - declared)
        assert not missing, (
            f"生产代码运行时会读、但门禁 RUNTIME_CONFIG_ASSETS 未登记的资产：{missing}\n"
            "未登记 = R10 不会检查它是否被 .dockerignore 挡掉、R12 也不会检查是否被卷遮蔽。"
        )

    def test_noStaleDeclaration(self):
        """表里每一条都要指向真实存在的文件（声明面不得指向已退役资产）。"""
        gate = _loadGate()
        stale = sorted(asset for asset in gate.RUNTIME_CONFIG_ASSETS if not (REPO_ROOT / asset).is_file())
        assert not stale, f"RUNTIME_CONFIG_ASSETS 声明了不存在的文件：{stale}"


class TestFakeBuildManifest:
    def test_everyDeclaredAssetLandsInImage(self):
        """假构建清单：声明资产一个都不能少。"""
        gate = _loadGate()
        manifest = _imageConfigManifest()
        missing = sorted(asset for asset in gate.RUNTIME_CONFIG_ASSETS if asset not in manifest)
        assert not missing, (
            f"这些运行时资产被 .dockerignore 挡在构建上下文之外（镜像里不存在）：{missing}\n"
            ".dockerignore 的 `config/*.json` 是一刀切排除——按运行所需逐个 `!` 放行。"
        )

    def test_manifestCoversPresetsDirectory(self):
        """预设是目录级读取（glob *.json），不能只放行单个 defaults.json。"""
        manifest = _imageConfigManifest()
        presets = [rel for rel in manifest if rel.startswith("config/llm_presets/")]
        assert presets, "假构建清单里没有任何 llm_presets/*.json —— 模型预设会静默回落"

    def test_filterIsNotVacuous(self):
        """反向控制：确实被排除的文件必须判为排除（防模拟器永远通过）。"""
        gate = _loadGate()
        assert gate.isDockerignored("config/some-local-only.json") is True
        assert gate.isDockerignored("config/cors.json") is False


class TestFakeImageCopiesParseWithRuntimeReaders:
    """从假镜像目录读通：文件在不在之外，还要"读得动"。"""

    def test_corsPolicyReadsImageCopy(self, imageRoot):
        from neurova.api import cors_policy

        imageCors = imageRoot / "config" / "cors.json"
        raw = json.loads(imageCors.read_text(encoding="utf-8"))
        assert cors_policy.effectiveOrigins(config_file=str(imageCors)) == raw["origins"]

    def test_providerManagerReadsImageCopy(self, imageRoot, monkeypatch):
        from neurova.llm import provider_manager

        imageTemplates = imageRoot / "config" / "llm_provider_templates.json"
        raw = json.loads(imageTemplates.read_text(encoding="utf-8"))
        monkeypatch.setattr(provider_manager, "_providerTemplatePath", lambda: imageTemplates)
        defs = provider_manager.builtinProviderDefs()
        assert [d["id"] for d in defs] == [e["id"] for e in raw["providers"]]
        assert defs, "镜像内的服务商模板解析出 0 条 —— 服务商管理页会整块不可用"

    def test_evolutionSettingsReadsImageCopy(self, imageRoot, monkeypatch):
        from neurova.evolution import evolution_settings

        imageSettings = imageRoot / "config" / "evolution_settings.json"
        raw = json.loads(imageSettings.read_text(encoding="utf-8"))
        monkeypatch.setenv("NEUROVA_EVOLUTION_SETTINGS", str(imageSettings))
        settings = evolution_settings.load_settings()
        assert settings.text_evolution == raw["text_evolution"]
        assert settings.lifecycle_interval_hours == raw["lifecycle_interval_hours"]

    def test_presetRegistryReadsImageCopy(self, imageRoot):
        from neurova.llm import presets

        presetsDir = imageRoot / "config" / "llm_presets"
        rawCount = sum(
            len(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(presetsDir.glob("*.json"))
        )
        registry = presets.LLMPresetRegistry(presets_dir=str(presetsDir))
        assert len(registry.list_presets()) == rawCount, (
            "镜像内预设解析条数与文件声明不符——预设目录未随镜像完整交付"
        )