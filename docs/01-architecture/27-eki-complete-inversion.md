# 27. EKI 单步更新与高斯过程代理

> 状态：✅ 现役（2026-11-27 收口）
> 关键代码：`neurova/cognitive_layers/memory_layer/bayesian_eki/`（`inversion.py`、`gp_surrogate.py`、`cognitive_optimizer.py`）+ `modules/eki_module.py`
> 关联：[02-memory-system](02-memory-system.md)、[12-memory-temperature-mechanism](12-memory-temperature-mechanism.md)

## 1. 当前边界

`bayesian_eki` 当前交付两部分：

- `ekiUpdate`：一步随机集合卡尔曼更新，扰动观测并做协方差膨胀；
- `GaussianProcessSurrogate`：RBF/Matérn 核高斯过程代理，供认知优化器训练与预测。

`EnsembleKalmanInversion` 完整求解器只有测试消费者，未接入业务管线，已于 DEAD-10 退役。
自适应步长、嵌入式采样、Metropolis-Hastings 精修、选点与精英替换不属于当前 API；
历史测试已删除，包导出与文档同步收口。

## 2. 单步更新

逆问题设定：

```
y = G(θ) + η,   η ~ N(0, Γ),   先验 θ ~ N(m0, C0)
```

集合 `{θ_j}_{j=1..J}` 上的一步随机 EKI 更新：

```
C_θg = 1/(J-1) Σ (θ_j-θ̄)(g_j-ḡ)ᵀ
C_gg = 1/(J-1) Σ (g_j-ḡ)(g_j-ḡ)ᵀ
y_j  = y + Γ^{1/2} ξ_j
θ_j  ← θ_j + Δt · C_θg (C_gg + Γ_eff)^{-1} (y_j - g_j)
```

`inflation=β` 对状态/响应异常值同乘 `√β` 后再估协方差；病态协方差通过 Cholesky 抖动兜底。

## 3. 高斯过程代理

- 核：RBF / Matérn-5/2，支持 ARD；输入与输出内部标准化；
- 超参数：最大化对数边缘似然，使用 L-BFGS-B 多起点优化；
- 预测：返回均值与边缘方差；
- 后验采样：按各输出维独立采样。

`EKICognitiveOptimizer.train_surrogate` 使用真 GP 拟合内容特征，`surrogatePredict` 读取预测结果。

## 4. 仓内接线

```
/api/v1/memory/eki/* 端点
        │
        ▼
MemoryManager.eki_*
        │
        ▼
EKIModule.update_with_observation ──调用──> ekiUpdate

EKICognitiveOptimizer.train_surrogate ──调用──> GaussianProcessSurrogate
EKICognitiveOptimizer.surrogatePredict ──读取──> 训练后的代理
```

## 5. 使用示例

```python
from neurova.cognitive_layers.memory_layer.bayesian_eki import ekiUpdate

updated = ekiUpdate(
    ensemble=ensemble,
    responses=responses,
    observation=observation,
    gamma=gamma,
    stepSize=0.1,
    inflation=1.02,
)
```

## 6. 验证与边界

- 现役回归：`tests/unit/cognitive_layers/memory_layer/test_eki_complete_inversion.py`、`test_bayesian_eki_honest_docs.py`；
- 退役判据：`tests/unit/ci/test_dead_api_retirement.py` 禁止完整求解器重新进入包导出；
- `_compute_information_gain` 仍为词汇启发式；
- `_flush_updates` 仍显式抛 `NotImplementedError`；
- 本模块只提供单步更新与代理能力，不宣称完整反演管线已接线。
