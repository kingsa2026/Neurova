"""
测试 StateManager 模块
"""
import sys
import os
import tempfile
import json
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from neurova.core.state_manager import StateManager, reset_state_manager


def test_basic_get_set():
    """测试基本的 get/set 操作"""
    manager = StateManager()
    
    manager.set("key1", "value1")
    assert manager.get("key1") == "value1"
    
    manager.set("key1", "new_value")
    assert manager.get("key1") == "new_value"
    print("✓ test_basic_get_set 通过")


def test_nested_state():
    """测试嵌套状态访问"""
    manager = StateManager()
    
    manager.set("user.profile.name", "张三")
    manager.set("user.profile.age", 25)
    
    assert manager.get("user.profile.name") == "张三"
    assert manager.get("user.profile.age") == 25
    assert manager.get("user.profile.nonexistent") is None
    print("✓ test_nested_state 通过")


def test_has_key():
    """测试 has 检查"""
    manager = StateManager()
    
    assert manager.has("key1") is False
    manager.set("key1", None)
    assert manager.has("key1") is True
    
    manager.set("a.b.c", 100)
    assert manager.has("a.b.c") is True
    assert manager.has("a.b") is True
    assert manager.has("a.b.nonexistent") is False
    print("✓ test_has_key 通过")


def test_delete():
    """测试删除操作"""
    manager = StateManager()
    
    manager.set("key1", "value1")
    assert manager.has("key1") is True
    
    deleted = manager.delete("key1")
    assert deleted == "value1"
    assert manager.has("key1") is False
    
    # 删除不存在的键
    assert manager.delete("nonexistent") is None
    print("✓ test_delete 通过")


def test_listeners():
    """测试监听器功能"""
    manager = StateManager()
    changes = []
    
    def listener(key, old, new):
        changes.append((key, old, new))
    
    manager.on_change("key1", listener)
    manager.set("key1", "value1")
    
    assert len(changes) == 1
    assert changes[0] == ("key1", None, "value1")
    print("✓ test_listeners 通过")


def test_snapshots():
    """测试快照功能"""
    manager = StateManager()
    
    manager.set("setting1", "v1")
    manager.set("setting2", "v2")
    snapshot_id = manager.create_snapshot("初始状态")
    
    manager.set("setting1", "modified")
    assert manager.get("setting1") == "modified"
    
    success = manager.restore_snapshot(snapshot_id)
    assert success is True
    assert manager.get("setting1") == "v1"
    print("✓ test_snapshots 通过")


def test_persistence():
    """测试状态持久化"""
    temp_dir = tempfile.mkdtemp()
    state_file = Path(temp_dir) / "state.json"
    
    manager1 = StateManager()
    manager1.set_persist_path(state_file)
    manager1.set("user.name", "李四")
    manager1.set("user.id", 123)
    save_success = manager1.save()
    assert save_success is True
    
    manager2 = StateManager()
    manager2.set_persist_path(state_file)
    load_success = manager2.load()
    assert load_success is True
    assert manager2.get("user.name") == "李四"
    assert manager2.get("user.id") == 123
    
    # 清理
    import shutil
    shutil.rmtree(temp_dir)
    print("✓ test_persistence 通过")


def test_update_multiple():
    """测试批量更新"""
    manager = StateManager()
    
    changes = manager.update({
        "a": 1,
        "b": 2,
        "c.d": 3
    })
    
    assert len(changes) == 3
    assert manager.get("a") == 1
    assert manager.get("c.d") == 3
    print("✓ test_update_multiple 通过")


def main():
    """运行所有测试"""
    print("=" * 50)
    print("开始运行 StateManager 测试")
    print("=" * 50)
    
    all_passed = True
    
    try:
        test_basic_get_set()
    except Exception as e:
        print(f"✗ test_basic_get_set 失败: {e}")
        all_passed = False
    
    try:
        test_nested_state()
    except Exception as e:
        print(f"✗ test_nested_state 失败: {e}")
        all_passed = False
    
    try:
        test_has_key()
    except Exception as e:
        print(f"✗ test_has_key 失败: {e}")
        all_passed = False
    
    try:
        test_delete()
    except Exception as e:
        print(f"✗ test_delete 失败: {e}")
        all_passed = False
    
    try:
        test_listeners()
    except Exception as e:
        print(f"✗ test_listeners 失败: {e}")
        all_passed = False
    
    try:
        test_snapshots()
    except Exception as e:
        print(f"✗ test_snapshots 失败: {e}")
        all_passed = False
    
    try:
        test_persistence()
    except Exception as e:
        print(f"✗ test_persistence 失败: {e}")
        all_passed = False
    
    try:
        test_update_multiple()
    except Exception as e:
        print(f"✗ test_update_multiple 失败: {e}")
        all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 所有 StateManager 测试通过！")
    else:
        print("❌ 部分 StateManager 测试失败")
    print("=" * 50)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
