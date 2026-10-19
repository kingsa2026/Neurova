"""刀3（先行）：技能符号只允许一条取用路径（红→绿 TDD）

修复前实测缺陷（同一批符号三条取用路径的实体）：
- 顶层 `neurova/skill_system.py` 被同名包 **遮蔽**，包 `__getattr__` 再用
  `spec_from_file_location` 把它按路径 exec 回来（cache key
  `neurova.skill_system_module_standalone`）——取一次符号即多一个模块键；
- 门面 re-export 的 `SkillResult` 指 `skills/executor.py:20`（output 形状），
  而注册表与 agent 热路径（`agent/loops/base.py:568` 读 `.data`）实际返回
  影子文件 `:32` 那份——公共名与实物不符；
- 影子文件自己还在 `:638` 用幽灵名 `import neurova.skill_system_module_standalone`
  反向指认自己。

判据只锁三件事：门面给出的类 == 运行时真正返回的类；取符号不再触发第二次
exec；被遮蔽的同名文件退役。
"""

import asyncio
import sys
from pathlib import Path

import neurova.skill_system as facade

REPO_ROOT = Path(__file__).resolve().parents[3]

#: 扫描根单点，必须写在模块级：绑在函数里的名字，面自证棘轮的取数口认不出，整档会静默掉出它的面。
NEUROVA = REPO_ROOT / "neurova"


def testFacadeSkillResultIsWhatRuntimeReturns():
    """门面所发 SkillResult 必须是运行时 execute() 实际返回的那个类。"""
    from neurova.skill_system import ToolSequenceSkill

    result = asyncio.run(ToolSequenceSkill("probeSeq", "", []).execute({}, None))
    assert not result.success, "空序列应失败——探针不得走到成功分支"
    assert type(result) is facade.SkillResult, (
        f"门面名 SkillResult 指向 {facade.SkillResult.__module__}.{facade.SkillResult.__name__}，"
        f"而运行时返回的是 {type(result).__module__}.{type(result).__name__}——名实不符"
    )


def testTouchingFacadeSymbolsStartsNoSecondExec():
    """逐个取门面符号后，进程内不得存在任何 skill_system 的反射 exec 缓存键。

    判据取"集合为空"而非"没有新增"：后者会被同会话里先跑的测试喂成恒真
    （门面早在上一个用例就把键塞进 sys.modules），守卫形同虚设。
    """
    ghostPrefix = "neurova.skill_system_module"
    for name in facade.__all__:
        getattr(facade, name)
    present = sorted(k for k in sys.modules if k.startswith(ghostPrefix))
    assert not present, (
        f"技能系统存在反射 exec 的模块键 {present}——同一批符号有了第二条取用路径"
    )


def testShadowFileIsRetired():
    """被同名包遮蔽的顶层 skill_system.py 必须退役（遮蔽本身即根病灶）。"""
    shadow = REPO_ROOT / "neurova" / "skill_system.py"
    assert not shadow.exists(), (
        f"{shadow} 仍在——只要它与同名包并存，import 永不到达它，"
        "所有取用只能靠 importlib 后门，双源就无法收敛"
    )


def testNoSourceReflectivelyLoadsSkillSystem():
    """源级防回流：不得再按路径反射加载技能系统。

    仓内 `spec_from_file_location` 另有正当用途（plugin_manager 载插件、
    skill_service 载用户脚本），判据只锁"反射加载 skill_system"这一条。
    """
    sources = sorted(NEUROVA.rglob("*.py"))
    assert len(sources) > 500, (
        f"扫描面现读 {len(sources)} 档（根＝{NEUROVA}）——量级对不上生产源码总数＝根被改窄")
    offenders = [
        str(p.relative_to(NEUROVA))
        for p in sources
        if "spec_from_file_location" in (body := p.read_text(encoding="utf-8", errors="replace"))
        and "skill_system" in body
    ]
    assert not offenders, f"仍有按路径反射加载 skill_system 的落点：{offenders}"


def testBridgeSkillIsRuntimeSkill():
    """executor→Skill 桥接体必须是运行时 Skill 的实例。

    该桥接当年为绕开"包占位类"而自包含实现，不继承基类；遮蔽消解后这个
     workaround 没有理由留着——`SkillRegistry.register_skill()` 的
    `isinstance(manifest, Skill)` 分支对内置技能同样静默走错路。
    """
    from neurova.skills.executor import BaseSkillExecutor, ExecutorBackedSkill

    class _ProbeExecutor(BaseSkillExecutor):
        def execute(self, params, *args, **kwargs):
            from neurova.skills.executor import SkillResult

            return SkillResult(success=True, output={"echo": dict(params or {})})

    bridge = ExecutorBackedSkill(_ProbeExecutor("probe_bridge"))
    assert isinstance(bridge, facade.Skill), (
        "桥接技能不是运行时 Skill 实例——注册表按类型分支的入口对它失效"
    )


def testBridgeReturnsRuntimeSkillResult():
    """桥接返回的结果类必须是门面所发 SkillResult（名实一致）。"""
    from neurova.skills.executor import BaseSkillExecutor, ExecutorBackedSkill, SkillResult

    class _ProbeExecutor(BaseSkillExecutor):
        def execute(self, params, *args, **kwargs):
            return SkillResult(success=True, output={"echo": dict(params or {})})

    bridge = ExecutorBackedSkill(_ProbeExecutor("probe_bridge"))
    result = asyncio.run(bridge.execute({"k": 1}, None))
    assert type(result) is facade.SkillResult, (
        f"桥接返回 {type(result).__module__}.{type(result).__name__}，"
        "与门面名不符——同一符号又多一份定义"
    )
