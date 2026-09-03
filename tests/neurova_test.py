"""
Neurova 功能测试脚本
测试系统各项核心功能的完整性和正确性
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 测试结果收集
test_results = {
    "timestamp": datetime.now().isoformat(),
    "tests": [],
    "summary": {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0
    }
}


def log_test(name: str, status: str, message: str = "", details: dict = None):
    """记录测试结果"""
    test_results["tests"].append({
        "name": name,
        "status": status,
        "message": message,
        "details": details or {},
        "timestamp": datetime.now().isoformat()
    })
    test_results["summary"]["total"] += 1
    if status == "passed":
        test_results["summary"]["passed"] += 1
        print(f"✅ {name}: {message}")
    elif status == "failed":
        test_results["summary"]["failed"] += 1
        print(f"❌ {name}: {message}")
    else:
        test_results["summary"]["skipped"] += 1
        print(f"⏭️ {name}: {message}")


async def test_imports():
    """测试1: 验证核心模块导入"""
    print("\n" + "="*60)
    print("测试1: 验证核心模块导入")
    print("="*60)

    modules_to_test = [
        ("neurova.agent", "Agent核心"),
        ("neurova.router", "消息路由"),
        ("neurova.memory_rw_manager", "记忆读写"),
        ("neurova.context", "上下文管理"),
        ("neurova.context_compressor", "上下文压缩"),
        ("neurova.tool_layers.tool_router", "工具路由"),
        ("neurova.skills.registry", "Skill注册"),
        ("neurova.cognitive_layers.memory_layer.manager", "记忆管理"),
        ("neurova.api.endpoints.chat", "Chat API"),
        ("neurova.api.endpoints.media", "Media API"),
        ("neurova.api.endpoints.channel", "Channel API"),
        ("neurova.api.auth", "认证模块"),
        ("neurova.security.rbac", "RBAC权限"),
        ("neurova.tts.manager", "TTS管理"),
    ]

    passed = 0
    failed = 0

    for module_path, module_name in modules_to_test:
        try:
            module = __import__(module_path, fromlist=[''])
            if module:
                print(f"  ✅ {module_name} ({module_path})")
                passed += 1
            else:
                print(f"  ❌ {module_name}: 模块为空")
                failed += 1
        except Exception as e:
            print(f"  ❌ {module_name}: {str(e)[:80]}")
            failed += 1

    log_test(
        "核心模块导入",
        "passed" if failed == 0 else "failed",
        f"成功 {passed}/{len(modules_to_test)}",
        {"passed": passed, "failed": failed, "total": len(modules_to_test)}
    )


async def test_agent_initialization():
    """测试2: 验证Agent初始化"""
    print("\n" + "="*60)
    print("测试2: 验证Agent初始化")
    print("="*60)

    try:
        from neurova.agent import Agent, AgentConfig

        config = AgentConfig(
            name="TestAgent",
            agent_id="test_agent",
            workspace_path="data/test_agent",
            db_path="data/test_agent/memory.db",
        )

        agent = Agent(config)

        checks = [
            ("name", agent.config.name == "TestAgent"),
            ("agent_id", agent.config.agent_id == "test_agent"),
            ("conversation_history", hasattr(agent, 'conversation_history')),
            ("memory_manager", hasattr(agent, 'memory_manager')),
            ("tool_memory", hasattr(agent, 'tool_memory')),
            ("context_builder", hasattr(agent, 'context_builder')),
        ]

        all_passed = True
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}: {result}")
            if not result:
                all_passed = False

        log_test(
            "Agent初始化",
            "passed" if all_passed else "failed",
            f"Agent '{agent.config.name}' 初始化成功" if all_passed else "Agent初始化失败"
        )

        return agent

    except Exception as e:
        log_test("Agent初始化", "failed", str(e))
        return None


async def test_memory_operations(agent):
    """测试3: 验证记忆操作"""
    print("\n" + "="*60)
    print("测试3: 验证记忆操作")
    print("="*60)

    if not agent or not hasattr(agent, 'memory_manager'):
        log_test("记忆操作", "skipped", "Agent未初始化，跳过")
        return

    try:
        memory_mgr = agent.memory_manager

        test_content = f"测试记忆内容 {datetime.now().isoformat()}"
        memory_id = memory_mgr.create_memory(
            content=test_content,
            category="test",
            importance=0.8
        )

        print(f"  ✅ 创建记忆: {memory_id[:20]}...")

        results = memory_mgr.recall(query="测试记忆", limit=5)
        print(f"  ✅ 检索记忆: 找到 {len(results)} 条")

        memory = memory_mgr.get_memory(memory_id)
        print(f"  ✅ 获取记忆: {'成功' if memory else '失败'}")

        if memory and test_content in str(memory.content):
            log_test("记忆操作", "passed", f"写入/检索/获取功能正常")
        else:
            log_test("记忆操作", "failed", "记忆内容验证失败")

    except Exception as e:
        log_test("记忆操作", "failed", str(e))


async def test_context_management(agent):
    """测试4: 验证上下文管理"""
    print("\n" + "="*60)
    print("测试4: 验证上下文管理")
    print("="*60)

    if not agent:
        log_test("上下文管理", "skipped", "Agent未初始化，跳过")
        return

    try:
        system_prompt = agent._build_system_prompt()

        checks = [
            ("system_prompt不为空", len(system_prompt) > 0),
            ("包含Agent名称", agent.config.name in system_prompt),
        ]

        all_passed = True
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")
            if not result:
                all_passed = False

        context = agent.context_builder.build_context(
            system_prompt=system_prompt,
            memories=[],
            conversation_history=[],
            user_input="测试输入"
        )

        checks2 = [
            ("context不为空", len(context) > 0),
            ("包含用户输入", "测试输入" in str(context)),
        ]

        for check_name, result in checks2:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")
            if not result:
                all_passed = False

        log_test(
            "上下文管理",
            "passed" if all_passed else "failed",
            "上下文构建正常" if all_passed else "上下文构建失败"
        )

    except Exception as e:
        log_test("上下文管理", "failed", str(e))


async def test_tool_router():
    """测试5: 验证工具路由"""
    print("\n" + "="*60)
    print("测试5: 验证工具路由")
    print("="*60)

    try:
        from neurova.tool_layers.tool_router import ToolRouter

        router = ToolRouter()

        builtin_tools = router.get_builtin_tools()
        print(f"  ✅ 内置工具数量: {len(builtin_tools)}")

        for tool_name in builtin_tools[:5]:
            print(f"     - {tool_name}")

        has_builtin = len(builtin_tools) > 0

        log_test(
            "工具路由",
            "passed" if has_builtin else "failed",
            f"工具路由系统正常，内置工具: {len(builtin_tools)}"
        )

    except Exception as e:
        log_test("工具路由", "failed", str(e))


async def test_skill_registry():
    """测试6: 验证Skill注册"""
    print("\n" + "="*60)
    print("测试6: 验证Skill注册")
    print("="*60)

    try:
        from neurova.skills.registry import SkillRegistry

        registry = SkillRegistry()

        skills = registry.list_skills()
        print(f"  ✅ 已注册Skill数量: {len(skills)}")

        for skill_name in skills[:5]:
            print(f"     - {skill_name}")

        log_test(
            "Skill注册",
            "passed",
            f"Skill注册系统正常，已注册: {len(skills)}"
        )

    except Exception as e:
        log_test("Skill注册", "failed", str(e))


async def test_api_endpoints():
    """测试7: 验证API端点注册"""
    print("\n" + "="*60)
    print("测试7: 验证API端点注册")
    print("="*60)

    try:
        from neurova.api.app import app

        routes = []
        for route in app.routes:
            if hasattr(route, 'path') and hasattr(route, 'methods'):
                routes.append({
                    "path": route.path,
                    "methods": list(route.methods) if route.methods else []
                })

        print(f"  ✅ 注册路由数量: {len(routes)}")

        endpoints = {
            "chat": [r for r in routes if "/chat" in r["path"]],
            "media": [r for r in routes if "/media" in r["path"]],
            "channel": [r for r in routes if "/channel" in r["path"]],
            "settings": [r for r in routes if "/settings" in r["path"]],
            "audit": [r for r in routes if "/audit" in r["path"]],
            "firewall": [r for r in routes if "/firewall" in r["path"]],
        }

        for category, ep_list in endpoints.items():
            if ep_list:
                print(f"     {category}: {len(ep_list)} 端点")

        key_endpoints = [
            ("/api/v1/chat", "/chat" in str(routes)),
            ("/api/v1/media", "/media" in str(routes)),
        ]

        all_key_exist = all(result for _, result in key_endpoints)

        log_test(
            "API端点注册",
            "passed" if all_key_exist else "failed",
            f"API系统正常，路由: {len(routes)}"
        )

    except Exception as e:
        log_test("API端点注册", "failed", str(e))


async def test_auth_system():
    """测试8: 验证认证系统"""
    print("\n" + "="*60)
    print("测试8: 验证认证系统")
    print("="*60)

    try:
        from neurova.api.auth import create_access_token, verify_token
        from neurova.security.rbac import ROLE_PERMISSIONS

        test_user = "test_user"
        token = create_access_token(subject=test_user)

        checks = [
            ("Token创建成功", len(token) > 0),
        ]

        try:
            payload = verify_token(token)
            checks.append(("Token验证成功", payload.get("sub") == test_user))
        except Exception as e:
            print(f"  ⚠️ Token验证失败: {e}")
            checks.append(("Token验证成功", False))

        admin_perms = ROLE_PERMISSIONS.get("admin", set())
        checks.append(("Admin角色权限定义", len(admin_perms) > 0))

        all_passed = True
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")
            if not result:
                all_passed = False

        log_test(
            "认证系统",
            "passed" if all_passed else "failed",
            "认证和权限系统正常" if all_passed else "认证系统存在问题"
        )

    except Exception as e:
        log_test("认证系统", "failed", str(e))


async def test_tts_system():
    """测试9: 验证TTS系统"""
    print("\n" + "="*60)
    print("测试9: 验证TTS系统")
    print("="*60)

    try:
        from neurova.tts.manager import TTSManager, TTSConfig

        config = TTSConfig(engine="mock")

        tts_mgr = TTSManager(config)

        checks = [
            ("TTS管理器创建", tts_mgr is not None),
            ("配置正确", tts_mgr.config.engine == "mock"),
        ]

        initialized = await tts_mgr.initialize()
        checks.append(("TTS初始化", initialized))

        all_passed = all(result for _, result in checks)
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")

        log_test(
            "TTS系统",
            "passed" if all_passed else "failed",
            "TTS系统正常" if all_passed else "TTS系统存在问题"
        )

    except Exception as e:
        log_test("TTS系统", "failed", str(e))


async def test_channels():
    """测试10: 验证消息渠道系统"""
    print("\n" + "="*60)
    print("测试10: 验证消息渠道系统")
    print("="*60)

    try:
        from neurova.channels import MessageChannel

        channels = list(MessageChannel)

        print(f"  ✅ 支持的消息渠道数量: {len(channels)}")
        for channel in channels[:10]:
            print(f"     - {channel.value}")

        from neurova.channels.manager import ChannelManager

        manager = ChannelManager()

        checks = [
            ("渠道管理器创建", manager is not None),
            ("路由器创建", hasattr(manager, 'router')),
        ]

        all_passed = all(result for _, result in checks)
        for check_name, result in checks:
            status = "✅" if result else "❌"
            print(f"  {status} {check_name}")

        log_test(
            "消息渠道系统",
            "passed" if all_passed else "failed",
            f"消息渠道系统正常，支持 {len(channels)} 种渠道"
        )

    except Exception as e:
        log_test("消息渠道系统", "failed", str(e))


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("🧪 Neurova 功能测试套件")
    print("="*60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    await test_imports()
    agent = await test_agent_initialization()
    await test_memory_operations(agent)
    await test_context_management(agent)
    await test_tool_router()
    await test_skill_registry()
    await test_api_endpoints()
    await test_auth_system()
    await test_tts_system()
    await test_channels()

    print("\n" + "="*60)
    print("📊 测试报告摘要")
    print("="*60)
    print(f"总测试数: {test_results['summary']['total']}")
    print(f"✅ 通过: {test_results['summary']['passed']}")
    print(f"❌ 失败: {test_results['summary']['failed']}")
    print(f"⏭️ 跳过: {test_results['summary']['skipped']}")

    if test_results['summary']['failed'] == 0:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️ 有 {test_results['summary']['failed']} 项测试失败，请检查。")

    print("="*60)

    # 报告写到当前工作目录（脚本在项目根目录下运行）
    output = json.dumps(test_results, ensure_ascii=False, indent=2)
    with open("test_results.json", "w", encoding="utf-8") as f:
        f.write(output)

    print("\n📄 测试报告已保存到: test_results.json")

    return test_results


if __name__ == "__main__":
    asyncio.run(main())
