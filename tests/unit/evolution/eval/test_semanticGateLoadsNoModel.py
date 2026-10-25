# -*- coding: utf-8 -*-
"""进化闸的语义相似度**不许**为了算一次分数把模型拉起来（CI 挂死的根因面）。

来路不是推演，是 `PR #367` 的 CI 实测：`unit-tests` 这一腿在
`protected subset with coverage gate` 上跑 **25 分钟**后被平台掐断，
本地实跑栈形是

    service.evolve → ConstraintValidator.validate → semantic_similarity
        → _embedding_similarity → get_embedding_engine()
        → ONNXEmbeddingEngine.initialize_sync()
        → ModelDownloader.ensure_model(download_any=True)
        → 下载源解析 / HF 出网（无缓存时是 130MB 权重）

`requirements-ci` 刻意不带 torch/onnxruntime/模型权重，于是这一跳只可能
**出网**或**等出网超时**——判据是在拿网络当计时器。CI 日志里没有一条测试
失败正是这个形状：整段跑到点被掐断，不是"有测试红了"。

两道判据各钉一半：
1. 这一跳**只读就绪状态**，不许建模型（`initialize_sync` / `ensure_model`
   一旦被调用即红）——修在产生侧，不靠给等待加墙上限；
2. 但相似度面**必须还在**：把 `semantic_similarity` 整段摘掉换常量，这里
   当场红（否则"不加载模型"可以靠"什么都不算"骗过去）。
"""

import pytest

from neurova.evolution.eval.constraints import semantic_similarity

SIMILAR = ("先复述用户问题再作答，不确定时明确说不知道。" * 3,
           "先复述用户问题再作答，不确定时明确说不知道。补充：不确定就拒绝。" * 3)
DIVERGENT = ("先复述用户问题再作答，不确定时明确说不知道。" * 3,
             "把论文按关键词检索并汇总摘要。" * 3)


class _ModelLoadAttempted(BaseException):
    """真的去建/下模型时抛的哨兵。`BaseException` 才不被全兜底 except 吞掉。"""


def _forbidModelLoading(monkeypatch):
    """把模型装载面整体上锁：任何一跳真的去建/下权重都当场炸。

    用 `BaseException` 子类，`except Exception` 吞不掉——`semantic_similarity`
    自己就是全兜底 except 的形态，普通异常会被它吞成"回退到 Jaccard"，闸也就
    成了哑闸（同形先例见 `tests/unit/evolution/eval/conftest.py`）。
    """
    from neurova.embedding import onnx_embedding
    from neurova.tts import model_downloader

    def _blocked(*args, **kwargs):
        raise _ModelLoadAttempted(
            "进化闸为了算一次相似度去装载/下载嵌入模型——判据在拿网络当计时器")

    for owner, name in ((onnx_embedding.ONNXEmbeddingEngine, "initialize_sync"),
                        (onnx_embedding.ONNXEmbeddingEngine, "initialize"),
                        (model_downloader.ModelDownloader, "ensure_model")):
        if hasattr(owner, name):
            monkeypatch.setattr(owner, name, _blocked, raising=False)


@pytest.fixture(autouse=True)
def _blockedLoader(monkeypatch):
    _forbidModelLoading(monkeypatch)


class TestNoModelLoadOnTheGatePath:
    def testSimilarityIsComputedWithoutTouchingTheModelLoader(self, monkeypatch):
        """词面下界必须照算——回退路径不是"算不了"，是"不用模型也能算"。"""
        from neurova.evolution.eval import constraints

        # 按用例钉、用例结束即撤销：这一格是生产侧的**观测面**（`_noteEngineProbe` 写的
        # 就是它），裸赋值会把它留成空串，后续读它的判据看不到真实探测痕迹。
        monkeypatch.setattr(constraints, "_SEMANTIC_ENGINE_TOUCHED", "")
        similar = semantic_similarity(*SIMILAR)
        assert 0.0 <= similar <= 1.0
        assert similar > 0.5, f"同义改写被算成 {similar}：词面下界这条腿断了"
        diverged = semantic_similarity(*DIVERGENT)
        assert diverged < similar, (diverged, similar)

    def testNoModelLoadWhenTheEngineIsReportedReady(self, monkeypatch):
        """引擎**自称就绪**时也不许现场装配/下载。

        这一格守的是更隐蔽的一半：判据只看 `is_initialized`，而真正的装载动作
        藏在"就绪"那一刻的 `initialize_sync()` 里。用一个只会回 False 的就绪位
        替身 + 上锁的装载面，两条一起钉住——编码失败就如实回退到词面下界，
        **不许**回头去把模型拉起来补齐。
        """
        from neurova.embedding import onnx_embedding
        from neurova.evolution.eval import constraints

        class _ReadyButEmpty:
            is_initialized = True

            def encode(self, text):
                return []

        monkeypatch.setattr(onnx_embedding, "ONNXEmbeddingEngine",
                            lambda *a, **kw: _ReadyButEmpty())
        monkeypatch.setattr("neurova.embedding._embedding_engine", None, raising=False)
        monkeypatch.setattr(constraints, "_SEMANTIC_ENGINE_TOUCHED", "")
        value = semantic_similarity(*SIMILAR)
        assert 0.0 <= value <= 1.0
        assert constraints._SEMANTIC_ENGINE_TOUCHED in ("probed", "ready")

    def testTheEngineProbeActuallyRuns(self, monkeypatch):
        """反向钉住"什么都不算也能绿"：这一跳必须真的被走到。

        摘掉 `_embedding_similarity` 的调用（例如把 `semantic_similarity`
        改成恒返回 1.0）时，这一格没有读数 ⇒ 当场红。
        """
        from neurova.evolution.eval import constraints

        # 按用例钉、用例结束即撤销：这一格是生产侧的**观测面**（`_noteEngineProbe` 写的
        # 就是它），裸赋值会把它留成空串，后续读它的判据看不到真实探测痕迹。
        monkeypatch.setattr(constraints, "_SEMANTIC_ENGINE_TOUCHED", "")
        semantic_similarity(*SIMILAR)
        assert constraints._SEMANTIC_ENGINE_TOUCHED in ("probed", "ready"), (
            "语义相似度的取引擎跳没被走到——判据面可能已经被摘掉了")
