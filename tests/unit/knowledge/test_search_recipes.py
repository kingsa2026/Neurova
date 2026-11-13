# -*- coding: utf-8 -*-
"""C3（graphiti 对照批）：检索配方化。

配方 = 命名的检索参数组合（图路权重/精排方法/候选池/recency），把散在
env 读取点上的可调面收敛成可命名、可测试、可设置项化的资产。优先级：
env 显式设置 > 设置文件（active_recipe）> default 配方（=现网行为逐位不变）。
"""

import pytest

from neurova.knowledge import search_recipes


@pytest.fixture(autouse=True)
def _cleanEnv(monkeypatch, tmp_path):
    """隔离 env 与设置文件：每个用例从无 env、无文件的白纸起跑。"""
    for key in ("NEUROVA_RETRIEVAL_RECIPE", "NEUROVA_KB_GRAPH_ROUTE",
                "NEUROVA_KB_GRAPH_ROUTE_WEIGHT", "NEUROVA_RECENCY_WEIGHT",
                "NEUROVA_RECENCY_HALF_LIFE_DAYS", "NEUROVA_KB_MAIN_RERANK",
                "NEUROVA_KB_MAIN_RERANK_METHOD", "NEUROVA_KB_MAIN_RERANK_POOL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("neurova.security.retrieval_recipe_settings.settings_path",
                        lambda: tmp_path / "retrieval_recipe_settings.json")
    yield


class TestRecipeTable:
    def test_fourNamedRecipes(self):
        assert search_recipes.RECIPE_NAMES == (
            "default", "balanced", "precise", "graph_expanded")

    def test_defaultMatchesCurrentBehavior(self):
        """default 配方＝改造前 env 缺省逐位一致（行为不变锚点）。"""
        r = search_recipes.recipeByName("default")
        assert (r.graphRouteWeight, r.rerankMethod, r.rerankPoolFactor,
                r.recencyWeight, r.recencyHalfLifeDays) == (0.10, "weight", 3, 0.0, 30.0)

    def test_resolveDefaultsToDefaultRecipe(self):
        assert search_recipes.resolveRecipe().name == "default"

    def test_recipeByNameRejectsUnknown(self):
        with pytest.raises(ValueError):
            search_recipes.recipeByName("nope")


class TestResolveRecipe:
    def test_fileValueWinsOverDefault(self):
        search_recipes.saveActiveRecipe("graph_expanded")
        assert search_recipes.resolveRecipe().name == "graph_expanded"

    def test_envWinsOverFile(self, monkeypatch):
        search_recipes.saveActiveRecipe("precise")
        monkeypatch.setenv("NEUROVA_RETRIEVAL_RECIPE", "graph_expanded")
        assert search_recipes.resolveRecipe().name == "graph_expanded"

    def test_unknownFileValueFallsBackToDefault(self, tmp_path):
        p = tmp_path / "retrieval_recipe_settings.json"
        p.write_text('{"active_recipe": "bogus"}', encoding="utf-8")
        assert search_recipes.resolveRecipe().name == "default"

    def test_saveActiveRecipeRejectsUnknown(self):
        with pytest.raises(ValueError):
            search_recipes.saveActiveRecipe("bogus")


class TestResolveGraphRouteWeight:
    def test_recipeValueWithoutEnv(self):
        search_recipes.saveActiveRecipe("graph_expanded")
        assert search_recipes.resolveGraphRouteWeight() == 0.30

    def test_envStillWins(self, monkeypatch):
        search_recipes.saveActiveRecipe("graph_expanded")
        monkeypatch.setenv("NEUROVA_KB_GRAPH_ROUTE_WEIGHT", "0.42")
        assert search_recipes.resolveGraphRouteWeight() == 0.42

    def test_invalidEnvFallsBackToDefault(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_KB_GRAPH_ROUTE_WEIGHT", "abc")
        assert search_recipes.resolveGraphRouteWeight() == 0.10


class TestResolveRerankParams:
    def test_recipeValuesWithoutEnv(self):
        search_recipes.saveActiveRecipe("precise")
        assert search_recipes.resolveRerankParams() == ("model", 5)

    def test_envStillWins(self, monkeypatch):
        search_recipes.saveActiveRecipe("precise")
        monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK_METHOD", "weight")
        monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK_POOL", "2")
        assert search_recipes.resolveRerankParams() == ("weight", 2)

    def test_invalidPoolFallsBackToRecipe(self, monkeypatch):
        search_recipes.saveActiveRecipe("precise")
        monkeypatch.setenv("NEUROVA_KB_MAIN_RERANK_POOL", "abc")
        assert search_recipes.resolveRerankParams() == ("model", 5)


class TestResolveRecencyParams:
    def test_recipeValuesWithoutEnv(self):
        search_recipes.saveActiveRecipe("balanced")
        assert search_recipes.resolveRecencyParams() == (0.15, 30.0)

    def test_envStillWins(self, monkeypatch):
        search_recipes.saveActiveRecipe("balanced")
        monkeypatch.setenv("NEUROVA_RECENCY_WEIGHT", "0.5")
        monkeypatch.setenv("NEUROVA_RECENCY_HALF_LIFE_DAYS", "7")
        assert search_recipes.resolveRecencyParams() == (0.5, 7.0)

    def test_defaultRecipeKeepsRecencyOff(self):
        """default 配方 recency=0：不设 env 时主路行为与改造前一致。"""
        assert search_recipes.resolveRecencyParams() == (0.0, 30.0)


class TestAdapterWiring:
    def _adapter(self, hops):
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter

        class _Walker:
            def __init__(self, rows):
                self._rows = rows

            def walkFromQuery(self, *args, **kwargs):
                return self._rows

        return KnowledgeRetrieverAdapter(repo=None, graphWalker=_Walker(hops))

    @staticmethod
    def _context():
        from types import SimpleNamespace

        return SimpleNamespace(query="齿轮箱", limit=5, user_id=None, metadata={})

    def test_graphRouteWeightFollowsRecipe(self):
        adapter = self._adapter([])
        _ranks, _support, weight = adapter._graphRoute(self._context(), "agt", 5)
        assert weight == 0.10  # default 配方

    def test_graphRouteWeightFollowsNonDefaultRecipe(self):
        search_recipes.saveActiveRecipe("graph_expanded")
        adapter = self._adapter([])
        _ranks, _support, weight = adapter._graphRoute(self._context(), "agt", 5)
        assert weight == 0.30


class TestMainPathWiring:
    def test_fromEnvFollowsRecipe(self):
        from neurova.knowledge.rerank.main_path import MainPathRerankConfig

        search_recipes.saveActiveRecipe("precise")
        cfg = MainPathRerankConfig.fromEnv()
        assert cfg.method == "model"
        assert cfg.poolFactor == 5

    def test_fromEnvDefaultUnchanged(self):
        from neurova.knowledge.rerank.main_path import MainPathRerankConfig

        cfg = MainPathRerankConfig.fromEnv()
        assert cfg.method == "weight"
        assert cfg.poolFactor == 3
        assert cfg.enabled is True
