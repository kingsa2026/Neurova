"""
GitHub Push Skill 演示脚本

展示如何使用 GitHub Push 技能进行 Git 操作
"""

import asyncio
import tempfile
import os
import shutil
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

async def demo_github_push_skill():
    """演示 GitHub Push 技能的使用"""
    print("=== GitHub Push Skill 演示 ===")
    print()
    
    # 导入技能
    from neurova.skills.builtin.github_push import create_github_push_skill, push_to_github
    
    # 创建技能实例
    skill = create_github_push_skill()
    print(f"✅ 技能创建成功")
    print(f"   名称: {skill.name}")
    print(f"   描述: {skill.description}")
    print()
    
    # 显示技能信息
    info = skill.get_info()
    print("📋 技能信息:")
    print(f"   标签: {', '.join(info.tags)}")
    print(f"   参数: {', '.join(info.parameters.keys())}")
    print()
    
    # 创建临时演示目录
    demo_dir = Path(tempfile.mkdtemp(prefix="github_push_demo_"))
    print(f"📁 演示目录: {demo_dir}")
    
    # 创建示例文件
    (demo_dir / "main.py").write_text('print("Hello, GitHub Push Skill!")')
    (demo_dir / "README.md").write_text("# Demo Project\n\n这是一个演示项目。")
    (demo_dir / "config.json").write_text('{"version": "1.0.0"}')
    
    print("📝 创建示例文件:")
    print("   - main.py")
    print("   - README.md")
    print("   - config.json")
    print()
    
    # 初始化 Git 仓库
    os.system(f"cd {demo_dir} && git init")
    os.system(f"cd {demo_dir} && git config user.email 'demo@neurova.com'")
    os.system(f"cd {demo_dir} && git config user.name 'Neurova Demo'")
    print("🔧 初始化 Git 仓库")
    print()
    
    # 设置技能仓库路径
    skill.repo_path = demo_dir
    
    # 演示 1: 获取状态
    print("🔍 演示 1: 获取 Git 状态")
    status_result = await skill.execute({"action": "status"})
    if status_result.success:
        print(f"   状态: {'干净' if status_result.data.get('clean') else '有更改'}")
        print(f"   更改文件数: {status_result.data.get('total_files', 0)}")
        if status_result.data.get('files'):
            for file_info in status_result.data['files'][:3]:  # 只显示前3个
                print(f"   - {file_info['status']}: {file_info['file']}")
    else:
        print(f"   ❌ 错误: {status_result.error}")
    print()
    
    # 演示 2: 添加文件
    print("➕ 演示 2: 添加文件到暂存区")
    add_result = await skill.execute({"action": "add"})
    if add_result.success:
        print(f"   ✅ 成功添加 {add_result.data.get('staged_count', 0)} 个文件")
    else:
        print(f"   ❌ 错误: {add_result.error}")
    print()
    
    # 演示 3: 提交更改
    print("💾 演示 3: 提交更改")
    commit_result = await skill.execute({
        "action": "commit",
        "message": "演示: 添加示例文件"
    })
    if commit_result.success:
        print(f"   ✅ 提交成功")
        print(f"   提交哈希: {commit_result.data.get('commit_hash', 'N/A')[:8]}...")
        print(f"   提交文件数: {commit_result.data.get('files_committed', 0)}")
    else:
        print(f"   ❌ 错误: {commit_result.error}")
    print()
    
    # 演示 4: 完整推送工作流（模拟，不实际推送）
    print("🚀 演示 4: 完整推送工作流（模拟）")
    print("   注意: 此演示不实际推送到远程仓库")
    print("   实际使用时，技能会执行:")
    print("   1. git status --porcelain")
    print("   2. git add .")
    print("   3. git commit -m 'message'")
    print("   4. git push origin <branch>:main")
    print()
    
    # 演示 5: 使用便捷函数
    print("⚡ 演示 5: 使用便捷函数")
    print("   代码示例:")
    print("   from neurova.skills.builtin.github_push import push_to_github")
    print("   result = await push_to_github('更新代码', push_to_main=True)")
    print()
    
    # 清理（注释掉以避免权限错误）
    # shutil.rmtree(demo_dir)
    print("🧹 清理演示目录（已跳过，避免权限错误）")
    print(f"   演示目录保留在: {demo_dir}")
    print()
    
    print("=== 演示完成 ===")
    print()
    print("📌 使用提示:")
    print("   1. 技能支持直接推送到 main 分支（无需合并）")
    print("   2. 所有操作都是异步的，不会阻塞主线程")
    print("   3. 支持自定义仓库路径和分支")
    print("   4. 详细的错误处理和状态报告")
    print()
    print("📚 更多信息请查看: docs/github_push_skill_usage.md")


async def demo_practical_usage():
    """演示实际使用场景"""
    print("=== 实际使用场景演示 ===")
    print()
    
    from neurova.skills.builtin.github_push import create_github_push_skill
    
    # 场景 1: 日常开发推送
    print("📝 场景 1: 日常开发推送")
    print("   代码:")
    print("   skill = create_github_push_skill()")
    print("   result = await skill.execute({")
    print('       "action": "full_push",')
    print('       "message": "日常开发更新"')
    print("   })")
    print()
    
    # 场景 2: 紧急修复推送
    print("🚨 场景 2: 紧急修复推送")
    print("   代码:")
    print("   result = await skill.execute({")
    print('       "action": "full_push",')
    print('       "message": "紧急修复: 登录问题",')
    print('       "push_to_main": True')
    print("   })")
    print()
    
    # 场景 3: 仅提交不推送
    print("💾 场景 3: 仅提交不推送")
    print("   代码:")
    print("   await skill.execute({\"action\": \"add\"})")
    print("   result = await skill.execute({")
    print('       "action": "commit",')
    print('       "message": "本地保存"')
    print("   })")
    print()
    
    print("=== 场景演示完成 ===")


if __name__ == "__main__":
    asyncio.run(demo_github_push_skill())
    print()
    asyncio.run(demo_practical_usage())