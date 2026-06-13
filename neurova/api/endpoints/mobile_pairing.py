"""
移动设备配对 API

端点:
- POST /mobile/pairing/generate   — 生成配对码 + 二维码
- GET  /mobile/pairing/qrcode/{code} — 获取二维码图片
- POST /mobile/pairing/confirm    — 手机端确认配对
- GET  /mobile/pairing/status/{code} — 轮询配对状态
- GET  /mobile/pairing/list       — 列出已配对设备
- DELETE /mobile/pairing/{pairing_id} — 解除配对
- WS   /mobile/ws                 — 已配对设备的 WebSocket 连接
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()
security = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class GeneratePairingRequest(BaseModel):
    """生成配对请求"""

    device_name: Optional[str] = Field(default=None, description="设备名称")
    device_type: str = Field(default="mobile", description="设备类型")


class GeneratePairingResponse(BaseModel):
    """生成配对响应"""

    code: str
    qr_code_url: str
    expires_in: int
    pairing_id: str


class ConfirmPairingRequest(BaseModel):
    """确认配对请求"""

    code: str = Field(..., description="配对码")
    device_name: Optional[str] = Field(default=None, description="设备名称")
    device_id: Optional[str] = Field(default=None, description="设备 ID")


class ConfirmPairingResponse(BaseModel):
    """确认配对响应"""

    success: bool
    ws_token: Optional[str] = None
    ws_url: Optional[str] = None
    pairing_id: Optional[str] = None
    message: str


class PairingStatusResponse(BaseModel):
    """配对状态响应"""

    code: str
    status: str  # pending, confirmed, expired, revoked
    device_name: Optional[str] = None
    confirmed_at: Optional[float] = None


class PairedDeviceResponse(BaseModel):
    """已配对设备响应"""

    pairing_id: str
    device_name: str
    device_type: str
    device_id: Optional[str] = None
    paired_at: float
    last_active: Optional[float] = None
    is_online: bool = False


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_pairing_codes: Dict[str, Dict[str, Any]] = {}  # code -> pairing info
_paired_devices: Dict[str, Dict[str, Any]] = {}  # pairing_id -> device info
_user_devices: Dict[str, Set[str]] = {}  # user_id -> set of pairing_ids

# WebSocket 连接管理
_ws_connections: Dict[str, WebSocket] = {}  # user_id -> WebSocket

# HMAC 密钥（用于生成 WS Token）
_WS_SECRET = os.environ.get("NEUROVA_WS_SECRET", "neurova-ws-secret-key-2026")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _generate_pairing_code() -> str:
    """生成 6 位数字配对码"""
    import random

    return "".join([str(random.randint(0, 9)) for _ in range(6)])


def _generate_ws_token(user_id: str, pairing_id: str) -> str:
    """生成 WebSocket Token（HMAC 签名）"""
    message = f"{user_id}:{pairing_id}:{int(time.time())}"
    signature = hmac.new(_WS_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}:{signature}"


def _verify_ws_token(token: str) -> Optional[Dict[str, str]]:
    """验证 WebSocket Token"""
    try:
        parts = token.split(":")
        if len(parts) != 4:
            return None

        user_id, pairing_id, timestamp, signature = parts
        message = f"{user_id}:{pairing_id}:{timestamp}"
        expected_signature = hmac.new(_WS_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return None

        # 检查是否过期（24 小时）
        if time.time() - float(timestamp) > 86400:
            return None

        return {"user_id": user_id, "pairing_id": pairing_id}
    except Exception:
        return None


def _get_current_user_id(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """从 JWT Token 提取 user_id（用户隔离）"""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization")

    # 这里简化处理，实际应该验证 JWT
    credentials.credentials
    # 模拟从 JWT 中提取 user_id
    # 实际实现应该使用 jwt.decode()
    return "default-user"


# ---------------------------------------------------------------------------
# MobileConnectionManager
# ---------------------------------------------------------------------------


class MobileConnectionManager:
    """移动设备 WebSocket 连接管理器"""

    _instance: Optional["MobileConnectionManager"] = None

    def __init__(self):
        if MobileConnectionManager._instance is not None:
            raise RuntimeError("Use get_instance() instead")
        self._connections: Dict[str, WebSocket] = {}
        self._user_connections: Dict[str, Set[str]] = {}  # user_id -> set of connection_ids

    @classmethod
    def get_instance(cls) -> "MobileConnectionManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self, websocket: WebSocket, user_id: str, connection_id: str):
        """建立连接"""
        await websocket.accept()
        self._connections[connection_id] = websocket

        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(connection_id)

        logger.info("Mobile WebSocket connected: %s for user %s", connection_id, user_id)

    def disconnect(self, connection_id: str, user_id: str):
        """断开连接"""
        self._connections.pop(connection_id, None)
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(connection_id)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]

        logger.info("Mobile WebSocket disconnected: %s", connection_id)

    async def send_to_user(self, user_id: str, message: dict):
        """向指定用户的所有连接发送消息"""
        if user_id not in self._user_connections:
            return

        connection_ids = list(self._user_connections[user_id])
        for conn_id in connection_ids:
            ws = self._connections.get(conn_id)
            if ws:
                try:
                    await ws.send_json(message)
                except Exception:
                    self.disconnect(conn_id, user_id)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        for conn_id, ws in list(self._connections.items()):
            try:
                await ws.send_json(message)
            except Exception:
                # 清理断开的连接
                user_id = None
                for uid, conn_ids in self._user_connections.items():
                    if conn_id in conn_ids:
                        user_id = uid
                        break
                if user_id:
                    self.disconnect(conn_id, user_id)

    def get_online_count(self) -> int:
        """获取在线连接数"""
        return len(self._connections)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/pairing/generate", response_model=GeneratePairingResponse)
async def generate_pairing(
    body: GeneratePairingRequest,
    user_id: str = Depends(_get_current_user_id),
):
    """生成配对码 + 二维码"""
    code = _generate_pairing_code()
    pairing_id = f"pair-{uuid.uuid4().hex[:12]}"
    expires_in = 300  # 5 分钟

    _pairing_codes[code] = {
        "code": code,
        "pairing_id": pairing_id,
        "user_id": user_id,
        "device_name": body.device_name,
        "device_type": body.device_type,
        "status": "pending",
        "created_at": time.time(),
        "expires_at": time.time() + expires_in,
    }

    # 生成二维码 URL（包含 WS 连接信息）
    ws_url = f"ws://localhost:8000/mobile/ws?code={code}"
    qr_code_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={ws_url}"

    return GeneratePairingResponse(
        code=code,
        qr_code_url=qr_code_url,
        expires_in=expires_in,
        pairing_id=pairing_id,
    )


@router.get("/pairing/qrcode/{code}")
async def get_pairing_qrcode(code: str):
    """获取配对二维码图片（PNG）"""
    pairing = _pairing_codes.get(code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    # 尝试生成 PNG 二维码
    try:
        import io

        import qrcode
        from fastapi.responses import Response

        ws_url = f"ws://localhost:8000/mobile/ws?code={code}"
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(ws_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="qr-{code}.png"'},
        )
    except ImportError:
        # 降级为 SVG
        return _generate_svg_qrcode(code)


def _generate_svg_qrcode(code: str):
    """生成简单的 SVG 二维码占位图（降级方案）"""
    from fastapi.responses import Response

    svg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="200" height="200" xmlns="http://www.w3.org/2000/svg">
  <rect width="200" height="200" fill="white"/>
  <rect x="20" y="20" width="160" height="160" fill="none" stroke="black" stroke-width="2"/>
  <text x="100" y="90" text-anchor="middle" font-family="Arial" font-size="12" fill="black">
    配对码: {code}
  </text>
  <text x="100" y="120" text-anchor="middle" font-family="Arial" font-size="10" fill="gray">
    请使用手机 App 扫描
  </text>
</svg>"""

    return Response(
        content=svg_content,
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'inline; filename="qr-{code}.svg"'},
    )


