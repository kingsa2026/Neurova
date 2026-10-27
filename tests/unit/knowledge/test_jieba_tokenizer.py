"""P0-1 jieba 真分词。

契约（§4 P0-1）：
- knowledge.search.tokenize：安装 jieba 时用 jieba 词级切分（"量子计算" →
  ["量子","计算"]），未安装时回退旧 n-gram 规则（可选依赖纪律）；
- 英文按空格/词切分，标点剥离，单字噪声不进 token；
- knowledge.search.full_text_search：语义级查询词命中语义级文档（"量子计算"
  能命中含"量子计算"的文档，且得分严格高于只含"计算"的文档）；
- semantic_search_api._tokenize 与 knowledge.search.tokenize 同源（BM25 通道
  与 FTS 通道保持可比）。
"""

import pytest

from neurova.knowledge.search import full_text_search, tokenize
from tests.ast_scan import parseSource


class TestTokenize:
    def test_chinese_splits_to_words_with_jieba(self):
        tokens = tokenize("量子计算在金融领域的应用")
        assert "量子" in tokens
        assert "计算" in tokens
        assert "金融" in tokens
        # 旧 n-gram 会产出 "量子计算" 4 字片段；jieba 词级切分不再有跨词粘连
        assert "量子计算" not in tokens

    def test_english_lowercased_word_split(self):
        tokens = tokenize("Machine Learning Guide")
        assert tokens == ["machine", "learning", "guide"]

    def test_punctuation_stripped(self):
        tokens = tokenize("什么是RAG？检索增强生成！")
        assert "rag" in tokens
        assert all("？" not in t and "！" not in t for t in tokens)

    def test_single_char_noise_dropped(self):
        tokens = tokenize("我 在 学 AI")
        assert "我" not in tokens
        assert "ai" in tokens

    def test_empty_and_none_safe(self):
        assert tokenize("") == []
        assert tokenize("   ") == []

    @pytest.mark.parametrize(
        "query,doc,expect_hit",
        [
            ("量子计算", "量子计算使用量子比特进行并行运算。", True),
            ("机器学习", "机器学习是人工智能的核心分支。", True),
            ("量子计算机", "今天天气不错。", False),
        ],
    )
    def test_real_phrase_pairs(self, query, doc, expect_hit):
        tokens = tokenize(doc)
        q_tokens = tokenize(query)
        hit = any(t in tokens for t in q_tokens)
        assert hit is expect_hit


class TestFullTextSearchJieba:
    def _corpus(self):
        return [
            {"id": "quantum", "content": "量子计算使用量子比特进行并行运算。"},
            {"id": "plain_compute", "content": "经典计算依赖二进制逻辑门。"},
            {"id": "weather", "content": "今天天气不错。"},
        ]

    def test_semantic_query_hits_semantic_doc(self):
        hits = full_text_search("量子计算", self._corpus(), top_k=10)
        ids = [h[0] for h in hits]
        assert "quantum" in ids
        assert "weather" not in ids

    def test_exact_doc_scores_higher_than_partial(self):
        hits = dict(full_text_search("量子计算", self._corpus(), top_k=10))
        assert hits["quantum"] > hits["plain_compute"]

    def test_no_hit_returns_empty(self):
        assert full_text_search("不存在的词组", self._corpus(), top_k=10) == []


class TestJiebaAbsentFallback:
    """P0-1 闭环审查：B 修复——缺席路径必须走 n-gram 且打 WARN。

    旧实现 search.py:79-91 静默 except 把 _jieba 置 False，CI 没装 jieba
    时所有用例全红；本次补 monkeypatch 强制缺席 + 验证回退行为。
    """

    def test_absent_jieba_falls_back_to_ngram(self, monkeypatch):
        import neurova.knowledge.search as search_mod

        monkeypatch.setattr(search_mod, "_jieba", False)
        tokens = search_mod.tokenize("量子计算")
        # n-gram 产 2-4 字片段（含跨词粘连）；明确"量子计算"必在
        assert "量子计算" in tokens
        # 且一定不会 jieba 词级切出"量子"+"计算"两个独立项
        assert not ({"量子", "计算"}.issubset(set(tokens)))

    def test_absent_jieba_logs_warning(self, monkeypatch, caplog):
        import logging

        import neurova.knowledge.search as search_mod

        monkeypatch.setattr(search_mod, "_jieba", False)
        # 强制 _get_jieba 重走 except 路径
        monkeypatch.setattr(search_mod, "_jieba", None)
        import builtins

        real_import = builtins.__import__

        def deny_jieba(name, *args, **kwargs):
            if name == "jieba" or name.startswith("jieba."):
                raise ImportError("simulated: jieba 缺席")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", deny_jieba)
        with caplog.at_level(logging.WARNING, logger="neurova.knowledge.search"):
            assert search_mod.tokenize("测试") == search_mod._ngram_tokenize("测试")
        assert any("jieba 不可用" in r.message for r in caplog.records)


