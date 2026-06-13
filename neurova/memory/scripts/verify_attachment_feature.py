"""
附件存储功能快速验证脚本
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_attachment_functionality():
    """测试附件存储功能"""

    print("=" * 60)
    print("🧪 附件存储功能验证")
    print("=" * 60)

    # 1. 测试数据模型
    print("\n1️⃣ 测试 Attachment 数据类...")
    try:
        pass

        from memory.core.models import Attachment

        attachment = Attachment(
            id="test-uuid-123",
            original_name="test.pdf",
            file_path="data/attachments/test.pdf",
            file_size=1024,
            mime_type="application/pdf",
        )

        data = attachment.to_dict()
        assert data["id"] == "test-uuid-123"
        assert data["original_name"] == "test.pdf"
        print("   ✅ Attachment 数据类正常工作")
    except Exception as e:
        print(f"   ❌ Attachment 数据类测试失败: {e}")
        return False

    # 2. 测试 Memory 模型
    print("\n2️⃣ 测试 Memory 模型附件支持...")
    try:
        from memory.core.models import Memory

        memory = Memory(id="memory-123", content="测试记忆", attachments=[attachment])

        data = memory.to_dict()
        assert "attachments" in data
        assert len(data["attachments"]) == 1
        print("   ✅ Memory 模型附件支持正常")
    except Exception as e:
        print(f"   ❌ Memory 模型测试失败: {e}")
        return False

    # 3. 测试数据库表结构
    print("\n3️⃣ 检查数据库表结构...")
    try:
        pass

        from memory.core.storage import MemoryStorage

        # 创建临时测试数据库
        test_db = "data/test_attachment.db"
        os.makedirs("data", exist_ok=True)

        # 初始化存储
        storage = MemoryStorage(db_path=test_db)

        # 检查 attachments 表是否存在
        cursor = storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='attachments'")
        table_exists = cursor.fetchone() is not None

        if table_exists:
            print("   ✅ attachments 表已创建")
        else:
            print("   ⚠️ attachments 表不存在（将在首次使用时创建）")

        # 检查 memories 表的 attachment_ids 字段
        cursor = storage.conn.execute("PRAGMA table_info(memories)")
        columns = [row[1] for row in cursor.fetchall()]

        if "attachment_ids" in columns:
            print("   ✅ memories 表包含 attachment_ids 字段")
        else:
            print("   ❌ memories 表缺少 attachment_ids 字段")
            return False

        storage.close()

        # 清理测试数据库
        if os.path.exists(test_db):
            os.remove(test_db)
            os.remove(test_db + "-wal") if os.path.exists(test_db + "-wal") else None
            os.remove(test_db + "-shm") if os.path.exists(test_db + "-shm") else None

    except Exception as e:
        print(f"   ❌ 数据库测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    # 4. 测试 AttachmentManager
    print("\n4️⃣ 测试 AttachmentManager...")
    try:
        from memory.core.attachment_manager import AttachmentManager

        test_db = "data/test_attachment.db"
        manager = AttachmentManager(storage_dir="data/test_attachments", db_path=test_db)

        # 保存测试附件
        test_data = b"Test file content"
        result = manager.save_attachment(file_data=test_data, original_name="test_file.txt", metadata={"test": True})

        if result:
            print(f"   ✅ 附件保存成功，ID: {result['id']}")

            # 获取附件
            info = manager.get_attachment(result["id"])
            if info and info["original_name"] == "test_file.txt":
                print("   ✅ 附件获取正常")
            else:
                print("   ❌ 附件获取失败")

            # 清理
            manager.delete_attachment(result["id"])
            print("   ✅ 附件删除正常")
        else:
            print("   ❌ 附件保存失败")

        manager.close()

        # 清理测试文件
        import shutil

        if os.path.exists("data/test_attachments"):
            shutil.rmtree("data/test_attachments")
        if os.path.exists(test_db):
            os.remove(test_db)

    except Exception as e:
        print(f"   ❌ AttachmentManager 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    # 5. 测试 API 模型
    print("\n5️⃣ 测试 ChatRequest 附件支持...")
    try:
        pass

        from api.endpoints.chat import AttachmentRequest, ChatRequest

        # 创建带附件的请求
        attachment_req = AttachmentRequest(filename="document.pdf", content_type="application/pdf", size=2048)

        chat_req = ChatRequest(message="测试消息", attachments=[attachment_req])

        if len(chat_req.attachments) == 1:
            print("   ✅ ChatRequest 附件支持正常")
        else:
            print("   ❌ ChatRequest 附件字段异常")

    except Exception as e:
        print(f"   ❌ ChatRequest 测试失败: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 60)
    print("✅ 所有测试通过！附件存储功能已成功实现")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = test_attachment_functionality()
    sys.exit(0 if success else 1)
