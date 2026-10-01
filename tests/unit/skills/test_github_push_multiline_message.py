"""github_push 技能多行 commit message 的红灯测试（Windows git 坑 2）。

'-m' 参数内嵌换行在 Windows 命令行传参时被空格化——多行 message 必须
走 'git commit -F -' + stdin。
"""

import subprocess

import pytest

from neurova.skills.builtin.github_push.skill import GitHubPushSkill


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, encoding="utf-8")
    git("init", "--quiet")
    git("config", "user.name", "t")
    git("config", "user.email", "t@t")
    (repo / "f.txt").write_text("hello", encoding="utf-8")
    return repo


@pytest.mark.asyncio
async def test_multiline_commit_message_preserved(repo):
    skill = GitHubPushSkill()
    skill.repo_path = repo
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)

    result = await skill._commit_changes("标题行\n\n正文第一段")

    assert result.success, result.error
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--format=%s%n%b", "-n1"],
        capture_output=True, encoding="utf-8", check=True)
    assert log.stdout.startswith("标题行\n")  # subject 独立成行
    assert "正文第一段" in log.stdout
    assert "标题行 正文第一段" not in log.stdout  # 未被空格化合并
