"""状态字面量三处（Python / TS / ArkTS）必须同一集合，且一次性凭据不得有回边（设计方案 §5.6／§5.5）。

为什么钉三处而不是只钉一处：Web 徽标、App 徽标与服务端回话读的是**同一批词**。
任一侧漂出一个新状态而另两侧不知道，表现就是「面板显示等待扫码、其实已解除」
这类看不见故障——正是本卷反复记过的「判据读的对象与真装配点不同形」（形态 403）。

单源落点：`neurova/tunnel/protocol.py`。另两侧各持一份同名字面量，本守卫断言**集合相等**。
不生成代码、不加同步脚本——那是教义第 6 条点名的「两边都留着、加个同步脚本」。

跑法：`.venv/Scripts/python.exe -m pytest -q tests/unit/test_tunnelStateEnumSingleSource.py -p no:cacheprovider`
"""
import io
import os
import re

import pytest

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_enum_ss_0123456")

from neurova.tunnel import protocol  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TS_CONTRACT = os.path.join(REPO_ROOT, "NeurUI", "src", "api", "contracts", "pairingStates.ts")
ETS_CONTRACT = os.path.join(REPO_ROOT, "NeurovaHarmony", "entry", "src", "main", "ets",
                            "libs", "protocol", "PairingProtocol.ets")

#: (Python 属性名, 两份前端契约里的同名常量, 该集合的**最小**必含成员)
#: 下限钉住是为了让「扫描面缩水」不被读成「缺陷已扫净」：某侧偷偷少一个状态时，
#: 只比相等有可能被两边同时漂成同一个错值骗过，这里再按成员点名一次。
_CONTRACTS = (
    ("PAIRING_CODE_STATES", "PAIRING_CODE_STATES", ("pending", "scanned", "confirmed",
                                                    "expired", "revoked", "used", "aborted")),
    ("DEVICE_REGISTRY_STATES", "DEVICE_REGISTRY_STATES", ("unpaired", "paired", "online",
                                                          "offline", "dormant", "revoked")),
    ("TUNNEL_STATES", "TUNNEL_STATES", ("disabled", "probing", "via_relay", "relay_down",
                                        "evicted")),
    ("DEVICE_CONNECTION_STATES", "DEVICE_CONNECTION_STATES",
     ("idle", "reauthing", "connecting", "authed", "streaming", "reconnecting", "failed",
      "closed")),
)


def _read(path: str) -> str:
    assert os.path.exists(path), (
        f"契约文件不存在：{path}——三处单源少了一处，判据当场失明（不是「没有漂」，是「看不见漂」）")
    with io.open(path, encoding="utf-8") as f:
        return f.read()


def _literalsIn(text: str, constName: str) -> list:
    """抽 `NAME = [...]`（TS 的 `as const`／ArkTS 的类型标注都认）里的字面量集合。"""
    block = re.search(rf"{constName}\s*(?::[^=]+)?=\s*\[(.*?)\]", text, re.S)
    assert block, f"契约里找不到常量 {constName}——它被改名或删掉了，三语对齐即刻失效"
    return re.findall(r"['\"]([^'\"]+)['\"]", block.group(1))


@pytest.mark.parametrize("pyAttr,constName,mustContain", _CONTRACTS)
def test_python_typescript_arkts_literals_are_the_same_set(pyAttr, constName, mustContain):
    pySet = set(getattr(protocol, pyAttr))
    tsSet = set(_literalsIn(_read(TS_CONTRACT), constName))
    etsSet = set(_literalsIn(_read(ETS_CONTRACT), constName))

    assert pySet == tsSet, f"{constName}：Python {sorted(pySet)} ↔ TS {sorted(tsSet)} 不等"
    assert pySet == etsSet, f"{constName}：Python {sorted(pySet)} ↔ ArkTS {sorted(etsSet)} 不等"
    assert set(mustContain) <= pySet, (
        f"{constName} 少了设计里点名的状态：{sorted(set(mustContain) - pySet)}")


def test_one_time_credential_has_no_back_edge_to_pending():
    """§10.1 已裁：`ref` 一经 resolve 即消费，任何"超时退回待扫"都等于把一次性改成可重放。"""
    backEdges = [src for src, dsts in protocol.PAIRING_CODE_TRANSITIONS.items()
                 if "pending" in dsts]
    assert not backEdges, (
        f"配对码存在回到 pending 的合法边 {backEdges}——一次性凭据被做成可重放")
    assert "pending" not in protocol.PAIRING_CODE_TRANSITIONS.get("scanned", ()), (
        "scanned → pending 仍在合法边集合里")


def test_dormant_is_a_notice_not_a_deletion():
    """§4.9 已裁：30 天无活动进 dormant，而 dormant 不是删除态。"""
    assert "dormant" in protocol.DEVICE_REGISTRY_STATES
    assert "dormant" not in protocol.DEVICE_REGISTRY_TERMINAL_STATES, (
        f"dormant 被列进终态 {protocol.DEVICE_REGISTRY_TERMINAL_STATES}——提醒变成了代删")


def test_literal_extractor_hits_a_drifted_sample():
    """反空转：真造一份漂了的契约，抽取器必须说"不等"，否则上面几条是恒真的空守卫。"""
    drifted = "export const PAIRING_CODE_STATES = ['pending', 'confirmed'] as const"
    assert set(_literalsIn(drifted, "PAIRING_CODE_STATES")) != set(protocol.PAIRING_CODE_STATES), (
        "抽取器对明显少了四个状态的样本都不报警——判据不判事")
