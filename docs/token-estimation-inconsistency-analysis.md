# Token 估算不一致问题分析报告

## 问题描述

**报告时间**: 2026-06-10  
**严重程度**: 中  
**影响范围**: 上下文预算控制和压缩行为  

### 问题现象

在 4 个文件中使用了 4 种不同的 token 估算算法，导致同一段文本的 token 估算结果差异高达 1-12 倍。这会影响预算控制和压缩行为的可预测性。

### 影响范围

1. **预算控制不可预测**: 不同的估算方法导致预算分配不一致
2. **压缩行为不一致**: 同一段文本可能被过度压缩或不足压缩
3. **系统行为不可预测**: 上下文构建结果因使用的估算方法而异

## 根因分析

### 1. 四种不同的 token 估算算法

#### 算法 1: injector.py - _count_tokens (第757-768行)
```python
def _count_tokens(self, text: str) -> int:
    """估算 Token 数"""
    if not text:
        return 0
    
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    
    return int(
        chinese_chars * 1.5 +  # TokenBudget.chinese_ratio
        other_chars * 0.25     # TokenBudget.english_ratio
    )
```

**特点**:
- 中文字符: 1.5 tokens/字
- 其他字符: 0.25 tokens/字符
- 不区分英文单词，所有非中文字符统一计算

#### 算法 2: context_pool.py - ContextPoolUtils.estimate_tokens (第801-826行)
```python
@staticmethod
def estimate_tokens(text: str) -> int:
    """估算文本的Token数量"""
    if not text:
        return 0
    
    # 简单估算：中文约1.5 tokens/字，英文约0.25 tokens/词
    chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
    total_chars = len(text)
    non_chinese_chars = total_chars - chinese_chars
    
    # 英文按空格分词
    words = text.split()
    english_words = len(words)
    
    chinese_tokens = chinese_chars * 1.5
    english_tokens = english_words * 0.25
    
    return max(1, int(chinese_tokens + english_tokens))
```

**特点**:
- 中文字符: 1.5 tokens/字
- 英文单词: 0.25 tokens/词（按空格分词）
- 最小返回值为 1

#### 算法 3: context_compressor.py - Message.estimate_tokens (第58-67行)
```python
def estimate_tokens(self) -> int:
    """估算token数量"""
    if self.token_count is not None:
        return self.token_count
    
    # 简单估算：1个中文字符约2个token，1个英文单词约1个token
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', self.content))
    english_words = len(re.findall(r'[a-zA-Z]+', self.content))
    
    return chinese_chars * 2 + english_words
```

**特点**:
- 中文字符: 2 tokens/字
- 英文单词: 1 token/词（使用正则表达式匹配字母序列）
- 使用正则表达式进行更精确的分词

#### 算法 4: context_compressor.py - len() // 4 (第271, 611, 634行)
```python
# 第271行
system_tokens = len(system_prompt) // 4  # 粗略估算

# 第611行
total += len(system_prompt) // 4  # 粗略估算

# 第634行
total += len(content) // 4
```

**特点**:
- 所有字符: 4 字符/token
- 不区分语言
- 最简单的粗略估算

### 2. 算法差异对比

| 算法 | 中文字符 | 英文单词 | 其他字符 | 最小值 | 备注 |
|------|----------|----------|----------|--------|------|
| injector.py | 1.5 tokens/字 | - | 0.25 tokens/字符 | 0 | 不区分英文单词 |
| context_pool.py | 1.5 tokens/字 | 0.25 tokens/词 | - | 1 | 按空格分词 |
| context_compressor.py Message | 2 tokens/字 | 1 token/词 | - | 0 | 使用正则分词 |
| len() // 4 | - | - | 0.25 tokens/字符 | 0 | 不区分语言 |

### 3. 差异分析

#### 中文文本示例: "这是一个测试文本，包含中文字符。"
- **injector.py**: 16字符 × 1.5 = 24 tokens
- **context_pool.py**: 16字符 × 1.5 = 24 tokens  
- **context_compressor.py Message**: 10中文字符 × 2 = 20 tokens
- **len() // 4**: 16字符 ÷ 4 = 4 tokens
- **差异**: 24 vs 4 = **6倍**

