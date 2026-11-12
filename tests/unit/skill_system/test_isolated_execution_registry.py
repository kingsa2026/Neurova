# -*- coding: utf-8 -*-
"""P2-14 execute_skill_isolated 子进程重建注册表红测（全库断点审计 2026-11-12）。

缺陷：隔离执行的子进程代码跑 `SkillRegistry()`——**空注册表**（builtin 技能
的注册只在父进程 create_default_registry 里发生），任何技能在子进程里都落
"Skill 不存在"；外层再静默降级回普通执行——隔离语义名存实亡。

修复口径（审计开方，拍板：真实现）：子进程改用 create_default_registry()
重建同一套注册表，隔离执行真正可跑。
"""
import json
import os
import subprocess
import sys

import pytest


@pytest.fixture
def registry():
    from neurova.skill_system.core import create_default_skills

    return create_default_skills()


@pytest.mark.asyncio
async def test_isolated_execution_rebuilds_registry(registry, monkeypatch):
    import neurova.execution_layers as execution_layers

    captured: dict = {}

    class FakeRuntime:
        async def start(self):
            return None

        async def stop(self):
            return None

        async def exec(self, command, args, env, timeout):
            captured["command"] = command
            captured["args"] = list(args)
            captured["env"] = env

            class _Result:
                success = True
                stdout = "{}"
                stderr = ""
                error = None

            return _Result()

    class FakeFactory:
        @staticmethod
        def create(runtime_type, runtime_id=None):
            return FakeRuntime()

    monkeypatch.setattr(execution_layers, "RuntimeFactory", FakeFactory)

    result = await registry.execute_skill_isolated(
        "memory", {"action": "store", "content": "x"}, runtime_type="local"
    )

    code = captured["args"][1]
    assert "create_default_skills" in code, (
        f"子进程必须重建注册表（原 SkillRegistry() 空表 → 任何技能'不存在'）：{code}"
    )

    # 真跑一遍捕获的子进程代码：技能必须能解析并执行（而非报"不存在"）
    env = dict(os.environ)
    env.update(captured["env"])
    proc = subprocess.run(
        [sys.executable] + captured["args"],
        capture_output=True, text=True, timeout=180, env=env,
    )
    payload = json.loads(proc.stdout or "{}")
    assert payload.get("success") is True, (
        f"子进程重建注册表后技能仍未能执行：stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
