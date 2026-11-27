"""一步集合卡尔曼反演更新（EKI）——在线记忆状态更新的数学核心。"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .gp_surrogate import _jitteredCholesky

__all__ = ["ekiUpdate"]


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
    Ctg = thAnom.T @ gAnom / (J - 1)
    Cgg = gAnom.T @ gAnom / (J - 1)
    if stochastic:
        Lg = _jitteredCholesky(gamma)
        D = yObs[None, :] + rng.standard_normal((J, d)) @ Lg.T
    else:
        D = np.tile(yObs, (J, 1))
    S = Cgg + (gamma if gammaGain is None else gammaGain)
    S = 0.5 * (S + S.T)
    S = S + jitterRel * max(float(np.trace(S)), 1.0) * np.eye(d)
    gain = Ctg @ np.linalg.inv(S)
    return theta + step * (D - g) @ gain.T
