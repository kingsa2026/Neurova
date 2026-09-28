# -*- coding: utf-8 -*-
"""镜像内「随代码走的资产」必须真的能在镜像里读到（Issue #289）。

## 现象

镜像构建成功、容器正常启动，但容器里 **没有** 任何模型权重：
`neurova/embedding/onnx_embedding.py` 把落点锚在
`repoAsset("models", "embedding", "bge-small-zh-v1.5")`（仓库根下的资产，
不随 CWD 漂移——这正是 `repoAsset` 的设计语义），而 `.dockerignore` 的
`models/*.onnx` / `models/*.safetensors` / `models/*.bin` 把权重挡在构建
上下文之外，Dockerfile 里也**没有** `COPY models/`。放进镜像的只有
`neurova/`、`start_server.py`、`requirements.txt`、`config/`。

于是容器里 `backend == "onnx"` 会在 `models/embedding/bge-small-zh-v1.5/model.onnx`
上拿不到文件、初始化失败并**静默降级 TF-IDF**（`unified_vector_store` 的
`_create_encoder` 只 `logger.warning`）——比崩溃更难发现。

## 根因（不是「忘了抄一行 COPY」）

既有判据 `scripts/ci/deploy_config_consistency_check.py` 的 R10 问的是
「`.dockerignore` 有没有把某个路径挡掉」，而它的清单 `RUNTIME_CONFIG_ASSETS`
是**人填**的两条（`config/` 下）。两处结构性缺口：

1. **清单人填** ⇒ 新资产不进清单就永远不被检查。这是「只写不读的第二份定义」；
2. **判定面只到 `.dockerignore`** ⇒ 放行了构建上下文也不代表镜像里有它
   （`COPY` 可能根本没写）。

故本判据从**生产读取方**反推资产（`repoAsset(...)` 的调用点即清单事实源），
并要求「放行 + 拷贝」两句同时成立。

## 三种处置不是同一种

反推出的资产必须逐条落到「进镜像」或「退役」之一，**不许留在悬空态**：

- **进镜像**：生产读取方真的存在、且读取方是主链路（如 embedding 权重）；
- **退役**：读取方本身不可达（零生产消费方）——那要连读取方一起处理，
  不能靠"给镜像多加几十 MB"掩盖一条死链；
- **可选能力**：读取方按 `auto_download` 走「本地没有就下载」的**诚实**路径
  （加载失败即 `return False`，不假装初始化成功），且该能力不在默认装机面内。
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: 生产代码里「随代码走的资产」的解析入口。资产清单的事实源是**它的调用点**，
#: 不是本文件手抄的一张表——手抄的表会立刻过期（AGENTS.md 修复教义第 6 条）。
REPO_ASSET_CALL = re.compile(r"repoAsset\(\s*([^)]*)\)")

#: Dockerfile 的 `COPY` 指令。
COPY_RE = re.compile(r"^\s*COPY\s+(?P<srcs>.+?)\s+(?P<dest>\S+)\s*$", re.MULTILINE)

#: 允许不进镜像的资产，逐条写明**为什么**它是可选能力或已退役。
#: 本表是判据的显式白名单：新增资产必须落进「进镜像」或来这里写明理由，
#: 不许静默悬空。两条都要求读取方自己走诚实降级路径。
OPTIONAL_ASSETS = {
    "models/asr/funasr": (
        "FunASR 是可选 ASR 能力（install.py 仅 --with-local-asr 时安装 funasr/torchaudio）；"
        "funasr_engine.initialize() 在 funasr 缺席或模型加载失败时 logger.warning + "
        "return False（诚实降级），且 AutoModel 本就会从 ModelScope 下载到 model_dir。"
        "镜像默认不装 funasr，故权重进镜像也无读取方。"
    ),
    "models/asr/whisper": (
        "whisper 同属可选 ASR 能力；whisper_engine.initialize() 走 "
        "load_model(..., download_root=model_dir)，本地无权重即按官方路径下载，"
        "失败则 return False（诚实降级），不假装初始化成功。"
    ),
}


def productionPythonFiles() -> list:
    root = PROJECT_ROOT / "neurova"
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def declaredRepoAssets() -> dict:
    """从生产代码的 `repoAsset(...)` 调用点反推资产 → 读取方。

    只认**字面量**参数；动态参数无法静态裁定，如实跳过而不是猜。
    """
    found: dict = {}
    for path in productionPythonFiles():
        text = io.open(path, encoding="utf-8").read()
        for match in REPO_ASSET_CALL.finditer(text):
            parts = re.findall(r"[\"']([^\"']+)[\"']", match.group(1))
            if not parts:
                continue
            rel = "/".join(parts)
            found.setdefault(rel, set()).add(
                str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
            )
    return found


def _patternMatches(path: str, pattern: str) -> bool:
    """单条 .dockerignore 模式是否命中某仓库相对路径。

    与既有 `deploy_config_consistency_check.py::R10` 同一口径（那里是
    「`.dockerignore` 挡没挡掉运行时资产」这一判据的既有实现，本文件不新造第二套）。
    `*` 不跨 `/`，故 `models/*.onnx` 只命中 `models/` 直下，命中整棵树靠显式通配。
    """
    import fnmatch

    return (
        fnmatch.fnmatch(path, pattern)
        or path.startswith(pattern + "/")
        or fnmatch.fnmatch(path.split("/")[-1], pattern)
    )


def ignoredByDockerignore(path: str) -> bool:
    """复算 .dockerignore 对某相对路径的最终判定（后写的规则覆盖先写的）。"""
    rules = [
        line.strip()
        for line in io.open(PROJECT_ROOT / ".dockerignore", encoding="utf-8").read().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    state = False
    for rule in rules:
        negate = rule.startswith("!")
        pattern = (rule[1:] if negate else rule).rstrip("/")
        if _patternMatches(path, pattern):
            state = not negate
    return state


def blanketWeightExclusions() -> list:
    """放在 `models/` 段里的**跨目录**权重排除（`models/*.ext` 形态）。

    这是本批的病根形状：`*` 不跨 `/`，但在 `models/` 下写 `models/*.safetensors`
    时它挡的是**直下**的 `models/xxx.safetensors`——而本仓权重实际在
    `models/embedding/...`。于是这条排除既没排掉权重（放行了 274MB），
    又让读者以为"权重已排除"，直到 `COPY models/` 把整棵树搬进上下文。
    真正的排除必须落在**具体资产路径**上（`models/<子目录>/<资产>/...`）。
    """
    modelsIndex = None
    lines = io.open(PROJECT_ROOT / ".dockerignore", encoding="utf-8").read().splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "# 模型文件":
            modelsIndex = i
            break
    assert modelsIndex is not None, (
        ".dockerignore 的「# 模型文件」段不见了——本判据的锚点失效，"
        "模型段的排除项将不再被检查（禁止用「找不到就不查」短路）。"
    )
    return [
        line.strip()
        for line in lines[modelsIndex:]
        if line.strip().startswith("models/*")
    ]


def copiedPrefixes() -> list:
    """Dockerfile 里 `COPY` 的源前缀（本仓 Dockerfile 只有目录/单文件形态）。"""
    text = io.open(PROJECT_ROOT / "Dockerfile", encoding="utf-8").read()
    prefixes = []
    for match in COPY_RE.finditer(text):
        for src in match.group("srcs").split():
            if src.startswith("--"):
                continue
            prefixes.append(src.rstrip("/"))
    return prefixes


class TestAssetInventoryIsDerivedNotHandCopied:
    """判据自己不得成为"第二份人填清单"。"""

    def test_productionDeclaresRepoAssets(self):
        """反向控制：反推面不得退化成空集（否则下面的断言空转通过）。"""
        assets = declaredRepoAssets()
        assert assets, (
            "生产代码里一个 repoAsset(...) 调用点都没扫到——反推面失效，"
            "本判据会静默空转。禁止用「扫不到就算过」短路它。"
        )
        assert "models/embedding/bge-small-zh-v1.5" in assets, (
            "反推面漏掉了 embedding 权重这一个已知资产——扫描口径坏了，"
            "不是「它恰好不需要进镜像」。"
        )

    def test_optionalAllowlistDoesNotDriftIntoStaleEntries(self):
        """白名单里的每条都必须仍是生产侧真实声明的资产。

        防「资产改名/退役后白名单条目留着」——那种条目会静默放行一个不再存在的路径，
        更坏的是它会让判据看起来还在工作。
        """
        declared = declaredRepoAssets()
        stale = sorted(set(OPTIONAL_ASSETS) - set(declared))
        assert not stale, (
            "白名单里有生产侧已不再声明的资产（条目已过期，请删除或改判）：\n  "
            + "\n  ".join(stale)
        )


class TestEveryAssetIsEitherShippedOrDeclaredOptional:
    """每条资产必须落进「进镜像」或「显式可选」之一，不许悬空。"""

    def test_everyRepoAssetIsCopiedIntoTheImage(self):
        prefixes = copiedPrefixes()
        missing = {}
        for asset, readers in declaredRepoAssets().items():
            if asset in OPTIONAL_ASSETS:
                continue
            if not any(asset == p or asset.startswith(p + "/") for p in prefixes):
                missing[asset] = readers
        assert not missing, (
            "这些资产没有 `COPY` 进镜像，也不是显式登记的可选能力：\n"
            + "\n".join(
                f"  {asset}（读取方：{', '.join(sorted(readers))}）"
                for asset, readers in sorted(missing.items())
            )
            + "\n放进镜像与「登记为可选能力」二者必居其一——悬空态的后果是"
            "容器里静默降级，而构建与启动都不报错。"
        )

    def test_everyAssetMagicallyAppearsInTheImageContext(self):
        """放行 + 拷贝缺一不可，且这句必须对**全部**资产成立。

        口径（第一版踩过的坑）：不能只对"COPY 命中的那些资产"检查 .dockerignore
        ——那等于让 COPY 自己给自己发合格证。把白名单摘掉、只留具体排除项时，
        "COPY 命中集"会缩成空集，断言就空转通过了；而真实后果是
        `COPY models/.../` 在构建上下文里找不到源，**`docker build` 直接失败**
        （比静默降级更硬，但同样不该等构建时才暴露）。

        故这句对**每条被声明为"应当进镜像"的资产**成立：它既要没有被
        .dockerignore 挡掉，也要真的被 `COPY` 进镜像。
        """
        prefixes = copiedPrefixes()
        declared = declaredRepoAssets()
        shipped = [a for a in declared if a not in OPTIONAL_ASSETS]
        assert shipped, (
            "没有任何资产被判为「应当进镜像」——反推面失效，本判据会静默空转。"
            "禁止用「没有就算过」短路它。"
        )
        broken = {
            asset: declared[asset]
            for asset in shipped
            if ignoredByDockerignore(asset)
            or not any(asset == p or asset.startswith(p + "/") for p in prefixes)
        }
        assert not broken, (
            "这些资产声称要进镜像，但「放行 + 拷贝」没有同时成立：\n"
            + "\n".join(
                f"  {asset}（读取方：{', '.join(sorted(readers))}）"
                f" —— .dockerignore 挡掉={ignoredByDockerignore(asset)}，"
                f"被 COPY 命中={any(asset == p or asset.startswith(p + '/') for p in prefixes)}"
                for asset, readers in sorted(broken.items())
            )
            + "\n被 .dockerignore 挡掉会让 `COPY` 在构建时报「目录不存在」；"
            "没被 COPY 命中则镜像里没有它，运行时静默降级。两条都要落。"
        )


class TestEmbeddingWeightsAreReallyShipped:
    """embedding 权重是本批的实锤：读取方在生产主链上，降级是静默的。"""

    ASSET = "models/embedding/bge-small-zh-v1.5"

    def test_dockerfileCopiesTheModelTree(self):
        assert any(
            self.ASSET == p or self.ASSET.startswith(p + "/") for p in copiedPrefixes()
        ), (
            "Dockerfile 没有把模型树 COPY 进镜像。"
            "neurova/embedding/onnx_embedding.py 的 repoAsset 落点在仓库根，"
            "容器里读不到就静默降级 TF-IDF。"
        )

    def test_dockerignoreLetsTheWeightsThrough(self):
        assert not ignoredByDockerignore(f"{self.ASSET}/model.onnx"), (
            ".dockerignore 把 model.onnx 挡在构建上下文之外——"
            "`COPY models/` 会因此构建失败，而不是「少拷一个文件」。"
        )
        for pattern in ("models/*.bin", "models/*.safetensors", "models/*.onnx"):
            rules = io.open(PROJECT_ROOT / ".dockerignore", encoding="utf-8").read().splitlines()
            assert not any(line.strip() == pattern for line in rules), (
                f".dockerignore 仍有 `{pattern}` 这条全局排除——"
                "它挡的是整棵 models/ 树里的权重，放行必须落在具体路径上。"
            )

    def test_noBlanketCrossDirectoryWeightExclusion(self):
        """跨目录权重通配必须归零——它既排不掉真权重，又制造"已排除"的错觉。"""
        blankets = blanketWeightExclusions()
        assert not blankets, (
            ".dockerignore 的模型段里仍有跨目录权重通配：\n  "
            + "\n  ".join(blankets)
            + "\n`*` 不跨 `/`，`models/*.safetensors` 只命中 models/ 直下——"
            "本仓权重在 models/embedding/<资产>/ 下，它一条都挡不住，"
            "却让读者以为权重没进构建上下文。排除请写成具体资产路径。"
        )

    def test_nonWeightsInTheModelTreeAreNotBlocked(self):
        """附带反证：被排除的必须只有权重本体，元数据/清单要能进镜像。"""
        for keep in ("models/MANIFEST.json", f"{self.ASSET}/config.json",
                     f"{self.ASSET}/tokenizer.json"):
            assert not ignoredByDockerignore(keep), (
                f"{keep} 被 .dockerignore 排除——模型元数据进不了镜像，"
                "运行时无法判断模型是否完整（`is_model_available` 只看 required_files）。"
            )
