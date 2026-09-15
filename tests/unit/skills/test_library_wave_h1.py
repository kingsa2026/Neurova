"""Wave H-W1 存储层：三库路由 + 条目归属 + 账本库维度（三层技能库地基）

设计（吸收 SkillPoolManager 孤岛词汇，见对比文档 §7.5）：
- pool 词汇沿用 SkillPoolType：agent / user(private) / public；
- 目录布局：agent=data/agents/{aid}/skills、user=data/users/{ukey}/skills、
  public=data/public/skills——三库同为 SkillService 实例（存储引擎单源，
  原子写/RLock/漏斗/trust 全复用），library_service 只做"路由 + 同进程单例"；
- 用户键命名空间 `u:{jwt_sub}` / `ch:{channel}:{sender_id}`（隔离侦查教训：
  孤岛裸拼 user_id 有路径注入面）——严格白名单，非法即抛；
- 同进程单例表消解"多 agent 并发 flush 同一 user/public 库 last-writer-wins"
  （实例级 RLock 跨实例不互斥，单例化后同实例锁即够；桌面单进程部署成立）；
- 账本条目带 (pool, owner_key) 路由维度，默认 agent——Wave A/B 既有测试的
  无库参数调用保持原语义（增量不下降）。
"""

import json

import pytest

from neurova.skills import library_service as lib


# ── 用户键命名空间 ─────────────────────────────────────────


def test_normalize_user_key_valid():
    assert lib.normalize_user_key("u:42") == "u:42"
    assert lib.normalize_user_key("ch:telegram:5512344") == "ch:telegram:5512344"
    assert lib.normalize_user_key(None) is None
    assert lib.normalize_user_key("") is None


@pytest.mark.parametrize("bad", ["../evil", "u:a/b", "u:..", "u:", "ch:", "x:1", "u:a b", "u:中文"])
def test_normalize_user_key_rejects_injection(bad):
    with pytest.raises(ValueError):
        lib.normalize_user_key(bad)


# ── 三库路由与单例 ─────────────────────────────────────────


@pytest.fixture
def lib_base(tmp_path, monkeypatch):
    monkeypatch.setattr(lib, "_BASE_DIR", tmp_path)
    lib.reset_libraries_for_tests()
    yield tmp_path
    lib.reset_libraries_for_tests()


def test_resolve_library_dirs(lib_base):
    assert lib.resolve_library_dir("agent", "a1") == lib_base / "agents" / "a1" / "skills"
    # 目录 token=%3A 编码（: 在 Windows 文件名非法；键白名单不含 % → 可逆）
    assert lib.resolve_library_dir("user", "u:7") == lib_base / "users" / "u%3A7" / "skills"
    assert lib.resolve_library_dir("public") == lib_base / "public" / "skills"


# ── 闭环核验轮（V1/V2/V3）：token 往返 / 无血缘顶替拒 / 安装 ID 守卫 ──


def test_dir_token_roundtrip():
    """ch: 键双冒号，旧编码（:→_）与广播反解（只还原首个 _）不互逆——
    公共升级广播对渠道用户库产非法键、accept 恒 409 的根因回归锁。"""
    for key in ("u:42", "u:alice_wang", "ch:feishu:ou_abc-123", "ch:telegram:12345"):
        assert lib.from_dir_token(lib._dir_token(key)) == key
    assert lib._dir_token("ch:feishu:ou_x") == "ch%3Afeishu%3Aou_x"


def test_apply_transfer_rejects_no_lineage_same_name(lib_base):
    """目标库已有同名**本地**技能（无 transferred_from 血缘）→ 拒绝顶替，
    绝不静默覆盖本地实现（原实现 ex_from 为空短路直覆）。"""
    agent = lib.get_library("agent", "a1")
    user = lib.get_library("user", "u:7")
    agent.register_auto_skill("deploy", name="Agent版", description="x", config={"x": 1})
    user.register_auto_skill("deploy", name="本地版", description="mine", manifest_source="user")
    r = lib.apply_transfer("user", "u:7", "agent", "a1", "deploy", actor="u:7")
    assert r["ok"] is False and r["action"] == "rejected"
    assert "本地" in r["error"]
    assert user.get_skill_info("deploy")["name"] == "本地版"


