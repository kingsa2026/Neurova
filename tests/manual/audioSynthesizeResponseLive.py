# -*- coding: utf-8 -*-
"""§6-171 活体自证：/api/v1/audio/synthesize 交回的是真字节，产物为空时不许回 200。

补的是一条常被跳过的证据：单元判据用真 router + 替身引擎，这里用**真 `create_app()` 装配**
（含 lifespan、AppState、路由注册、依赖与中间件），打真端点，读回真响应。

边界说明（只有一处替身，且是刻意选的）：TTS 引擎被钉成离线 mock。原因不是省事——
现役回退链是 `moss-nano → edge-tts → sapi5 → mock`（`neurova/tts/manager.py:38`），
其中 edge-tts 会向远端合成服务发请求。判据与活体都不许开外网、不许花服务商额度，
所以这里显式 `TTSConfig(engine="mock")`；链上其余环节（端点、格式判定、错误处理、响应头）
全是生产代码。

四段读数：
① 真装配 + 真端点：200、响应体非空且是 RIFF/WAVE、`Content-Type` 落 audio/wav、
   `X-TTS-Engine` 报的是引擎真名（不是硬编码 unknown）；
② 产物是 MP3 帧头 ⇒ 媒体类型必须跟着魔数走（audio/mpeg）；
③ 引擎"成功返回但没有字节" ⇒ 500 且 detail 说清是合成失败，**不得回 200 空身体**
   （这一条就是本仓反复点名的"假成功"形态在语音端的落点）；
④ 引擎自报错误 ⇒ 500 且 detail 就是那句错误，不吞、不改写成通用文案。
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
# Windows 控制台默认 cp936，读数里的箭头与符号会把脚本自己打崩（不是被测对象崩）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 打不了 unicode 不影响判定，读数仍走退出码
    pass

failures: list = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


class _StubInner:
    """只替"引擎产物"这一边界：initialize/is_initialized 走真属性名，synthesize 返预定字节。"""

    def __init__(self, audioBytes=None, error=None):
        self.is_initialized = True
        self._bytes = audioBytes
        self._error = error

    async def synthesize(self, text, **kwargs):
        if self._error is not None:
            raise self._error
        return self._bytes


def main() -> int:
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    from fastapi.testclient import TestClient

    from neurova.api.app import create_app
    from neurova.api.endpoints import get_app_state
    from neurova.tts.manager import TTSConfig, TTSManager
    from neurova.voice_engine import VoiceEngine, VoiceEngineType

    app = create_app()
    client = TestClient(app)
    with client:  # 触发 lifespan，让 AppState 按生产方式装配
        state = get_app_state()
        _check(isinstance(state, dict) and "voice_engines" in state,
               f"真装配：lifespan 建起了 AppState（get_app_state 实得 {type(state).__name__}）")

        manager = TTSManager(config=TTSConfig(engine="mock"))
        import asyncio

        ok = asyncio.run(manager.initialize())
        _check(bool(ok), "离线 mock TTS 引擎初始化成功（不开外网）")
        state["voice_engines"]["tts"] = VoiceEngine(engine_type=VoiceEngineType.TTS, engine=manager)

        print("\n① 真端点交回的是引擎产物")
        resp = client.post("/api/v1/audio/synthesize", json={"text": "这是给活体的一段话"})
        _check(resp.status_code == 200, f"状态码 200（实得 {resp.status_code}：{resp.text[:80] if resp.status_code != 200 else ''}）")
        body = resp.content
        _check(len(body) > 1000, f"响应体是真音频字节流，长度={len(body)}（不是 JSON 元数据）")
        _check(body[:4] == b"RIFF", f"产物头部是 RIFF/WAVE（实得 {body[:4]!r}）")
        _check(resp.headers.get("content-type", "").startswith("audio/wav"),
               f"媒体类型随魔数落 wav（实得 {resp.headers.get('content-type')!r}）")
        header = resp.headers.get("X-TTS-Engine", "")
        _check(header and header != "unknown", f"引擎头报真名：{header!r}")

        print("\n② 魔数换 MP3，媒体类型必须跟着变")
        state["voice_engines"]["tts"] = VoiceEngine(
            engine_type=VoiceEngineType.TTS, engine=_StubInner(audioBytes=b"\xff\xfb\x90\x00" + b"\x00" * 40))
        resp2 = client.post("/api/v1/audio/synthesize", json={"text": "x"})
        _check(resp2.status_code == 200 and resp2.headers.get("content-type", "").startswith("audio/mpeg"),
               f"MP3 帧头应报 audio/mpeg（实得 {resp2.headers.get('content-type')!r} / {resp2.status_code}）")

        print("\n③ 引擎成功返回但产物为空 ⇒ 不许 200")
        state["voice_engines"]["tts"] = VoiceEngine(
            engine_type=VoiceEngineType.TTS, engine=_StubInner(audioBytes=b""))
        resp3 = client.post("/api/v1/audio/synthesize", json={"text": "x"})
        _check(resp3.status_code == 500,
               f"空产物回 500（实得 {resp3.status_code}，身体长度 {len(resp3.content)}——200 空身体就是假成功）")
        _check("合成失败" in str(resp3.json().get("detail", "")),
               f"500 的 detail 说清了原因：{resp3.json().get('detail')!r}")

        print("\n④ 引擎抛错 ⇒ 错误被如实带出，不吞成成功")
        state["voice_engines"]["tts"] = VoiceEngine(
            engine_type=VoiceEngineType.TTS, engine=_StubInner(error=RuntimeError("合成器坏了")))
        resp4 = client.post("/api/v1/audio/synthesize", json={"text": "x"})
        _check(resp4.status_code == 500, f"引擎异常回 500（实得 {resp4.status_code}）")
        _check("合成器坏了" in str(resp4.json().get("detail", "")),
               f"detail 带着原始错误：{resp4.json().get('detail')!r}")

    print()
    if failures:
        print(f"活体未过：{len(failures)} 项")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("活体全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
