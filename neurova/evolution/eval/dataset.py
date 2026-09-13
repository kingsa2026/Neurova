"""评测集 — train/val/holdout 划分。

对位 Hermes `core/dataset_builder.py` 的 EvalDataset,但切分用固定种子,
保证可复现(测试要能断言,进化结果要能重放)。
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class EvalExample:
    """单条评测用例。

    expected_behavior 是**评分细则(rubric)**,不是精确输出文本——
    judge 据此判断"agent 输出好不好",而非字符串比对。
    """

    task_input: str
    expected_behavior: str
    difficulty: str = "medium"
    category: str = "general"
    source: str = "synthetic"  # synthetic|history|golden

    def to_dict(self) -> dict:
        return {
            "task_input": self.task_input,
            "expected_behavior": self.expected_behavior,
            "difficulty": self.difficulty,
            "category": self.category,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvalExample":
        allowed = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class EvalDataset:
    """train/val/holdout 三集划分。"""

    train: list[EvalExample] = field(default_factory=list)
    val: list[EvalExample] = field(default_factory=list)
    holdout: list[EvalExample] = field(default_factory=list)

    @property
    def all_examples(self) -> list[EvalExample]:
        return self.train + self.val + self.holdout

    @classmethod
    def split(
        cls,
        examples: list[EvalExample],
        ratios: tuple[float, float, float] = (0.5, 0.25, 0.25),
        seed: int = 42,
    ) -> "EvalDataset":
        """按比例切分;固定种子可复现。保证不丢样本(小集也不丢)。"""
        items = list(examples)
        if not items:
            return cls()
        rng = random.Random(seed)
        rng.shuffle(items)
        n = len(items)
        tr, va = ratios[0], ratios[1]
        n_train = max(1, int(n * tr)) if n >= 1 else 0
        n_val = int(n * va)
        # 保证三集之和 == n:余数归 train,val 至少保留到不越界
        if n_train + n_val > n:
            n_val = max(0, n - n_train)
        train = items[:n_train]
        val = items[n_train : n_train + n_val]
        holdout = items[n_train + n_val :]
        return cls(train=train, val=val, holdout=holdout)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        for name, split in (("train", self.train), ("val", self.val), ("holdout", self.holdout)):
            with open(path / f"{name}.jsonl", "w", encoding="utf-8") as f:
                for ex in split:
                    f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> "EvalDataset":
        path = Path(path)
        ds = cls()
        for name in ("train", "val", "holdout"):
            split_file = path / f"{name}.jsonl"
            if not split_file.exists():
                continue
            examples: list[EvalExample] = []
            with open(split_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            examples.append(EvalExample.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, TypeError):
                            continue
            setattr(ds, name, examples)
        return ds


def dataset_dir_for(name: str, base: Optional[Path] = None) -> Path:
    """评测集落盘目录:data/evolution/datasets/<name>/。"""
    root = base or Path(os.environ.get("NEUROVA_EVAL_DATASETS_DIR", "data/evolution/datasets"))
    return Path(root) / name
