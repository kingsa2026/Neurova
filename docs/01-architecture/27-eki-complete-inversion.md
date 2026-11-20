# 27. EKI 完整反演（集合卡尔曼反演 + 高斯过程代理 + 嵌入式采样）

> 状态: ✅ 已实现（2026-11-20 落库）
> 关键代码: `neurova/cognitive_layers/memory_layer/bayesian_eki/`（`inversion.py`、`gp_surrogate.py`、`cognitive_optimizer.py`）+ `modules/eki_module.py`
> 关联: [02-memory-system](02-memory-system.md)、[12-memory-temperature-mechanism](12-memory-temperature-mechanism.md)

## 0. 摘要与动机

`bayesian_eki` 包此前在 `__init__.py` 诚实标注三处缺口：

1. 当前实现为简化版，非真正 EKI 算法（`EKIModule` 用标量伪增益、无扰动观测）；
2. 代理模型（高斯过程）—— 未实现（`EKICognitiveOptimizer.train_surrogate` 是调集合参数的假代理）；
3. 嵌入式代表性采样 —— 未实现。

本批把完整算法落为**单一事实源**并接通全部消费方：

- `ekiUpdate`：一步随机 EKI 更新，被 `EKIModule`（活链：`/api/v1/memory/eki/*` 端点 → `MemoryManager.eki_*` → `EKIModule`）与求解器共用；
- `EnsembleKalmanInversion`：完整求解器（代理辅助 + 自适应步长 + 嵌入式采样）；
- `GaussianProcessSurrogate`：真高斯过程代理，被求解器与 `train_surrogate` 共用。

## 1. 逆问题与 EKI 数学

逆问题设定：

```
y = G(θ) + η,   η ~ N(0, Γ),   先验 θ ~ N(m0, C0)
```

集合 `{θ_j}_{j=1..J}` 上的一步随机 EKI 更新（`ekiUpdate`）：

```
C_θg = 1/(J-1) Σ (θ_j-θ̄)(g_j-ḡ)ᵀ          # 参数-响应互协方差（p×d）
C_gg = 1/(J-1) Σ (g_j-ḡ)(g_j-ḡ)ᵀ           # 响应协方差（d×d）
y_j  = y + Γ^{1/2} ξ_j                      # 扰动观测（随机性来源）
θ_j  ← θ_j + Δt · C_θg (C_gg + Γ_eff)^{-1} (y_j - g_j)
```

要点：

- **协方差膨胀**：`inflation=β` 对状态/响应异常值同乘 `√β` 再估协方差（增益分母变大、防集合坍缩），不直接放大更新量；
- **代理不确定度诚实并入**：代理辅助模式下 `Γ_eff = Γ + diag(代理方差均值)`，代理误差进入增益分母而不是被忽略；
- **自适应步长**：对增量 `Δθ` 在 `{1, 0.7, 0.5, 0.3, 0.15}` 上按代理失配回溯线搜索选 `Δt`；
- 病态协方差用逐次放大抖动的 Cholesky 兜底（`_jitteredCholesky`）。

## 2. 高斯过程代理（`GaussianProcessSurrogate`）

- 核：RBF / Matérn-5/2，ARD（各输入维独立长度尺度）；输入/输出内部标准化；
- 超参数：对数边缘似然 `−½yᵀK_y⁻¹y − ½log|K_y| − n/2·log2π` 最大化（L-BFGS-B 多起点 + 上一轮热启动）；
- 预测：`μ* = k*ᵀK_y⁻¹y`，边缘方差 `k(x*,x*) − ‖L⁻¹k*‖²`；
- 后验采样：`f* = μ* + L_cov·z`，各输出维独立 GP 逐维采样，返回形状 `(nSamples, s, m)`；
- 训练分解（Cholesky）按数据版本缓存：每轮重拟合后才重算，MH 循环内的高频 `predict` 不再付出 O(n³)。

## 3. 嵌入式采样（`EnsembleKalmanInversion` 每轮 EKI 更新后执行）

1. **集合高斯重采样**：`θ* ~ N(θ̄, C_θ)` 抽 `nResample` 个候选；
2. **GP 后验 Metropolis-Hastings 精修**：对当前集合粒子做随机游走 MH，目标对数密度 =
   `log N(y; μ(θ), diag(var(θ)) + Γ) + log N(θ; m0, C0)`——采样嵌入在 EKI 迭代内部、由代理后验驱动；
3. **选点评分**：LCB `score = (μ−y)ᵀΓ⁻¹(μ−y) − κ·varᵀdiag(Γ⁻¹)`（乐观探索），
   或 `candidateMode="thompson"` 直接用 GP 后验采样评分；
