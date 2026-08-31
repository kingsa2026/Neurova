# 融合网络（FusionNetwork）详细设计

> **版本**: v1.0  
> **创建日期**: 2026-06-12  
> **基于论文**: MeMo: Memory as a Model (arXiv:2605.15156)

## 1. 概述

融合网络负责将多通道检索结果融合为统一的记忆表示。其核心思想：
- **通道注意力**：学习不同通道的重要性
- **跨通道交互**：捕获通道间的依赖关系
- **动态融合**：根据查询自适应调整融合策略

## 2. 架构设计

### 2.1 整体架构

```python
class FusionNetwork(nn.Module):
    """融合网络 - 多通道记忆融合"""
    
    def __init__(self, config: FusionConfig):
        super().__init__()
        
        # 1. 通道注意力融合
        self.channel_attention = ChannelAttentionFusion(
            num_channels=config.num_channels,
            hidden_size=config.hidden_size
        )
        
        # 2. 跨通道交互
        self.cross_channel = CrossChannelInteraction(
            hidden_size=config.hidden_size,
            num_channels=config.num_channels
        )
        
        # 3. 动态融合网络
        self.dynamic_fusion = DynamicFusionNetwork(
            hidden_size=config.hidden_size,
            num_channels=config.num_channels
        )
        
        # 4. 记忆评分网络
        self.scoring = MemoryScoringNetwork(
            hidden_size=config.hidden_size
        )
        
        # 5. 输出投影
        self.output_projection = nn.Linear(config.hidden_size, config.output_dim)
        
    def forward(
        self,
        query_repr: QueryRepresentation,
        channel_memories: Dict[str, List[RetrievedMemory]]
    ) -> FusionOutput:
        """
        前向传播
        
        Args:
            query_repr: 查询表示
            channel_memories: 各通道检索结果
            
        Returns:
            FusionOutput: 融合结果
        """
        # 步骤1: 通道注意力融合
        channel_outputs = {}
        for channel_name, memories in channel_memories.items():
            channel_embedding = self._aggregate_channel_memories(memories)
            channel_outputs[channel_name] = channel_embedding
        
        # 步骤2: 跨通道交互
        enhanced_outputs = self.cross_channel(channel_outputs)
        
        # 步骤3: 动态融合
        fused_embedding = self.dynamic_fusion(
            query_repr.context_enhanced_embedding,
            enhanced_outputs
        )
        
        # 步骤4: 评分
        memory_scores = self.scoring(
            query_repr.context_enhanced_embedding,
            fused_embedding.unsqueeze(1)
        )
        
        # 步骤5: 输出投影
        output_embedding = self.output_projection(fused_embedding)
        
        return FusionOutput(
            fused_memory=output_embedding,
            memory_scores=memory_scores,
            channel_contributions=self._compute_contributions(enhanced_outputs),
            confidence=self._compute_confidence(memory_scores)
        )
```

### 2.2 配置类

```python
@dataclass
class FusionConfig:
    """融合网络配置"""
    num_channels: int = 6  # 温度、文本、分类、图谱、情感、语音
    hidden_size: int = 512
    output_dim: int = 768
    
    # 通道注意力配置
    attention_heads: int = 8
    attention_dropout: float = 0.1
    
    # 跨通道交互配置
    cross_channel_layers: int = 2
    cross_channel_heads: int = 8
    
    # 动态融合配置
    fusion_transformer_layers: int = 2
    fusion_transformer_heads: int = 8
    
    # 评分配置
    scoring_hidden_size: int = 256
    
    # 训练配置
    learning_rate: float = 1e-4
    weight_decay: float = 0.01
```

## 3. 核心组件详解

### 3.1 通道注意力融合（ChannelAttentionFusion）

