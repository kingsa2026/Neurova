"""凭据桶与 social_search 隔离面测试

现状（2026-11-12 agent_reach CLI 面收口后）：
1. UserCredentialStore：按 (user_id) 分桶的凭据管理——凭据值经 Neurova
   SecretStore 加密落盘（明文不落磁盘）。消费方：SSH 主机凭据（ssh_runner）、
   RDP 凭据（rdp_provider）、设置面读写（settings 端点）。
2. social_search 已切 CLI 面：登录态归上游 agent-reach 自己的浏览器会话，
   reach 模块不再引用凭据桶（旧 per-user env 注入路径 social_exec 已退役）。
   用户 A 的凭据对 B 不可见的桶级断言见 TestUserCredentialStore。
"""

import pytest


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


class TestSocialSearchCliFace:
    def test_social_search_detached_from_credential_store(self, monkeypatch):
        """CLI 面集成（教义第 7 条收口）：social_search 不读凭据桶、不接 user_id。

        登录态归上游 agent-reach 的浏览器会话；渠道就绪即执行，无需任何
        本仓凭据配置。旧路径（per-user env 注入）连同 social_exec 一并退役。
        """
        from neurova.web_reach import agent_reach_cli as cli
        from neurova.web_reach import reach

        # 结构格：reach 不得再引用凭据桶读取口
        assert not hasattr(reach, "get_credential_store"), (
            "reach 又引用了凭据桶——CLI 面下登录态归上游，本仓凭据桶不进工具执行路径"
        )

        monkeypatch.setattr(
            cli,
            "runDoctor",
            lambda: {
                "success": True,
                "version": "1.6.0",
                "data": {"channels": [{"channel": "twitter", "status": "unverified"}]},
            },
        )
        monkeypatch.setattr(
            cli,
            "runChannelAction",
            lambda *a, **kw: {"success": True, "backend": "opencli", "items": [{"title": "t1"}]},
        )
        result = reach.social_search("twitter", "neurova")  # 无任何凭据配置

        assert result["success"] is True
        assert result["platform"] == "twitter"
