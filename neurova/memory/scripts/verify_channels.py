#!/usr/bin/env python3
"""
验证所有渠道配置是否正确

测试:
1. 检查所有渠道适配器文件是否存在
2. 检查渠道管理器是否正确注册所有适配器
3. 检查API能力描述是否完整
4. 检查UI图标映射是否正确
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
# 使用更可靠的方法定位项目根目录
current_file = Path(__file__).resolve()
# 从 scripts 向上找到 Neurova 根目录 (包含 README 或其他标识文件)
project_root = current_file
while project_root.name != "Neurova" and project_root.parent != project_root:
    project_root = project_root.parent

sys.path.insert(0, str(project_root))


def check_file_exists(file_path, description):
    """检查文件是否存在"""
    if file_path.exists():
        print(f"✅ {description}: {file_path}")
        return True
    else:
        print(f"❌ {description} 不存在: {file_path}")
        return False


def check_channel_adapters():
    """检查渠道适配器文件"""
    print("\n=== 检查渠道适配器 ===")
    channels_dir = project_root / "neurova" / "channels"

    adapters = [
        ("feishu.py", "飞书适配器"),
        ("dingtalk.py", "钉钉适配器"),
        ("wechat.py", "微信适配器"),
        ("telegram.py", "Telegram适配器"),
        ("qq.py", "QQ频道适配器"),
        ("qqbot.py", "QQ Bot适配器"),
        ("discord.py", "Discord适配器"),
        ("sip.py", "SIP语音适配器"),
        ("xiaoyi.py", "小艺适配器"),
        ("mqtt.py", "MQTT适配器"),
        ("websocket.py", "WebSocket适配器"),
    ]

    results = []
    for filename, desc in adapters:
        results.append(check_file_exists(channels_dir / filename, desc))

    return all(results)


def check_channel_manager():
    """检查渠道管理器"""
    print("\n=== 检查渠道管理器 ===")
    manager_file = project_root / "neurova" / "channels" / "manager.py"

    if not manager_file.exists():
        print("❌ 渠道管理器不存在")
        return False

    content = manager_file.read_text(encoding="utf-8")

    # 检查是否导入了所有适配器
    adapters = [
        "feishu",
        "dingtalk",
        "wechat",
        "telegram",
        "qq",
        "qqbot",
        "discord",
        "sip",
        "xiaoyi",
        "mqtt",
        "websocket",
    ]
    results = []

    for adapter in adapters:
        if f"from neurova.channels.{adapter} import create_{adapter}_adapter" in content:
            print(f"✅ 渠道管理器导入了 {adapter}")
            results.append(True)
        else:
            print(f"❌ 渠道管理器未导入 {adapter}")
            results.append(False)

    return all(results)


def check_api_capabilities():
    """检查API能力描述"""
    print("\n=== 检查API能力描述 ===")
    api_file = project_root / "neurova" / "channels" / "api.py"

    if not api_file.exists():
        print("❌ API文件不存在")
        return False

    content = api_file.read_text(encoding="utf-8")

    channels = [
        "feishu",
        "dingtalk",
        "wechat",
        "telegram",
        "qq",
        "qqbot",
        "discord",
        "sip",
        "xiaoyi",
        "mqtt",
        "websocket",
    ]
    results = []

    for channel in channels:
        if f'"{channel}"' in content:
            print(f"✅ API包含 {channel} 能力描述")
            results.append(True)
        else:
            print(f"❌ API缺少 {channel} 能力描述")
            results.append(False)

    return all(results)


def check_ui_icons():
    """检查UI图标映射"""
    print("\n=== 检查UI图标映射 ===")
    ui_file = project_root / "neurova" / "channels-ui.html"

    if not ui_file.exists():
        print("❌ UI文件不存在")
        return False

    content = ui_file.read_text(encoding="utf-8")

    channels = [
        "feishu",
        "dingtalk",
        "wechat",
        "telegram",
        "qq",
        "qqbot",
        "discord",
        "sip",
        "xiaoyi",
        "mqtt",
        "websocket",
    ]
    results = []

    for channel in channels:
        if channel in content:
            print(f"✅ UI包含 {channel} 图标映射")
            results.append(True)
        else:
            print(f"❌ UI缺少 {channel} 图标映射")
            results.append(False)

    return all(results)


def main():
    print("=" * 60)
    print("Neurova 渠道配置验证")
    print("=" * 60)

    results = [
        check_channel_adapters(),
        check_channel_manager(),
        check_api_capabilities(),
        check_ui_icons(),
    ]

    print("\n" + "=" * 60)
    if all(results):
        print("✅ 所有渠道配置验证通过!")
        return 0
    else:
        print("❌ 部分渠道配置存在问题!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
