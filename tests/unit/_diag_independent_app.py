"""
独立的 FastAPI 测试应用 - 用于诊断 POST 超时问题
完全绕过 Neurova 项目代码
"""
from fastapi import FastAPI
from typing import Dict, Any

# 创建独立应用
app = FastAPI(title="独立测试应用", description="用于诊断 POST 超时问题")

@app.get("/test-get")
async def test_get() -> Dict[str, Any]:
    """GET 测试端点"""
    return {
        "status": "ok",
        "method": "GET",
        "endpoint": "/test-get",
        "message": "GET 请求正常"
    }

@app.post("/test-post")
async def test_post() -> Dict[str, Any]:
    """POST 测试端点（无参数）"""
    return {
        "status": "ok",
        "method": "POST",
        "endpoint": "/test-post",
        "message": "POST 请求正常（无参数）"
    }

@app.post("/test-post-with-body")
async def test_post_with_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST 测试端点（有参数）"""
    return {
        "status": "ok",
        "method": "POST",
        "endpoint": "/test-post-with-body",
        "received_payload": payload,
        "message": "POST 请求正常（有参数）"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9530)