@router.post("/pairing/confirm", response_model=ConfirmPairingResponse)
async def confirm_pairing(body: ConfirmPairingRequest):
    """确认配对（手机端调用，无需 JWT）"""
    pairing = _pairing_codes.get(body.code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Invalid pairing code")

    if pairing["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Pairing code is {pairing['status']}")

    if time.time() > pairing["expires_at"]:
        pairing["status"] = "expired"
        raise HTTPException(status_code=410, detail="Pairing code expired")

    # 确认配对
    pairing["status"] = "confirmed"
    pairing["confirmed_at"] = time.time()
    pairing["device_name"] = body.device_name or pairing.get("device_name", "Unknown Device")
    pairing["device_id"] = body.device_id

    # 生成 WS Token
    ws_token = _generate_ws_token(pairing["user_id"], pairing["pairing_id"])

    # 添加到已配对设备
    _paired_devices[pairing["pairing_id"]] = {
        "pairing_id": pairing["pairing_id"],
        "user_id": pairing["user_id"],
        "device_name": pairing["device_name"],
        "device_type": pairing.get("device_type", "mobile"),
        "device_id": body.device_id,
        "paired_at": pairing["confirmed_at"],
        "last_active": None,
        "is_online": False,
    }

    # 更新用户设备列表
    user_id = pairing["user_id"]
    if user_id not in _user_devices:
        _user_devices[user_id] = set()
    _user_devices[user_id].add(pairing["pairing_id"])

    return ConfirmPairingResponse(
        success=True,
        ws_token=ws_token,
        ws_url=f"ws://localhost:8000/mobile/ws?token={ws_token}",
        pairing_id=pairing["pairing_id"],
        message="配对成功",
    )


@router.get("/pairing/status/{code}", response_model=PairingStatusResponse)
async def get_pairing_status(code: str):
    """轮询配对状态"""
    pairing = _pairing_codes.get(code)
    if not pairing:
        raise HTTPException(status_code=404, detail="Pairing code not found")

    # 检查是否过期
    if pairing["status"] == "pending" and time.time() > pairing["expires_at"]:
        pairing["status"] = "expired"

    return PairingStatusResponse(
        code=code,
        status=pairing["status"],
        device_name=pairing.get("device_name"),
        confirmed_at=pairing.get("confirmed_at"),
    )


@router.get("/pairing/list")
async def list_paired_devices(
    user_id: str = Depends(_get_current_user_id),
):
    """列出已配对设备（需 JWT 认证）"""
    device_ids = _user_devices.get(user_id, set())
    devices = []

    for pairing_id in device_ids:
        device = _paired_devices.get(pairing_id)
        if device:
            # 检查是否在线
            device["is_online"] = pairing_id in _ws_connections
            devices.append(device)

    return {
        "code": 0,
        "data": {
            "devices": devices,
            "total": len(devices),
        },
    }


@router.delete("/pairing/{pairing_id}")
async def revoke_pairing(
    pairing_id: str,
    user_id: str = Depends(_get_current_user_id),
):
    """解除配对（需 JWT 认证）"""
    device = _paired_devices.get(pairing_id)
    if not device:
        raise HTTPException(status_code=404, detail="Pairing not found")

    if device["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your device")

    # 移除设备
    del _paired_devices[pairing_id]
    if user_id in _user_devices:
        _user_devices[user_id].discard(pairing_id)

    # 关闭 WebSocket 连接
    if pairing_id in _ws_connections:
        ws = _ws_connections.pop(pairing_id)
        try:
            await ws.close()
        except Exception:
            pass

    return {
        "code": 0,
        "message": f"设备 '{device['device_name']}' 已解除配对",
    }


@router.websocket("/ws")
async def mobile_websocket(websocket: WebSocket):
    """移动设备 WebSocket 连接"""
    # 从查询参数获取认证信息
    code = websocket.query_params.get("code")
    token = websocket.query_params.get("token")

    user_id = None
    pairing_id = None

    if code:
        # 通过配对码认证
        pairing = _pairing_codes.get(code)
        if not pairing or pairing["status"] != "confirmed":
            await websocket.close(code=4001, reason="Invalid or unconfirmed pairing code")
            return
        user_id = pairing["user_id"]
        pairing_id = pairing["pairing_id"]
    elif token:
        # 通过 Token 认证
        token_info = _verify_ws_token(token)
        if not token_info:
            await websocket.close(code=4001, reason="Invalid or expired token")
            return
        user_id = token_info["user_id"]
        pairing_id = token_info["pairing_id"]
    else:
        await websocket.close(code=4001, reason="Missing authentication")
        return

    # 建立连接
    connection_id = f"ws-{uuid.uuid4().hex[:12]}"
    manager = MobileConnectionManager.get_instance()

    await manager.connect(websocket, user_id, connection_id)
    _ws_connections[pairing_id] = websocket

    # 更新设备在线状态
    if pairing_id in _paired_devices:
        _paired_devices[pairing_id]["is_online"] = True
        _paired_devices[pairing_id]["last_active"] = time.time()

    try:
        # 消息循环
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # 处理心跳
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "timestamp": time.time()})
                continue

            # 更新最后活跃时间
            if pairing_id in _paired_devices:
                _paired_devices[pairing_id]["last_active"] = time.time()

            # 处理其他消息（这里可以扩展）
            logger.info("Received message from %s: %s", pairing_id, message)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", connection_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
    finally:
        # 清理连接
        manager.disconnect(connection_id, user_id)
        _ws_connections.pop(pairing_id, None)

        # 更新设备在线状态
        if pairing_id in _paired_devices:
            _paired_devices[pairing_id]["is_online"] = False
