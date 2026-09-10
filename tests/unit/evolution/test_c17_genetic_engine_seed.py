"""C-17 回归测试：ToolGeneticEngine 使用实例级 random.Random(seed)。

缺陷：全文件使用全局 random 模块且无 seed，进化过程不可复现。
修复：__init__ 增加 seed 参数（None=系统熵），全部随机调用收敛到
self._rng = random.Random(seed)。
"""

from neurova.evolution.genetic_engine import ToolGeneticEngine, ToolGenotype


def _seeded_sequences(seed):
    engine = ToolGeneticEngine(seed=seed)
    engine.add_to_population(ToolGenotype(tool_sequence=["file_read", "file_write"]))
    engine.add_to_population(ToolGenotype(tool_sequence=["memory_search", "memory_store"]))
    engine.add_to_population(ToolGenotype(tool_sequence=["browser_navigate", "browser_click"]))
    engine.evolve(generations=5)
    return [g.tool_sequence for g in engine.population]


def test_same_seed_reproduces_evolution():
    assert _seeded_sequences(42) == _seeded_sequences(42)


def test_seed_none_runs_with_system_entropy():
    engine = ToolGeneticEngine()
    engine.add_to_population(ToolGenotype(tool_sequence=["file_read", "file_write"]))
    engine.add_to_population(ToolGenotype(tool_sequence=["memory_search", "memory_store"]))
    result = engine.evolve(generations=2)
    assert isinstance(result, list) and len(result) > 0


def test_all_random_calls_routed_through_instance():
    # 源码约束：除 Random(seed) 构造外，模块体不得再触达全局 random.*
    import inspect

    import neurova.evolution.genetic_engine as ge

    src = inspect.getsource(ge)
    stray = [
        line
        for line in src.splitlines()
        if "random." in line and "random.Random" not in line
    ]
    assert stray == []