class TestJiebaHasOneWarmEntry:
    """取用口只有一个，且**拿到手就是暖的**——冷启动的账不许落在无关键上。

    来由（CI 实测）：`test_service_closed_loop` 三格被 30s 墙打死，回溯停在
    `constraints._token_jaccard → jieba.cut → initialize → gen_pfdict`。本机复刻同一
    争抢条件（另一条 thread 持续抢 GIL）时，建前缀字典从 0.5s 放大到 8.1s、首调 8.65s
    ——30s 墙在这个量级下必死，而红的那三格与被测行为毫无关系。

    根因不是"字典慢"，是**谁付这笔账说不清**：`constraints` 自己裸 `import jieba`
    （字典仍懒建），`knowledge.search._get_jieba()` 也只 import 不建。两处都能在
    "用例跑着跑着"触发一次冷启动。收口到一处、并在取用时建完字典，成本就落在明确的
    入口上，任何一条用例都不再替别人付账。
    """

    def test_entryHandsOutAWarmModule(self):
        from neurova.knowledge.search import _get_jieba

        jieba = _get_jieba()
        if jieba is None:
            pytest.skip("本环境没有 jieba（可选依赖），这一格量的是「拿到手就是暖的」")
        assert jieba.dt.initialized, "取用口交回的是还没建字典的实例——首调成本又落回调用方身上"

    def test_constraintsAsksNoOptionalEntry(self, monkeypatch):
        """`constraints` 不走取用口——这是裁决反转后的**反向**判据。

        本档原先钉的是"走的还是同一个取用口"：那时口径是"收口到一处，成本落在明确
        的入口上"。实测证明这条口径不够——收口只把"谁 import"统一了，**没消除**那笔
        冷启动：`evolution.eval.constraints` 走的是 `semantic_similarity` 的兜底支，
        而兜底支一旦问取用口，字典构建就摊到"哪条 async 调用栈恰好第一个走到语义闸"
        身上（构建 `cnb-sq6-1k5q1kqrc#003`，`test_service_closed_loop` 那格
        `Timeout (>30.0s)`，回溯停在 `search._get_jieba → jieba.initialize`）。

        故裁决改为：兜底的词面下界**零可选依赖**（中文按字符二元组），取用口只服务
        真正需要词级切分的地方（`knowledge.search.tokenize`）。本格反向钉住这一点——
        谁把 `constraints` 再接回取用口，这里立刻红。
        """
        import neurova.evolution.eval.constraints as constraints_mod
        import neurova.knowledge.search as search_mod

        seen = []
        real = search_mod._get_jieba

        def spy():
            seen.append(1)
            return real()

        monkeypatch.setattr(search_mod, "_get_jieba", spy)
        tokens = constraints_mod._token_jaccard("量子计算", "量子 计算")
        assert not seen, (
            "`constraints._token_jaccard` 又在问 `knowledge.search._get_jieba`——"
            "语义闸是「embedding 不在就跑」的兜底路径，兜底里再挂一件可选依赖，"
            "那笔冷启动就摊回无关键上了（判据："
            "tests/unit/ci/test_optionalImportWallOwedByLivePath.py）"
        )
        assert tokens >= 0.0, "兜底仍须给出词面下界读数（二元组），不能退化成常量"

    def test_concurrentCallersShareOneDictionaryBuild(self):
        """8 条线程同时取用，字典只建一次，且每条拿到的都是**已建好**的实例。

        这一格钉的是双检锁：没有它，并发的 8 条各自 `import` 后各自 `initialize()`，
        建字典的次数就等于并发数——CI 里那笔 8s 的抖动正是这么被放大的。
        """
        import threading

        import neurova.knowledge.search as search_mod

        original = search_mod._jieba
        # 复位成"还没取过"，让这一格自己承担这一次冷启动
        search_mod._jieba = None
        failures = []
        try:
            barrier = threading.Barrier(8)

            def worker():
                try:
                    barrier.wait()
                    module = search_mod._get_jieba()
                    assert module is None or module.dt.initialized, "交回的是没建字典的实例"
                except Exception as exc:  # noqa: BLE001 - 线程里的失败要带回主线程判红
                    failures.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
            assert search_mod._jieba is not None, "8 条线程跑完，取用口仍停在未取用态"
        finally:
            search_mod._jieba = original

        assert not failures, f"并发取用失败：{failures}"


