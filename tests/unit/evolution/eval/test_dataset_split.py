"""Wave 1 — EvalDataset train/val/holdout 切分测试。

核心纪律:固定种子切分必须可复现(测试要能断言);边界(空集/单条)不崩。
"""

import json

import pytest

from neurova.evolution.eval.dataset import EvalDataset, EvalExample


def _mk(n, source="synthetic"):
    return [EvalExample(task_input=f"task {i}", expected_behavior=f"rubric {i}", source=source) for i in range(n)]


class TestSplit:
    def test_split_ratios(self):
        ds = EvalDataset.split(_mk(20), seed=42)
        assert len(ds.train) == 10
        assert len(ds.val) == 5
        assert len(ds.holdout) == 5

    def test_split_is_reproducible(self):
        a = EvalDataset.split(_mk(20), seed=42)
        b = EvalDataset.split(_mk(20), seed=42)
        assert [e.task_input for e in a.train] == [e.task_input for e in b.train]
        assert [e.task_input for e in a.holdout] == [e.task_input for e in b.holdout]

    def test_different_seed_differs(self):
        a = EvalDataset.split(_mk(50), seed=1)
        b = EvalDataset.split(_mk(50), seed=2)
        assert [e.task_input for e in a.train] != [e.task_input for e in b.train]

    def test_split_covers_all_without_overlap(self):
        ds = EvalDataset.split(_mk(20), seed=42)
        seen = [e.task_input for e in ds.all_examples]
        assert len(seen) == 20
        assert len(set(seen)) == 20

    def test_empty_input(self):
        ds = EvalDataset.split([], seed=42)
        assert ds.train == [] and ds.val == [] and ds.holdout == []

    def test_single_example_goes_to_train(self):
        ds = EvalDataset.split(_mk(1), seed=42)
        assert len(ds.all_examples) == 1

    def test_small_set_no_loss(self):
        ds = EvalDataset.split(_mk(3), seed=42)
        assert len(ds.all_examples) == 3


class TestPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        ds = EvalDataset.split(_mk(20), seed=42)
        ds.save(tmp_path)
        assert (tmp_path / "train.jsonl").exists()
        assert (tmp_path / "val.jsonl").exists()
        assert (tmp_path / "holdout.jsonl").exists()
        loaded = EvalDataset.load(tmp_path)
        assert len(loaded.all_examples) == 20
        assert loaded.train[0].task_input == ds.train[0].task_input

    def test_load_missing_dir_returns_empty(self, tmp_path):
        loaded = EvalDataset.load(tmp_path / "nope")
        assert loaded.all_examples == []

    def test_example_roundtrip(self):
        e = EvalExample(task_input="t", expected_behavior="e", difficulty="hard", category="cat")
        d = e.to_dict()
        assert EvalExample.from_dict(d) == e

    def test_from_dict_ignores_unknown_keys(self):
        e = EvalExample.from_dict({"task_input": "t", "expected_behavior": "e", "bogus": 1})
        assert e.task_input == "t"

    def test_saved_jsonl_is_valid_json(self, tmp_path):
        EvalDataset.split(_mk(5), seed=1).save(tmp_path)
        line = (tmp_path / "train.jsonl").read_text(encoding="utf-8").splitlines()[0]
        assert json.loads(line)["task_input"]
