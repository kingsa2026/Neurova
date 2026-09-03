"""社交平台凭据按用户分桶测试（TDD 红绿）—— 遗留项：登录态凭据服务器全局共享

修复目标（docs/agent-reach-integration.md 遗留项）：
1. UserCredentialStore：按 (user_id) 分桶的 agent-reach 凭据管理
   - 每用户独立 config.yaml（经 agent-reach Config 的 config_path 指向用户桶）
   - 凭据值经 Neurova SecretStore 加密落盘（明文不落磁盘）
2. social_search 真实执行路径：后端就绪时用该用户桶注入凭据执行上游 CLI
   （env 隔离：TWITTER_AUTH_TOKEN/TWITTER_CT0 仅存在于子进程环境）
3. 隔离断言：用户 A 的凭据对 B 不可见；未配置用户仍走 needs_setup 引导
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from neurova.web_reach.reach import _SOCIAL_CHANNELS


class TestUserCredentialStore:
    def test_store_and_get_roundtrip(self, tmp_path):
        from neurova.web_reach.credentials import UserCredentialStore

        store = UserCredentialStore(base_dir=str(tmp_path))
        store.set_credential("user-7", "twitter_auth_token", "tok-value")

        assert store.get_credential("user-7", "twitter_auth_token") == "tok-value"
        assert store.get_credential("user-8", "twitter_auth_token") is None  # 跨用户不可见

    def test_per_user_bucket_files_isolated(self, tmp_path):
        from neurova.web_reach.credentials import UserCredentialStore

        store = UserCredentialStore(base_dir=str(tmp_path))
        store.set_credential("user-7", "twitter_auth_token", "tok-a")
        store.set_credential("user-8", "twitter_auth_token", "tok-b")

        # 分桶落盘：不同用户不同文件
        assert (tmp_path / "user-7").exists()
        assert (tmp_path / "user-8").exists()

        # 明文不落盘（经 SecretStore 加密）
        raw = (tmp_path / "user-7" / "secrets.json").read_text(encoding="utf-8")
        assert "tok-a" not in raw

    def test_delete_credential_scoped(self, tmp_path):
        from neurova.web_reach.credentials import UserCredentialStore

        store = UserCredentialStore(base_dir=str(tmp_path))
        store.set_credential("user-7", "twitter_auth_token", "tok-a")
        store.set_credential("user-8", "twitter_auth_token", "tok-b")

        assert store.delete_credential("user-7", "twitter_auth_token") is True
        assert store.get_credential("user-7", "twitter_auth_token") is None
        assert store.get_credential("user-8", "twitter_auth_token") == "tok-b"

    def test_list_platform_status(self, tmp_path):
        from neurova.web_reach.credentials import UserCredentialStore

        store = UserCredentialStore(base_dir=str(tmp_path))
        store.set_credential("user-7", "twitter_auth_token", "t")
        store.set_credential("user-7", "twitter_ct0", "c")

        status = store.list_platforms("user-7")
        assert "twitter" in status and status["twitter"] is True
        assert "reddit" not in status or status.get("reddit") is False


class TestReachConfigPath:
    def test_config_path_points_to_user_bucket(self, tmp_path):
        """agent-reach Config 指向用户桶路径（上游 HOME 隔离姿势）"""
        from neurova.web_reach.credentials import user_config_path

        p = user_config_path("user-7", base_dir=str(tmp_path))
        assert str(tmp_path / "user-7" / "config.yaml") == str(p)

    def test_config_loads_user_yaml(self, tmp_path):
        from agent_reach.config import Config

        from neurova.web_reach.credentials import user_config_path

        p = user_config_path("user-7", base_dir=str(tmp_path))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("twitter_auth_token: from-yaml\n", encoding="utf-8")

        cfg = Config(config_path=p, read_only=True)
        assert cfg.get("twitter_auth_token") == "from-yaml"


class TestSocialSearchRealExecution:
    @pytest.mark.asyncio
    async def test_executes_with_user_env_isolation(self, tmp_path):
        """后端就绪 + 用户有凭据 → 经 env 注入执行上游 CLI，凭据不进返回值/日志"""
        from neurova.web_reach import reach

        store = reach.get_credential_store.__wrapped__() if hasattr(reach.get_credential_store, "__wrapped__") else None
        # 直接构造独立 store 注入
        from neurova.web_reach.credentials import UserCredentialStore

        cred_store = UserCredentialStore(base_dir=str(tmp_path / "creds"))
        cred_store.set_credential("user-7", "twitter_auth_token", "tok-secret")
        cred_store.set_credential("user-7", "twitter_ct0", "ct0-secret")

        fake_doctor = {"channels": {"twitter": {"active_backend": "twitter-cli"}}}
        fake_run = MagicMock(returncode=0, stdout='[{"text": "tweet about agents"}]', stderr="")

        with (
            patch.object(reach, "run_doctor", return_value=fake_doctor),
            patch.object(reach, "get_credential_store", return_value=cred_store),
            patch("neurova.web_reach.social_exec.subprocess.run", return_value=fake_run) as run_mock,
        ):
            result = reach.social_search("twitter", "neurova", user_id="user-7")

        assert result["success"] is True
        assert result["executed"] is True
        assert "tweet about agents" in json.dumps(result["results"], ensure_ascii=False)
        # 凭据只进子进程 env，不进返回值
        assert "tok-secret" not in json.dumps(result, default=str)
        env = run_mock.call_args.kwargs.get("env") or run_mock.call_args.kwargs["env"]
        assert env["TWITTER_AUTH_TOKEN"] == "tok-secret"
        assert env["TWITTER_CT0"] == "ct0-secret"

    @pytest.mark.asyncio
    async def test_no_credentials_still_setup_guide(self, tmp_path):
        """后端就绪但该用户无凭据 → 仍走 needs_setup（不借用他人凭据）"""
        from neurova.web_reach import reach
        from neurova.web_reach.credentials import UserCredentialStore

        cred_store = UserCredentialStore(base_dir=str(tmp_path / "creds"))
        fake_doctor = {"channels": {"twitter": {"active_backend": "twitter-cli"}}}

        with (
            patch.object(reach, "run_doctor", return_value=fake_doctor),
            patch.object(reach, "get_credential_store", return_value=cred_store),
        ):
            result = reach.social_search("twitter", "x", user_id="user-7")

        assert result["success"] is False
        assert result["needs_setup"] is True

    @pytest.mark.asyncio
    async def test_executor_passes_request_user(self, tmp_path):
        """tool_executor 分发 social_search 时注入请求级用户身份（_current_user_id）"""
        from neurova.tool_executor import ToolExecutor
        from neurova.web_reach import reach as reach_mod

        agent = MagicMock()
        agent._current_user_id = "user-42"
        exe = ToolExecutor(agent)

        captured = {}

        def fake_social_search(platform, query, limit=10, user_id=None):
            captured["user_id"] = user_id
            return {"success": True, "data": {"results": []}}

        with (
            patch("neurova.web_reach.social_search", new=fake_social_search),
            patch("neurova.web_reach.reach.run_doctor", return_value={}),
        ):
            result = await exe._execute_social_search({"platform": "twitter", "query": "x"})

        assert result["success"] is True
        assert captured["user_id"] == "user-42"


class _AgentStub:
    pass
