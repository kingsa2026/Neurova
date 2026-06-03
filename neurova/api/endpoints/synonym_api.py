"""
同义词库管理API - Synonym Dictionary Management API

提供同义词库的CRUD操作、配置管理和语义搜索增强功能。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class SynonymInfo(BaseModel):
    """同义词信息"""
    word: str
    synonyms: List[str] = []
    category: str = "general"
    created_at: float = 0
    updated_at: float = 0


class AddSynonymRequest(BaseModel):
    """添加同义词请求"""
    word: str = Field(..., description="词语")
    synonyms: List[str] = Field(..., description="同义词列表")
    category: str = Field(default="general", description="分类")


class SetSynonymsRequest(BaseModel):
    """设置同义词请求（覆盖）"""
    word: str = Field(..., description="词语")
    synonyms: List[str] = Field(..., description="同义词列表")
    category: str = Field(default="general", description="分类")


class SynonymConfigRequest(BaseModel):
    """同义词配置请求"""
    enabled: bool = Field(default=True, description="是否启用同义词扩展")
    max_expansions: int = Field(default=5, description="最大扩展数量")
    boost_exact: bool = Field(default=True, description="是否提升精确匹配权重")


class TestSearchRequest(BaseModel):
    """测试搜索请求"""
    query: str = Field(..., description="查询文本")
    use_synonyms: bool = Field(default=True, description="是否使用同义词扩展")


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_synonyms_store: Dict[str, Dict[str, Any]] = {}
_config: Dict[str, Any] = {
    "enabled": True,
    "max_expansions": 5,
    "boost_exact": True,
}


def _get_vsa():
    """获取向量搜索高级模块"""
    try:
        from neurova.cognitive_layers.memory_layer.vector_search_advanced import VectorSearchAdvanced
        return VectorSearchAdvanced()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_stats():
    """获取同义词库统计信息"""
    total_words = len(_synonyms_store)
    total_synonyms = sum(len(entry.get("synonyms", [])) for entry in _synonyms_store.values())
    categories = set(entry.get("category", "general") for entry in _synonyms_store.values())
    return {
        "code": 0,
        "data": {
            "total_words": total_words,
            "total_synonyms": total_synonyms,
            "categories": list(categories),
            "config": _config,
        },
    }


@router.get("", response_model=List[SynonymInfo])
async def get_all_synonyms(
    category: Optional[str] = Query(default=None, description="按分类筛选"),
    limit: int = Query(default=100, le=500),
):
    """获取所有同义词"""
    entries = list(_synonyms_store.values())
    if category:
        entries = [e for e in entries if e.get("category") == category]
    return [SynonymInfo(**e) for e in entries[:limit]]


@router.get("/{word}", response_model=SynonymInfo)
async def get_synonyms(word: str):
    """获取指定词语的同义词"""
    entry = _synonyms_store.get(word.lower())
    if not entry:
        raise HTTPException(status_code=404, detail=f"Word '{word}' not found")
    return SynonymInfo(**entry)


@router.post("", response_model=SynonymInfo)
async def add_synonyms(body: AddSynonymRequest):
    """添加同义词"""
    word = body.word.lower()
    now = time.time()
    
    if word in _synonyms_store:
        # 合并同义词
        existing = _synonyms_store[word]
        existing_synonyms = set(existing.get("synonyms", []))
        existing_synonyms.update(body.synonyms)
        existing["synonyms"] = list(existing_synonyms)
        existing["updated_at"] = now
        return SynonymInfo(**existing)
    
    entry = {
        "word": word,
        "synonyms": body.synonyms,
        "category": body.category,
        "created_at": now,
        "updated_at": now,
    }
    _synonyms_store[word] = entry
    return SynonymInfo(**entry)


@router.put("", response_model=SynonymInfo)
async def set_synonyms(body: SetSynonymsRequest):
    """设置同义词列表（覆盖）"""
    word = body.word.lower()
    now = time.time()
    
    entry = _synonyms_store.get(word)
    if not entry:
        entry = {"word": word, "created_at": now}
    
    entry["synonyms"] = body.synonyms
    entry["category"] = body.category
    entry["updated_at"] = now
    _synonyms_store[word] = entry
    return SynonymInfo(**entry)


@router.delete("/{word}/synonyms/{synonym}")
async def remove_synonym(word: str, synonym: str):
    """移除单个同义词"""
    entry = _synonyms_store.get(word.lower())
    if not entry:
        raise HTTPException(status_code=404, detail=f"Word '{word}' not found")
    
    synonyms = entry.get("synonyms", [])
    if synonym not in synonyms:
        raise HTTPException(status_code=404, detail=f"Synonym '{synonym}' not found")
    
    synonyms.remove(synonym)
    entry["synonyms"] = synonyms
    entry["updated_at"] = time.time()
    return {"code": 0, "message": f"Synonym '{synonym}' removed from '{word}'"}


@router.delete("/{word}")
async def delete_word(word: str):
    """删除整个词语"""
    if word.lower() not in _synonyms_store:
        raise HTTPException(status_code=404, detail=f"Word '{word}' not found")
    del _synonyms_store[word.lower()]
    return {"code": 0, "message": f"Word '{word}' deleted"}


@router.post("/load")
async def load_from_file(file_path: str = Query(..., description="文件路径")):
    """从文件加载同义词库"""
    try:
        import json
        from pathlib import Path
        path = Path(file_path)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        now = time.time()
        count = 0
        for word, synonyms in data.items():
            if isinstance(synonyms, list):
                _synonyms_store[word.lower()] = {
                    "word": word.lower(),
                    "synonyms": synonyms,
                    "category": "imported",
                    "created_at": now,
                    "updated_at": now,
                }
                count += 1
        
        return {"code": 0, "message": f"Loaded {count} words from '{file_path}'"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/save")
async def save_to_file(file_path: str = Query(..., description="文件路径")):
    """保存同义词库到文件"""
    try:
        import json
        from pathlib import Path
        
        data = {word: entry.get("synonyms", []) for word, entry in _synonyms_store.items()}
        
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        return {"code": 0, "message": f"Saved {len(data)} words to '{file_path}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/llm")
async def get_llm_config():
    """获取LLM配置"""
    return {
        "code": 0,
        "data": {
            "enabled": _config.get("enabled", True),
            "max_expansions": _config.get("max_expansions", 5),
            "boost_exact": _config.get("boost_exact", True),
        },
    }


@router.put("/config/llm")
async def set_llm_config(body: SynonymConfigRequest):
    """设置LLM配置"""
    _config["enabled"] = body.enabled
    _config["max_expansions"] = body.max_expansions
    _config["boost_exact"] = body.boost_exact
    return {"code": 0, "message": "LLM config updated", "data": _config}


@router.post("/test-search")
async def test_semantic_search(body: TestSearchRequest):
    """测试语义搜索"""
    expanded_terms = []
    if body.use_synonyms and _config.get("enabled", True):
        query_lower = body.query.lower()
        for word, entry in _synonyms_store.items():
            if word in query_lower or query_lower in word:
                expanded_terms.extend(entry.get("synonyms", [])[:_config.get("max_expansions", 5)])
    
    return {
        "code": 0,
        "data": {
            "original_query": body.query,
            "expanded_terms": list(set(expanded_terms)),
            "synonyms_enabled": _config.get("enabled", True),
        },
    }