```python
class ChannelAttentionFusion(nn.Module):
    """通道注意力融合 - 学习通道重要性"""
    
    def __init__(self, num_channels: int, hidden_size: int):
        super().__init__()
        
        # 通道嵌入
        self.channel_embeddings = nn.Embedding(num_channels, hidden_size)
        
        # 通道注意力
        self.channel_attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )
        
        # 门控机制
        self.gate = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.Sigmoid()
        )
        
    def forward(
        self,
        channel_memories: Dict[str, torch.Tensor],
        query_embedding: torch.Tensor
    ) -> torch.Tensor:
        """通道注意力融合"""
        # 构建通道序列
        channel_names = list(channel_memories.keys())
        channel_embs = []
        
        for i, name in enumerate(channel_names):
            # 通道嵌入 + 记忆表示
            channel_emb = self.channel_embeddings(
                torch.tensor(i, device=query_embedding.device)
            )
            memory_emb = channel_memories[name]
            
            # 融合通道和记忆
            fused = channel_emb + memory_emb.mean(dim=0)
            channel_embs.append(fused)
        
        # 堆叠为序列
        channel_sequence = torch.stack(channel_embs).unsqueeze(0)  # [1, num_channels, hidden]
        
        # 注意力
        attended, attention_weights = self.channel_attention(
            query_embedding.unsqueeze(1),
            channel_sequence,
            channel_sequence
        )
        
        # 门控融合
        gate_input = torch.cat([
            attended.squeeze(1),
            query_embedding
        ], dim=-1)
        gate = self.gate(gate_input)
        
        # 加权融合
        fused = torch.zeros_like(query_embedding)
        for i, name in enumerate(channel_names):
            weight = attention_weights[0, 0, i]
            fused += weight * channel_memories[name].mean(dim=0)
        
        return fused
```

### 3.2 跨通道交互（CrossChannelInteraction）

```python
class CrossChannelInteraction(nn.Module):
    """跨通道交互 - 捕获通道间依赖"""
    
    def __init__(self, hidden_size: int, num_channels: int):
        super().__init__()
        
        # 通道间注意力
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )
        
        # 通道间门控
        self.cross_gate = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.Sigmoid()
        )
        
        # 残差连接
        self.residual_scale = nn.Parameter(torch.ones(1))
        
    def forward(
        self,
        channel_outputs: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """跨通道交互"""
        # 构建通道序列
        channel_names = list(channel_outputs.keys())
        channel_sequence = torch.stack([
            channel_outputs[name].mean(dim=0) 
            for name in channel_names
        ]).unsqueeze(0)  # [1, num_channels, hidden]
        
        # 通道间注意力
        enhanced_sequence, _ = self.cross_attention(
            channel_sequence,
            channel_sequence,
            channel_sequence
        )
        
        # 门控残差
        enhanced_outputs = {}
        for i, name in enumerate(channel_names):
            original = channel_outputs[name].mean(dim=0)
            enhanced = enhanced_sequence[0, i]
            
            # 门控
            gate_input = torch.cat([original, enhanced], dim=-1)
            gate = self.cross_gate(gate_input)
            
            # 残差连接
            output = original + self.residual_scale * gate * (enhanced - original)
            enhanced_outputs[name] = output
        
        return enhanced_outputs
```

### 3.3 动态融合网络（DynamicFusionNetwork）

```python
class DynamicFusionNetwork(nn.Module):
    """动态融合网络 - 根据查询自适应融合"""
    
    def __init__(self, hidden_size: int, num_channels: int):
        super().__init__()
        
        # 查询感知的融合权重生成器
        self.weight_generator = nn.Sequential(
            nn.Linear(hidden_size, hidden_size // 2),
            nn.ReLU(),
            nn.Linear(hidden_size // 2, num_channels),
            nn.Softmax(dim=-1)
        )
        
        # 融合变换器
        self.fusion_transformer = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=hidden_size,
                nhead=8,
                dim_feedforward=hidden_size * 4,
                dropout=0.1,
                batch_first=True
            ),
            num_layers=2
        )
        
        # 输出投影
        self.output_projection = nn.Linear(hidden_size, hidden_size)
        
    def forward(
        self,
        query_embedding: torch.Tensor,
        channel_embeddings: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """动态融合"""
        # 生成融合权重
        fusion_weights = self.weight_generator(query_embedding)  # [batch, num_channels]
        
        # 构建输入序列
        channel_names = list(channel_embeddings.keys())
        input_sequence = torch.stack([
            channel_embeddings[name] 
            for name in channel_names
        ]).transpose(0, 1)  # [batch, num_channels, hidden]
        
        # Transformer融合
        fused_sequence = self.fusion_transformer(input_sequence)
        
        # 加权求和
        fused_embedding = torch.bmm(
            fusion_weights.unsqueeze(1),
            fused_sequence
        ).squeeze(1)
        
        # 输出投影
        output = self.output_projection(fused_embedding)
        
        return output
```

### 3.4 记忆评分网络（MemoryScoringNetwork）

