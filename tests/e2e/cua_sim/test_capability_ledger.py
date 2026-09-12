"""R2-3 能力台账机械契约：action_result 词表中的每个拒绝码必须已登记台账。

台账（docs/CUA能力台账.md）与测试互为证据——新拒绝码先登记、后使用，
杜绝"代码里冒出台账上没有的失败语义"。
"""

from pathlib import Path

from neurova.computer_use import action_result as ar

LEDGER_PATH = Path(__file__).parents[3] / "docs" / "CUA能力台账.md"


def test_every_refusal_code_documented():
    content = LEDGER_PATH.read_text(encoding="utf-8")
    missing = [code for code in sorted(ar.REFUSAL_CODES) if f"`{code}`" not in content]
    assert not missing, f"拒绝码未登记台账: {missing}"


def test_every_route_documented():
    content = LEDGER_PATH.read_text(encoding="utf-8")
    missing = [route for route in sorted(ar.ROUTES) if f"`{route}`" not in content]
    assert not missing, f"route 未登记台账: {missing}"
