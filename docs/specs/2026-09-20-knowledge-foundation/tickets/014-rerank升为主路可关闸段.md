# 014 rerank 升为主路可关闸段（灭 B05）

**Blocked by**: 011
**阶段**: E2（§7）

## 目标
已有的精修能力（`knowledge/rerank/`）从旁路 API 进入对话主路，且可关闸、成本可控。

## 涉及层
- [ ] 逻辑层：主路末端接 `WeightRerankRunner`（默认，无外部依赖）与可选 `ModelRerankRunner`
      （provider 缺席即降级并记 `unevidenced`，不得静默当"已重排"）
- [ ] 配置：门控开关 + top-k 截断，避免整池重排引发成本尖峰
- [ ] 测试：`tests/unit/knowledge/test_main_path_rerank.py`

## 验收标准
- 关闸态与 011 开闸态逐条一致；开闸态 002 读数不降。
- `semantic_search_api.py` 与主路共用同一 runner 实现，不出现第二份排序逻辑。
- 模型重排缺席时的降级路径有显式读数，不冒充"已生效"。
