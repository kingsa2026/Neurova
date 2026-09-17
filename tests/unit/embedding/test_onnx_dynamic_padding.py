"""Short queries must not incur max_length ONNX work on dynamic models."""
from types import SimpleNamespace

import numpy as np
import pytest

from neurova.embedding.onnx_embedding import ONNXEmbeddingEngine


class Tokenizer:
    def __init__(self, tokens):
        self.tokens = tokens

    def encode(self, text):
        # Return stored lists too: padding must not mutate tokenizer-owned data.
        return self.tokens[text]


class Session:
    def __init__(self, width):
        self.width = width
        self.calls = []

    def get_inputs(self):
        return [SimpleNamespace(name=name, shape=["batch", self.width]) for name in
                ("input_ids", "attention_mask", "token_type_ids")]

    def run(self, _, inputs):
        self.calls.append(inputs)
        ids = inputs["input_ids"]
        if isinstance(self.width, int):
            assert ids.shape[1] == self.width
        vectors = np.ones((ids.shape[0], ids.shape[1], 3), dtype=np.float32)
        return [vectors]


def make_engine(tokens, width="seq", max_length=512):
    engine = ONNXEmbeddingEngine(max_length=max_length, auto_download=False)
    engine._initialized = True
    engine._backend_type = "onnx"
    engine._dimension = 3
    engine._tokenizer = Tokenizer(tokens)
    engine._ort_session = Session(width)
    return engine


@pytest.mark.parametrize("width", ["seq", None])
def test_dynamic_padding_uses_batch_longest_and_preserves_mask(width):
    tokens = {"short": [101, 5, 102], "long": [101, 6, 7, 8, 102]}
    engine = make_engine(tokens, width)
    result = engine.encode_batch(["short", "long"])
    inputs = engine._ort_session.calls[0]
    assert inputs["input_ids"].shape == (2, 5)
    assert inputs["input_ids"].tolist()[0] == [101, 5, 102, 0, 0]
    assert inputs["attention_mask"].tolist() == [[1, 1, 1, 0, 0], [1] * 5]
    assert not inputs["token_type_ids"].any()
    assert inputs["input_ids"].dtype == np.int64
    assert tokens["short"] == [101, 5, 102]
    assert len(result.vectors) == 2
    assert np.allclose(np.linalg.norm(result.vectors, axis=1), 1)
    assert engine.stats["total_requests"] == 2


def test_dynamic_padding_still_truncates_at_max_length():
    engine = make_engine({"long": list(range(20)), "short": [1]}, max_length=8)
    engine.encode_batch(["long", "short"])
    inputs = engine._ort_session.calls[0]
    assert inputs["input_ids"].shape == (2, 8)
    assert inputs["input_ids"][0].tolist() == list(range(8))
    assert inputs["attention_mask"][1].tolist() == [1, 0, 0, 0, 0, 0, 0, 0]


def test_fixed_sequence_model_keeps_declared_input_width():
    engine = make_engine({"short": [101, 102], "long": list(range(20))}, width=8)
    result = engine.encode_batch(["short", "long"])
    inputs = engine._ort_session.calls[0]
    assert inputs["input_ids"].shape == (2, 8)
    assert inputs["attention_mask"][0].tolist() == [1, 1, 0, 0, 0, 0, 0, 0]
    assert np.allclose(np.linalg.norm(result.vectors, axis=1), 1)


def test_dynamic_empty_token_sequence_keeps_nonzero_axis():
    engine = make_engine({"empty": []})
    engine.encode_batch(["empty"])
    inputs = engine._ort_session.calls[0]
    assert inputs["input_ids"].shape == (1, 1)
    assert not inputs["attention_mask"].any()
