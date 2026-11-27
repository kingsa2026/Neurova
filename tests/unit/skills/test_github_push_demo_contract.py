import asyncio

from examples import github_push_demo


def testDemoRendersCurrentListParameterSchema(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(github_push_demo.tempfile, "mkdtemp", lambda prefix: str(tmp_path))

    asyncio.run(github_push_demo.demo_github_push_skill())

    output = capsys.readouterr().out
    assert "参数: action, message, files, push_to_main, branch, repo_path" in output
    assert "演示完成" in output
