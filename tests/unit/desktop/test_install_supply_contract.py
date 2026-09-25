# -*- coding: utf-8 -*-
"""install.py 供给契约守卫：依赖安装与模型安装必须接真事实源。

为什么要有本守卫（每条都对应一次实测断裂）：

1. **模型清单两份定义** —— `models/MANIFEST.json` 是 Windows 首启链路
   （`NeurUI/src-tauri/src/lib.rs` 读它判就绪）的模型事实源，而真正的下载器是
   `neurova/tts/model_downloader.py` 的 `MODEL_REGISTRY` 与
   `neurova/asr/model_downloader.py` 的 `ASR_MODEL_REGISTRY`。两边 id 与
   repo_id 各写一份：MANIFEST 写 `moss-nano` / repo `iic/moss-tts-mixed`，
   下载器写 `moss-tts-nano` / repo `OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX`。
   install.py 按哪份都对不上另一份，用户下载的模型目录与运行时要读的目录不同名。

2. **代码裸 import 的包没进运行时清单** —— `modelscope`（ModelScope 下载源的
   唯一实现）、`requests`（`channels/feishu_auth.py:12` 模块级）、`PyYAML`
   （`plugins/plugin_manager.py:26` 模块级）、`comtypes`（Windows SAPI5 TTS）
   在 requirements.txt 里零声明，干净机器装完即缺。

3. **假成功、真断链** —— 原 `download_asr_model` 只 `mkdir models/asr/funasr`
   就报「[OK] FunASR 模型」，而 `ASRManager` 链首正是 funasr：用户看到安装成功，
   实际语音识别整链不可用（无引擎、无权重、无包）。

4. **前端装依赖绕过 lock** —— 原实现只看 `node_modules` 目录存在且用
   `npm install`；半损坏（.bin 丢失）骗过检查，且 `npm install` 会改写 lock
   之外的版本。start.py 已按「vite 可执行文件在场 + npm ci」收口，install.py
   必须同判据（同一契约两处消费，不能各写一套）。

5. **验证面与供给面不同源** —— 原 `verify_installation` 只探 6 个 import，
   既没覆盖清单声明的探针面（`models/MANIFEST.json` 的 `runtime.pip.probe`），
   也不检查模型就绪，于是「装完」与「跑得起来」被混为一谈。
"""
from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_INSTALL = _REPO / "install.py"
_MANIFEST = _REPO / "models" / "MANIFEST.json"


def _read(path: Path) -> str:
    return io.open(path, encoding="utf-8").read()


_INSTALL_SRC = _read(_INSTALL)


