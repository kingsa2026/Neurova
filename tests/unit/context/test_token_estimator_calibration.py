# -*- coding: utf-8 -*-
"""P0-1 尺子标定：估算是"要不要压缩"的判据，必须与真值同量级。

根因（三链路审计 P0-1）：`window_compactor.estimate_window_tokens` 与所有判据侧
一律走 `TokenEstimator(BALANCED)`，而 BALANCED 的 word-splitting 分支把英文/代码/
JSON 按"空白分词数 × 0.25"计价，`other_char_ratio` 在该分支不参与。

实测（本文件红灯即证）：
- `estimate_tokens("x" * 9000) == 1`，o200k 真值 1125 → 低估 1125 倍；
- 12 段英文散文 + 12 段 JSON + 一个 9000 字符无空格块：估算 509 / 真值 4897，
  在 45480 预算下判"未超预算" → 折叠消息数 0，9000 字符块原样进视图。

契约（修复后必须成立）：
1. 判据侧（`estimate_tokens` / `estimate_window_tokens` 默认档）估算不得低估真值，
   三种形态（无空格长串 / 纯英文段 / 中英混排）各自"估算 ÷ o200k 真值"∈ [1.0, 2.5]；
2. tiktoken 不可用时回退档仍不得低估（只允许高估），保证"没装 tokenizer 也不会漏折叠"；
3. P11 复现：9000 字符块在 45480 预算下必须触发折叠。

反向锁（guard）：断言 BALANCED 老口径对同一批文本确实低估——证明红灯源于尺子本身，
不是测试写错。
"""

import json

import pytest


def _true_tokens(text: str) -> int:
    tiktoken = pytest.importorskip("tiktoken")
    return len(tiktoken.get_encoding("o200k_base").encode(text))


def _english_blob() -> str:
    return (
        "Context compression decides whether a model can hold a long conversation. "
        "If the estimate is wrong, folding never triggers and the prompt grows without bound. "
    ) * 6


def _json_blob() -> str:
    return json.dumps(
        {"name": "alpha", "items": [{"id": 1, "tag": "x"}, {"id": 2, "tag": "y"}],
         "nested": {"a": "b", "deep": {"z": [1, 2, 3]}}},
        ensure_ascii=False, indent=2,
    ) * 6


def _mixed_blob() -> str:
    return (
        "用户说 the context pool 需要 is a 无损归档，draw() 只做视图层 selection。"
        "请 check 一下 RELEVANCE_FLOOR = 0.65 是否合理。"
    ) * 6


class TestJudgeSideNeverUnderestimates:
    """判据侧默认档：不允许低估真值（低估 = 该压缩时不压缩）。"""

    @pytest.mark.parametrize(
        "nospace_blob",
        ["x" * 9000, "x" * 200],
        ids=["long", "short"],
    )
    def test_no_whitespace_blob_not_underestimated(self, nospace_blob):
        from neurova.context.token_estimator import estimate_tokens

        estimate = estimate_tokens(nospace_blob)
        true = _true_tokens(nospace_blob)
        assert estimate >= true, (
            f"无空格长串被低估：估算 {estimate} < o200k 真值 {true}"
            f"（{len(nospace_blob)} 字符）——折叠判据对 base64/长串形态永不触发"
        )

    def test_english_prose_not_underestimated(self):
        from neurova.context.token_estimator import estimate_tokens

        blob = _english_blob()
        estimate, true = estimate_tokens(blob), _true_tokens(blob)
        assert estimate >= true, f"英文散文被低估：估算 {estimate} < 真值 {true}"

    def test_json_blob_not_underestimated(self):
        from neurova.context.token_estimator import estimate_tokens

        blob = _json_blob()
        estimate, true = estimate_tokens(blob), _true_tokens(blob)
        assert estimate >= true, f"JSON 被低估：估算 {estimate} < 真值 {true}"

    def test_mixed_blob_not_underestimated(self):
        from neurova.context.token_estimator import estimate_tokens

        blob = _mixed_blob()
        estimate, true = estimate_tokens(blob), _true_tokens(blob)
        assert estimate >= true, f"中英混排被低估：估算 {estimate} < 真值 {true}"

    def test_ratio_bound_in_all_three_shapes(self):
        """估算/真值 ∈ [1.0, 2.5]：既不许低估，也不许离谱高估（否则折叠过度）。"""
        from neurova.context.token_estimator import estimate_tokens

        for label, blob in (
            ("无空格长串", "x" * 9000),
            ("英文散文", _english_blob()),
            ("中英混排", _mixed_blob()),
        ):
            estimate = estimate_tokens(blob)
            true = _true_tokens(blob)
            ratio = estimate / true
            assert 1.0 <= ratio <= 2.5, (
                f"{label} 估算/真值={ratio:.2f} 越界（估算 {estimate} / 真值 {true}）"
            )


