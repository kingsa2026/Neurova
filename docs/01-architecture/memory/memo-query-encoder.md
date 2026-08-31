# 查询编码器（QueryEncoder）详细设计

> **版本**: v1.0  
> **创建日期**: 2026-06-12  
> **基于论文**: MeMo: Memory as a Model (arXiv:2605.15156)

## 1. 概述

查询编码器是记忆模型的第一步，负责将自然语言查询转换为语义向量表示。其核心目标是：
- **语义理解**：捕获查询的深层含义
- **意图识别**：自动检测查询类型
- **上下文感知**：融合对话历史和用户状态

## 2. 架构设计

### 2.1 整体架构

```python
class QueryEncoder(nn.Module):
    """查询编码器 - 多层级语义理解"""
    
    def __init__(self, config: QueryEncoderConfig):
        super().__init__()
        
        # 1. 基础文本编码器（预训练Transformer）
        self.text_encoder = AutoModel.from_pretrained(
            config.base_model_name,
            config=config.auto_config
        )
        
        # 2. 意图检测头
        self.intent_detector = IntentDetectionHead(
            hidden_size=config.hidden_size,
            num_intents=len(QueryIntent),
            dropout=config.dropout_rate
        )
        
        # 3. 上下文融合模块
        self.context_fusion = ContextFusionModule(
            hidden_size=config.hidden_size,
            max_history_length=config.max_history_length
        )
        
        # 4. 多粒度表示
        self.multi_granularity = MultiGranularityEncoder(
            hidden_size=config.hidden_size,
            granularities=["token", "sentence", "paragraph"]
        )
        
    def forward(
        self, 
        query: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> QueryRepresentation:
        """前向传播"""
        # 步骤1: 基础文本编码
        inputs = self.tokenizer(
            query, 
            return_tensors="pt", 
            padding=True, 
            truncation=True,
            max_length=self.config.max_query_length
        )
        base_output = self.text_encoder(**inputs)
        
        # 步骤2: 多粒度表示
        token_emb = base_output.last_hidden_state
        sentence_emb = self.multi_granularity.get_sentence_embedding(token_emb)
        paragraph_emb = self.multi_granularity.get_paragraph_embedding(token_emb)
        
        # 步骤3: 意图检测
        intent_logits = self.intent_detector(sentence_emb)
        intent_probs = F.softmax(intent_logits, dim=-1)
        detected_intent = QueryIntent(intent_probs.argmax(dim=-1).item())
        
        # 步骤4: 上下文融合
        if context is not None:
            context_enhanced = self.context_fusion(sentence_emb, context)
        else:
            context_enhanced = sentence_emb
        
        # 步骤5: 构建表示
        return QueryRepresentation(
            token_embeddings=token_emb,
            sentence_embedding=sentence_emb,
            paragraph_embedding=paragraph_emb,
            context_enhanced_embedding=context_enhanced,
            intent_probs=intent_probs,
            detected_intent=detected_intent,
            raw_text=query,
            attention_mask=inputs.attention_mask
        )
```

### 2.2 配置类

```python
@dataclass
class QueryEncoderConfig:
    """查询编码器配置"""
    base_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    hidden_size: int = 384
    max_query_length: int = 128
    max_history_length: int = 10
    dropout_rate: float = 0.1
    
    # 意图检测配置
    num_intents: int = 6
    intent_loss_weight: float = 0.2
    
    # 上下文融合配置
    use_context_fusion: bool = True
    context_window_size: int = 5
    
    # 训练配置
    learning_rate: float = 2e-5
    warmup_steps: int = 100
    weight_decay: float = 0.01
```

## 3. 核心组件详解

### 3.1 意图检测头（IntentDetectionHead）

```python
class IntentDetectionHead(nn.Module):
    """意图检测头 - 基于BERT的分类器"""
    
    def __init__(
        self, 
        hidden_size: int, 
        num_intents: int, 
        dropout: float = 0.1
    ):
        super().__init__()
        
        # 多层感知器
        self.classifier = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 2, hidden_size // 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size // 4, num_intents)
        )
        
        # 注意力池化
        self.attention_pooling = AttentionPooling(hidden_size)
        
    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """
        Args:
            hidden_states: [batch, seq_len, hidden_size]
            
        Returns:
            intent_logits: [batch, num_intents]
        """
        # 注意力池化得到句子表示
        pooled = self.attention_pooling(hidden_states)  # [batch, hidden_size]
        
        # 分类
        logits = self.classifier(pooled)  # [batch, num_intents]
        
        return logits
```

