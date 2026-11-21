# -*- coding: utf-8 -*-
"""G2 真实 transcript 回放契约测试。

对 ``replay_fixtures/`` 下每份**已存在**的 fixture：
1. 用真 NeuacpClient 管线回放，断言握手结果 / 步骤结果 / 事件回调序列 /
   转录帧序与录制时一致（:func:`assertReplayMatchesFixture`）；
2. 注入三类变异（相邻两帧互换 / 丢一帧 / 改一个字段类型），同一契约断言
   必须变红——防恒真：证明上述断言不是"怎么跑都绿"；
3. 卫生检查：fixture 帧必须已脱敏（redactFrame 幂等不变），真实 transcript
   不带凭据落库；
4. 家族覆盖登记：已录家族必须有 handshake fixture；未录家族（gemini-cli
   本机未安装）如实标注缺失，不伪造。

fixture 由 ``scripts/neuacp_record_fixture.py`` 录制（真 CLI + 真
NeuacpClient + 真 frame_log 脱敏链路）；本测试不依赖真实 CLI 在场——
回放是离线的（注入 transport），任何机器上都能复现同一契约。
"""
import copy
import json
import sys
from pathlib import Path

import pytest

from neurova.agent.neuacp.acp_client import NeuacpClient
from neurova.agent.neuacp.redaction import redactFrame

# 本目录无 __init__.py 且 pytest 用 importlib 装载：兄弟模块 replay_harness
# （与录制脚本共用的步骤解释器/回放器）需显式入 path 才能作为顶层模块导入。
_HARNESS_DIR = str(Path(__file__).resolve().parent)
if _HARNESS_DIR not in sys.path:
    sys.path.insert(0, _HARNESS_DIR)

from replay_harness import assertReplayMatchesFixture, replay  # noqa: E402

FIXTURE_ROOT = Path(__file__).with_name("replay_fixtures")

#: 家族覆盖登记（与 replay_fixtures/README.md 的录制矩阵同口径）：
#: recorded=本机已录；missing=本机不可录，原因如实登记（不伪造 fixture）。
FAMILY_STATUS = {
    "opencode": "recorded",
    "claude-code": "recorded",
    "codex": "recorded",
    "gemini-cli": "missing: 本机未安装 gemini CLI（如实缺失，不伪造 fixture）",
}

#: 回放客户端请求超时（秒）：fixture 帧是即取即供的，正常回放远快于真机；
#: 只有变异（丢帧/换序导致应答丢失）才会走满超时——取短值控制套件时长。
REPLAY_REQUEST_TIMEOUT_S = 3.0


def discoverFixtures():
    """收集全部已存在 fixture（<family>/<scenario>.json），按路径稳定排序。"""
    if not FIXTURE_ROOT.exists():
        return []
    return sorted(p for p in FIXTURE_ROOT.glob("*/*.json") if p.is_file())


def makeReplayClientFactory():
    """构造回放用 client_factory：真 NeuacpClient，命令仅占位。

    replay() 期间 Popen 被替换为 ScriptedTransport，不会真拉起进程；
    命令名取不可能存在的值，防止任何路径意外落回真 spawn。
    """
    def factory():
        return NeuacpClient(
            ["neurova-replay-placeholder-agent", "--fixture"],
            request_timeout=REPLAY_REQUEST_TIMEOUT_S,
        )
    return factory


# ---------- 变异器（变异防恒真） ----------

def _iterSlots(obj):
    """深度优先按插入序产出 (container, key, value)，供确定性变异定位。"""
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            yield obj, key, obj[key]
            yield from _iterSlots(obj[key])
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield obj, index, value
            yield from _iterSlots(value)


def _mutated(fixture, frames):
    out = copy.deepcopy(fixture)
    out["frames"] = frames
    return out


def mutateSwapAdjacent(fixture):
    """变异一：交换第一对内容不同的相邻帧（打乱 transcript 时序/因果）。"""
    frames = copy.deepcopy(fixture.get("frames") or [])
    for i in range(len(frames) - 1):
        a, b = frames[i], frames[i + 1]
        if (a.get("direction"), a.get("frame")) != (b.get("direction"), b.get("frame")):
            frames[i], frames[i + 1] = b, a
            return _mutated(fixture, frames)
    return None


def mutateDropFrame(fixture):
    """变异二：丢弃第一个 in 帧（agent 侧帧缺失→应答丢失/事件缺失）。"""
    frames = copy.deepcopy(fixture.get("frames") or [])
    for index, record in enumerate(frames):
        if record.get("direction") == "in":
            del frames[index]
            return _mutated(fixture, frames)
    return None


