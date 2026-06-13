"""
记忆场神经网络 (NeRF-inspired MemoryField)

将记忆表示为连续隐式函数：语义位置 → (内容向量, 重要性)
支持连续语义空间查询、记忆插值、增量学习。

理论来源：
- NeRF (Mildenhall et al., 2020)
- Instant-NGP (Müller et al., 2022)
"""

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


# ────── 配置 ──────


@dataclass
class MemoryFieldConfig:
    """记忆场配置"""

    semantic_dim: int = 384  # 语义向量维度
    hidden_dim: int = 256  # 隐藏层维度
    num_layers: int = 4  # MLP 层数
    use_positional_encoding: bool = True
    num_frequencies: int = 6  # 位置编码频率数

    # 训练
    learning_rate: float = 1e-4
    batch_size: int = 32
    num_epochs: int = 100

    # 增量学习
    buffer_size: int = 1000
    incremental_steps: int = 10
    incremental_lr: float = 1e-5


# ────── PyTorch 位置编码层 ──────


class PositionalEncodingLayer(nn.Module):
    """位置编码层 (PyTorch 版本)"""

    def __init__(self, num_frequencies: int = 6):
        super().__init__()
        self.num_frequencies = num_frequencies
        self.register_buffer("frequencies", 2.0 ** torch.arange(num_frequencies).float())

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: (..., D) → (..., D * L * 2 + D)
        """
        angles = x.unsqueeze(-1) * self.frequencies * np.pi
        sin_vals = torch.sin(angles)
        cos_vals = torch.cos(angles)
        encoded = torch.stack([sin_vals, cos_vals], dim=-1)
        encoded = encoded.reshape(*x.shape[:-1], -1)
        return torch.cat([x, encoded], dim=-1)


# ────── 记忆场网络 ──────


class MemoryFieldNetwork(nn.Module):
    """
    记忆场神经网络

    结构: 语义向量 → 位置编码 → MLP → (内容向量, 重要性)

    用途:
        network = MemoryFieldNetwork()
        content, importance = network(semantic_vector)
    """

    def __init__(self, config: Optional[MemoryFieldConfig] = None):
        super().__init__()
        self.config = config or MemoryFieldConfig()

        # 位置编码
        if self.config.use_positional_encoding:
            self.pos_encoding = PositionalEncodingLayer(self.config.num_frequencies)
            encoded_dim = self.config.semantic_dim * self.config.num_frequencies * 2 + self.config.semantic_dim
        else:
            self.pos_encoding = nn.Identity()
            encoded_dim = self.config.semantic_dim

        # MLP
        layers = []
        in_dim = encoded_dim
        for _ in range(self.config.num_layers - 1):
            layers.extend(
                [
                    nn.Linear(in_dim, self.config.hidden_dim),
                    nn.GELU(),
                    nn.LayerNorm(self.config.hidden_dim),
                ]
            )
            in_dim = self.config.hidden_dim
        layers.append(nn.Linear(in_dim, self.config.semantic_dim + 1))
        self.mlp = nn.Sequential(*layers)

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, semantic_pos: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            semantic_pos: (B, semantic_dim)
        Returns:
            content: (B, semantic_dim)
            importance: (B, 1)
        """
        encoded = self.pos_encoding(semantic_pos)
        output = self.mlp(encoded)
        content = output[:, :-1]
        importance = torch.sigmoid(output[:, -1:])
        return content, importance


# ────── 记忆场训练器 ──────


