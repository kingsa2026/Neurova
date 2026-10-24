"""本地 bge reranker provider（可选依赖，诚实失败）。

模型目录按 `NEUROVA_RERANK_MODEL_DIR` → `models/rerank/<name>` 解析；目录或
`sentence-transformers` 缺失时抛 `RerankConfigError`，由装配口退化为加权并写明原因。
不在导入期加载模型：只有请求 model 通道时才触碰重型依赖。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, List, Optional

DEFAULT_MODEL_NAME = "bge-reranker-v2-m3"


def _repoRoot() -> Path:
    return Path(__file__).resolve().parents[3]


def resolveModelPath(modelPath: str = "", modelName: str = "") -> Optional[Path]:
    explicit = (modelPath or os.environ.get("NEUROVA_RERANK_MODEL_DIR") or "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_dir() else None
    candidate = _repoRoot() / "models" / "rerank" / (modelName or DEFAULT_MODEL_NAME)
    return candidate if candidate.is_dir() else None


def buildLocalBgeProvider(
    modelPath: str = "",
    modelName: str = "",
    loader: Optional[Callable[[str], object]] = None,
) -> Callable[[str, List[str]], List[float]]:
    """返回 `(query, doc_texts) -> scores`；不可用时抛 RerankConfigError。"""
    from neurova.llm.rerank_client import RerankConfigError

    path = resolveModelPath(modelPath, modelName)
    if path is None:
        raise RerankConfigError(
            "本地 rerank 模型未就绪（目录不存在）",
            reason="local_model_missing:%s" % (modelPath or modelName or DEFAULT_MODEL_NAME),
        )
    if loader is None:
        def loader(localPath: str):
            try:
                from sentence_transformers import CrossEncoder
            except Exception as exc:  # noqa: BLE001 - 可选依赖按配置故障处理
                raise RerankConfigError(
                    "sentence-transformers 不可用，无法加载本地 rerank 模型",
                    reason="local_dependency_missing:sentence-transformers",
                ) from exc
            return CrossEncoder(localPath)

    try:
        model = loader(str(path))
    except RerankConfigError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RerankConfigError(
            "本地 rerank 模型加载失败: %s" % exc,
            reason="local_model_load_failed:%s" % path.name,
        ) from exc

    def provider(query: str, docTexts: List[str]) -> List[float]:
        pairs = [(query, str(text or "")) for text in docTexts]
        scores = model.predict(pairs)
        return [float(score) for score in scores]

    return provider