```python
class MemoryScoringNetwork(nn.Module):
    """记忆评分网络 - 预测记忆相关性"""
    
    def __init__(self, hidden_size: int):
        super().__init__()
        
        # 交叉注意力
        self.cross_attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )
        
        # 评分MLP
        self.scoring_mlp = nn.Sequential(
            nn.Linear(hidden_size * 2, hidden_size),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_size, 1)
        )
        
    def forward(
        self,
        query_embedding: torch.Tensor,
        memory_embeddings: torch.Tensor
    ) -> torch.Tensor:
        """评分"""
        # 交叉注意力
        attended, _ = self.cross_attention(
            query_embedding.unsqueeze(1),
            memory_embeddings,
            memory_embeddings
        )
        
        # 拼接并评分
        batch_size, num_memories, hidden_size = memory_embeddings.shape
        
        query_expanded = query_embedding.unsqueeze(1).expand(-1, num_memories, -1)
        
        combined = torch.cat([attended, query_expanded], dim=-1)
        
        scores = self.scoring_mlp(combined).squeeze(-1)
        
        return scores
```

## 4. 高级融合策略

### 4.1 门控融合（GatedFusion）

```python
class GatedFusion(nn.Module):
    """门控融合 - 学习融合门控"""
    
    def __init__(self, hidden_size: int, num_channels: int):
        super().__init__()
        
        # 门控网络
        self.gate_network = nn.Sequential(
            nn.Linear(hidden_size * num_channels, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, num_channels),
            nn.Sigmoid()
        )
        
    def forward(
        self,
        channel_embeddings: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """门控融合"""
        # 拼接所有通道
        channel_names = list(channel_embeddings.keys())
        concatenated = torch.cat([
            channel_embeddings[name] 
            for name in channel_names
        ], dim=-1)
        
        # 生成门控
        gates = self.gate_network(concatenated)  # [batch, num_channels]
        
        # 加权融合
        fused = torch.zeros_like(list(channel_embeddings.values())[0])
        for i, name in enumerate(channel_names):
            fused += gates[:, i:i+1] * channel_embeddings[name]
        
        return fused
```

### 4.2 注意力融合（AttentionFusion）

```python
class AttentionFusion(nn.Module):
    """注意力融合 - 使用注意力机制融合"""
    
    def __init__(self, hidden_size: int, num_channels: int):
        super().__init__()
        
        # 注意力层
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size,
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )
        
        # 查询投影
        self.query_projection = nn.Linear(hidden_size, hidden_size)
        
    def forward(
        self,
        query_embedding: torch.Tensor,
        channel_embeddings: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """注意力融合"""
        # 查询投影
        query = self.query_projection(query_embedding).unsqueeze(1)
        
        # 构建值序列
        channel_names = list(channel_embeddings.keys())
        values = torch.stack([
            channel_embeddings[name] 
            for name in channel_names
        ]).transpose(0, 1)
        
        # 注意力融合
        fused, _ = self.attention(query, values, values)
        
        return fused.squeeze(1)
```

### 4.3 图神经网络融合（GNNFusion）

```python
class GNNFusion(nn.Module):
    """图神经网络融合 - 使用GNN捕获通道间关系"""
    
    def __init__(self, hidden_size: int, num_channels: int):
        super().__init__()
        
        # 图卷积层
        self.conv1 = GraphConv(hidden_size, hidden_size)
        self.conv2 = GraphConv(hidden_size, hidden_size)
        
        # 邻接矩阵
        self.adjacency = self._build_adjacency(num_channels)
        
    def _build_adjacency(self, num_channels: int) -> torch.Tensor:
        """构建邻接矩阵"""
        # 全连接图
        adj = torch.ones(num_channels, num_channels)
        # 移除自环
        adj.fill_diagonal_(0)
        # 归一化
        adj = adj / adj.sum(dim=1, keepdim=True)
        
        return adj
        
    def forward(
        self,
        channel_embeddings: Dict[str, torch.Tensor]
    ) -> torch.Tensor:
        """GNN融合"""
        # 构建节点特征
        channel_names = list(channel_embeddings.keys())
        node_features = torch.stack([
            channel_embeddings[name] 
            for name in channel_names
        ]).unsqueeze(0)  # [1, num_channels, hidden]
        
        # 图卷积
        x = F.relu(self.conv1(node_features, self.adjacency))
        x = self.conv2(x, self.adjacency)
        
        # 全局池化
        fused = x.mean(dim=1)
        
        return fused
```

## 5. 与Neurova现有系统集成

### 5.1 与VolumeRenderer集成

