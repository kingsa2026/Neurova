# 深入 Grilling: EvolutionFacade

## 关键设计问题讨论

### 问题 1：接口设计

**当前 EvolutionOrchestrator 暴露的方法：**
- `on_before_tool_selection()` → 过滤+排序
- `on_after_tool_execution()` → 更新权重+生命周期
- `on_experience_recorded()` → 经验反馈+模式挖掘+结晶
- `get_statistics()` → 统计信息

**Facade 接口设计：**

```python
class EvolutionFacade:
    # 工具权重
    def get_tool_weight(tool_name) -> float
    def update_tool_weight(tool_name, success, latency)
    def rank_tools(tool_names) -> List[str]
    
    # 工具生命周期
    def get_tool_lifecycle_state(tool_name) -> str
    def touch_tool(tool_name)
    
    # 工具选择
    def select_tools(available_tools, context) -> Dict
    
    # 经验处理
    def record_experience(text, task, tools, success) -> Dict
    
    # 模式挖掘
    def add_tool_sequence(tools, context)
    def get_frequent_patterns(top_n) -> List[Dict]
    
    # 工具合成
    def synthesize_tools(top_n) -> List[Dict]
    
    # 统计
    def get_statistics() -> Dict
```

### 问题 2：向后兼容

```python
class EvolutionFacade:
    def on_after_tool_execution(self, tool_name, success, context, latency):
        """兼容旧接口"""
        self.update_tool_weight(tool_name, success, latency)
        self.touch_tool(tool_name)
    
    def on_experience_recorded(self, text, task, tools, success):
        """兼容旧接口"""
        return self.record_experience(text, task, tools, success)
```

### 问题 3：性能优化

**缓存策略：**
- 工具权重缓存（TTL 60s）
- 频繁模式缓存（TTL 300s）
- 统计信息缓存（TTL 60s）

**并行优化：**
- 经验处理中的模式挖掘和结晶可并行
- 统计信息计算可异步

### 问题 4：测试策略

**单元测试：**
1. `test_get_tool_weight` — 获取权重
2. `test_update_tool_weight_success` — 成功更新
3. `test_update_tool_weight_failure` — 失败更新
4. `test_rank_tools` — 排序工具
5. `test_select_tools` — 选择工具
6. `test_record_experience` — 记录经验
7. `test_add_tool_sequence` — 添加序列
8. `test_get_frequent_patterns` — 获取模式
9. `test_synthesize_tools` — 合成工具
10. `test_get_statistics` — 获取统计

**集成测试：**
1. `test_tool_execution_flow` — 完整执行流程
2. `test_experience_loop` — 经验闭环
3. `test_pattern_mining` — 模式挖掘

## 最终设计决策

### 决策 1：Facade vs Adapter
**选择：Facade 模式**
- 理由：简化接口，内部协调

### 决策 2：单例 vs 实例
**选择：单例工厂 + 实例化支持**
- 理由：生产单例，测试独立

### 决策 3：是否需要事件驱动
**选择：先直接调用，预留扩展点**
- 理由：当前组件不多，直接调用简单

## 实施清单

- [ ] 定义 EvolutionFacade 接口
- [ ] 实现各功能模块委托
- [ ] 添加单例工厂函数
- [ ] 实现向后兼容适配器
- [ ] 编写 10 个单元测试
- [ ] 编写 3 个集成测试