4. **真值回填 + 精英替换**：top-`evalPerIter` 候选做真值评估，进入 GP 训练集，
   并替换集合中代理失配最差的等量成员。

每轮真值评估预算恒为 `evalPerIter`：总评估次数 = `nEnsemble + evalPerIter × nIter`，
与"每轮全集合真值评估"的朴素 EKI 相比省 `~nEnsemble×` 前向调用。

## 4. 仓内接线（单一事实源）

```
/api/v1/memory/eki/* 端点
        │
        ▼
MemoryManager.eki_*（manager.py 委托层）
        │
        ▼
EKIModule.update_with_observation ──调用──> ekiUpdate（bayesian_eki/inversion.py）
        ↑ 活链消费方 1                        ↑
EKICognitiveOptimizer.train_surrogate ──调用──> GaussianProcessSurrogate
        ↑ 消费方 2                              ↑
EnsembleKalmanInversion（完整求解器）────────────┘（代理辅助 + 嵌入式采样宿主）
```

- `EKIModule` 的状态更新公式（原 `_compute_covariance`/`_compute_kalman_gain`/`_update_ensemble` 标量伪增益）已删除，改调 `ekiUpdate`；观测算子 `h(θ)=importance` 分量，`observation_variance` 即增益分母正则项（默认 0.1，与旧分母 +0.1 同量级），更新后仍走 `_inflate` 维持实际集合散布；
- `EKICognitiveOptimizer.train_surrogate` 弃假用真：内容特征化（词汇丰富度/长度/关键词命中/平均词长）→ GP 拟合，新增 `surrogatePredict` 读面与 `surrogate` 属性；`VALUE_KEYWORDS` 收为模块常量单源；
- 包导出面（`bayesian_eki.__init__`）新增 `ekiUpdate` / `EnsembleKalmanInversion` / `GaussianProcessSurrogate`，诚实标注同步翻转（高斯过程与嵌入式采样改为已实现；`_compute_information_gain` 仍为词汇启发式、`_flush_updates` 仍显式抛 `NotImplementedError`）。

## 5. 使用示例

```python
from neurova.cognitive_layers.memory_layer.bayesian_eki import (
    EnsembleKalmanInversion, GaussianProcessSurrogate, ekiUpdate,
)

solver = EnsembleKalmanInversion(
    forward=G, yObs=y, gamma=Gamma,             # 真值前向算子 + 观测 + 噪声协方差
    priorMean=m0, priorCov=C0,
    nEnsemble=32, nIter=25, evalPerIter=5,      # 每轮只花 5 次真值评估
    adaptiveStep=True, seed=11, verbose=False,
)
bestTheta, bestMisfit, ensemble = solver.run()   # solver.trueEvals 记录真值评估数
```

## 6. 测试与验收

- 验收测试：`tests/unit/cognitive_layers/memory_layer/test_eki_complete_inversion.py`（24 项：GP 拟合/采样/多输出、单步更新、线性和非线性反演收敛、真值评估预算恰好等于 `nEnsemble + evalPerIter×nIter`、EKIModule 活链行为、train_surrogate 真 GP 接线）；
- 诚实标注守卫：`test_bayesian_eki_honest_docs.py` 按"改规则为准"翻转——高斯过程/嵌入式采样钉为已实现，剩余简化面继续钉住；
- 红灯证据：实现前新测试文件 `ImportError: cannot import name 'EnsembleKalmanInversion'`；
- 绿灯证据：新测试 24 passed；`tests/unit/cognitive_layers/` 全量 657 passed / 0 failed / 1 xfailed（A/B 探针：无本批改动时同套件 640 passed；期间一次 1 失败经最小组合与复跑定位为并行会话中途修改 `manager.py` 的环境噪声，与本批无关）；
- 依赖登记：`scipy>=1.10.0` 进 `requirements.txt`（`scipy.optimize.minimize` 超参优化、`scipy.stats.qmc` 拉丁超立方初始化两处功能依赖；线性代数走 numpy）。

## 7. 边界与未竟

- `_compute_information_gain` 仍为词汇启发式（诚实标注保留），升级为真正信息增益需接入检索通道，另批立项；
- `_flush_updates` 仍显式抛 `NotImplementedError`（实时更新语义下无批量冲刷需求）；
- 求解器每轮全量重拟合 GP（`restarts=3` + 热启动），当前规模（数百点内）成本可忽略；数据量上量后再考虑稀疏近似；
- `EnsembleKalmanInversion` 目前由测试与包导出面消费，尚未接入具体业务管线（如记忆衰减参数的批量重估）；接入时按核心原则第 7 条补影响面说明。
