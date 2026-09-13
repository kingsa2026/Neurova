from fastapi import FastAPI
from fastapi.responses import JSONResponse
import datetime

app = FastAPI()

@app.get("/test")
def test_get():
    """GET 测试端点"""
    return {"status": "ok", "method": "GET", "timestamp": str(datetime.datetime.now())}

@app.post("/test")
def test_post():
    """POST 测试端点（无参数）"""
    return {"status": "ok", "method": "POST", "timestamp": str(datetime.datetime.now())}

@app.post("/test-body")
async def test_post_body(request: dict):
    """POST 测试端点（有参数）"""
    return {"status": "ok", "method": "POST", "body": request, "timestamp": str(datetime.datetime.now())}
