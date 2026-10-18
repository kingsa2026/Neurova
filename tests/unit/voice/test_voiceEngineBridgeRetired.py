# -*- coding: utf-8 -*-
"""语音引擎桥 `neurova/voice_adapter.py` 已退役（§6-108；§9 序 4 复算改判的第二格）。

原登记（§6-104）把它判成"需人裁：全仓唯一实装"。本轮按用户关注点复算后**改判为可退役**，
三条依据：

1. **它不在渠道语音这条链上**。渠道侧入站的真 ASR 在
   `neurova/channels/voice_precheck.py:43-84`（经 `manager.py:319-327` 调用），
   出站走 `channels/voice.py` 的 TwiML；而 `voice_adapter.py` 生产侧 import 复算为 **0**
   （`neurova/`、`scripts/`、配置、动态入口全扫）。删它不影响"能不能语音对话"。
2. **它想统一的分派已有现役实装**：`neurova/voice_engine.py:71 process()` 内部就按
   `VoiceEngineType.ASR/TTS` 分派到 `_process_asr`/`_process_tts`。所以"引擎调用桥"这一
   职责并非唯一实装——按教义第 7 条比过之后，它没有不可替代的部分（ABC + 两个
   manager adapter + 工厂 + 便捷函数，逐项都在 `VoiceEngine` 里有同名对应）。
3. **给它作证的三格是"名字可导入"式恒真断言**：
   `tests/unit/voice/test_voice_system_integration.py` 的 `TestVoiceEngineAdapter`
   （263-351）与 `test_voice_system_closed_loop.py` 的 `TestVoiceAdapterInterfaceAlignment`
   （146-212）测的是"能不能 import / 工厂能不能 new 出来 / `_engine_type` 字段等不等于字面量"，
   不跑任何真引擎、不碰渠道与 agent。留着它们等于让 mock 替一个不参与的模块作证。

**本批只删孤儿自己，不动活的邻居**——这是这组判据的重点：
`neurova/voice_memory_bridge.py` 是**活的**（`agent_core.py:706-717` 构造、
`agent_shutdown.py:87-90` 收尾），`neurova/channels/voice.py` 的渠道适配器也仍在。
⚠ **本档原先那句"`api/app.py` 注册 VoiceAdapter"已于 2026-10-13 §6-180 失效**：那条平行装配读的是
全仓无人写入的 `voice_enabled`/`twilio_*` 四个键（生产里恒 enabled=False、凭据空），已由 §6-180 退役；
voice 现在与其它 13 个渠道同路，走 `api/endpoints/channel_config.py _create_adapter` 从持久化配置建。
所以两个混合测试文件按**格**摘、不按文件删：只删直接依赖孤儿的类/格，
`TestVoiceMemoryBridgeAsyncio`、`TestAgentShutdown`、`TestVoiceAdapterRegistration`、
`TestVoicePerformanceMonitoring`、`TestVoiceMemoryBridgeClosedLoop` 等全部保留。

反向对照（防删过头）：下面 `test_liveVoiceFacesStillWired` 必须在删除前后都绿——
它钉的是"渠道适配器可构造 + 引擎分派在位 + 记忆桥确实被 agent 装配与收尾"。
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests import ast_scan

import pytest

REPO = Path(__file__).resolve().parents[3]
PROD_ROOT = REPO / "neurova"
TESTS_ROOT = REPO / "tests"
RETIRED = "neurova.voice_adapter"

pytestmark = pytest.mark.timeout(60)


def _hits(root: Path) -> list[str]:
    """子树里仍 import 已退役桥的文件清单（四种取法都认）。

    取数走 `tests/ast_scan` 的共享入口 `importersOfModule`：它自己按**末段名**
    （`voice_adapter`）预筛——那是判据的充分条件，而相对形的源码里根本没有包前缀，
    按全名预筛会把它们在文本这一关就滤掉。此前这里是私有 `_importedNames`，写着
    `and not node.level`，相对形与父包取名形（`from neurova import voice_adapter`）
    两条形都不在面内。显示名由入口按"仓内给相对路径／仓外给绝对路径"给，
    注入探针落在 tmp 下不会把 `ValueError` 冒名成被测故障。
    """
    return sorted({rel for rel, _lineno, _form in ast_scan.importersOfModule(root, RETIRED)})


def test_noImportOfRetiredEngineBridge():
    """生产与测试两侧都不得再引用这座桥（退役前生产引用面实测为 0）。"""
    found = _hits(PROD_ROOT) + _hits(TESTS_ROOT)
    assert not found, f"还有地方引用已退役的语音引擎桥：{found}"


def test_bridgeFileIsGone():
    assert not (PROD_ROOT / "voice_adapter.py").is_file(), \
        "voice_adapter.py 又回到了包树里"


def test_liveVoiceFacesStillWired():
    """反向对照：活的三件必须都还在——本批改的是不参与链路的桥，不是语音能力本身。"""
    # ① 渠道适配器可构造（channels/voice.py）
    chan = PROD_ROOT / "channels" / "voice.py"
    names = {n.name for n in ast.walk(ast.parse(chan.read_text(encoding="utf-8")))
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    assert {"VoiceAdapter", "create_voice_adapter"} <= names, "渠道侧语音适配器不见了"
    # ② 引擎分派在位（voice_engine.py 的 process + 两条内部支路）
    engine = (PROD_ROOT / "voice_engine.py").read_text(encoding="utf-8")
    for fn in ("async def process", "_process_asr", "_process_tts"):
        assert fn in engine, f"现役引擎分派面缺了 {fn}——那才是真正在承担桥职责的地方"
    # ③ 记忆桥仍被 agent 装配与收尾（它不是孤儿，别一起删）
    core = (PROD_ROOT / "agent_core.py").read_text(encoding="utf-8")
    shut = (PROD_ROOT / "agent_shutdown.py").read_text(encoding="utf-8")
    assert "VoiceMemoryBridge(" in core, "agent 侧不再构造语音记忆桥——本批不该动它"
    assert "voice_memory_bridge" in shut, "收尾链不再关这座桥——本批不该动它"


def test_mixedTestFilesKeepTheirLiveClasses(tmp_path):
    """两个混合文件按格摘过之后，覆盖活代码的类必须还在（防整文件删掉带走真覆盖）。"""
    loop = (TESTS_ROOT / "unit" / "voice" / "test_voice_system_closed_loop.py"
            ).read_text(encoding="utf-8")
    integ = (TESTS_ROOT / "unit" / "voice" / "test_voice_system_integration.py"
             ).read_text(encoding="utf-8")
    for cls in ("TestVoiceMemoryBridgeClosedLoop",
                "TestVoiceAdapterLifecycleCompleteness"):
        assert f"class {cls}" in loop, f"closed_loop 里的活覆盖类 {cls} 被一起删了"
    for cls in ("TestVoiceMemoryBridgeAsyncio", "TestAgentShutdown",
                "TestVoiceAdapterRegistration", "TestVoicePerformanceMonitoring"):
        assert f"class {cls}" in integ, f"integration 里的活覆盖类 {cls} 被一起删了"


def test_scannerCatchesARevival(tmp_path):
    """注入探针：造一处 import 必须被抓到，且现役邻居不误伤。"""
    bad = tmp_path / "revival.py"
    bad.write_text("from neurova.voice_adapter import VoiceAdapterFactory\n", encoding="utf-8")
    assert [p.rsplit("/", 1)[-1] for p in _hits(tmp_path)] == ["revival.py"]

    # 父包取名形：真引用，旧那份私有谓词（`and not node.level`）看不见这一形
    viaParent = tmp_path / "via_parent.py"
    viaParent.write_text("from neurova import voice_adapter\n", encoding="utf-8")
    assert sorted(p.rsplit("/", 1)[-1] for p in _hits(tmp_path)) == ["revival.py", "via_parent.py"], \
        "父包取名形没被抓到——导入通道判据又在学旧口径只比一种取法"

    ok = tmp_path / "live.py"
    ok.write_text("from neurova.voice_engine import VoiceEngine\n", encoding="utf-8")
    okParent = tmp_path / "live_parent.py"
    okParent.write_text("from neurova import voice_engine\n", encoding="utf-8")
    bad.unlink()
    viaParent.unlink()
    assert not _hits(tmp_path), f"误伤了现役引擎：{_hits(tmp_path)}"
