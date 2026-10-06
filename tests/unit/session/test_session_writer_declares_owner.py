# -*- coding: utf-8 -*-
"""会话写入口必须能声明属主（"共享"要是显式决定，不是默认产物）

缺陷：`SessionManager.save_message()` 建新记录时把 `"user_id": ""` 写死，
签名里根本没有属主入参（`session_manager.py:1289-1299`）。它的两个生产调用方因此
都无法声明归属：

- `console.py:1781` 的 fork —— 侥幸保住：前一行 `create_session(user_id=…)` 已建好带属主
  的文件，`save_message` 走"更新既有记录"分支。这份侥幸没有任何东西守着，
  哪天 fork 改成不先 create 就会静默产出无属主会话。
- `collaboration/room_store.py:44` 的房间消息 —— 直接产出**永远共享**的会话。
  房间按设计是多人可见，所以"共享"本身没错，**错的是它来自默认值而不是声明**。

同一问题的导入侧版本已被修过并写下判据（`import_session_messages` docstring：
"读侧『空属主=任何人可见』是正确的规则，错的是写入口生产了『没有属主』这份状态——
所以修在产生它的那一侧，不去读侧加兜底"）。本批把同一条口径补到 `save_message`。

装配：真 SessionManager（`NEUROVA_SESSIONS_DIR` 隔离）+ 真 ABC，不起 app
——判据在写入口这一层，端点面的分桶行为已由
`test_session_counts_are_user_scoped.py` 与 `test_session_ownership_single_source.py` 覆盖。
"""

import pytest


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    from neurova.session_repository import get_session_repository, reset_session_repository

    reset_session_repository()
    yield get_session_repository()
    reset_session_repository()


def test_saveMessageCanDeclareOwner(repo):
    """carol 经 save_message 建的会话，dave 不该在分桶列表里看到它。"""
    ok = repo.save_message(
        agent_id="agent_x", session_id="s-carol", role="user", content="carol 的私密消息",
        user_id="carol",
    )
    assert ok, "save_message 写入失败"
    others = [s for s in repo.list_sessions(user_id="dave")
              if s.get("session_id") == "s-carol"]
    assert not others, "dave 看到了 carol 声明属主的会话——属主没写进去"
    mine = [s for s in repo.list_sessions(user_id="carol") if s.get("session_id") == "s-carol"]
    assert len(mine) == 1, "carol 看不到自己的会话"


def test_productionCallSitesDeclareOwnerExplicitly():
    """生产代码里每个 `save_message(` 调用都必须显式写 `user_id=`。

    判据为什么不写成"参数无默认值"：那会把 24 个不建模归属的测试调用点全拖进来填
    `user_id=""`，噪声稀释它们原本的断言；而真实风险面只有生产侧两个调用方
    （console 的 fork、collaboration 的房间）。所以按本仓既有形态钉**源码事实**：
    生产目录里的调用点少写一次就红，测试夹具不受牵连。

    房间那条尤其要显式：多人可见是设计决定，不该由"忘了传"得来。
    """
    import pathlib
    import re

    offenders = []
    for path in pathlib.Path("neurova").rglob("*.py"):
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\.save_message\(", src):
            # 取该调用起始后的 400 字符窗口判有没有 user_id=（调用都是短参表）
            window = src[m.end():m.end() + 400]
            if not re.search(r"\buser_id\s*=", window):
                lineNo = src[:m.start()].count("\n") + 1
                offenders.append("%s:%d" % (path, lineNo))
    assert not offenders, (
        "生产侧 save_message 调用未声明属主，会静默产出共享会话（fork 的属主目前只靠"
        "“先 create 再 save” 的顺序侥幸）：" + ", ".join(offenders)
    )


def test_sharedRoomMessageStaysShared(repo):
    """显式共享（房间）必须仍对所有人可见——收紧不许把共享语义顺手关掉。"""
    repo.save_message(agent_id="room-1", session_id="room-1", role="user",
                      content="房间广播", user_id="")
    both = [s for s in repo.list_sessions(user_id="dave") if s.get("session_id") == "room-1"]
    assert len(both) == 1, "显式共享的会话对 dave 不可见了"


def test_forkKeepsForkerAsOwner(repo):
    """fork 的属主不能只靠"先 create 再 save"的顺序侥幸。"""
    sid = repo.create_session(agent_id="agent_x", user_id="erin", title="母会话")
    repo.save_message(agent_id="agent_x", session_id=sid, role="user",
                      content="复制来的消息", user_id="erin")
    forked = repo.find_session(sid)
    assert forked and forked.get("user_id") == "erin", f"fork 后属主丢了：{forked}"
    assert [s for s in repo.list_sessions(user_id="erin") if s["session_id"] == sid]
    assert not [s for s in repo.list_sessions(user_id="mallory") if s["session_id"] == sid]


def test_existingOwnerIsNeverSilentlyRewritten(repo):
    """既有属主是只读事实：后续以他人身份写消息不得改写它。"""
    sid = repo.create_session(agent_id="agent_x", user_id="frank", title="frank 的会话")
    repo.save_message(agent_id="agent_x", session_id=sid, role="assistant",
                      content="补一条", user_id="mallory")
    got = repo.find_session(sid)
    assert got.get("user_id") == "frank", f"属主被后续写入悄悄改了：{got.get('user_id')}"