def _install_module():
    """按文件路径加载 install.py（仓库根不在测试 sys.path 时也能引导）。"""
    root = str(_REPO)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("neurova_install_entry", _INSTALL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads(_read(_MANIFEST))


def _code_only(src: str) -> str:
    """滤掉整行注释：断言针对行为，不针对「为什么这么做」的说明。"""
    return "\n".join(
        line for line in src.splitlines() if not line.strip().startswith("#")
    )


def _declared_runtime_packages() -> set[str]:
    names = set()
    for raw in _read(_REPO / "requirements.txt").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        import re

        names.add(
            re.split(r"[>=<!\[;~ ]", line)[0].strip().lower().replace("-", "_")
        )
    return names


class TestModelSupplyHasSingleSource:
    """MANIFEST（首启链路读）与代码 registry（下载器执行）必须同名同源。"""

    @staticmethod
    def _registry_keys() -> dict:
        sys.path.insert(0, str(_REPO))
        from neurova.asr.model_downloader import ASR_MODEL_REGISTRY
        from neurova.tts.model_downloader import MODEL_REGISTRY

        merged = {}
        merged.update({k: v for k, v in MODEL_REGISTRY.items()})
        merged.update({k: v for k, v in ASR_MODEL_REGISTRY.items()})
        return merged

    def test_every_manifest_model_exists_in_code_registry(self):
        registry = self._registry_keys()
        unknown = [e["id"] for e in _manifest()["models"] if e["id"] not in registry]
        assert not unknown, (
            "models/MANIFEST.json 的模型 id 在代码 registry 里找不到 → "
            "首启链路按 MANIFEST 判就绪，install.py 按 registry 下载，两者永不重合。"
            f"未登记: {unknown}\n可用 id: {sorted(registry)}"
        )

    def test_repo_id_agrees_with_code_registry(self):
        """同一模型在两处声明的仓库必须一致（否则下载到 A，运行时读 B 的身份）。"""
        registry = self._registry_keys()
        drift = []
        for entry in _manifest()["models"]:
            declared = entry.get("repo_id")
            if not declared:
                continue
            code = registry[entry["id"]].get("repo_id")
            if code and code != declared:
                drift.append(f"{entry['id']}: MANIFEST={declared} ≠ 代码={code}")
        assert not drift, "模型仓库两处声明不一致:\n  " + "\n  ".join(drift)


class TestRuntimeDepsCoverCodeImports:
    """代码里真被 import 的运行期第三方包必须在 requirements.txt 声明。"""

    # 裸 import 且能力路径依赖（各条都给出代码位置）；豁免项说明见各注释。
    REQUIRED = {
        "modelscope": "neurova/tts/model_downloader.py（ModelScope 下载源唯一实现）",
        "requests": "neurova/channels/feishu_auth.py:12 模块级 import（飞书 API）",
        "pyyaml": "neurova/plugins/plugin_manager.py:26 模块级 import",
        "comtypes": "neurova/tts/sapi5_tts.py（Windows SAPI5 离线 TTS）",
    }

    @pytest.mark.parametrize("pkg,why", sorted(REQUIRED.items()))
    def test_declared_in_runtime_requirements(self, pkg, why):
        declared = _declared_runtime_packages()
        assert pkg in declared, (
            f"requirements.txt 未声明 {pkg}（{why}）。生产安装（Dockerfile / "
            "install.py）按本文件装依赖，缺席即该功能路径 import 崩。"
        )

    def test_engine_packages_declared_in_manifest_not_hardcoded(self):
        """可选 ASR 引擎包只允许在清单里声明一处，install.py 只消费不硬编码。

        「基础依赖」入 requirements.txt（Dockerfile 与首启 pip 都装这一份）；
        「可选引擎包」体积大（torch CPU 版约 200MB），不进基础清单，但规格串
        仍须有唯一出处——放 models/MANIFEST.json 的 runtime.asr，否则
        install.py 与首启链路各抄一份，改一处必漏另一处。
        """
        asr = ((_manifest().get("runtime") or {}).get("asr") or {})
        declared = {e["spec"] for e in asr.get("enginePackages") or []}
        assert declared, "清单未声明 runtime.asr.enginePackages（可选引擎包无出处）"
        # install.py 不得出现裸规格串（`foo>=1.2` 形态）——那是第二份声明
        hardcoded = re.findall(r'"(?:funasr|torchaudio|openai-whisper)[^"]*[<>=]', _code_only(_INSTALL_SRC))
        assert not hardcoded, (
            f"install.py 硬编码了引擎包规格（应在 models/MANIFEST.json 单源声明）: {hardcoded}"
        )
        body = _code_only(_INSTALL_SRC)
        assert "runtime" in body and "asr" in body, (
            "install.py 未从清单 runtime.asr 读取引擎包声明"
        )


class TestInstallRunsRealDownloaderAndPlan:
    """install.py 的模型阶段必须跑真下载器，不得用空目录冒充安装成功。"""

    def test_model_stage_reads_code_registry(self):
        src = _code_only(_INSTALL_SRC)
        assert "MODEL_REGISTRY" in src or "ensure_model" in src, (
            "install.py 未接代码 registry 的下载能力（ensure_model）——"
            "模型阶段成了一组写死的名字"
        )
        assert "ASR_MODEL_REGISTRY" in src or "ensure_model" in src, (
            "install.py 的 ASR 阶段未接真模型下载面"
        )

    def test_no_mkdir_only_pretend_success(self):
        body = _code_only(_INSTALL_SRC)
        assert "mkdir(parents=True, exist_ok=True)\n        print(t(\"asr_ok\"" not in body, (
            "ASR 阶段仍以「建目录即报成功」冒充安装：用户看到 OK，"
            "ASRManager 链首 funasr 实际不可用（假成功属禁止的表面抹除）"
        )

    def test_translation_covers_every_step_key(self):
        """每一步的文案键必须四语言齐备（新增步骤不得只写中文）。"""
        mod = _install_module()
        langs = set(mod.TRANSLATIONS)
        assert {"zh", "en", "ja", "ru"} <= langs
        base = set(mod.TRANSLATIONS["zh"])
        for lang in ("en", "ja", "ru"):
            missing = base - set(mod.TRANSLATIONS[lang])
            assert not missing, f"{lang} 缺文案键: {sorted(missing)}"


class TestEnginePackageShortageIsNamed:
    """引擎包缺席必须点名「缺哪个包」，不能抛裸 ModuleNotFoundError 了事。

    实测：whisper 权重经 `whisper.load_model` 拉取，openai-whisper 不在场时
    原实现直接把 `ModuleNotFoundError` 抛到用户屏幕上——用户看到的是 traceback，
    没有任何「装哪个包」的线索。修复教义第 2 条要求报错以诚实形态暴露并点名原因。
    """

    def test_model_with_engine_dependency_declares_it(self):
        asr = ((_manifest().get("runtime") or {}).get("asr") or {})
        declared = {e["import"] for e in asr.get("enginePackages") or []}
        for entry in _manifest()["models"]:
            engine = entry.get("engineImport")
            if engine:
                assert engine in declared, (
                    f"模型 {entry['id']} 的 engineImport={engine} 未在 "
                    "runtime.asr.enginePackages 声明——规格串就出现了第二份出处"
                )

    def test_engine_spec_resolves_for_engine_backed_model(self):
        mod = _install_module()
        spec = mod.engineSpecFor(_manifest(), "whisper-base")
        assert spec, "engineSpecFor 未能为 whisper-base 解析出引擎包规格"
        # 解析结果必须与清单声明逐字一致（不得在代码里另抄规格）
        asr = ((_manifest().get("runtime") or {}).get("asr") or {})
        assert spec in {e["spec"] for e in asr["enginePackages"]}

    def test_engine_spec_is_none_for_pure_download_models(self):
        mod = _install_module()
        assert mod.engineSpecFor(_manifest(), "bge-small-zh-v1.5") is None, (
            "纯下载模型不应被误判为依赖引擎包"
        )

    def test_worker_names_the_missing_package(self):
        tree = ast.parse(_INSTALL_SRC)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "modelWorker"
        )
        body = ast.get_source_segment(_INSTALL_SRC, fn) or ""
        assert "ImportError" in body, (
            "modelWorker 未捕 ImportError：引擎包缺席会以 traceback 暴露而非点名原因"
        )
        assert "engineSpecFor" in body, (
            "modelWorker 未用清单声明的引擎规格点名要装哪个包"
        )

    def test_download_stage_skips_instead_of_warning(self):
        """引擎未装时是「跳过权重」而非「下载失败」——可选能力不该报故障噪音。"""
        tree = ast.parse(_INSTALL_SRC)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "downloadModels"
        )
        body = ast.get_source_segment(_INSTALL_SRC, fn) or ""
        assert "engineImportable" in body, (
            "downloadModels 未先探引擎包可导入性：默认安装会为未选择的 ASR 能力报 WARN"
        )


