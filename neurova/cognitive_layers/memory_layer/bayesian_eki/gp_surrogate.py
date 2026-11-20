"""高斯过程代理模型 — bayesian_eki 包的代理组件

用途: 为 EKI 求解器替代昂贵前向算子, 并为嵌入式采样提供后验分布。
- 核: RBF / Matérn-5/2, 支持 ARD(各输入维独立长度尺度)
- 超参数: 对数边缘似然最大化(L-BFGS-B 多起点 + 热启动)
- 输入/输出内部标准化; 训练分解(Cholesky)按数据版本缓存, 重复预测不重算
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize


def _squaredDistance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """成对平方欧氏距离, (n,d),(m,d) -> (n,m)。"""
    a2 = np.sum(a * a, axis=1)[:, None]
    b2 = np.sum(b * b, axis=1)[None, :]
    return np.maximum(a2 + b2 - 2.0 * (a @ b.T), 0.0)


def _jitteredCholesky(mat: np.ndarray, tries: int = 6) -> np.ndarray:
    """带抖动的 Cholesky, 应对半正定/病态协方差。"""
    mat = 0.5 * (mat + mat.T)
    scale = float(np.trace(mat)) / mat.shape[0]
    jitter = max(scale, 1.0) * 1e-12
    for _ in range(tries):
        try:
            return np.linalg.cholesky(mat + jitter * np.eye(mat.shape[0]))
        except np.linalg.LinAlgError:
            jitter *= 100.0
    raise np.linalg.LinAlgError("Cholesky failed even with jitter")


class GaussianProcessSurrogate:
    """多输出高斯过程代理: 各输出维共享核超参数、过程相互独立。"""

    def __init__(self, kernel: str = "matern52", ard: bool = True, seed: int = 0):
        if kernel not in ("rbf", "matern52"):
            raise ValueError(f"unsupported kernel: {kernel}")
        self.kernel = kernel
        self.ard = ard
        self.seed = seed
        self.xMean: Optional[np.ndarray] = None
        self.xStd: Optional[np.ndarray] = None
        self.yMean: Optional[np.ndarray] = None
        self.yStd: Optional[np.ndarray] = None
        self.Xz: Optional[np.ndarray] = None   # (n, d) 标准化输入
        self.Yz: Optional[np.ndarray] = None   # (n, m) 标准化输出
        self.logHp: Optional[np.ndarray] = None  # [log ell * k, log sigma_f, log sigma_n]
        self._decomposeCache: Optional[Tuple[np.ndarray, np.ndarray]] = None

    # ────── 核 ──────

    @property
    def _numLengthScales(self) -> int:
        assert self.Xz is not None
        return self.Xz.shape[1] if self.ard else 1

    def _kernel(self, a: np.ndarray, b: np.ndarray, logHp: np.ndarray) -> np.ndarray:
        ls = np.exp(logHp[: self._numLengthScales])
        sf2 = np.exp(2.0 * logHp[self._numLengthScales])
        if self.kernel == "rbf":
            return sf2 * np.exp(-0.5 * _squaredDistance(a / ls, b / ls))
        r = np.sqrt(5.0) * np.sqrt(_squaredDistance(a / ls, b / ls))
        return sf2 * (1.0 + r + r * r / 3.0) * np.exp(-r)

    # ────── 训练 ──────

    def _negLogMarginal(self, logHp: np.ndarray) -> float:
        assert self.Xz is not None and self.Yz is not None
        n = self.Xz.shape[0]
        K = self._kernel(self.Xz, self.Xz, logHp)
        sn2 = np.exp(2.0 * logHp[-1])
        try:
            L = _jitteredCholesky(K + sn2 * np.eye(n))
        except np.linalg.LinAlgError:
            return float(np.inf)
        nll = 0.0
        for m in range(self.Yz.shape[1]):
            y = self.Yz[:, m]
            alpha = np.linalg.solve(L.T, np.linalg.solve(L, y))
            nll += 0.5 * float(y @ alpha) + float(np.sum(np.log(np.diag(L))))
        return nll + 0.5 * n * self.Yz.shape[1] * np.log(2.0 * np.pi)

    def fit(self, X: np.ndarray, Y: np.ndarray,
            refitFrom: Optional[np.ndarray] = None, restarts: int = 3) -> np.ndarray:
        """拟合 GP; refitFrom 传上一次的 logHp 作热启动起点。"""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        Y = np.asarray(Y, dtype=float)
        if Y.ndim == 1:
            Y = Y[:, None]
        self.xMean = X.mean(axis=0)
        xStd = X.std(axis=0)
        self.xStd = np.where(xStd < 1e-12, 1.0, xStd)
        self.yMean = Y.mean(axis=0)
        yStd = Y.std(axis=0)
        self.yStd = np.where(yStd < 1e-12, 1.0, yStd)
        self.Xz = (X - self.xMean) / self.xStd
        self.Yz = (Y - self.yMean) / self.yStd
        self._decomposeCache = None

        k = self._numLengthScales
        bounds = ([(np.log(1e-3), np.log(1e3))] * k
                  + [(np.log(1e-3), np.log(1e3)),     # log sigma_f
                     (np.log(1e-6), np.log(1.0))])    # log sigma_n
        rng = np.random.default_rng(self.seed)
        starts: List[np.ndarray] = [
            np.concatenate([np.full(k, np.log(0.5)), [0.0, np.log(1e-3)]])
        ]
        for _ in range(restarts):
            starts.append(np.concatenate([
                rng.uniform(np.log(0.05), np.log(5.0), size=k),
                [rng.uniform(-1.0, 1.0), rng.uniform(np.log(1e-4), np.log(1e-1))],
            ]))
        if refitFrom is not None and len(refitFrom) == k + 2:
            starts.insert(0, np.asarray(refitFrom, dtype=float))

        lo = np.array([b[0] for b in bounds])
        hi = np.array([b[1] for b in bounds])
        bestHp, bestNll = None, float(np.inf)
        for s0 in starts:
            s0 = np.clip(s0, lo, hi)
            try:
                res = minimize(self._negLogMarginal, s0, method="L-BFGS-B", bounds=bounds)
            except np.linalg.LinAlgError:
                continue
            if np.isfinite(res.fun) and res.fun < bestNll:
                bestNll, bestHp = float(res.fun), res.x
        if bestHp is None:
            bestHp = np.clip(starts[0], lo, hi)
        self.logHp = bestHp
        self._decomposeCache = None
        return bestHp

    # ────── 预测 / 采样 ──────

    def _decompose(self) -> Tuple[np.ndarray, np.ndarray]:
        assert self.Xz is not None and self.Yz is not None and self.logHp is not None
        if self._decomposeCache is None:
            n = self.Xz.shape[0]
            K = self._kernel(self.Xz, self.Xz, self.logHp)
            sn2 = np.exp(2.0 * self.logHp[-1])
            L = _jitteredCholesky(K + sn2 * np.eye(n))
            alpha = np.linalg.solve(L.T, np.linalg.solve(L, self.Yz))  # (n, m)
            self._decomposeCache = (L, alpha)
        return self._decomposeCache

    def _toStandard(self, Xs: np.ndarray) -> np.ndarray:
        Xs = np.atleast_2d(np.asarray(Xs, dtype=float))
        assert self.xMean is not None and self.xStd is not None
        return (Xs - self.xMean) / self.xStd

    def predict(self, Xs: np.ndarray, returnVar: bool = False):
        """返回还原量纲后的均值 (s, m); returnVar 时附边缘方差 (s, m)。"""
        assert self.logHp is not None and self.yMean is not None and self.yStd is not None
        Zs = self._toStandard(Xs)
        L, alpha = self._decompose()
        ks = self._kernel(self.Xz, Zs, self.logHp)     # (n, s)
        muZ = ks.T @ alpha                              # (s, m)
        mu = muZ * self.yStd[None, :] + self.yMean[None, :]
        if not returnVar:
            return mu
        sf2 = np.exp(2.0 * self.logHp[self._numLengthScales])
        v = np.linalg.solve(L, ks)                      # (n, s)
        varZ = np.maximum(sf2 - np.sum(v * v, axis=0), 1e-12)
        var = varZ[:, None] * (self.yStd ** 2)[None, :]
        return mu, var

    def samplePosterior(self, Xs: np.ndarray, nSamples: int = 1,
                        rng: Optional[np.random.Generator] = None) -> np.ndarray:
        """从 GP 后验联合采样, 返回 (nSamples, s, m)。"""
        rng = rng or np.random.default_rng(0)
        assert self.logHp is not None and self.yMean is not None and self.yStd is not None
        Zs = self._toStandard(Xs)
        L, alpha = self._decompose()
        ks = self._kernel(self.Xz, Zs, self.logHp)
        muZ = ks.T @ alpha                              # (s, m)
        kss = self._kernel(Zs, Zs, self.logHp)          # (s, s)
        v = np.linalg.solve(L, ks)                      # (n, s)
        covZ = kss - v.T @ v
        Lc = _jitteredCholesky(covZ)
        s, m = Zs.shape[0], self.Yz.shape[1]
        # 各输出维为独立 GP（共享跨点协方差），逐输出独立采样
        fZ = np.empty((nSamples, s, m))
        for j in range(m):
            z = rng.standard_normal((s, nSamples))
            fZ[:, :, j] = (Lc @ z).T + muZ[:, j][None, :]
        return fZ * self.yStd[None, None, :] + self.yMean[None, None, :]