```python
class VolumeRendererFusion(nn.Module):
    """与Neurova VolumeRenderer集成的融合网络"""
    
    def __init__(self, config: FusionConfig):
        super().__init__()
        
        # 原有的VolumeRenderer
        self.volume_renderer = VolumeRenderer()
        
        # 新的融合网络
        self.fusion_network = FusionNetwork(config)
        
        # 混合权重
        self.hybrid_weight = nn.Parameter(torch.tensor(0.7))
        
    def forward(
        self,
        query_repr: QueryRepresentation,
        channel_memories: Dict[str, List[RetrievedMemory]]
    ) -> FusionOutput:
        """混合融合"""
        # 1. VolumeRenderer融合
        volume_output = self.volume_renderer.render(
            query_repr.raw_text,
            channel_memories
        )
        
        # 2. 新融合网络
        fusion_output = self.fusion_network(query_repr, channel_memories)
        
        # 3. 混合
        weight = torch.sigmoid(self.hybrid_weight)
        hybrid_embedding = weight * fusion_output.fused_memory + (1 - weight) * volume_output
        
        return FusionOutput(
            fused_memory=hybrid_embedding,
            memory_scores=fusion_output.memory_scores,
            channel_contributions=fusion_output.channel_contributions,
            confidence=fusion_output.confidence
        )
```

### 5.2 与NeurovaRecallEngine集成

```python
class RecallEngineFusion:
    """与NeurovaRecallEngine集成的融合策略"""
    
    def __init__(self, recall_engine: NeurovaRecallEngine):
        self.recall_engine = recall_engine
        self.fusion_network = None
        
    async def retrieve_and_fuse(
        self, 
        query: str, 
        context: Dict
    ) -> FusedResult:
        """检索并融合"""
        # 1. 使用NeurovaRecallEngine检索
        recall_results = await self.recall_engine.retrieve(query, context)
        
        # 2. 按通道分组
        channel_memories = self._group_by_channel(recall_results)
        
        # 3. 使用融合网络融合
        if self.fusion_network is not None:
            # 使用新融合网络
            query_repr = self.query_encoder(query, context)
            fusion_output = self.fusion_network(query_repr, channel_memories)
        else:
            # 使用传统加权融合
            fusion_output = self._weighted_fusion(channel_memories)
        
        return fusion_output
    
    def _group_by_channel(
        self, 
        results: List[RecalledMemory]
    ) -> Dict[str, List[RetrievedMemory]]:
        """按通道分组"""
        channel_groups = {}
        for result in results:
            channel = result.channel
            if channel not in channel_groups:
                channel_groups[channel] = []
            channel_groups[channel].append(result)
        
        return channel_groups
```

## 6. 训练策略

### 6.1 损失函数

```python
class FusionLoss(nn.Module):
    """融合损失函数"""
    
    def __init__(self):
        super().__init__()
        
        # 对比损失
        self.contrastive_loss = ContrastiveLoss()
        
        # 排序损失
        self.ranking_loss = RankingLoss()
        
        # 通道一致性损失
        self.channel_consistency_loss = ChannelConsistencyLoss()
        
    def forward(
        self,
        fusion_output: FusionOutput,
        targets: FusionTargets
    ) -> Dict[str, torch.Tensor]:
        """计算融合损失"""
        losses = {}
        
        # 1. 对比损失：融合结果应该接近目标
        losses["contrastive"] = self.contrastive_loss(
            fusion_output.fused_memory,
            targets.target_memory
        )
        
        # 2. 排序损失：相关记忆分数应该更高
        losses["ranking"] = self.ranking_loss(
            fusion_output.memory_scores,
            targets.relevance_labels
        )
        
        # 3. 通道一致性损失：各通道贡献应该合理
        losses["channel_consistency"] = self.channel_consistency_loss(
            fusion_output.channel_contributions,
            targets.channel_weights
        )
        
        # 总损失
        total_loss = (
            0.5 * losses["contrastive"] +
            0.3 * losses["ranking"] +
            0.2 * losses["channel_consistency"]
        )
        
        losses["total"] = total_loss
        
        return losses
```

### 6.2 训练循环