**意图类型定义**：

```python
class QueryIntent(Enum):
    """查询意图类型"""
    FACTUAL = "factual"      # 事实查询：精确匹配
    TEMPORAL = "temporal"    # 时间查询：时间敏感
    CAUSAL = "causal"        # 因果查询：因果推理
    COMPARATIVE = "comparative"  # 比较查询：多维对比
    EXPLORATORY = "exploratory"  # 探索查询：广泛发现
    UNKNOWN = "unknown"      # 未知意图
```

**意图关键词映射**：

```python
INTENT_KEYWORDS = {
    QueryIntent.FACTUAL: [
        "what", "who", "where", "how many", "how much",
        "什么", "谁", "哪里", "多少", "怎么"
    ],
    QueryIntent.TEMPORAL: [
        "when", "time", "date", "before", "after",
        "什么时候", "时间", "日期", "之前", "之后"
    ],
    QueryIntent.CAUSAL: [
        "why", "cause", "reason", "because", "how",
        "为什么", "原因", "因为", "怎么"
    ],
    QueryIntent.COMPARATIVE: [
        "compare", "difference", "similar", "versus", "or",
        "比较", "区别", "相似", "对比", "还是"
    ],
    QueryIntent.EXPLORATORY: [
        "tell me about", "explain", "describe", "overview",
        "告诉我", "解释", "描述", "概述"
    ]
}
```

### 3.2 上下文融合模块（ContextFusionModule）

```python
class ContextFusionModule(nn.Module):
    """上下文融合模块 - 融合对话历史"""
    
    def __init__(self, hidden_size: int, max_history_length: int = 10):
        super().__init__()
        
        # 历史编码器
        self.history_encoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=hidden_size,
                nhead=8,
                dim_feedforward=hidden_size * 4,
                dropout=0.1,
                batch_first=True
            ),
            num_layers=2
        )
        
        # 融合门控
        self.fusion_gate = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.Sigmoid()
        )
        
        # 位置编码
        self.positional_encoding = PositionalEncoding(
            hidden_size, 
            max_history_length
        )
        
    def forward(
        self, 
        query_embedding: torch.Tensor, 
        context: Dict[str, Any]
    ) -> torch.Tensor:
        """融合查询和上下文"""
        # 提取历史对话
        history = context.get("conversation_history", [])
        
        if not history:
            return query_embedding
        
        # 编码历史
        history_texts = [msg["content"] for msg in history[-10:]]  # 最近10条
        history_embeddings = self.encode_history(history_texts)
        
        # 添加位置编码
        history_with_pos = self.positional_encoding(history_embeddings)
        
        # Transformer编码
        context_encoded = self.history_encoder(history_with_pos)
        
        # 融合查询和上下文
        query_expanded = query_embedding.unsqueeze(1).expand_as(context_encoded)
        
        # 门控融合
        gate_input = torch.cat([query_expanded, context_encoded], dim=-1)
        gate = self.fusion_gate(gate_input)
        
        fused = gate * query_expanded + (1 - gate) * context_encoded
        
        # 池化得到最终表示
        fused_embedding = fused.mean(dim=1)
        
        return fused_embedding
```

### 3.3 多粒度编码器（MultiGranularityEncoder）

```python
class MultiGranularityEncoder(nn.Module):
    """多粒度编码器 - 生成不同粒度的表示"""
    
    def __init__(self, hidden_size: int, granularities: List[str]):
        super().__init__()
        
        self.granularities = granularities
        
        # 不同粒度的池化层
        self.pooling_layers = nn.ModuleDict()
        for granularity in granularities:
            if granularity == "token":
                self.pooling_layers[granularity] = nn.Identity()
            elif granularity == "sentence":
                self.pooling_layers[granularity] = AttentionPooling(hidden_size)
            elif granularity == "paragraph":
                self.pooling_layers[granularity] = MultiHeadAttentionPooling(
                    hidden_size, 
                    num_heads=8
                )
        
    def forward(self, token_embeddings: torch.Tensor) -> Dict[str, torch.Tensor]:
        """生成多粒度表示"""
        results = {}
        for granularity, layer in self.pooling_layers.items():
            results[granularity] = layer(token_embeddings)
        
        return results
```

## 4. 训练策略

### 4.1 预训练策略

**对比学习**：
```python
# 正样本：相关查询对
# 负样本：随机采样的不相关查询
loss = InfoNCELoss(query_emb, positive_emb, negative_embs)
```

