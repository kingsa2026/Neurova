"""RSI 子包 conftest —— 收集缓存按「节点身份」去重导致的 fixture 丢失兜底。

**为什么这里需要显式再导入一次父包的 fixture，而不是直接继承**

`tests/unit/evolution/` 下没有 `__init__.py`，因此它由 `_pytest.main.Dir`
（`nodeid` = `tests/unit/evolution`、`name` = `evolution`）收集；
而 `tests/unit/evolution/rsi/test_parameter_source_of_truth.py` 这种 initial path
走的是 `Session.collect()` 的逐层下钻，父链上挂的是 `Dir tests/unit/evolution`。

两份 `Dir` 的 `nodeid` 相同但**不同一个对象**：`Node.__hash__` 用 nodeid，
而 `Node.__eq__` 是身份比较（`cpython` 默认 object 语义）。于是
`Session._collect_one_node` 的 `node in self._collection_cache` 键比较落空
（改用 `list(...)` 的同一路径 id 才算命中，见
`tests/unit/test_pytest_runner_guards.py` 的实跑证据），同一份收集报告被算两次。

`FixtureManager._matchfactories` 的可见性判据是
`fixturedef.node in parent_nodes`（`parent_nodes` 是 `list`，故按恒等身份比较）——
一旦同一目录存在两个 collector 身份，父包 conftest 里的 fixture 就可能绑到
"当前 item 的父链上不存在"的那一个，表现为成片
`fixture 'xxx' not found`（受保护子集实测 65 个 error）。

**这里为什么这样修**：判定"哪个父链身份会被复用"需要精确重演 pytest 的
收集顺序，脆弱且随版本变动；而在**子包自己的 conftest 里重新声明同一批
fixture**，可见性判据只在"本包 collector"这一层求值，不会再踩到跨身份比较。
fixture 实现仍然只有一份 —— 全部从父包 conftest 直接引用，不做任何复制。

父包 fixture 的完整清单见 `tests/unit/evolution/conftest.py`；
新增 fixture 时必须同步加进下面这张表（否则 RSI 子包下同样会丢）。
"""

from __future__ import annotations

from tests.unit.evolution.conftest import (
    blind_eval_harness,
    fake_skill,
    measured_eval_harness,
    null_systems,
    probe_tool_memory_system,
    rsi_probe_factory,
)