class MemoryFieldTrainer:
    """
    记忆场训练器

    支持全量训练和增量训练。
    使用经验回放防止灾难性遗忘。

    用法:
        trainer = MemoryFieldTrainer()
        trainer.train_full(memories)       # 全量训练
        trainer.train_incremental(new_mem) # 增量更新
        content, imp = trainer.query(vec)  # 查询
    """

    def __init__(self, config: Optional[MemoryFieldConfig] = None):
        self.config = config or MemoryFieldConfig()
        self.network = MemoryFieldNetwork(self.config)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=self.config.learning_rate)
        self.criterion = nn.MSELoss()
        self.replay_buffer: List[Tuple[np.ndarray, float]] = []
        self._lock = threading.RLock()
        self._trained = False

    @property
    def is_trained(self) -> bool:
        return self._trained

    def train_full(self, memories: List[Dict]) -> Dict[str, float]:
        """
        全量训练

        Args:
            memories: [{'embedding': np.ndarray, 'importance': float}, ...]
        """
        with self._lock:
            embeddings = [m["embedding"] for m in memories if "embedding" in m]
            if not embeddings:
                return {"loss": 0.0, "num_samples": 0}

            tensor = torch.FloatTensor(np.array(embeddings))
            self.network.train()

            total_loss = 0.0
            steps = 0
            for _ in range(self.config.num_epochs):
                indices = torch.randperm(len(tensor))
                for i in range(0, len(indices), self.config.batch_size):
                    batch = tensor[indices[i : i + self.config.batch_size]]
                    pred_content, pred_imp = self.network(batch)

                    loss = self.criterion(pred_content, batch)
                    self.optimizer.zero_grad()
                    loss.backward()
                    self.optimizer.step()
                    total_loss += loss.item()
                    steps += 1

            self._update_buffer(memories)
            self._trained = True
            return {"loss": total_loss / max(1, steps), "num_samples": len(embeddings)}

    def train_incremental(self, new_memories: List[Dict]) -> Dict[str, float]:
        """增量训练 (小学习率 + 经验回放)"""
        with self._lock:
            replay = self._sample_buffer(len(new_memories))
            all_mems = new_memories + replay
            embeddings = [m["embedding"] for m in all_mems if "embedding" in m]
            if not embeddings:
                return {"loss": 0.0, "num_samples": 0}

            tensor = torch.FloatTensor(np.array(embeddings))
            self.network.train()

            total_loss = 0.0
            # 临时降低学习率
            for pg in self.optimizer.param_groups:
                pg["lr"] = self.config.incremental_lr

            for _ in range(self.config.incremental_steps):
                idx = torch.randint(0, len(tensor), (min(self.config.batch_size, len(tensor)),))
                batch = tensor[idx]
                pred_content, _ = self.network(batch)
                loss = self.criterion(pred_content, batch)
                self.optimizer.zero_grad()
                loss.backward()
                self.optimizer.step()
                total_loss += loss.item()

            # 恢复学习率
            for pg in self.optimizer.param_groups:
                pg["lr"] = self.config.learning_rate

            self._update_buffer(new_memories)
            return {"loss": total_loss / self.config.incremental_steps, "num_samples": len(all_mems)}

    def query(self, semantic_pos: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        查询记忆场

        Args:
            semantic_pos: 语义位置向量 (semantic_dim,)
        Returns:
            (content_vector, importance)
        """
        self.network.eval()
        with torch.no_grad():
            t = torch.FloatTensor(semantic_pos).unsqueeze(0)
            content, imp = self.network(t)
            return content.squeeze(0).numpy(), imp.item()

    def query_batch(self, positions: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """批量查询"""
        self.network.eval()
        with torch.no_grad():
            t = torch.FloatTensor(positions)
            content, imp = self.network(t)
            return content.numpy(), imp.squeeze(-1).numpy()

    def _update_buffer(self, memories: List[Dict]):
        for m in memories:
            if "embedding" in m:
                self.replay_buffer.append((m["embedding"], m.get("importance", 0.5)))
        if len(self.replay_buffer) > self.config.buffer_size:
            self.replay_buffer.sort(key=lambda x: x[1], reverse=True)
            self.replay_buffer = self.replay_buffer[: self.config.buffer_size]

    def _sample_buffer(self, k: int) -> List[Dict]:
        if not self.replay_buffer:
            return []
        k = min(k, len(self.replay_buffer))
        indices = np.random.choice(len(self.replay_buffer), k, replace=False)
        return [{"embedding": self.replay_buffer[i][0], "importance": self.replay_buffer[i][1]} for i in indices]

    def save(self, path: str):
        torch.save(
            {
                "network": self.network.state_dict(),
                "optimizer": self.optimizer.state_dict(),
                "config": self.config,
                "buffer": self.replay_buffer,
            },
            path,
        )

    def load(self, path: str):
        ckpt = torch.load(path, weights_only=False)
        self.network.load_state_dict(ckpt["network"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        self.replay_buffer = ckpt.get("buffer", [])
        self._trained = True


# ────── 单例管理 ──────

_memory_field: Optional[MemoryFieldTrainer] = None


def get_memory_field(config: Optional[MemoryFieldConfig] = None) -> MemoryFieldTrainer:
    global _memory_field
    if _memory_field is None:
        _memory_field = MemoryFieldTrainer(config)
    return _memory_field


def reset_memory_field():
    global _memory_field
    _memory_field = None