**意图分类**：
```python
loss = F.cross_entropy(intent_logits, intent_labels)
```

**多任务学习**：
```python
total_loss = α * contrastive_loss + β * intent_loss + γ * reconstruction_loss
```

### 4.2 数据增强

1. **同义词替换**：使用WordNet替换关键词
2. **句子重排**：随机打乱句子顺序
3. **回译**：英→中→英 翻译增强
4. **随机插入**：随机插入相关词汇

### 4.3 优化器配置

```python
optimizer = AdamW(
    model.parameters(),
    lr=config.learning_rate,
    weight_decay=config.weight_decay
)

scheduler = get_linear_schedule_with_warmup(
    optimizer,
    num_warmup_steps=config.warmup_steps,
    num_training_steps=total_training_steps
)
```

## 5. 评估指标

### 5.1 意图检测准确率

```python
def compute_intent_accuracy(predictions, labels):
    """计算意图检测准确率"""
    correct = (predictions == labels).sum().item()
    total = len(labels)
    return correct / total
```

### 5.2 检索性能

```python
def compute_retrieval_metrics(query_embeddings, memory_embeddings, labels):
    """计算检索性能指标"""
    # 余弦相似度
    similarities = F.cosine_similarity(
        query_embeddings.unsqueeze(1),
        memory_embeddings.unsqueeze(0),
        dim=2
    )
    
    # Top-K准确率
    top_k = 10
    top_k_predictions = similarities.topk(top_k, dim=1).indices
    
    # 计算召回率
    recall_at_k = compute_recall_at_k(top_k_predictions, labels, top_k)
    
    # 计算MRR
    mrr = compute_mrr(similarities, labels)
    
    return {
        "recall_at_k": recall_at_k,
        "mrr": mrr
    }
```

## 6. 部署配置

### 6.1 模型导出

```python
# 导出为ONNX格式
torch.onnx.export(
    model,
    dummy_input,
    "query_encoder.onnx",
    opset_version=14,
    input_names=["input_ids", "attention_mask"],
    output_names=["sentence_embedding", "intent_logits"]
)
```

### 6.2 推理优化

```python
# 量化配置
quantization_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16
)

# 加载量化模型
model = AutoModelForSequenceClassification.from_pretrained(
    model_name,
    quantization_config=quantization_config
)
```

## 7. 代码文件结构

```
neurova/memory_model/query_encoder/
├── __init__.py
├── config.py              # 配置类
├── encoder.py             # 主编码器
├── intent_detector.py     # 意图检测
├── context_fusion.py      # 上下文融合
├── multi_granularity.py   # 多粒度表示
├── loss.py                # 损失函数
├── trainer.py             # 训练器
└── inference.py           # 推理引擎
```

## 8. 测试用例

### 8.1 单元测试

```python
class TestQueryEncoder:
    def test_forward_pass():
        """测试前向传播"""
        config = QueryEncoderConfig()
        model = QueryEncoder(config)
        
        query = "What is the capital of France?"
        context = {"conversation_history": []}
        
        output = model(query, context)
        
        assert output.sentence_embedding.shape == (1, config.hidden_size)
        assert output.detected_intent == QueryIntent.FACTUAL
        
    def test_intent_detection():
        """测试意图检测"""
        # 测试事实查询
        query1 = "What is machine learning?"
        # 测试时间查询
        query2 = "When did the meeting start?"
        # 测试因果查询
        query3 = "Why is the sky blue?"
```

### 8.2 集成测试

```python
class TestQueryEncoderIntegration:
    def test_with_memory_retriever():
        """与记忆检索器集成测试"""
        # 测试查询编码器与检索器的配合
```

## 9. 常见问题

### 9.1 模型选择

**推荐模型**：
- **轻量级**：`sentence-transformers/all-MiniLM-L6-v2`（384维，速度快）
- **平衡型**：`sentence-transformers/all-mpnet-base-v2`（768维，效果好）
- **高质量**：`sentence-transformers/all-large-v1`（1024维，效果最好）

### 9.2 性能优化

1. **批量处理**：一次编码多个查询
2. **缓存机制**：缓存编码结果
3. **异步处理**：使用异步IO
4. **模型量化**：使用INT8/FP16量化

### 9.3 错误处理

```python
try:
    output = model(query, context)
except Exception as e:
    logger.error(f"查询编码失败: {e}")
    # 降级处理：返回默认表示
    output = get_default_representation(query)
```

---

**下一步**：[记忆检索器详细设计](./memo-memory-retriever.md)