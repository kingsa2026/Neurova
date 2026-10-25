"""评测集 — train/val/holdout 划分。

保证可复现(测试要能断言,进化结果要能重放)。
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from neurova.core.data_root import callerPath


@dataclass
class EvalExample:
    """单条评测用例。

    expected_behavior 是**评分细则(rubric)**,不是精确输出文本——
    judge 据此判断"agent 输出好不好",而非字符串比对。
    """

    task_input: str
    expected_behavior: str
    source: str = "synthetic"  # synthetic|history|golden

    def to_dict(self) -> dict:
        return {
            "task_input": self.task_input,
            "expected_behavior": self.expected_behavior,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EvalExample":
        allowed = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in allowed})


@dataclass
class EvalDataset:
    """train/val/holdout 三集划分 + heldout 真留出报告集。

    holdout 是接受判据的组成部分（会被搜索过程反复比较）；
    heldout 只做最终验收证据，永不参与判定——防自适应污染。
    """

    train: list[EvalExample] = field(default_factory=list)
    val: list[EvalExample] = field(default_factory=list)
    holdout: list[EvalExample] = field(default_factory=list)
    heldout: list[EvalExample] = field(default_factory=list)
    #: 取语料链上"哪几级没成、成因是什么"（`[{"source": "synthetic", "reason": "..."}]`）。
    #: 三级回退里被跳过的那几级**不静默**：把它们记在产物上，请求回执与运行读数
    #: 才能把"确实没有语料"与"取语料的哪一级炸了"分开——两者此前都收敛成一句
    #: `empty_dataset`，于是"合成器请求失败"被读成"这个技能没有评测用例"。
    #: 只在内存里传递，**不落盘**（分集落盘格式是既有的三/四键 jsonl 契约）。
    sourceIssues: list[dict] = field(default_factory=list)
    requestedSource: str = ""

    @property
    def all_examples(self) -> list[EvalExample]:
        return self.train + self.val + self.holdout + self.heldout

    def carve_heldout(self, heldout_ratio: float) -> "EvalDataset":
        """从 holdout 尾部按比例划出真留出报告集（确定性，不改原对象）。

        heldout_ratio<=0 或 holdout 不足 2 条时原样返回（保证 holdout
        至少保留 1 条继续充当判据）。
        """
        if heldout_ratio <= 0 or len(self.holdout) < 2:
            return self
        n_held = max(1, int(len(self.holdout) * heldout_ratio))
        n_held = min(n_held, len(self.holdout) - 1)
        carved = EvalDataset(
            train=list(self.train), val=list(self.val),
            holdout=list(self.holdout[:-n_held]),
            heldout=list(self.holdout[-n_held:]),
        )
        # 取语料链的失败记名必须跟着切分走（见 `withSourceIssues` 的说明）
        return withSourceIssues(carved, self.sourceIssues,
                                requested=self.requestedSource)

    @classmethod
    def split(
        cls,
        examples: list[EvalExample],
        ratios: tuple[float, float, float] = (0.5, 0.25, 0.25),
        seed: int = 42,
        heldout_ratio: float = 0.0,
    ) -> "EvalDataset":
        """按比例切分;固定种子可复现。保证不丢样本(小集也不丢)。

        heldout_ratio>0 时从 val+holdout 之外的剩余尾（holdout 末尾）按
        比例划出真留出报告集；默认 0 = 与旧三集切分逐元素一致。
        """
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
        ds = cls(train=train, val=val, holdout=holdout)
        if heldout_ratio > 0:
            ds = ds.carve_heldout(heldout_ratio)
        return ds

    def save(self, path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        for name, split in (("train", self.train), ("val", self.val),
                            ("holdout", self.holdout), ("heldout", self.heldout)):
            if name == "heldout" and not split:
                continue  # 空 heldout 不落盘：旧三键目录字节兼容
            with open(path / f"{name}.jsonl", "w", encoding="utf-8") as f:
                for ex in split:
                    f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> "EvalDataset":
        path = Path(path)
        ds = cls()
        for name in ("train", "val", "holdout", "heldout"):
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


def withSourceIssues(dataset: "EvalDataset", issues: list[dict],
                     *, requested: str = "") -> "EvalDataset":
    """把取语料链的失败记名挂到数据集上（**不改集合内容**，只补两格读数）。

    `carve_heldout` 这类会重造对象的方法也走这一处，否则切完留出集就把它丢了——
    丢了之后调用方看到的是"语料为空"，而真相是"合成那一级请求失败了"。

    传 `None` 时原样回 `None`（记名无处可挂）；生产侧的调用方一律先备一个空集合，
    让"三级全空且有级抛过"这条读数有地方落（`SkillEvolutionService._build_dataset_inner`）。
    """
    if dataset is None:
        return None
    dataset.sourceIssues = list(issues or [])
    dataset.requestedSource = str(requested or "")
    return dataset


def evaluation_split(dataset: "EvalDataset") -> list[EvalExample]:
    """接受判据用的评测集选取（单一事实源）：holdout 优先，依次回退 val/train。

    runner 的留出终审与 service 的噪声校准都必须经此函数取集，
    保证两处口径永远一致。
    """
    return dataset.holdout or dataset.val or dataset.train


def dataset_dir_for(name: str, base: Optional[Path] = None) -> Path:
    """评测集落盘目录:data/evolution/datasets/<name>/。"""
    root = callerPath(base or os.environ.get("NEUROVA_EVAL_DATASETS_DIR"), "evolution/datasets")
    return Path(root) / name
