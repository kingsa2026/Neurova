"""T-01 通道词表单源守卫

设计稿 §0.3 把"动作走了哪条通道"这件事收口到 `action_result.ROUTES` 的 `route` 与
`DELIVERIES` 的 `delivery`，并明确**不引入** `channel`/`plane`/`streamId`/`exitCode`
四个同义键。本守卫钉三件事，都是"当下可能没事、日后必然漂移"的那类：

1. 词表每个值在设计稿里有映射——防"代码加了值、文档没登记"的两份事实源；
2. `desktop_uia` 不再自称 SendInput——docstring 与实现（pyautogui）不符即失实；
3. 同义键不得作为 payload 字段回流——教义第 6 条禁止第二份定义。
"""

import re
from pathlib import Path

import pytest

from neurova.computer_use import action_result as ar

_REPO = Path(__file__).resolve().parents[3]
_DESIGN_DOC = (
    _REPO
    / "docs"
    / "04-plans"
    / "2026-10-01-computer-use-nonintrusive-and-dock-observability.md"
)
_DESKTOP_UIA = _REPO / "neurova" / "computer_use" / "desktop_uia.py"

# 通道广播面：后端产出侧 + WS 装配侧 + 前端消费侧，缺一处就漏一处
_CONTRACT_FILES = [
    *_REPO.joinpath("neurova", "computer_use").glob("*.py"),
    _REPO / "neurova" / "tool_executor.py",
    _REPO / "NeurUI" / "src" / "composables" / "useComputerPanel.ts",
    _REPO / "NeurUI" / "src" / "components" / "chat" / "ComputerUsePanel.vue",
    _REPO / "NeurUI" / "src" / "components" / "chat" / "dock" / "panels" / "ComputerTab.vue",
]

# 与 route/delivery/terminal.sessionId/terminal.exit 同义的键名，一律禁止出现在键位上
_BANNED_KEYS = ("channel", "plane", "streamId", "exitCode")
_KEY_ALT = "|".join(_BANNED_KEYS)
# 形态一：字符串字面量作字典键/下标——payload 里 {"channel": ...}、payload["channel"] = ...
_KEYED_STRING = re.compile(r"""["'](%s)["']\s*[:\]]""" % _KEY_ALT)
# 形态二：对象/接口成员裸名——`channel?: string` 这一型**必须拦得住**：
# 变异实测过，只扫带引号的字面量时，在前端 interface 里加一个 channel 字段守卫毫无反应，
# 而那正是第二份通道词表最自然的诞生方式。
_MEMBER_KEY = re.compile(r"^\s*(?:readonly\s+)?(%s)\s*\??\s*:" % _KEY_ALT, re.MULTILINE)


def _key_position_hits(text: str) -> list:
    """只认"键位"上的同义名，放过协议字面量与第三方 API 属性名。

    仓内两处合法命中必须不被误伤：`tool_executor.py` 的 `<|channel|>`（网关消息格式字面量）、
    `ssh_runner.py` 的 `stdout.channel`（paramiko 属性）——两者都不带引号也不在键位。
    """
    hits = []
    for pattern in (_KEYED_STRING, _MEMBER_KEY):
        for m in pattern.finditer(text):
            hits.append(m.group(0).strip())
    return hits


def _design_text() -> str:
    assert _DESIGN_DOC.is_file(), f"设计稿不在位：{_DESIGN_DOC}"
    return _DESIGN_DOC.read_text(encoding="utf-8")


def _section03_text() -> str:
    """只取 §0.3 收口映射表那一节——扫全文会让 "remote"/"dom" 之类通用词偶然命中而恒真。"""
    doc = _design_text()
    marker = "### 0.3"
    assert marker in doc, "设计稿缺 §0.3 通道映射表，词表守卫失去对照物"
    tail = doc.split(marker, 1)[1]
    end = tail.find("\n## ")
    return tail if end == -1 else tail[:end]


class TestVocabularyIsDocumented:
    def test_every_route_value_has_a_mapping(self):
        section = _section03_text()
        missing = [
            value
            for value in sorted(ar.ROUTES)
            if not re.search(rf"\b{re.escape(value)}\b", section, re.IGNORECASE)
        ]
        assert not missing, f"ROUTES 值在设计稿 §0.3 无映射（词表与文档已分叉）：{missing}"

    def test_every_delivery_value_is_named_in_design(self):
        doc = _design_text()
        missing = [
            value
            for value in sorted(ar.DELIVERIES)
            if not re.search(rf"\b{re.escape(value)}\b", doc, re.IGNORECASE)
        ]
        assert not missing, f"DELIVERIES 值在设计稿中未登记：{missing}"


class TestNoSecondChannelVocabulary:
    def test_contractSurfaceIsNotEmpty(self):
        """面自证：广播面清单本身要数得出量——路径搬家时 parametrize 会退化成零格守卫。"""
        present = [p for p in _CONTRACT_FILES if p.is_file()]
        surface = len(present)
        assert surface > 12, (
            f"契约面现读 {surface} 个在位文件（清单 {len(_CONTRACT_FILES)} 项）——"
            "路径段被改掉后这格只会比文档，不再拦第二份词表")

    @pytest.mark.parametrize(
        "path",
        [p for p in _CONTRACT_FILES if p.is_file()],
        ids=lambda p: p.name,
    )
    def test_banned_synonyms_absent(self, path: Path):
        text = path.read_text(encoding="utf-8")
        hits = _key_position_hits(text)
        assert not hits, (
            f"{path.relative_to(_REPO)} 在键位上出现了与 route/delivery 同义的 {hits}"
            "——通道事实源必须是 action_result 词表，不得另起一份（教义第 6 条）"
        )


class TestDeliveryDocstringIsTruthful:
    def test_desktop_uia_does_not_claim_send_input(self):
        """该文件的全局投递走 pyautogui，docstring 却自称 SendInput（全仓无 SendInput 调用）。

        失实自述属教义第 2 条禁止的形态：读代码的人据它判断"存在裸 SendInput 直注通道"，
        而真实闸门是 env + pyautogui，两者自救动作完全不同。
        """
        text = _DESKTOP_UIA.read_text(encoding="utf-8")
        assert "SendInput" not in text, (
            "desktop_uia 仍自称 SendInput；实际实现是 pyautogui，"
            "请把 docstring 改为陈述真实投递手段"
        )