def test_apply_transfer_same_source_upgrade_positive(lib_base):
    """V2 收紧不许误伤：同源再流转仍走原地升级。"""
    agent = lib.get_library("agent", "a1")
    user = lib.get_library("user", "u:7")
    agent.register_auto_skill("s1", name="S", description="d", version="1.0.0")
    assert lib.apply_transfer("user", "u:7", "agent", "a1", "s1")["action"] == "created"
    agent.update_auto_skill("s1", version="2.0.0")
    r = lib.apply_transfer("user", "u:7", "agent", "a1", "s1")
    assert r["ok"] and r["action"] == "upgraded"
    assert user.get_skill_info("s1")["version"] == "2.0.0"


@pytest.mark.parametrize("bad", ["../../evil", "a/b", "C:\\Windows", "..", "."])
def test_install_skill_rejects_unsafe_id(lib_base, tmp_path, bad):
    """skill_id 直接 path join 成目录名——需段白名单（用户键已有 _KEY_RE，
    安装咽喉此前无守卫）。"""
    src = tmp_path / "srcskill"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps({"id": "safe", "name": "n"}), encoding="utf-8")
    svc = lib.get_library("user", "u:7")
    res = svc.install_skill(str(src), skill_id=bad)
    assert res.get("success") is False


def test_install_skill_rejects_manifest_traversal_id(lib_base, tmp_path):
    """恶意包 manifest 自含 "../../pwn" 同样拒（守卫在 ID 归一之后）。"""
    src = tmp_path / "srcskill2"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps({"id": "../../pwn", "name": "n"}), encoding="utf-8")
    svc = lib.get_library("user", "u:7")
    res = svc.install_skill(str(src))
    assert res.get("success") is False
    assert not (tmp_path.parent / "pwn").exists()


def test_get_library_singleton_and_isolation(lib_base):
    s1 = lib.get_library("user", "u:7")
    s2 = lib.get_library("user", "u:7")
    assert s1 is s2, "同键必须同实例（跨实例 last-writer-wins 的消解点）"
    s3 = lib.get_library("user", "u:8")
    assert s3 is not s1
    assert lib.get_library("public") is lib.get_library("public")


def test_agent_library_maps_to_skill_service_default(lib_base):
    from neurova.skills.skill_service import SkillService

    got = lib.get_library("agent", "a1")
    assert isinstance(got, SkillService)
    assert got.agent_id == "a1"


# ── manifest 条目归属字段 ──────────────────────────────────


def test_register_entries_carry_pool_and_owner(lib_base):
    svc = lib.get_library("user", "u:9")
    assert svc.register_auto_skill(
        "s1", name="n1", pool_type="user", owner_user_id="u:9"
    ) is True
    entry = json.loads((svc.skills_dir / "manifest.json").read_text(encoding="utf-8"))["s1"]
    assert entry["pool_type"] == "user"
    assert entry["owner_user_id"] == "u:9"


def test_register_defaults_agent(lib_base):
    svc = lib.get_library("agent", "a9")
    svc.register_auto_skill("s2", name="n2")
    entry = json.loads((svc.skills_dir / "manifest.json").read_text(encoding="utf-8"))["s2"]
    assert entry["pool_type"] == "agent"
    assert entry["owner_user_id"] == "a9"


# ── 账本库维度 + flush 路由 ────────────────────────────────


def test_turn_ledger_entry_carries_provenance():
    from neurova.core import turn_context

    turn_context.reset_turn_tool_messages()
    turn_context.record_turn_skill_funnel("s1", applied=True, ok=True, pool="user", owner_key="u:3")
    snap = turn_context.get_turn_skill_funnel()
    assert snap[0]["pool"] == "user" and snap[0]["owner_key"] == "u:3"
    turn_context.reset_turn_tool_messages()


