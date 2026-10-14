# -*- coding: utf-8 -*-
"""live-verify（批 §6-209）：用户回执经真 HTTP 端点补进结晶器证据面，寒暄轮不吃票。

单元档在端点接缝上装桩（同族现行做法）；这一支要证的是**真装配**下的四件事：

1. 真 `create_app()` + 真 agent 的真 `crystallizer` + 真会话仓储落的一轮真对话；
2. 对该轮点赞 ⇒ 盘上 `crystallizer_state.json` 的 `evidenced` 由 0 变 1，
   而 `observations` **不变**（补票不是新增一次观察，否则 `min_observations` 被虚增绕过）；
3. 纯对话轮（伪工具 `chat`，用户裁定甲明确排除）点赞后 `evidenced` 仍 0；
4. 反证：不点赞时 `evidenced` 必须仍是 0——否则"变 1"可能来自别处（例如 observe 自己写了票）。

鉴权依赖按端点模块实际 import 的那个名字走 `dependency_overrides`，不伪造管理员凭证。

跑法（仓库根）：

    PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe -m tests.manual.crystallizerEvidenceFromFeedbackLive
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

READINGS: dict = {}
FAILURES: list[str] = []
TOOL_QUESTION = "帮我查一下北京明天的天气并给出行衣建议"
CHAT_QUESTION = "晚上好呀，今天有点无聊想聊两句"


def _evidenceTotals(statePath: Path):
    """状态文件里的 (观察数, 有票数)——按聚合形态读，与重启恢复口径同一份。"""
    if not statePath.exists():
        return (-1, -1)
    data = json.loads(statePath.read_text(encoding="utf-8"))
    obs = ev = 0
    for key, agg in data.items():
        if key == "pending" or not isinstance(agg, dict):
            continue
        obs += int(agg.get("observations", 0) or 0)
        ev += int(agg.get("evidenced", 0) or 0)
    return (obs, ev)


def main() -> int:
    from tests.manual._liveVerifyIsolation import (
        isolatedAgentWorkspaces,
        isolatedDataRoot,
    )

    isolatedDataRoot(prefix="neurovaCryEvidence")
    isolatedAgentWorkspaces(prefix="neurovaCryEvidence")

    from fastapi.testclient import TestClient

    import neurova.api.endpoints.console as consoleModule
    from neurova.api.app import create_app
    from neurova.api.endpoints import get_agent_instance
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import CHAT_PSEUDO_TOOL
    from neurova.session_repository import get_session_repository

    app = create_app()
    app.dependency_overrides[consoleModule.get_current_user] = lambda: {
        "id": "live-cr", "username": "live-cr", "user_id": "live-cr"}
    consoleModule._get_user_id = lambda *a: "live-cr"

    repo = get_session_repository()
    sessionId = "live-cry-evidence"
    userText = "live-cr"

    with TestClient(app) as client:
        # 认知图在 lifespan 里装配：agent 必须在 with 之内取，否则拿到的是 None
        READINGS["app_boot"] = "ok"
        agent = get_agent_instance(agent_id="default")
        cry = getattr(agent, "crystallizer", None) if agent else None
        READINGS["agent_has_crystallizer"] = cry is not None
        if cry is None:
            print(json.dumps(READINGS, ensure_ascii=False))
            print("[FAIL] 真 agent 没装配结晶器，本支无从取证")
            raise SystemExit(1)
        statePath = Path(cry._state_path)

        # ── 1. 真路观察一轮工具调用（closed_loop 用的就是 observe 这个口）──
        cry.observe(tool_name="web_search", context=TOOL_QUESTION, success=None)
        cry.observe(tool_name=CHAT_PSEUDO_TOOL, context=CHAT_QUESTION, success=None)
        baseObs, baseEv = _evidenceTotals(statePath)
        READINGS["before"] = {"observations": baseObs, "evidenced": baseEv}

        # ── 2. 反证：一条都没赞的时候 evidenced 必须是 0 ──
        if baseEv != 0:
            FAILURES.append("未点赞时 evidenced=%s，应为 0——那“变 1”就不是本批带来的" % baseEv)

        # ── 3. 落一轮真对话，再经真 HTTP 端点点赞 ──
        repo.save_message(agent_id="default", session_id=sessionId, role="user",
                          content=TOOL_QUESTION, user_id=userText)
        repo.save_message(agent_id="default", session_id=sessionId, role="assistant",
                          content="北京明天晴，18 度，建议带薄外套", user_id=userText)
        history = repo.get_history(agent_id="default", session_id=sessionId)
        stamps = [m.get("timestamp") for m in history if m.get("role") == "assistant"]
        READINGS["assistant_round_found"] = bool(stamps)
        if not stamps:
            FAILURES.append("会话里读不到 assistant 轮次，反馈端点无从定位")
            print(json.dumps(READINGS, ensure_ascii=False, indent=2))
            return 1

        resp = client.post("/api/v1/console/chat/feedback",
                                          json={"session_id": sessionId,
                                                "timestamp": stamps[-1], "feedback": "like"})
        READINGS["feedback_status"] = resp.status_code
        likeObs, likeEv = _evidenceTotals(statePath)
        READINGS["after_like"] = {"observations": likeObs, "evidenced": likeEv}

        # ── 4. 寒暄轮点赞：evidenced 不得增长（裁定甲）──
        repo.save_message(agent_id="default", session_id=sessionId, role="user",
                          content=CHAT_QUESTION, user_id=userText)
        repo.save_message(agent_id="default", session_id=sessionId, role="assistant",
                          content="是呀，陪你聊聊", user_id=userText)
        history2 = repo.get_history(agent_id="default", session_id=sessionId)
        chatStamps = [m.get("timestamp") for m in history2 if m.get("role") == "assistant"]
        resp2 = client.post("/api/v1/console/chat/feedback",
                                            json={"session_id": sessionId,
                                                  "timestamp": chatStamps[-1], "feedback": "like"})
        READINGS["chat_feedback_status"] = resp2.status_code
        chatObs, chatEv = _evidenceTotals(statePath)
        READINGS["after_chat_like"] = {"observations": chatObs, "evidenced": chatEv}

    if READINGS.get("feedback_status") != 200:
        FAILURES.append("反馈端点没通（%s）" % READINGS.get("feedback_status"))
    if likeEv != 1:
        FAILURES.append("工具轮点赞后 evidenced=%s，应为 1（回执没到结晶器）" % likeEv)
    if likeObs != baseObs:
        FAILURES.append("补票把观察数也改了：%s → %s（min_observations 被虚增绕过）"
                        % (baseObs, likeObs))
    if chatEv != 1:
        FAILURES.append("寒暄轮点赞改变了 evidenced（%s）——裁定甲被绕过" % chatEv)
    if chatObs != likeObs:
        FAILURES.append("寒暄轮又新增了一次观察：%s → %s" % (likeObs, chatObs))

    print(json.dumps(READINGS, ensure_ascii=False, indent=2))
    for f in FAILURES:
        print("[FAIL] " + f)
    if FAILURES:
        return 1
    print("LIVE-PASS：真 HTTP 回执补进结晶证据（observations 不变、evidenced 0→1），"
          "寒暄轮按裁定甲不吃票")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