class TestFallbackRulerNeverUnderestimates:
    """tiktoken 缺席时的回退档：装不上 tokenizer 也不许漏折叠。"""

    @pytest.fixture
    def estimator_without_tiktoken(self, monkeypatch):
        import builtins

        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator

        real_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "tiktoken" or name.startswith("tiktoken."):
                raise ImportError("tiktoken blocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked_import)
        estimator = TokenEstimator(EstimationStrategy.EXACT)
        estimator._tiktoken_encoder = None
        estimator._tiktoken_failed = False
        return estimator

    @pytest.mark.parametrize(
        "blob",
        ["x" * 9000, _english_blob(), _json_blob(), _mixed_blob()],
        ids=["nospace", "english", "json", "mixed"],
    )
    def test_fallback_never_underestimates(self, estimator_without_tiktoken, blob):
        estimate = estimator_without_tiktoken.estimate(blob)
        assert estimator_without_tiktoken._tiktoken_failed is True, "回退分支未被触发"
        true = _true_tokens(blob)
        assert estimate >= true, (
            f"回退档低估：估算 {estimate} < 真值 {true}——无 tokenizer 环境会漏掉折叠"
        )


class TestWindowFoldMath:
    """P11 复现：9000 字符块必须在预算内触发折叠，而不是原样进视图。"""

    def _three_round_history(self):
        msgs = []
        for i in range(12):
            msgs.append({"role": "user", "content": f"English paragraph {i}: " + _english_blob()[:160]})
        for i in range(12):
            msgs.append({"role": "assistant", "content": _json_blob()[:180]})
        msgs.append({"role": "user", "content": "x" * 9000})
        return msgs

    def test_window_estimate_matches_magnitude(self):
        from neurova.context.window_compactor import estimate_window_tokens

        msgs = self._three_round_history()
        estimate = estimate_window_tokens(msgs)
        true = sum(_true_tokens(m["content"]) + 4 for m in msgs)
        assert estimate >= true, f"窗口估算 {estimate} 低估真值 {true}"

    @pytest.mark.asyncio
    async def test_oversized_block_triggers_folding(self):
        """真值超预算就必须折叠——老尺子对同一批输入判"未超预算"，折叠数 0。"""
        from neurova.context.window_compactor import compact_window, estimate_window_tokens

        msgs = self._three_round_history()
        true_tokens = sum(_true_tokens(m["content"]) + 4 for m in msgs)
        budget = true_tokens - 200  # 真值之下：任何诚实的尺子都必须判超预算
        assert estimate_window_tokens(msgs) > budget, (
            f"估算 {estimate_window_tokens(msgs)} 未超预算 {budget}（真值 {true_tokens}）"
            "——低估使折叠对英文/JSON/长串形态永不触发"
        )

        async def _summarize(dropped, previous_summary=""):
            return "早期对话摘要"

        compaction = await compact_window(msgs, budget, summarize=_summarize)
        assert compaction is not None, "真值已超预算却未折叠（尺子低估的直接后果）"
        assert compaction.compacted_count > 0
        assert compaction.tokens_after < compaction.tokens_before, "折叠后 token 未下降"


class TestSingleRulerSource:
    """单一事实源：不再保留会低估的第二口径（LEGACY_* / CONSERVATIVE 等），
    且全仓不得再出现就地近似（`len//4` / `len*1.5` / `len/1.5`）作为 token 判据。"""

    def test_no_underestimating_strategies_remain(self):
        from neurova.context.token_estimator import EstimationStrategy

        names = {s.name for s in EstimationStrategy}
        assert names == {"EXACT", "BALANCED"}, f"存在第二份估算口径残留：{sorted(names)}"

    def test_no_inline_approximation_in_context_chain(self):
        """判据链路上不允许再出现就地近似——它是第二把尺子的温床。"""
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[3] / "neurova"
        # 只允许出现在被显式标注为"非 token 用途"的位置；此处按文件排除白名单外的全扫
        suspicious = re.compile(
            r"len\([^()]*\)\s*(?://|/)\s*4(?!\d)|len\([^()]*\)\s*\*\s*1\.5|len\([^()]*\)\s*/\s*1\.5"
        )
        allowlist = {
            "llm/multi_model_client.py",  # mock 流式切块步长，与 token 判据无关
        }
        offenders = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel in allowlist:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "token" not in stripped.lower():
                    continue
                if suspicious.search(stripped):
                    offenders.append(f"{rel}:{lineno}: {stripped}")
        assert not offenders, (
            "token 判据链路上出现就地近似（会低估 5~20 倍，等于第二把尺子）：\n"
            + "\n".join(offenders)
        )

    def test_balanced_is_upper_bound_fallback(self):
        """BALANCED 只作无 tokenizer 回退，且对任何形态都不得低估。"""
        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator

        balanced = TokenEstimator(EstimationStrategy.BALANCED)
        for label, blob in (
            ("无空格长串", "x" * 9000),
            ("英文散文", _english_blob()),
            ("JSON", _json_blob()),
            ("中英混排", _mixed_blob()),
        ):
            estimate, true = balanced.estimate(blob), _true_tokens(blob)
            assert estimate >= true, f"{label}：BALANCED 回退档低估 {estimate} < {true}"