def mutateChangeFieldType(fixture):
    """变异三：改一个字段类型——优先动 in 帧里第一个整数值（int→str）。

    优先 in 帧：那是真正会喂进客户端管线的帧；整型→字符串正是 ACP 线上
    协议（protocolVersion 必须整数）踩过的陷阱形状。任何 in 帧都无整数时，
    退而求其次改任意帧的第一个整数；连整数都没有时改第一个非纯数字字符串
    为其长度（int）。无可变异内容返回 None。
    """
    frames = copy.deepcopy(fixture.get("frames") or [])

    def tryMutateInt(scope):
        for record in scope:
            for container, key, value in _iterSlots(record.get("frame") or {}):
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    container[key] = str(value)
                    return True
        return False

    inFrames = [r for r in frames if r.get("direction") == "in"]
    if tryMutateInt(inFrames) or tryMutateInt(frames):
        return _mutated(fixture, frames)
    for record in frames:
        for container, key, value in _iterSlots(record.get("frame") or {}):
            if isinstance(value, str) and not value.isdigit():
                container[key] = len(value)
                return _mutated(fixture, frames)
    return None


MUTATIONS = [
    ("swap_adjacent", mutateSwapAdjacent),
    ("drop_frame", mutateDropFrame),
    ("change_field_type", mutateChangeFieldType),
]


# ---------- 契约回放 ----------

@pytest.mark.parametrize("fixture_path", discoverFixtures(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_replayMatchesRecordedContract(fixture_path):
    """对每份已存在 fixture：真管线回放行为必须与录制时一致。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = replay(fixture, makeReplayClientFactory())
    assertReplayMatchesFixture(fixture, result)


@pytest.mark.parametrize("fixture_path", discoverFixtures(), ids=lambda p: f"{p.parent.name}/{p.stem}")
@pytest.mark.parametrize("mutation_name,mutate", MUTATIONS)
def test_mutationTurnsContractRed(fixture_path, mutation_name, mutate):
    """变异防恒真：三类变异任一注入后，同一契约断言必须变红。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    mutated = mutate(fixture)
    if mutated is None:
        pytest.skip(f"变异 {mutation_name} 对该 fixture 不适用（无可变异位置）")
    result = replay(mutated, makeReplayClientFactory())
    with pytest.raises(AssertionError):
        assertReplayMatchesFixture(fixture, result)


# ---------- fixture 卫生与覆盖登记 ----------

def test_fixtureInventoryAndCoverage():
    """已录家族必须有 handshake fixture；未录家族如实登记缺失。"""
    fixtures = discoverFixtures()
    assert fixtures, (
        "replay_fixtures/ 下没有任何 fixture——先运行 "
        "scripts/neuacp_record_fixture.py 录制（本测试不伪造 transcript）"
    )
    byFamily = {}
    for path in fixtures:
        byFamily.setdefault(path.parent.name, []).append(path.stem)
    for family, status in FAMILY_STATUS.items():
        if status == "recorded":
            assert family in byFamily, f"家族 {family} 登记为已录但 fixture 缺失"
            assert "handshake" in byFamily[family], f"家族 {family} 缺必录 handshake 场景"
        else:
            assert family not in byFamily, (
                f"家族 {family} 登记为缺失（{status}）却存在 fixture——要么补录转正，要么删 fixture"
            )


@pytest.mark.parametrize("fixture_path", discoverFixtures(), ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_fixtureFramesAreRedactedAndSchemaSane(fixture_path):
    """fixture 帧必须已脱敏（redactFrame 幂等不变），且 schema 完整可回放。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert fixture.get("fixture_version") == 1, "fixture_version 必须为 1"
    assert fixture.get("family") == fixture_path.parent.name, "family 与目录名一致"
    assert fixture.get("scenario") == fixture_path.stem, "scenario 与文件名一致"
    frames = fixture.get("frames") or []
    assert frames, "fixture 必须含至少一帧 transcript"
    for record in frames:
        assert record.get("direction") in ("in", "out", "observed"), f"方向非法: {record}"
        assert isinstance(record.get("frame"), dict), "帧载荷必须是 dict"
        assert redactFrame(record["frame"]) == record["frame"], (
            f"{fixture_path.name} 存在未脱敏帧——真实 transcript 不得带凭据落库"
        )
    expected = fixture.get("expected") or {}
    assert len(expected.get("steps") or []) == len(fixture.get("steps") or []), (
        "expected.steps 与 steps 必须一一对应（回放断言的基准）"
    )