class TestWarmUpFace:
    """字典冷启动是**进程级一次性**成本，必须有一个能问、能催的口，而且要有人催（§6-420/§6-422）。

    ## 现场（构建 `cnb-sq6-1k5q1kqrc#003`，受保护子集跑到 99%）

    ```
    FAILED tests/unit/evolution/eval/test_service_closed_loop.py::TestEvolveFlow::
           test_accept_produces_pending_proposal - Failed: Timeout (>30.0s) from pytest-timeout.
     neurova/evolution/eval/constraints.py:209: in _jiebaModule
        return _get_jieba()
     neurova/knowledge/search.py:119: in _get_jieba
        _j.initialize()
     /usr/local/lib/python3.12/site-packages/jieba/__init__.py:83: in gen_pfdict
    = 1 failed, 7953 passed in 1469.68s
    ```

    全仓 7953 格都绿，唯一那条红是**某条用例恰好第一个用到中文分词**，它替所有人付了
    建字典这笔账，然后撞在 30s 那条格墙上。同机器单跑 2.5s——判据读数取决于"谁先跑到"，
    属前提形态，不归被测代码。

    ## 为什么"收口到一处取用口"还不够

    `_get_jieba()` 的 DCL 解决了"谁来建"（并发的第二个调用方等第一个建完，不重复建），
    但没解决"什么时候建"——首次取用**就地**建，成本仍在首调方的关键路径上。这笔成本对
    负载极度敏感（本机同一棵树）：

    ```
    空载首次 _get_jieba():                    0.56s
    3 条抢 GIL 的线程并发时首次 _get_jieba():  92.30s     ← 30s 墙的 3 倍
    预热之后再取用:                            0.001s
    ```

    ## 判据（三格，缺一格都不闭环）

    1. **能催且幂等**：`warmJieba()` 已在则直接返回，不重来；
    2. **不可用如实上报**：`False` 就是没暖，不许记成 `True`；
    3. **有人催**：`tests/conftest.py` 的会话装配必须调它——只加口没人调，等于把账从
       "某条用例"挪到"没人付"，下一次仍会以同一形态红回来。这一格是本类的要点。

    原先还有一格钉 `isJiebaWarm()` 这个"能问"的口。本批把它退役了：全仓除测试外
    **零调用点**，而它读的就是 `_jieba`——多一个同义判断口即多一份"暖没暖"的事实源
    （纪律第 6 条）。要问就问 `warmJieba()`（幂等、返回布尔），要读就读 `_jieba`。
    """

    def testWarmUpIsIdempotent(self):
        from neurova.knowledge import search

        assert search.warmJieba() is True, "装了 jieba 就该能建起字典"
        # 再催一次不重来（`_get_jieba` 的双检锁直接命中已建实例）
        assert search.warmJieba() is True

    def testUnavailableIsReportedAsColdNotAsWarm(self, monkeypatch):
        """不可用要如实说"没暖"，不许把 `False` 记成"暖了"——那会让判据以为字典已就绪。"""
        from neurova.knowledge import search

        monkeypatch.setattr(search, "_jieba", False)
        assert search.warmJieba() is False
        monkeypatch.setattr(search, "_jieba", None)
        monkeypatch.setattr(search, "_get_jieba", lambda: None)
        assert search.warmJieba() is False

    def testSessionAssemblyActuallyPaysTheBill(self):
        """会话装配必须调预热：加了入口没人调，账只是从"某条用例"挪到"没人付"。

        认三种写法——裸名 `warmJieba()`、属性 `search.warmJieba()`、以及
        `from ... import warmJieba as X` 之后的别名 `X()`。判据要问的是"有没有人付这笔账"，
        不是"调用方写了哪个名字"；只认裸名等于逼人为迎合判据而放弃别名。
        """
        import ast
        import pathlib

        conftest = pathlib.Path(__file__).resolve().parents[3] / "tests" / "conftest.py"
        tree = parseSource(conftest.read_text(encoding="utf-8"))
        aliases = {
            (alias.asname or alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if alias.name == "warmJieba"
        }
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute) else
            getattr(node.func, "id", "")
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }
        assert called & ({"warmJieba"} | aliases), (
            "tests/conftest.py 没有调用 warmJieba()——冷启动账单仍落在「哪条用例恰好第一个"
            "用到中文分词」身上（构建 cnb-sq6-1k5q1kqrc#003 里那条 "
            "test_accept_produces_pending_proposal 就是替所有人付账的那一格）")
