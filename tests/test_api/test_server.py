"""最简单的测试服务器"""
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="Test Server")

@app.get("/test")
def test():
    return {"status": "ok", "message": "测试服务器正常工作"}

if __name__ == "__main__":
    print("🚀 启动测试服务器在 http://0.0.0.0:9527")
    uvicorn.run(app, host="0.0.0.0", port=9527)
