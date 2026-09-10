"""C-16 回归测试：ConvergenceAnalyzer 非法 window_size 的 fail-safe。

缺陷：window_size<=0 时 `len(gain_history) < window_size` 恒假 →
`gain_history[-0:]` 取全量、空历史 `sum([])/len([])` 抛 ZeroDivisionError。
修复：__init__ 校验 window_size（<=0/非 int 回落默认 20，warning）。
"""

from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer


def test_zero_window_falls_back_to_default():
    analyzer = ConvergenceAnalyzer(window_size=0)
    assert analyzer.window_size == 20


def test_negative_window_falls_back_to_default():
    analyzer = ConvergenceAnalyzer(window_size=-3)
    assert analyzer.window_size == 20


def test_valid_window_unchanged():
    assert ConvergenceAnalyzer(window_size=7).window_size == 7


def test_zero_window_empty_history_no_zero_division():
    analyzer = ConvergenceAnalyzer(window_size=0)
    # 旧代码此处 ZeroDivisionError；修复后数据不足语义
    result = analyzer.analyze_convergence()
    assert result["status"] == "insufficient_data"
    assert result["confidence"] == 0.0


def test_zero_window_records_and_analyzes_normally():
    analyzer = ConvergenceAnalyzer(window_size=0)
    for i in range(85):
        analyzer.record_iteration(gain=0.01, cost=0.05)
    # 旧代码 window_size=0 时窗口永不截断（85 条残留）；回落后窗口=2*20=40
    assert len(analyzer.gain_history) == 40
    result = analyzer.analyze_convergence()
    assert result["metrics"]["mean_gain"] == 0.01


def test_invalid_window_is_worth_continuing_safe():
    analyzer = ConvergenceAnalyzer(window_size=0)
    # 空历史下不崩（旧代码 ZeroDivisionError 路径的同源消费方）
    assert analyzer.is_worth_continuing() is False
