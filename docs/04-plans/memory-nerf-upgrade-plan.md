# Neurova 记忆系统 NeRF 升级计划

> 结合 NeRF 核心理论与 Neurova 现状，三阶段渐进式升级

---

## 现状 vs 目标

| 维度 | 现状 | 升级后 |
|------|------|--------|
| 时间衰减 | 分段函数(1/7/30天) | 位置编码连续函数 |
| 情感表示 | 9种离散枚举 | 连续向量(类型+强度+效价+唤醒度) |
| 通道融合 | 加权求和 | 体渲染积分 |
| 语义查询 | 离散向量匹配 | 连续语义场漫游 |
| 新记忆处理 | 直接存入 | 增量学习更新场 |

## 三阶段路线

```
Phase 1 (10h, 低风险)    Phase 2 (20h, 中风险)    Phase 3 (30h, 中风险)
位置编码增强              记忆场原型               多通道渲染
├── 时间位置编码          ├── MemoryField MLP     ├── VolumeRenderer
├── 情感位置编码          ├── 增量训练器           ├── 统一融合接口
└── 替换现有衰减函数      └── 连续语义查询         └── 新增 _channel_nerf
```

## 实现状态

| 阶段 | 文件 | 状态 | 说明 |
|------|------|------|------|
| Phase 1 | `positional_encoding.py` | **已完成** | 纯 Python，零外部依赖，4个编码器 |
| Phase 2 | `memory_field.py` | **已完成** | 需要 torch，MLP + 增量训练 + 经验回放 |
| Phase 3 | `volume_renderer.py` | **已完成** | 纯 Python，体渲染 + 注意力增强融合 |
| 测试 | `test_nerf_memory_upgrade.py` | **31/31 通过** | 纯 Python 测试 |
| 导出 | `__init__.py` | **已更新** | 版本 0.3.0 |

## 核心收益

1. **精度提升**: 位置编码替代分段衰减，连续值区分度从 3 级 → 无限级
2. **多通道协同**: 体渲染替代加权求和，考虑通道间"遮挡"关系
3. **情感细粒度**: 9 种枚举 → 48 维连续向量(类型+强度+效价+唤醒度)
4. **向后兼容**: 纯 Python 实现，不强制安装 numpy/torch

## 下一步集成

- [ ] 将 `TemporalPositionalEncoder` 集成到 `TemperatureEngine`
- [ ] 将 `EmotionPositionalEncoder` 集成到 `EmotionModule`
- [ ] 在 `NeurovaRecallEngine` 中添加 `_channel_nerf` 使用 `VolumeRenderer`
- [ ] 安装 torch 后启用 `MemoryField` 训练流程

## 详细代码

- `neurova/cognitive_layers/memory_layer/positional_encoding.py` — 位置编码器
- `neurova/cognitive_layers/memory_layer/memory_field.py` — 记忆场神经网络
- `neurova/cognitive_layers/memory_layer/volume_renderer.py` — 体渲染器
- `tests/unit/test_nerf_memory_upgrade.py` — 31 个测试
