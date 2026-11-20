"""完整 EKI 反演验收测试（高斯过程代理 + 嵌入式采样）

TDD 红灯阶段：bayesian_eki 包此前诚实标注「代理模型（高斯过程）— 未实现、
嵌入式代表性采样 — 未实现、当前为简化版非真正 EKI」。本文件钉住补齐后的完整契约：

  - GaussianProcessSurrogate：RBF/Matérn 核 + 边缘似然调参 + 后验采样
  - ekiUpdate：一步随机集合卡尔曼反演更新（扰动观测 + 协方差膨胀）
  - EnsembleKalmanInversion：完整求解器（代理辅助 + 自适应步长 + 嵌入式采样）
  - EKIModule / EKICognitiveOptimizer 接线到真实现（活链与认知优化器不再用假代理）
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.bayesian_eki import (
    EnsembleKalmanInversion,
    GaussianProcessSurrogate,
    ekiUpdate,
)
from neurova.cognitive_layers.memory_layer.bayesian_eki.cognitive_optimizer import (
    EKICognitiveOptimizer,
)
from neurova.cognitive_layers.memory_layer.modules.eki_module import EKIModule


# ────── 高斯过程代理 ──────


class TestGaussianProcessSurrogate:
    def test_gp_recovers_smooth_function(self):
        rng = np.random.default_rng(3)
        xTrain = np.linspace(0.0, 1.0, 12)[:, None]
        yTrain = np.sin(2.0 * np.pi * xTrain[:, 0]) + 0.01 * rng.standard_normal(12)
        gp = GaussianProcessSurrogate(kernel="matern52", seed=0)
        gp.fit(xTrain, yTrain)

        xTest = np.linspace(0.0, 1.0, 25)[:, None]
        mu, var = gp.predict(xTest, returnVar=True)
        truth = np.sin(2.0 * np.pi * xTest[:, 0])
        assert mu.shape == (25, 1)
        assert float(np.max(np.abs(mu[:, 0] - truth))) < 0.2
        # 训练点附近不确定度应低于远离数据的外推点
        _, varNear = gp.predict(np.array([[0.5]]), returnVar=True)
        _, varFar = gp.predict(np.array([[3.0]]), returnVar=True)
        assert float(varNear[0, 0]) < float(varFar[0, 0])

    def test_gp_posterior_sampling_shape_and_center(self):
        xTrain = np.linspace(0.0, 1.0, 10)[:, None]
        yTrain = np.cos(3.0 * xTrain[:, 0])
        gp = GaussianProcessSurrogate(kernel="rbf", seed=1)
        gp.fit(xTrain, yTrain)
        xTest = np.linspace(0.0, 1.0, 6)[:, None]
        samples = gp.samplePosterior(xTest, nSamples=200, rng=np.random.default_rng(5))
        assert samples.shape == (200, 6, 1)
        mu = gp.predict(xTest)
        sampleMean = samples.mean(axis=0)[:, 0]
        assert float(np.max(np.abs(sampleMean - mu[:, 0]))) < 0.2

    def test_gp_multioutput(self):
        rng = np.random.default_rng(7)
        xTrain = rng.uniform(-1.0, 1.0, size=(16, 2))
        yTrain = np.stack(
            [xTrain[:, 0] + 0.1 * rng.standard_normal(16),
             xTrain[:, 1] ** 2 + 0.1 * rng.standard_normal(16)],
            axis=1,
        )
        gp = GaussianProcessSurrogate(seed=2)
        gp.fit(xTrain, yTrain)
        mu, var = gp.predict(np.array([[0.2, 0.4]]), returnVar=True)
        assert mu.shape == (1, 2)
        assert var.shape == (1, 2)
        assert bool(np.all(var > 0.0))

    def test_gp_hyperparameters_fitted(self):
        xTrain = np.linspace(0.0, 1.0, 8)[:, None]
        gp = GaussianProcessSurrogate(seed=0)
        gp.fit(xTrain, xTrain[:, 0] ** 2)
        assert gp.logHp is not None
        assert np.all(np.isfinite(gp.logHp))


# ────── 单步 EKI 更新 ──────


class TestEkiUpdateStep:
    @staticmethod
    def _linearResponse(theta: np.ndarray) -> np.ndarray:
        return np.stack([theta[:, 0] + theta[:, 1], theta[:, 0] - theta[:, 1]], axis=1)

    def test_eki_update_reduces_misfit(self):
        rng = np.random.default_rng(0)
        theta = rng.standard_normal((40, 2))
        g = self._linearResponse(theta)
        yObs = np.array([1.0, -0.5])
        gamma = 0.01 * np.eye(2)
        misfitBefore = float(np.mean(np.sum((g - yObs) ** 2 / np.diag(gamma), axis=1)))
        thetaNew = ekiUpdate(theta, g, yObs, gamma, np.random.default_rng(1))
        gNew = self._linearResponse(thetaNew)
        misfitAfter = float(np.mean(np.sum((gNew - yObs) ** 2 / np.diag(gamma), axis=1)))
        assert misfitAfter < misfitBefore

    def test_eki_update_keeps_ensemble_diverse(self):
        rng = np.random.default_rng(0)
        theta = rng.standard_normal((40, 3))
        g = theta[:, [0]]
        thetaNew = ekiUpdate(
            theta, g, np.array([0.7]), np.array([[0.05]]), np.random.default_rng(2)
        )
        assert float(np.std(thetaNew[:, 0])) > 0.0

    def test_eki_update_deterministic_mode_moves_mean(self):
        rng = np.random.default_rng(0)
        theta = rng.standard_normal((30, 1)) * 0.5
        g = theta.copy()
        thetaNew = ekiUpdate(
            theta, g, np.array([2.0]), np.array([[0.1]]), np.random.default_rng(3),
            stochastic=False,
        )
        assert abs(float(np.mean(thetaNew)) - 2.0) < abs(float(np.mean(theta)) - 2.0)


# ────── 完整求解器（代理 + 嵌入式采样） ──────


class TestEnsembleKalmanInversion:
    @staticmethod
    def _runLinear(**overrides):
        thetaTrue = np.array([1.2, 0.4])
        noise = 0.01 * np.random.default_rng(9).standard_normal(2)
        yObs = np.array([thetaTrue[0] + thetaTrue[1], thetaTrue[0] - thetaTrue[1]]) + noise
        calls = {"count": 0}

        def forward(theta):
            calls["count"] += 1
            return np.array([theta[0] + theta[1], theta[0] - theta[1]])

        kwargs = dict(
            forward=forward, yObs=yObs, gamma=0.01 * np.eye(2),
            priorMean=np.zeros(2), priorCov=4.0 * np.eye(2),
            nEnsemble=24, nIter=12, evalPerIter=4, seed=17, verbose=False,
        )
        kwargs.update(overrides)
        solver = EnsembleKalmanInversion(**kwargs)
        bestTheta, bestMisfit, ensemble = solver.run()
        return solver, bestTheta, bestMisfit, calls["count"], ensemble, thetaTrue

    def test_linear_inversion_recovers_truth(self):
        solver, bestTheta, bestMisfit, calls, ensemble, thetaTrue = self._runLinear()
        assert bestMisfit < 10.0  # 自由度 2，失配应落到噪声水平量级
        assert float(np.max(np.abs(bestTheta - thetaTrue))) < 0.15
        assert float(np.max(np.abs(ensemble.mean(axis=0) - thetaTrue))) < 0.15

    def test_truth_evaluations_match_budget_exactly(self):
        solver, _, _, calls, _, _ = self._runLinear()
        # 初始集合 + 每轮 evalPerIter 次真值评估；前向除初始批外只花在嵌入式采样选点上
        assert solver.trueEvals == 24 + 4 * 12
        assert calls == solver.trueEvals

    def test_history_records_each_iteration(self):
        solver, _, _, _, _, _ = self._runLinear()
        assert len(solver.history) == 12
        for entry in solver.history:
            for key in ("iteration", "step", "bestTrueMisfit", "ensSpread", "trueEvals"):
                assert key in entry
        misfits = [entry["bestTrueMisfit"] for entry in solver.history]
        assert misfits[-1] <= misfits[0] + 1e-9

    def test_nonlinear_inversion_with_surrogate_and_adaptive_step(self):
        tGrid = np.array([0.2, 0.5, 1.0, 1.6, 2.4])
        thetaTrue = np.array([2.0, 2.0, 1.0])
        yObs = (
            thetaTrue[0] / (1.0 + np.exp(-thetaTrue[1] * (tGrid - thetaTrue[2])))
            + 0.03 * np.random.default_rng(7).standard_normal(tGrid.size)
        )

        def forward(theta):
            a, k, t0 = theta
            return a / (1.0 + np.exp(-k * (tGrid - t0)))

        solver = EnsembleKalmanInversion(
            forward=forward, yObs=yObs, gamma=0.03 ** 2 * np.eye(tGrid.size),
            priorMean=np.ones(3), priorCov=4.0 * np.eye(3),
            nEnsemble=16, nIter=10, evalPerIter=3, adaptiveStep=True, seed=11,
            verbose=False,
        )
        bestTheta, bestMisfit, _ = solver.run()
        assert bestMisfit < 8.0
        assert float(np.max(np.abs(bestTheta - thetaTrue))) < 0.35
        assert solver.trueEvals == 16 + 3 * 10  # 代理替身生效：远少于 16*11 次真值评估

    def test_thompson_candidate_mode_runs(self):
        self._runLinear(candidateMode="thompson", nIter=4, nEnsemble=12, evalPerIter=3,
                         nResample=8, mhSteps=2)


# ────── EKIModule 接线（活链：/eki/* → manager → EKIModule） ──────


class TestEkiModuleWiring:
    def test_observation_pulls_importance_toward_value(self):
        module = EKIModule(ensemble_size=12, seed=42)
        module.init()
        module.initialize_state(memory_id="m1", importance=0.2)
        first = module.predict_importance("m1")
        for _ in range(5):
            module.update_with_observation(memory_id="m1", observation=0.9)
        afterMany = module.predict_importance("m1")
        assert 0.0 <= first <= 1.0
        assert afterMany > first  # 观测 0.9 应把重要性往上拉
        assert afterMany < 1.0

    def test_different_observations_diverge(self):
        module = EKIModule(ensemble_size=12, seed=42)
        module.init()
        module.initialize_state(memory_id="high", importance=0.5)
        module.initialize_state(memory_id="low", importance=0.5)
        for _ in range(5):
            module.update_with_observation(memory_id="high", observation=0.95)
            module.update_with_observation(memory_id="low", observation=0.05)
        assert module.predict_importance("high") > module.predict_importance("low")

    def test_batch_update_contract_kept(self):
        module = EKIModule(ensemble_size=10)
        module.init()
        module.initialize_state(memory_id="a", importance=0.5)
        results = module.batch_update(updates=[("a", 0.8)])
        assert "a" in results
        assert 0.0 <= results["a"] <= 1.0


# ────── EKICognitiveOptimizer 代理接线 ──────


class TestCognitiveOptimizerSurrogateWiring:
    def test_train_surrogate_builds_real_gp(self):
        optimizer = EKICognitiveOptimizer(ensemble_size=8, learning_rate=0.1)
        optimizer.train_surrogate([
            ("alpha beta", 0.8),
            ("alpha beta gamma delta", 0.9),
            ("zzz qq", 0.1),
            ("zzz", 0.05),
        ])
        assert isinstance(optimizer.surrogate, GaussianProcessSurrogate)
        assert optimizer.surrogate.logHp is not None

    def test_surrogate_predict_reads_trained_gp(self):
        optimizer = EKICognitiveOptimizer(ensemble_size=8, learning_rate=0.1)
        optimizer.train_surrogate([
            ("important critical urgent", 0.9),
            ("important critical urgent now", 0.9),
            ("trivial tiny", 0.1),
            ("trivial tiny small", 0.1),
        ])
        high = optimizer.surrogatePredict("important critical urgent")
        low = optimizer.surrogatePredict("trivial tiny")
        assert 0.0 <= high <= 1.0
        assert 0.0 <= low <= 1.0
        assert high > low

    def test_train_surrogate_docstring_no_longer_marks_simplified(self):
        docstring = EKICognitiveOptimizer.train_surrogate.__doc__ or ""
        assert "简化" not in docstring
        assert "高斯过程" in docstring
