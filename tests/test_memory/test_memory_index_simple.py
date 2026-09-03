#!/usr/bin/env python
"""简单的MemoryIndex测试脚本"""

import tempfile
from neurova.cognitive_layers.memory_layer.memory_index import MemoryIndex
from neurova.cognitive_layers.memory_layer.storage import MemoryStorage
from neurova.cognitive_layers.memory_layer.isolation import IsolationContext

def test_basic():
    temp_dir = tempfile.mkdtemp()
    storage = MemoryStorage(temp_dir)
    index = MemoryIndex(storage)
    
    # 添加数据
    storage.save(content="测试1", memory_type="episodic")
    storage.save(content="测试2", memory_type="semantic")
    
    # 测试查询
    results = index.query()
    print(f"查询结果: {len(results)}")
    assert len(results) == 2
    
    # 测试标签搜索
    storage.save(content="Python测试", memory_type="episodic", tags=["python"])
    results = index.search_by_tags(["python"])
    print(f"标签搜索结果: {len(results)}")
    assert len(results) == 1
    
    # 测试文本搜索
    results = index.search_by_text("Python")
    print(f"文本搜索结果: {len(results)}")
    assert len(results) == 1
    
    print("所有基础测试通过！")

if __name__ == "__main__":
    test_basic()