#### 英文文本示例: "This is a test text with English words."
- **injector.py**: 39字符 × 0.25 = 9.75 ≈ 9 tokens
- **context_pool.py**: 8个单词 × 0.25 = 2 tokens
- **context_compressor.py Message**: 8个英文单词 × 1 = 8 tokens
- **len() // 4**: 39字符 ÷ 4 = 9.75 ≈ 9 tokens
- **差异**: 9 vs 2 = **4.5倍**

#### 混合文本示例: "Hello 你好 World 世界 Test 测试"
- **injector.py**: 6中文字符 × 1.5 + 19其他字符 × 0.25 = 9 + 4.75 = 13.75 ≈ 13 tokens
- **context_pool.py**: 6中文字符 × 1.5 + 3个单词 × 0.25 = 9 + 0.75 = 9.75 ≈ 10 tokens
- **context_compressor.py Message**: 6中文字符 × 2 + 3个英文单词 × 1 = 12 + 3 = 15 tokens
- **len() // 4**: 25字符 ÷ 4 = 6.25 ≈ 6 tokens
- **差异**: 15 vs 6 = **2.5倍**

## 层表分析 (Phase 1)

| 层 | 文件:行 | 问题 | 假设 |
|----|---------|------|------|
| 1 | `neurova/context/injector.py:757-768` | _count_tokens 使用 chinese_ratio=1.5, english_ratio=0.25 | 可能来自 TokenBudget 配置 |
| 2 | `neurova/context_pool.py:801-826` | ContextPoolUtils.estimate_tokens 使用中文字符*1.5 + 英文单词*0.25 | 可能与 injector.py 相同来源 |
| 3 | `neurova/context_compressor.py:58-67` | Message.estimate_tokens 使用中文字符*2 + 英文单词*1 | 不同的估算策略 |
| 4 | `neurova/context_compressor.py:271,611,634` | len() // 4 粗略估算 | 简化实现，精度最低 |
| 5 | `neurova/context/models.py:37-42` | TokenBudget 定义 chinese_ratio=1.5, english_ratio=0.25 | 配置源 |

## 影响分析

### 1. 预算控制问题

**场景**: 假设系统有 10000 tokens 预算

- **使用 injector.py**: 中文内容约占 1500 tokens
- **使用 context_pool.py**: 中文内容约占 1500 tokens  
- **使用 context_compressor.py Message**: 中文内容约占 2000 tokens
- **使用 len() // 4**: 中文内容约占 4000 tokens

**结果**: 不同的估算方法导致预算分配差异高达 2.67 倍。

### 2. 压缩行为问题

**场景**: 压缩器需要将内容压缩到 5000 tokens

