"""完整集合卡尔曼反演（EKI）— 本仓 EKI 数学核心的单一事实源

逆问题设定:
    y = G(theta) + eta,   eta ~ N(0, Gamma),   先验 theta ~ N(m0, C0)

- ekiUpdate: 一步随机 EKI 更新（扰动观测 + 协方差膨胀）。
  EKIModule 的记忆状态更新复用本函数，不再各自维护简化增益公式。
- EnsembleKalmanInversion: 完整求解器 = 随机 EKI 主循环 + 高斯过程代理
  + 自适应步长 + 嵌入式采样（集合高斯重采样、GP 后验 Metropolis-Hastings
  精修、LCB/Thompson 选点回填真值、精英替换）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import qmc

from .gp_surrogate import GaussianProcessSurrogate, _jitteredCholesky

__all__ = ["ekiUpdate", "EnsembleKalmanInversion"]


# ---------------------------------------------------------------- 单步更新

def ekiUpdate(theta: np.ndarray, g: np.ndarray, yObs: np.ndarray,
              gamma: np.ndarray, rng: np.random.Generator,
              inflation: float = 1.0, step: float = 1.0,
              stochastic: bool = True, gammaGain: Optional[np.ndarray] = None,
              jitterRel: float = 1e-10) -> np.ndarray:
    """一步（随机）集合卡尔曼反演更新。

    theta_j^{n+1} = theta_j + step * C_tg (C_gg + Gamma)^{-1} (y_j - g_j)
    其中 y_j = y + Gamma^{1/2} xi_j 为扰动观测; 协方差由集合经验估计;
    inflation 对状态/响应异常值同乘 sqrt(beta) 放大（防集合坍缩）。

    theta: (J, p) 参数集合;  g: (J, d) 前向响应（可为代理均值）
    yObs: (d,) 观测;  gamma: (d, d) 观测噪声协方差
    gammaGain: 仅用于增益分母的替代协方差（例如并入代理不确定度
               diag(var)），扰动观测仍用 gamma。
    """
    J = theta.shape[0]
    d = gamma.shape[0]
    thBar = theta.mean(axis=0)
    gBar = g.mean(axis=0)
    sq = np.sqrt(max(inflation, 1.0))
    thAnom = sq * (theta - thBar)
    gAnom = sq * (g - gBar)
    Ctg = thAnom.T @ gAnom / (J - 1)             # (p, d)
    Cgg = gAnom.T @ gAnom / (J - 1)              # (d, d)
    if stochastic:
        Lg = _jitteredCholesky(gamma)
        D = yObs[None, :] + rng.standard_normal((J, d)) @ Lg.T
    else:
        D = np.tile(yObs, (J, 1))
    S = Cgg + (gamma if gammaGain is None else gammaGain)
    S = 0.5 * (S + S.T)
    S = S + jitterRel * max(float(np.trace(S)), 1.0) * np.eye(d)
    gain = Ctg @ np.linalg.inv(S)                # (p, d)
    return theta + step * (D - g) @ gain.T


# ---------------------------------------------------------------- 求解器

class EnsembleKalmanInversion:
    """代理嵌入的完整 EKI 求解器。

    forward:   theta -> G(theta) 真值前向算子（可昂贵）
    yObs:      (d,) 观测
    gamma:     (d, d) 观测噪声协方差
    priorMean / priorCov: 高斯先验
    nEnsemble / nIter:    集合规模 / 迭代轮数
    inflation / step:     协方差膨胀系数 / 固定步长
    adaptiveStep:         用代理失配对增量做回溯线搜索选步长
    evalPerIter:          每轮真值评估预算 q（嵌入式采样的回填批量）
    kappa:                LCB 探索系数（评分 = 失配均值 - kappa*不确定度）
    candidateMode:        'lcb' 或 'thompson'（用 GP 后验采样评分）
    nResample / mhSteps / mhScale: 嵌入式采样规模与 MH 精修参数

    run() 返回 (bestTheta, bestMisfit, thetaFinal)。
    """

    def __init__(self, forward: Callable, yObs: np.ndarray, gamma: np.ndarray,
                 priorMean: np.ndarray, priorCov: np.ndarray,
                 nEnsemble: int = 32, nIter: int = 25,
                 inflation: float = 1.05, step: float = 1.0,
                 adaptiveStep: bool = False,
                 nResample: int = 64, mhSteps: int = 10, mhScale: float = 0.6,
                 evalPerIter: int = 5, kappa: float = 1.5,
                 candidateMode: str = "lcb",
                 kernel: str = "matern52", ard: bool = True,
                 lhsInit: bool = False, seed: int = 0, verbose: bool = True):
        if candidateMode not in ("lcb", "thompson"):
            raise ValueError(f"unsupported candidateMode: {candidateMode}")
        self.forward = forward
        self.yObs = np.asarray(yObs, dtype=float)
        self.gamma = np.asarray(gamma, dtype=float)
        self.priorMean = np.asarray(priorMean, dtype=float)
        self.priorCov = np.asarray(priorCov, dtype=float)
        self.nEnsemble = nEnsemble
        self.nIter = nIter
        self.inflation = inflation
        self.step = step
        self.adaptiveStep = adaptiveStep
        self.nResample = nResample
        self.mhSteps = mhSteps
        self.mhScale = mhScale
        self.evalPerIter = evalPerIter
        self.kappa = kappa
        self.candidateMode = candidateMode
        self.lhsInit = lhsInit
        self.verbose = verbose
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.gp = GaussianProcessSurrogate(kernel=kernel, ard=ard, seed=seed)
        self._XTrain: List[np.ndarray] = []
        self._GTrain: List[np.ndarray] = []
        self.trueEvals = 0
        self.history: List[Dict[str, Any]] = []
        self.bestTheta: Optional[np.ndarray] = None
        self.bestMisfit = float(np.inf)
        self.thetaFinal: Optional[np.ndarray] = None

    # ────── 真值评估与记录 ──────

    def _evalTrue(self, thetaBatch: np.ndarray) -> np.ndarray:
        thetaBatch = np.atleast_2d(thetaBatch)
        G = np.array([np.asarray(self.forward(t), dtype=float) for t in thetaBatch])
        self._XTrain.append(thetaBatch.copy())
        self._GTrain.append(G)
        self.trueEvals += len(thetaBatch)
        for t, g in zip(thetaBatch, G):
            r = g - self.yObs
            misfit = float(r @ np.linalg.solve(self.gamma, r))
            if misfit < self.bestMisfit:
                self.bestMisfit = misfit
                self.bestTheta = t.copy()
        return G

    def _gpFit(self) -> None:
        X = np.vstack(self._XTrain)
        Y = np.vstack(self._GTrain)
        self.gp.fit(X, Y, refitFrom=self.gp.logHp)

    # ────── 候选评分 ──────

    def _surrogateScore(self, mu: np.ndarray, var: np.ndarray) -> np.ndarray:
        """LCB 失配评分: 失配均值 - kappa*不确定度惩罚, 越小越值得真值评估。"""
        Sinv = np.linalg.inv(self.gamma)
        r = mu - self.yObs[None, :]
        misfit = np.einsum("jd,de,je->j", r, Sinv, r)
        penalty = self.kappa * np.einsum("jd,d->j", var, np.diag(Sinv))
        return misfit - penalty

    def _scoreCandidates(self, candidates: np.ndarray) -> np.ndarray:
        if self.candidateMode == "thompson":
            f = self.gp.samplePosterior(candidates, nSamples=1, rng=self.rng)[0]
            r = f - self.yObs[None, :]
            return np.einsum("jd,de,je->j", r, np.linalg.inv(self.gamma), r)
        mu, var = self.gp.predict(candidates, returnVar=True)
        return self._surrogateScore(mu, var)

    # ────── 嵌入式采样 ──────

    def _embeddedCandidates(self, theta: np.ndarray) -> np.ndarray:
        """集合高斯重采样 + GP 后验 MH 精修, 合成候选池。"""
        p = theta.shape[1]
        thBar = theta.mean(axis=0)
        cov = np.cov(theta, rowvar=False)
        Le = _jitteredCholesky(0.5 * (cov + cov.T) + 1e-12 * np.eye(p))
        resampled = thBar[None, :] + self.rng.standard_normal(
            (self.nResample, p)) @ Le.T
        refined = self._mhRefine(theta, Le)
        return np.vstack([resampled, refined])

    def _logPosteriorGp(self, theta: np.ndarray) -> float:
        """代理后验对数密度: GP 后验似然 + 高斯先验。"""
        mu, var = self.gp.predict(theta[None, :], returnVar=True)
        mu, var = mu[0], var[0]
        S = np.diag(var) + self.gamma
        r = self.yObs - mu
        _, logdet = np.linalg.slogdet(S)
        logLik = -0.5 * float(r @ np.linalg.solve(S, r)) - 0.5 * logdet
        d0 = theta - self.priorMean
        logPrior = -0.5 * float(d0 @ np.linalg.solve(self.priorCov, d0))
        return logLik + logPrior

    def _mhRefine(self, theta: np.ndarray, Le: np.ndarray) -> np.ndarray:
        out = theta.copy()
        curLp = np.array([self._logPosteriorGp(t) for t in out])
        for _ in range(self.mhSteps):
            proposal = out + self.mhScale * (self.rng.standard_normal(out.shape) @ Le.T)
            propLp = np.array([self._logPosteriorGp(t) for t in proposal])
            accept = np.log(self.rng.random(len(out))) < (propLp - curLp)
            out[accept] = proposal[accept]
            curLp[accept] = propLp[accept]
        return out

    def _elitistReplace(self, theta: np.ndarray, picks: np.ndarray) -> np.ndarray:
        """用新真值评估点替换集合中代理失配最差的等量成员。"""
        mu = self.gp.predict(theta)
        Sinv = np.linalg.inv(self.gamma)
        r = mu - self.yObs[None, :]
        misfit = np.einsum("jd,de,je->j", r, Sinv, r)
        out = theta.copy()
        out[np.argsort(misfit)[-len(picks):]] = picks
        return out

    # ────── 自适应步长 ──────

    def _lineSearch(self, theta: np.ndarray, delta: np.ndarray,
                    grid=(1.0, 0.7, 0.5, 0.3, 0.15)) -> float:
        Sinv = np.linalg.inv(self.gamma)
        bestT, bestMisfit = grid[0], float(np.inf)
        for t in grid:
            mu = self.gp.predict(theta + t * delta)
            r = mu - self.yObs[None, :]
            misfit = float(np.mean(np.einsum("jd,de,je->j", r, Sinv, r)))
            if misfit < bestMisfit:
                bestMisfit, bestT = misfit, t
        return bestT

    # ────── 主循环 ──────

    def run(self) -> Tuple[np.ndarray, float, np.ndarray]:
        rng = self.rng
        p = self.priorMean.size
        # 1. 初始化集合（先验采样 / 拉丁超立方）
        if self.lhsInit:
            u = qmc.LatinHypercube(d=p, seed=self.seed).random(self.nEnsemble)
            from scipy.stats import norm
            Z = norm.ppf(np.clip(u, 1e-9, 1.0 - 1e-9))
        else:
            Z = rng.standard_normal((self.nEnsemble, p))
        L0 = _jitteredCholesky(self.priorCov)
        theta = self.priorMean[None, :] + Z @ L0.T

        # 2. 真值评估初始集合, 训练首个代理
        self._evalTrue(theta)
        self._gpFit()

        # 3. 主循环: 代理 EKI 更新 → 嵌入式采样 → 真值回填 → 精英替换
        for n in range(self.nIter):
            mu, var = self.gp.predict(theta, returnVar=True)
            # 代理不确定度并入增益分母（诚实反映代理误差）
            gammaGain = self.gamma + np.diag(var.mean(axis=0))
            delta = ekiUpdate(theta, mu, self.yObs, self.gamma, rng,
                              inflation=self.inflation, step=1.0,
                              gammaGain=gammaGain) - theta
            step = self._lineSearch(theta, delta) if self.adaptiveStep else self.step
            thetaNew = theta + step * delta

            candidates = self._embeddedCandidates(thetaNew)
            order = np.argsort(self._scoreCandidates(candidates))
            picks = candidates[order[: self.evalPerIter]]
            self._evalTrue(picks)
            theta = self._elitistReplace(thetaNew, picks)
            self._gpFit()

            self.history.append(dict(
                iteration=n, step=step,
                bestTrueMisfit=self.bestMisfit,
                ensSpread=float(np.mean(np.std(theta, axis=0))),
                trueEvals=self.trueEvals,
            ))
            if self.verbose:
                entry = self.history[-1]
                print(f"[iter {n:03d}] best_misfit={entry['bestTrueMisfit']:.4f} "
                      f"spread={entry['ensSpread']:.4g} "
                      f"true_evals={entry['trueEvals']} step={step:.2f}")

        self.thetaFinal = theta
        return self.bestTheta, self.bestMisfit, theta