class TestInstallProbesShareTheSupplyContract:
    """验证面必须与供给面同源：探针来自清单，模型就绪判据来自下载器。"""

    def test_probe_surface_comes_from_manifest(self):
        src = _code_only(_INSTALL_SRC)
        assert "MANIFEST" in src or "indexUrls" in src, (
            "install.py 未消费 models/MANIFEST.json 的 runtime.pip 声明——"
            "pip 索引与探针面各写一份，Windows 首启与 install.py 的标准会分叉"
        )

    def test_verify_checks_model_readiness(self):
        """验证阶段必须落到「模型真就绪」判据，而不是只看依赖 import 得动。

        判据链：verifyInstallation → probeModels → 下载器的 is_model_available /
        asr 的 is_model_ready（同一批就绪事实源，不在这里另立一套）。
        """
        tree = ast.parse(_INSTALL_SRC)
        by_name = {
            n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
        }
        assert "verifyInstallation" in by_name, "install.py 找不到 verifyInstallation"
        verify_src = ast.get_source_segment(_INSTALL_SRC, by_name["verifyInstallation"]) or ""
        assert "probeModels" in verify_src, (
            "verifyInstallation 未接模型就绪探测——「装完」与「跑得起来」被混为一谈"
        )
        assert "probeModels" in by_name, "install.py 找不到 probeModels"
        probe_src = ast.get_source_segment(_INSTALL_SRC, by_name["probeModels"]) or ""
        assert "_MODEL_PROBE_SCRIPT" in probe_src, (
            "probeModels 未走 venv 子进程探针脚本（宿主解释器缺下载器依赖，进程内判会假失败）"
        )
        # 探针脚本自身必须用下载器的就绪判据，不得另立一套「文件在不在」
        code = _code_only(_INSTALL_SRC)
        assert "is_model_available" in code and "is_model_ready" in code, (
            "探测未用下载器的就绪判据（TTS 与 ASR 各一套真相即断链）"
        )


class TestFrontendInstallMatchesStartContract:
    """前端装依赖的判据必须与 start.py 同契约（半损坏可自愈 + lock 优先）。

    start.py 的 check_node_deps 已按「vite 可执行文件在位 + npm ci」收口
    （tests/unit/test_start_script_deps.py 锁定）。install.py 是同一契约的
    第二个消费方，判据必须一致——两处各写一套时，一处的半损坏自愈形同虚设。
    """

    @staticmethod
    def _start_probe() -> str:
        return _read(_REPO / "start.py")

    def test_both_entrypoints_probe_the_same_vite_binary(self):
        install_src = _code_only(_INSTALL_SRC)
        start_src = _code_only(self._start_probe())
        for src, who in ((install_src, "install.py"), (start_src, "start.py")):
            assert "node_modules" in src and ".bin" in src and "vite" in src, (
                f"{who} 未按「vite 可执行文件在位」判前端就绪——"
                "半损坏（.bin 丢失）会骗过目录存在性检查，npm run dev 报找不到 vite 且不自愈"
            )

    def test_both_entrypoints_prefer_npm_ci_with_lock(self):
        for src, who in (
            (_code_only(_INSTALL_SRC), "install.py"),
            (_code_only(self._start_probe()), "start.py"),
        ):
            assert "npm" in src and '"ci"' in src, f"{who} 未走 npm ci（lock 优先）"
            assert "package-lock.json" in src, f"{who} 未按 lock 存在与否选择 ci/install"