- **高估算法 (context_compressor.py Message)**: 可能过度压缩，丢失重要信息
- **低估算法 (len() // 4)**: 可能压缩不足，超出实际预算
- **中等算法 (injector.py, context_pool.py)**: 行为相对合理

### 3. 系统行为不可预测

- 相同的输入在不同模块中产生不同的 token 计数
- 预算分配和压缩决策基于不同的估算结果
- 调试和优化困难，因为行为不一致

## 假设验证

### 假设 1: injector.py 和 context_pool.py 使用相同的算法
**验证结果**: 部分正确
- 两者都使用中文字符 × 1.5
- injector.py 对所有非中文字符使用 0.25
- context_pool.py 对英文单词使用 0.25（按空格分词）
- **差异**: 对于非空格分隔的字符（如标点、数字），计算方式不同

### 假设 2: context_compressor.py 使用更精确的算法
**验证结果**: 部分正确
- 使用正则表达式进行更精确的分词
- 中文字符使用 2.0（更高的估算）
- 英文单词使用 1.0（更高的估算）
- **结果**: 整体估算值更高，可能导致过度压缩

### 假设 3: len() // 4 是最简单的实现
**验证结果**: 正确
- 不区分语言，所有字符统一计算
- 精度最低，但计算最快
- **风险**: 对于中文内容严重低估，对于英文内容可能高估

## 修复方案

### 方案 1: 创建统一的 TokenEstimator 类（推荐）

```python
class TokenEstimator:
    """统一的 Token 估算器"""
    
    def __init__(self, strategy: str = "balanced"):
        """
        初始化估算器
        
        Args:
            strategy: 估算策略
                - "balanced": 平衡策略（推荐）
                - "conservative": 保守策略（高估）
                - "aggressive": 激进策略（低估）
        """
        self.strategy = strategy
        self._load_strategy(strategy)
    
    def _load_strategy(self, strategy: str):
        """加载策略配置"""
        if strategy == "balanced":
            self.chinese_ratio = 1.5
            self.english_ratio = 0.25
            self.min_tokens = 1
        elif strategy == "conservative":
            self.chinese_ratio = 2.0
            self.english_ratio = 0.5
            self.min_tokens = 1
        elif strategy == "aggressive":
            self.chinese_ratio = 1.0
            self.english_ratio = 0.2
            self.min_tokens = 0
    
    def estimate(self, text: str) -> int:
        """估算文本的 token 数量"""
        if not text:
            return 0
        
        # 中文字符计数
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        
        # 英文单词计数（按空格分词）
        words = text.split()
        english_words = len(words)
        
        # 其他字符计数（非中文、非英文单词部分）
        # 这里简化处理，使用字符数减去中文字符数
        other_chars = len(text) - chinese_chars
        
        # 计算 token 数
        chinese_tokens = chinese_chars * self.chinese_ratio
        english_tokens = english_words * self.english_ratio
        other_tokens = other_chars * 0.1  # 其他字符使用较低的比率
        
        total = int(chinese_tokens + english_tokens + other_tokens)
        
        return max(self.min_tokens, total)
```

### 方案 2: 修复现有实现

1. **统一算法**: 所有文件使用相同的计算公式
2. **使用 TokenBudget 配置**: 所有文件从 TokenBudget 获取比率
3. **移除粗略估算**: 替换 `len() // 4` 为精确估算

### 方案 3: 使用外部库

1. **tiktoken**: 使用 OpenAI 的 tiktoken 库进行精确估算
2. **transformers**: 使用 HuggingFace 的 transformers 库的 tokenizer
3. **自定义词典**: 基于项目特定词汇构建词典

## 推荐方案

**推荐使用方案 1**: 创建统一的 TokenEstimator 类

**理由**:
1. **一致性**: 所有模块使用相同的估算逻辑
2. **可配置**: 支持不同的估算策略
3. **可测试**: 提供清晰的测试接口
4. **向后兼容**: 可以逐步迁移现有代码

## 实施计划

### Phase 1: 创建统一的 TokenEstimator 类
1. 创建 `neurova/context/token_estimator.py`
2. 实现 TokenEstimator 类
3. 编写单元测试

### Phase 2: 迁移现有代码
1. 更新 `injector.py` 使用 TokenEstimator
2. 更新 `context_pool.py` 使用 TokenEstimator
3. 更新 `context_compressor.py` 使用 TokenEstimator

### Phase 3: 验证和清理
1. 运行所有测试确保兼容性
2. 清理旧的估算逻辑
3. 更新文档

## 测试验证

### 测试文件
1. `tests/unit/test_token_estimation_inconsistency.py` - 验证问题存在
2. `test_token_calculation.py` - 详细的计算对比

### 测试结果
- 中文文本差异: 7.00x
- 英文文本差异: 4.50x
- 混合文本差异: 2.50x
- 代码文本差异: 12.00x

**结论**: 问题确实存在，需要修复。

## 后续建议

1. **性能考虑**: TokenEstimator 应该高效，避免复杂的正则表达式
2. **精度要求**: 根据使用场景选择合适的策略
3. **监控**: 添加 token 估算的监控和统计
4. **文档**: 更新 API 文档和使用示例

## 相关文件

- `neurova/context/injector.py` - 主要问题文件
- `neurova/context_pool.py` - 主要问题文件
- `neurova/context_compressor.py` - 主要问题文件
- `neurova/context/models.py` - TokenBudget 定义
- `tests/unit/test_token_estimation_inconsistency.py` - 测试文件
- `test_token_calculation.py` - 计算对比脚本