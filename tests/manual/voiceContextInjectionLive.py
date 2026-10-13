# -*- coding: utf-8 -*-
"""§6-174 活体自证：语音上下文进 prompt 这条链，走真 `ContextOrchestrator.build_context`。

本批把同一份注入逻辑的三处拷贝合成一处（`voiceContextLines()`），并退掉模块自持的进程级
"最近一次语音上下文"。单元判据证的是"实现只有一份"，这一支证的是**真上下文组装确实读得到它**：
现役读侧 `chat_pipeline.py:1667 → :1703` 把 `metadata["voice_context"]` 交给 `build_context()`，
两条分支（池 / 候选池）现在共用同一份实现。

计数用 wrapper 包生产对象而不是靠 grep：构造次数与调用次数都是运行时读数。
不花任何服务商额度——只调上下文组装，不调模型。
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 - 控制台编码不该决定判定，结论走退出码
    pass

failures: list = []


def _check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        failures.append(msg)


def main() -> int:
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    root = isolatedDataRoot()
    print(f"数据根（临时）：{root}")

    import asyncio

    import neurova.context.orchestrator as orchestratorModule
    import neurova.voice_context_module as voiceContextModule
    from neurova.context.orchestrator import ContextOrchestrator

    # 运行时计数：包一层，不改生产语义
    builtInstances: list = []
    realModuleClass = voiceContextModule.VoiceContextModule

    class _CountingModule(realModuleClass):
        def __init__(self, *a, **kw):
            builtInstances.append(True)
            super().__init__(*a, **kw)

    realLines = voiceContextModule.voiceContextLines
    lineCalls: list = []

    def _countingLines(ctx):
        lineCalls.append(ctx)
        return realLines(ctx)

    voiceContextModule.VoiceContextModule = _CountingModule
    orchestratorModule.VoiceContextModule = _CountingModule
    voiceContextModule.voiceContextLines = _countingLines
    try:
        from neurova.agent_core import Agent, AgentConfig

        # 只调上下文组装，不调模型：模型名用占位值，任何路径都不会发出 LLM 请求
        config = AgentConfig(
            name="ctx_live",
            agent_id="ctx_live",
            workspace_path=str(pathlib.Path(tempfile.mkdtemp(prefix="voiceCtxLive-"))),
            llm_model="gpt-4o-mini",
        )
        agent = Agent(config)
        orch = ContextOrchestrator(agent)

        print("\n① 带语音上下文的回合：真 build_context 的产出里要读到它")
        ctx = asyncio.run(orch.build_context(
            user_input="那明天呢",
            voice_context={
                "text": "帮我看下明天的排程",
                "confidence": 0.62,
                "language": "zh",
                "engine": "funasr",
                "emotion": {"primary_emotion": "neutral", "confidence": 0.3},
            },
        ))
        produced = ctx if isinstance(ctx, str) else str(ctx)
        _check("帮我看下明天的排程" in produced,
               "上下文里出现转写文本（否则这功能对接不到 prompt，正是本次要接的那条断口）")
        _check("识别置信度: 0.62" in produced, "上下文里出现置信度读数")
        _check("识别引擎: funasr" in produced, "上下文里出现引擎读数")
        _check("语音情感" not in produced, "neutral 情感没被当信息注入")
        _check(len(lineCalls) >= 1, f"唯一实现被调用 {len(lineCalls)} 次（两条分支共用它）")
        _check(not builtInstances,
               f"上下文组装期间不再构造 VoiceContextModule（此前每次白建一遍情感分析器）：{len(builtInstances)} 次")

        print("\n② 反向对照：没有语音上下文的回合不该出现这些行，也不该调用注入实现")
        lineCalls.clear()
        plain = asyncio.run(orch.build_context(user_input=" just text"))
        plainText = plain if isinstance(plain, str) else str(plain)
        _check("语音识别文本" not in plainText and not lineCalls,
               f"纯文字回合干净（调用次数 {len(lineCalls)}）")

        print("\n③ TTS 侧元数据同样走这一份实现")
        lineCalls.clear()
        withTts = asyncio.run(orch.build_context(
            user_input="复述一遍",
            voice_context={"audio_metadata": {"tts_engine": "moss-nano", "tts_voice": "zh-CN-XiaoxiaoNeural"}},
        ))
        text3 = withTts if isinstance(withTts, str) else str(withTts)
        _check("moss-nano" in text3 and "zh-CN-XiaoxiaoNeural" in text3,
               "TTS 引擎/音色读数进入上下文")
        _check(len(lineCalls) == 1, f"这一轮只调用唯一实现一次（实得 {len(lineCalls)}）")

        print("\n④ 模块不再自持进程级状态")
        _check(not hasattr(realModuleClass, "get_voice_context")
               and not hasattr(realModuleClass, "clear_voice_context"),
               "读口/清理口已退役（无会话键的进程级『最近一次』不该存在）")
        _check("_current_context" not in vars(realModuleClass()),
               "实例上不再有 _current_context 属性")
    finally:
        voiceContextModule.VoiceContextModule = realModuleClass
        orchestratorModule.VoiceContextModule = realModuleClass
        voiceContextModule.voiceContextLines = realLines

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