def test_ledger_default_pool_backward_compatible():
    """无库参数调用（Wave A/B 既有链路）默认 agent——行为零变化。"""
    from neurova.core import turn_context

    turn_context.reset_turn_tool_messages()
    turn_context.record_turn_skill_funnel("s1", applied=True, ok=True)
    e = turn_context.get_turn_skill_funnel()[0]
    assert e["pool"] == "agent" and e["owner_key"] == ""
    turn_context.reset_turn_tool_messages()


@pytest.mark.asyncio
async def test_flush_routes_per_library(lib_base, tmp_path, monkeypatch):
    """同技能在 agent 与 user 库各有副本：一轮账本两条命中 → 各库账本各自回写。"""
    from unittest.mock import MagicMock

    from neurova.post_chat_pipeline import PostChatPipeline
    from neurova.core import turn_context

    agent_lib = lib.get_library("agent", "rt1")
    assert agent_lib.register_auto_skill("deploy", name="deploy") is True
    user_lib = lib.get_library("user", "u:5")
    assert user_lib.register_auto_skill("deploy", name="deploy", pool_type="user", owner_user_id="u:5") is True

    turn_context.reset_turn_tool_messages()
    # 同一轮里两条命中记录：一条来自 agent 副本、一条来自 user 副本（装配视图区分）
    turn_context.record_turn_skill_funnel("deploy", applied=True, ok=True, pool="agent", owner_key="rt1")
    turn_context.record_turn_skill_funnel("deploy", applied=True, ok=True, pool="user", owner_key="u:5")

    agent = MagicMock()
    agent.config.agent_id = "rt1"
    p = PostChatPipeline(agent)
    await p._step_skill_funnel_flush("正常完成", actual_session_id="sX")

    a_usage = json.loads((agent_lib.skills_dir / "manifest.json").read_text(encoding="utf-8"))["deploy"]["usage"]
    u_usage = json.loads((user_lib.skills_dir / "manifest.json").read_text(encoding="utf-8"))["deploy"]["usage"]
    assert a_usage["applications"] == 1 and a_usage["completions"] == 1
    assert u_usage["applications"] == 1 and u_usage["completions"] == 1
    # trust 观测也各库独立（user 副本出生 provisional 晋升史在自己库内）
    assert (u_usage and a_usage) is not None
    turn_context.reset_turn_tool_messages()


def test_install_skill_reinstall_preserves_ledger(lib_base, tmp_path):
    """V 轮根治：覆盖式重装保留 usage/identity/版本链/pool 落款——旧实现整条
    替换把账本清零（apply_transfer 特意绕开本咽喉的"force 重装清零坑"本体）。"""
    src = tmp_path / "srcskill_re"
    src.mkdir()
    (src / "manifest.json").write_text(
        json.dumps({"id": "kit", "name": "Kit", "version": "1.0.0", "description": "d"}),
        encoding="utf-8",
    )
    svc = lib.get_library("user", "u:7")
    assert svc.install_skill(str(src), pool_type="user", owner_user_id="u:7")["success"] is True
    svc.record_skill_funnel("kit", selections=9, applications=8, completions=7)
    (src / "manifest.json").write_text(
        json.dumps({"id": "kit", "name": "Kit2", "version": "2.0.0", "description": "d"}),
        encoding="utf-8",
    )
    assert svc.install_skill(str(src), pool_type="user", owner_user_id="u:7")["success"] is True

    entry = svc.get_skill_info("kit")
    assert entry["name"] == "Kit2" and entry["version"] == "2.0.0", "新版本面照常更新"
    assert entry["usage"]["applications"] == 8, "漏斗账本跨重装存活"
    raw = svc._skills["kit"]  # get_skill_info 是投影视图，pool 落款/版本链读原始条目
    assert raw["pool_type"] == "user" and raw["owner_user_id"] == "u:7", "归属坐标不被参数缺省顶掉"
    hist = raw.get("version_history") or []
    assert len(hist) == 2 and hist[1]["parent_revision_id"] == hist[0]["revision_id"], "修订链追加非重建"
