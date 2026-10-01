"""Windows git 三坑的根因级防线 — git_runner 单源的红灯测试。

坑 1：subprocess 文本模式把 stdin 的 '\n' 翻译成 '\r\n'（污染 mktree
      路径/blob 内容）→ transport 必须二进制，str stdin 统一 utf-8 编码；
坑 2：'-m' 参数内嵌换行被 Windows 命令行传参空格化 → 多行 message 永远
      走 stdin（commit-tree / commit -F -）；
坑 3：git 的 %s 会把首个空行前的所有行折叠成 subject → subject 与 body
      之间强制空行。
"""

import subprocess

import pytest

from neurova.core.git_runner import commit_message, run_git


@pytest.fixture
def bare(tmp_path):
    """一个已初始化的 bare 仓。"""
    d = tmp_path / "fixture.git"
    proc = run_git("init", "--bare", "--quiet", str(d))
    assert proc.returncode == 0
    return d


class TestPitfall1BinaryTransport:
    def test_str_stdin_is_lf_not_crlf(self, bare):
        """str stdin 经 utf-8/LF 编码：'a\\nb' 与 bytes b'a\\nb' 得到同一
        blob sha——若发生 CRLF 翻译则 sha 必然不同。"""
        by_str = run_git("hash-object", "--stdin", git_dir=str(bare), stdin="a\nb")
        by_bytes = run_git("hash-object", "--stdin", git_dir=str(bare), stdin=b"a\nb")
        assert by_str.returncode == 0
        assert by_str.stdout == by_bytes.stdout

    def test_mktree_path_survives_newline(self, bare):
        """mktree 的路径条目不被 CRLF 污染（实测事故形态：路径变 's1.txt\\r'）。
        blob sha 用确定性内容断言。"""
        blob = run_git("hash-object", "-w", "--stdin", git_dir=str(bare),
                       stdin="新正文v1")
        blob_sha = blob.stdout.decode("ascii").strip()
        tree = run_git("mktree", git_dir=str(bare),
                       stdin=f"100644 blob {blob_sha}\ts1.txt\n")
        assert tree.returncode == 0, tree.stderr
        ls = run_git("ls-tree", tree.stdout.decode("ascii").strip(), git_dir=str(bare))
        assert ls.stdout.decode("utf-8").strip().endswith("\ts1.txt")


class TestPitfall2And3CommitMessage:
    def test_commit_tree_stdin_preserves_newlines(self, bare):
        """多行 message 走 stdin：commit 对象保留换行，%s 只出 subject 行。"""
        blob = run_git("hash-object", "-w", "--stdin", git_dir=str(bare), stdin="x")
        blob_sha = blob.stdout.decode("ascii").strip()
        tree = run_git("mktree", git_dir=str(bare),
                       stdin=f"100644 blob {blob_sha}\tf.txt\n")
        msg = commit_message("evolution: s1 evo_a", '{"holdout_after": 0.9}')
        commit = run_git("commit-tree", tree.stdout.decode("ascii").strip(),
                         git_dir=str(bare), stdin=msg)
        assert commit.returncode == 0, commit.stderr
        run_git("update-ref", "refs/heads/main", commit.stdout.decode("ascii").strip(),
                git_dir=str(bare))
        # %s 只含 subject（body 不并入）——坑 3 的钉子
        subject = run_git("log", "--format=%s", "-n1", "refs/heads/main", git_dir=str(bare))
        assert subject.stdout.decode("utf-8").strip() == "evolution: s1 evo_a"
        # %B 保留换行——坑 2 的钉子
        body = run_git("log", "--format=%b", "-n1", "refs/heads/main", git_dir=str(bare))
        assert body.stdout.decode("utf-8").strip() == '{"holdout_after": 0.9}'

    def test_commit_message_blank_line(self):
        assert commit_message("subj", "body") == "subj\n\nbody"
        assert commit_message("subj") == "subj"
        assert commit_message("subj", "") == "subj"


class TestCommitFDash:
    def test_git_commit_f_dash_multiline(self, tmp_path):
        """坑 2 的用户面修复：'git commit -F -' 多行 message 逐字保留
        （-m 形态在 Windows 下会被空格化）。"""
        repo = tmp_path / "work"
        repo.mkdir()
        env_extra = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                     "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

        def git(*args, stdin=None):
            proc = run_git(*args, cwd=str(repo), stdin=stdin, env_extra=env_extra)
            assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
            return proc

        git("init", "--quiet")
        (repo / "f.txt").write_text("hello", encoding="utf-8")
        git("add", "f.txt")
        git("commit", "-F", "-", "--quiet", stdin="标题行\n\n正文第一段\n正文第二段")
        subject = git("log", "--format=%s", "-n1")
        body = git("log", "--format=%b", "-n1")
        assert subject.stdout.decode("utf-8").strip() == "标题行"
        assert body.stdout.decode("utf-8").strip() == "正文第一段\n正文第二段"