```python
class FusionTrainer:
    """融合网络训练器"""
    
    def __init__(
        self,
        model: FusionNetwork,
        config: TrainingConfig,
        train_loader: DataLoader,
        val_loader: DataLoader
    ):
        self.model = model
        self.config = config
        self.train_loader = train_loader
        self.val_loader = val_loader
        
        self.optimizer = AdamW(
            model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay
        )
        
        self.scheduler = get_linear_schedule_with_warmup(
            self.optimizer,
            num_warmup_steps=config.warmup_steps,
            num_training_steps=config.total_steps
        )
        
        self.loss_fn = FusionLoss()
        
    def train_epoch(self, epoch: int):
        """训练一个epoch"""
        self.model.train()
        total_loss = 0
        
        for batch_idx, batch in enumerate(self.train_loader):
            # 前向传播
            output = self.model(
                batch["query_repr"],
                batch["channel_memories"]
            )
            
            # 计算损失
            losses = self.loss_fn(output, batch["targets"])
            
            # 反向传播
            losses["total"].backward()
            
            # 梯度裁剪
            torch.nn.utils.clip_grad_norm_(
                self.model.parameters(), 
                max_norm=1.0
            )
            
            # 更新参数
            self.optimizer.step()
            self.scheduler.step()
            self.optimizer.zero_grad()
            
            total_loss += losses["total"].item()
            
            if batch_idx % 100 == 0:
                print(f"Epoch {epoch}, Batch {batch_idx}, Loss: {losses['total'].item():.4f}")
        
        return total_loss / len(self.train_loader)
```

## 7. 评估指标

### 7.1 融合质量指标

```python
def compute_fusion_metrics(
    fusion_outputs: List[FusionOutput],
    ground_truth: List[FusionTargets]
) -> Dict[str, float]:
    """计算融合质量指标"""
    metrics = {}
    
    # 1. 相似度指标
    similarities = []
    for output, target in zip(fusion_outputs, ground_truth):
        sim = F.cosine_similarity(
            output.fused_memory.unsqueeze(0),
            target.target_memory.unsqueeze(0)
        ).item()
        similarities.append(sim)
    
    metrics["avg_similarity"] = np.mean(similarities)
    
    # 2. 排序指标
    ranking_scores = []
    for output, target in zip(fusion_outputs, ground_truth):
        # 计算排序质量
        scores = output.memory_scores
        labels = target.relevance_labels
        
        # 计算NDCG
        ndcg = compute_ndcg(scores, labels)
        ranking_scores.append(ndcg)
    
    metrics["avg_ndcg"] = np.mean(ranking_scores)
    
    # 3. 通道一致性指标
    channel_consistencies = []
    for output, target in zip(fusion_outputs, ground_truth):
        # 计算通道贡献与期望权重的一致性
        contributions = output.channel_contributions
        expected_weights = target.channel_weights
        
        consistency = 1 - np.mean(np.abs(
            np.array(list(contributions.values())) - 
            np.array(list(expected_weights.values()))
        ))
        channel_consistencies.append(consistency)
    
    metrics["avg_channel_consistency"] = np.mean(channel_consistencies)
    
    return metrics
```

## 8. 部署配置

### 8.1 模型导出

```python
# 导出为ONNX格式
torch.onnx.export(
    fusion_network,
    dummy_inputs,
    "fusion_network.onnx",
    opset_version=14,
    input_names=["query_embedding", "channel_embeddings"],
    output_names=["fused_memory", "memory_scores"]
)
```

### 8.2 推理优化

```python
# 使用TensorRT优化
import tensorrt as trt

# 构建TensorRT引擎
logger = trt.Logger(trt.Logger.WARNING)
builder = trt.Builder(logger)
network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
parser = trt.OnnxParser(network, logger)

# 解析ONNX模型
with open("fusion_network.onnx", "rb") as f:
    parser.parse(f.read())

# 构建引擎
config = builder.create_builder_config()
config.max_workspace_size = 1 << 30  # 1GB
engine = builder.build_engine(network, config)
```

## 9. 总结

### 9.1 关键技术点

1. **通道注意力**：学习不同通道的重要性
2. **跨通道交互**：捕获通道间的依赖关系
3. **动态融合**：根据查询自适应调整融合策略
4. **记忆评分**：预测记忆的相关性分数

### 9.2 性能优化

1. **缓存机制**：缓存融合结果
2. **异步处理**：使用异步IO
3. **批处理**：支持批量融合
4. **模型量化**：使用INT8/FP16量化

### 9.3 与现有系统集成

1. **与VolumeRenderer集成**：保持向后兼容
2. **与NeurovaRecallEngine集成**：渐进式迁移
3. **混合策略**：新旧系统并行运行

---

**下一步**：[训练策略详细设计](./memo-training-strategy.md)