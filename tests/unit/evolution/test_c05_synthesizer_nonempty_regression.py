"""M-?/C-05 回归测试：pattern_miner.to_skill_template_list 必须接受 top_n 并返回非空模板。

根因：to_skill_template_list 形参只有 min_support/min_success_rate，而调用方
（closed_loop.synthesize_from_patterns）用 top_n= 调用 → 参数名不匹配（TypeError）。
测试直接加载 pattern_miner 子模块（绕过可能很重的 neurova.evolution 包 __init__），
注入频繁模式后调用 to_skill_template_list(top_n=...)，断言返回非空且 top_n 生效。

红绿：无修复时 to_skill_template_list 不接受 top_n（TypeError）→ 测试失败（红）；
修复后（增加 top_n 形参并按其截断）→ 绿。
"""

import importlib.util
from pathlib import Path

# pattern_miner 仅用绝对导入（neurova.core.logger 等），直接按文件加载以避开
# 可能很重的 neurova.evolution 包 __init__
_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "pm_direct", str(_ROOT / "neurova" / "evolution" / "pattern_miner.py")
)
pm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pm)

PatternMiner = pm.PatternMiner
FrequentPattern = pm.FrequentPattern


def test_c05_top_n_returns_templates():
    miner = PatternMiner()
    miner._patterns = [
        FrequentPattern(tools=["a", "b"], support=5, context="c1"),
        FrequentPattern(tools=["c"], support=5, context="c2"),
    ]

    out = miner.to_skill_template_list(top_n=1)
    assert len(out) == 1, "C-05: top_n 必须生效，返回非空模板列表"

    out2 = miner.to_skill_template_list(top_n=10)
    assert len(out2) == 2, "C-05: 应返回全部 2 个频繁模式生成的模板"

    out0 = miner.to_skill_template_list()
    assert len(out0) == 2, "C-05: 不传 top_n 时应返回全部"
