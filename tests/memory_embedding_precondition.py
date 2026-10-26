# -*- coding: utf-8 -*-
"""记忆类判据的**嵌入前提**：只在这里判一次，缺件就 skip，且说清缺的是哪一件。

## 为什么不再"显式失败"

这几档（联想召回基线、向量线索通道、扇出闸、长期记忆六维门禁）的向量分量与生产同一条
链路，没有真嵌入读数就没有意义——这一点没变，它们也**不许**被改成"读数随便给个 0 就算过"。
变的是缺件时的处置：`requirements-ci.txt` 把 `transformers` / `tokenizers` /
`onnxruntime` / `sentencepiece` 明确列在**刻意排除**名单里（薄环境是 CI 的设计目的），
于是"显式失败"在 CI 上恒红——二十来格永久红，谁也读不出其中有没有真回归。
红久了的判据等于没有判据，还会把真正的断链稀释掉。

## 为什么要判"引擎真出非零向量"

`get_embedding_engine()` **从不返回 None**：模型档在、分词器/运行时装不上时它照样给一个
对象，随后初始化失败并兜底零向量（日志里只有一行 ERROR）。只判非 None 是恒真——
"向量分量"整条腿在这类环境里静默失效，红出来的是"写入时就没有向量"这种错位报错。
所以这里做一次真编码：零向量即前提不成立。

## 这一档不主张的事

skip 只说明"这台机器给不出这条读数"，**不**说明被测代码对。要真读数请装全量依赖
（`requirements-full.lock`）或云原生开发环境；CI 上是否需要补齐嵌入栈，是需要人裁的
依赖口径问题（见台账 §6-419），不在本文件里自决。
"""

from __future__ import annotations

import pytest

#: 引擎自检用的短句：只为判"算得出/算不出"，取值不参与任何断言。
PROBE_TEXT = "嵌入引擎自检"


def embeddingUnavailableReason() -> str:
    """算不出真向量时返回一句人话原因；算得出返回空串。

    两种缺件分开说，因为处置不同：
    - 引擎对象都没有 ⇒ 模型档不在（`models/embedding/` 没拉下来）；
    - 引擎在但回零向量 ⇒ 分词器/ONNX 运行时装不上（薄环境）。
    """
    from neurova.core import vector_math

    try:
        from neurova.embedding import get_embedding_engine

        engine = get_embedding_engine()
    except Exception as err:  # noqa: BLE001 - 可选依赖，缺席即"没有这条读数"
        return f"嵌入引擎不可用（{type(err).__name__}: {err}）"
    if engine is None:
        return (
            "嵌入引擎缺席：模型档不在（`models/embedding/bge-small-zh-v1.5/model.onnx`），"
            "本仓这几档判据的向量分量与生产同链路，缺档给不出读数"
        )
    # 引擎就绪（能真算）时**不许**再用"缺件"蒙过：编码抛错或回零向量说明它坏了，
    # 那是要人看的红，不是这台机器给不出读数。
    if getattr(engine, "_initialized", True):
        return ""
    if hasattr(engine, "encodeOrNone"):
        if engine.encodeOrNone(PROBE_TEXT) is not None:
            return ""
    elif not vector_math.isZeroVector(engine.encode(PROBE_TEXT)):
        return ""
    return (
        "嵌入引擎回零向量：模型档在，但分词器/ONNX 运行时装不上"
        "（`transformers` / `tokenizers` / `onnxruntime` 缺席时引擎走零向量兜底；"
        "`requirements-ci.txt` 刻意排除这四件，故薄环境必然走到这里）。"
        "要真读数请装 `requirements-full.lock` 或走云原生开发环境"
    )


def requireRealEmbeddingOrSkip(subject: str) -> None:
    """前提自给：引擎算不出真向量时 skip 并点名 `subject` 与缺的是哪一件。"""
    reason = embeddingUnavailableReason()
    if reason:
        pytest.skip(f"{subject}：{reason}", allow_module_level=False)
