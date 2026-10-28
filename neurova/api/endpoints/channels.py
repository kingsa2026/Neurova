from __future__ import annotations

import asyncio
import re

"""
渠道管理 API 端点

提供渠道适配器的状态查询、连接/断开、主动发送与 Webhook 回调处理。

路由清单（挂载前缀 `/api/v1` + `/channel-adapters`；每条都是**可寻址的真地址**）：
- GET  /api/v1/channel-adapters                                  - 全部实例健康状态（跨 agent）
- GET  /api/v1/channel-adapters/health/all                       - 同一份健康视图
- GET  /api/v1/channel-adapters/conflicts/check                  - 跨 agent 机器人身份冲突检测
- GET  /api/v1/channel-adapters/{channel_type}                   - 指定实例健康状态
- POST /api/v1/channel-adapters/{channel_type}/connect           - 连接该实例
- POST /api/v1/channel-adapters/{channel_type}/disconnect        - 断开该实例
- POST /api/v1/channel-adapters/{channel_type}/send              - 经该实例发送消息
- POST /api/v1/channel-adapters/{channel_type}/webhook           - 平台回调入口（飞书/钉钉/企微）
- POST /api/v1/channel-adapters/{channel_type}/restart           - 重启该实例
- POST /api/v1/channel-adapters/{channel_type}/clear-queue       - 清空该实例待处理队列

除 webhook 与 conflicts/check 外都接受 `agent_id` Query（缺省 default，实例表主键是
`(agent_id, channel_type)`）。这份清单由判据按真路由表**双向**核对——此前它写的是
`/channel-adapters/channels/...`（多一段、实际不存在）还漏了前端真正在用的三条；
契约文本错比没写更坏：它看起来是权威的。
"""

from neurova.core.logger import get_logger
from typing import TYPE_CHECKING, Any, Dict, Optional

from neurova.channels.base import ChannelMessage

from neurova.api.deps import get_current_user
from neurova.api.agent_access import requireAgentOwner
from fastapi import Depends, APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from neurova.channels.base import ChannelEventType, ChannelMessage
from neurova.channels.manager import get_channel_manager

if TYPE_CHECKING:  # 只作注解用；运行时靠 `from __future__ import annotations` 不解析
    from neurova.channels.base import ChannelMessage

logger = get_logger(__name__)


def _norm_agent(agent_id: Any) -> str:
    """空/非字符串身份回落 default（与 `channel_config._norm_agent` 同口径）。

    端点被直调（不经 FastAPI DI）时 `Query(default=...)` 会以 Query 对象进入
    函数体，故必须判类型而不只判真值。
    """
    return agent_id if isinstance(agent_id, str) and agent_id else "default"

router = APIRouter(tags=["渠道管理"])

# ============================================================
# 请求/响应模型
# ============================================================


class ChannelStatusResponse(BaseModel):
    """渠道状态响应"""

    channel_type: str
    connected: bool
    enabled: bool = True
    extra: Dict[str, Any] = Field(default_factory=dict)


class ChannelListResponse(BaseModel):
    """渠道列表响应"""

    running: bool
    adapters: Dict[str, ChannelStatusResponse]


class SendMessageRequest(BaseModel):
    """发送消息请求"""

    chat_id: str = Field(..., description="会话 ID")
    content: str = Field(..., description="消息内容")
    message_type: str = Field("text", description="消息类型: text, markdown, image, file")
    extra: Dict[str, Any] = Field(default_factory=dict)


class SendMessageResponse(BaseModel):
    """发送消息响应"""

    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None


class ConnectRequest(BaseModel):
    """连接渠道请求"""

    app_id: str = Field("", description="应用 ID")
    app_secret: str = Field("", description="应用密钥")
    use_stream: bool = Field(True, description="是否使用 Stream 模式")
    extra: Dict[str, Any] = Field(default_factory=dict)


class WebhookConfigRequest(BaseModel):
    """Webhook 配置请求"""

    webhook_url: str = Field("", description="Webhook 回调 URL")
    token: str = Field("", description="验证 Token")
    encrypt_key: str = Field("", description="加密密钥")


# ============================================================
# 渠道管理
# ============================================================


@router.get("", summary="列出所有渠道状态")
async def list_channels(current_user: Any = Depends(get_current_user),):
    """列出所有已注册的渠道适配器状态"""
    manager = get_channel_manager()
    health = await manager.health_check()
    return health


@router.get("/{channel_type}", summary="获取指定渠道状态")
async def get_channel_status(
    channel_type: str,
    agent_id: str = Query(default="default", description="Agent ID（实例表主键的一半）"),
    current_user: Any = Depends(get_current_user),):
    """获取指定渠道的连接状态

    与 restart / clear-queue 同形带 `agent_id`：缺省仍是 default（既有调用者一字不变），
    不传就打不到非 default 名下那条渠道——同一个 router 里"重启能精确到 agent、查状态不能"是两种口径。
    """
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type, agent_id=agent_id)
    if adapter is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_type}' not found (agent={agent_id})")
    return await adapter.health_check()


@router.post("/{channel_type}/connect", summary="连接指定渠道")
async def connect_channel(
    channel_type: str,
    request: ConnectRequest,
    agent_id: str = Query(default="default", description="Agent ID（实例表主键的一半）"),
    current_user: Any = Depends(get_current_user),):
    """连接指定渠道适配器"""
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type, agent_id=agent_id)
    if adapter is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_type}' not found (agent={agent_id})")

    # 更新配置
    if request.app_id:
        adapter.config.app_id = request.app_id
    if request.app_secret:
        adapter.config.app_secret = request.app_secret
    adapter.config.use_stream = request.use_stream
    adapter.config.extra.update(request.extra)

    success = await adapter.connect()
    return {"success": success, "channel_type": channel_type, "agent_id": agent_id}


@router.post("/{channel_type}/disconnect", summary="断开指定渠道")
async def disconnect_channel(
    channel_type: str,
    agent_id: str = Query(default="default", description="Agent ID（实例表主键的一半）"),
    current_user: Any = Depends(get_current_user),):
    """断开指定渠道适配器"""
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type, agent_id=agent_id)
    if adapter is None:
        raise HTTPException(
            status_code=404,
            detail=f"Channel '{channel_type}' not found (agent={agent_id})")
    await adapter.disconnect()
    return {"success": True, "channel_type": channel_type, "agent_id": agent_id}


@router.post("/{channel_type}/send", summary="发送消息")
async def send_message(
    channel_type: str,
    request: SendMessageRequest,
    agent_id: str = Query(default="default", description="Agent ID（实例表主键的一半）"),
    current_user: Any = Depends(get_current_user),):
    """通过指定渠道发送消息"""
    manager = get_channel_manager()
    # `agent_id` 由查询参数定，不让请求体 extra 里的同名字段越权决定发给哪个 bot
    msg_id = await manager.send_message(
        channel_type=channel_type,
        chat_id=request.chat_id,
        content=request.content,
        message_type=request.message_type,
        **{**request.extra, "agent_id": agent_id},
    )
    return SendMessageResponse(
        success=msg_id is not None,
        message_id=msg_id,
        error=None if msg_id else "Failed to send message",
    )


# ============================================================
# Webhook 回调处理
# ============================================================


def _feishuEnvelope(data: dict) -> tuple:
    """飞书回调信封的唯一取法：返回 (token, event_type)。

    v2 在 `header`，v1 在顶层；令牌比不比、怎么比只在适配器那一份。
    事件类型也在这里取，避免 handler 再写一遍 header 读法。
    """
    header = data.get("header") or {}
    token = header.get("token") or data.get("token") or ""
    return token, str(header.get("event_type") or "")


def _feishuCallbackToken(data: dict) -> str:
    return _feishuEnvelope(data)[0]


def _wecomEncryptOf(xmlText: str) -> str:
    """从企业微信回调体外层取 `<Encrypt>` 密文——只用于**选实例**时算签名。

    真正的投递仍走 `WeComAdapter.handle_callback`，它自己按安全口径解析 XML（限大小、
    拒 DOCTYPE/ENTITY）并再核一次签名；这里读到的东西不决定投递，放宽不了任何一道门。
    """
    match = re.search(r"<Encrypt>(.*?)</Encrypt>", xmlText, re.S)
    return match.group(1) if match else ""


def inboundCredentialPredicate(channelType: str, body: bytes, queryParams, headers):
    """返回"这条回调在这只实例自己的凭据下验得通吗"的谓词；不知道就返回 None（不猜）。

    设计本意是每 agent 各有专属渠道配置，而回调 URL 只带渠道类型——三平台的验签面用的都是
    实例自己的凭据（飞书 verification token、钉钉 appSecret、企微 callback token），所以
    同类型多只实例时该由凭据裁决落到哪一只，而不是让 default 插队（§6-197）。
    没有验签面的类型、或信封读不懂（畸形体、飞书密文回调）⇒ None，退回 §6-189 的原语义。
    """
    import json

    if channelType == "feishu":
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        if "encrypt" in data and "event" not in data and "challenge" not in data:
            return None  # 密文里没有可读令牌；真原因由 handler 点名，别在这里冒充"凭据不匹配"
        token = _feishuCallbackToken(data)

        def _feishuOk(adapter) -> bool:
            try:
                adapter.verify_event_token(token)
            except ValueError:
                return False
            return True

        return _feishuOk

    if channelType == "dingtalk":
        timestamp = (headers.get("timestamp") or "") if headers is not None else ""
        sign = (headers.get("sign") or "") if headers is not None else ""

        def _dingtalkOk(adapter) -> bool:
            try:
                adapter.verify_callback_headers(timestamp, sign)
            except ValueError:
                return False
            return True

        return _dingtalkOk

    if channelType == "wechat":
        msgSignature = queryParams.get("msg_signature", "") if queryParams is not None else ""
        timestamp = queryParams.get("timestamp", "") if queryParams is not None else ""
        nonce = queryParams.get("nonce", "") if queryParams is not None else ""
        encrypt = _wecomEncryptOf(body.decode("utf-8", errors="replace"))
        if not encrypt:
            return None

        def _wechatOk(adapter) -> bool:
            try:
                adapter.verifyKfSignature(msgSignature, timestamp, nonce, encrypt)
            except (ValueError, AttributeError):
                return False
            return True

        return _wechatOk

    if channelType == "wecom":
        msgSignature = queryParams.get("msg_signature", "") if queryParams is not None else ""
        if not msgSignature:
            return None  # 连签名都没有 ⇒ 谓词无从判断，交给 handler 去拒
        timestamp = queryParams.get("timestamp", "") if queryParams is not None else ""
        nonce = queryParams.get("nonce", "") if queryParams is not None else ""
        try:
            encrypt = _wecomEncryptOf(body.decode("utf-8", errors="replace"))
        except UnicodeError:
            return None

        def _wecomOk(adapter) -> bool:
            try:
                adapter.verifyCallbackSignature(msgSignature, timestamp, nonce, encrypt)
            except (ValueError, AttributeError):
                # AttributeError：这只实例根本没有那道门（未登记过的适配器类型），同样算不匹配
                return False
            return True

        return _wecomOk

    return None


@router.post("/{channel_type}/webhook", summary="Webhook 回调入口")
async def handle_webhook(channel_type: str, request: Request):
    """
    处理各平台的 Webhook 回调

    - 飞书: POST JSON，包含 challenge / header / event
    - 钉钉: POST JSON 或 form-data
    - 企业微信: POST XML
    """
    manager = get_channel_manager()
    # 先取体再解析：落哪一只实例由这条回调自己的凭据说（§6-197）。解析仍只在
    # `ChannelManager.resolveInboundAdapter` 那一处——实例表按 (agent_id, channel_type) 存，
    # 而回调 URL 只带 channel_type；取不到时几种失败要分得开（没配 / 歧义 / 凭据都不匹配 /
    # 凭据被两只共用），歧义绝不静默投给任意一个 bot。
    body = await request.body()
    adapter, failureReason = manager.resolveInboundAdapter(
        channel_type,
        inboundCredentialPredicate(channel_type, body, request.query_params, request.headers))
    if adapter is None:
        raise HTTPException(status_code=404, detail=failureReason)

    try:
        if channel_type == "feishu":
            return await _handle_feishu_webhook(adapter, body, request.query_params)
        elif channel_type == "dingtalk":
            return await _handle_dingtalk_webhook(
                adapter, body, request.query_params, request.headers)
        elif channel_type == "wecom":
            return await _handle_wecom_webhook(adapter, body, request.query_params, request)
        elif channel_type == "wechat":
            return await _handle_wechat_webhook(adapter, body, request.query_params)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported webhook for {channel_type}")
    except HTTPException:
        raise
    except ValueError as e:
        # 各适配器把"这不是来自平台的合法回调"统一翻成 ValueError：拒在投递之前，
        # 一条消息都不会进 manager。与意外故障（下面那支 500）分开，运维才分得清两种响。
        logger.warning("渠道回调被拒 %s: %s", channel_type, e)
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Webhook error for %s: %s", channel_type, e)
        raise HTTPException(status_code=500, detail=str(e))


async def _handle_feishu_webhook(adapter, body: bytes, query_params) -> dict:
    """处理飞书 Webhook

    投递前必须先过适配器的 verification token 门（C-23 同口径，未配置即 fail-closed）。
    此前这一支自己 echo challenge、自己把 `sender_id` 从请求体里取出来投进 manager，
    等于任何能 POST 到本端点的人都能冒充任意飞书用户驱动 agent 回合。
    """
    import json

    data = json.loads(body)

    # 密文回调（平台配了 Encrypt Key 时只给 {"encrypt": ...}）：本批不解密，就明确拒绝并点名原因。
    # "读不到令牌就当是明文放行"是最坏的那种兜底——那条路会让验签形同不存在。
    if "encrypt" in data and "event" not in data and "challenge" not in data:
        raise ValueError(
            "Feishu callback rejected: encrypted event is not supported here (configure "
            "Encrypt Key off, or implement decryption before dispatch)")

    # 令牌位置两代信封不同：v2 在 header.token，v1 在顶层 token。取哪个由这里负责，
    # "比不比、怎么比"只在适配器那一份。取法与选实例用的谓词同一处（§6-197）。
    token = _feishuCallbackToken(data)

    # URL 验证（challenge）——交给适配器核完令牌再回，不在这里 echo
    if "challenge" in data:
        return adapter.verify_url_challenge(data["challenge"], token)

    adapter.verify_event_token(token)

    # 服务台工单更新是事件，不是消息：走适配器的阶段判定，命中才 emit 接管事件。
    # 不能交给 buildInboundMessage（它读 message 字段，工单事件没有）。
    if _feishuEnvelope(data)[1] == "helpdesk.ticket.updated_v1":
        takeover = adapter.handle_helpdesk_ticket_event(data.get("event") or {})
        if takeover is not None:
            await adapter._emit_event(*takeover)
        return {"code": 0}

    # 内容口径不在这里：事件体 → 统一消息 只有 `FeishuAdapter.buildInboundMessage` 一份（§6-185）。
    # 此前这一支自己写了一份"只认 text"的解析，于是同一平台两种形状——语音进回合是空串、
    # 外部用户（user_id 为 null）的 sender_id 是空串、@提及完全不结构化，而 Stream 那半区三件都做。
    # 走线程池的原因：audio 分支含同步 HTTP 下载，一次 15 秒的下载会把整个进程的入站一起拖住。
    channel_msg = await asyncio.to_thread(
        adapter.buildInboundMessage, data.get("event") or {}, data)

    await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
    return {"code": 0}


async def _handle_dingtalk_webhook(adapter, body: bytes, query_params, headers) -> dict:
    """处理钉钉 Webhook

    投递前先按平台「接收消息」协议核 header 的 `timestamp` + `sign`（HMAC-SHA256、
    key=appSecret、偏差 1 小时）。这一支此前什么都不核，`senderId` 直接取自请求体。
    """
    import json

    adapter.verify_callback_headers(headers.get("timestamp", ""), headers.get("sign", ""))

    # 钉钉 Webhook 可能是 JSON 或 form-data
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # form-data 格式
        data = dict(query_params)

    msg_id = data.get("msgId", "")
    sender_id = data.get("senderId", "")
    sender_name = data.get("senderNick", "")
    chat_id = data.get("conversationId", "")
    msg_type = data.get("msgtype", "text")
    conversation_type = data.get("conversationType", "1")

    content = ""
    if msg_type == "text":
        content = data.get("text", {}).get("content", "").strip()

    channel_msg = adapter._make_message(
        message_id=msg_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        chat_id=chat_id,
        chat_type="group" if conversation_type == "2" else "p2p",
        message_type=msg_type,
        raw_event=data,
    )

    await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
    return {"errcode": 0}


async def _emitChannelMessage(adapter, event_type, channel_msg) -> None:
    """EventDoor 形状守卫的显式入口：只接单个消息对象，不接任意对象。

    注解里不写 `ChannelMessage`：那类在 `neurova.channels.base`（重型渠道包），
    本端点模块不为一个注解把它提到顶层（§3 可选依赖惰性 import），而字符串前向引用
    在静态闸眼里就是未定义名（F821）。形状由本函数只转一次的调用面保证。
    """
    await adapter._emit_event(event_type, channel_msg)


async def _handle_wechat_webhook(adapter, body: bytes, query_params) -> dict:
    """微信客服回调：URL 验证解密 echostr；事件回调走 sync_msg 后逐条投递。"""
    if not getattr(adapter, "kf_mode", False):
        raise ValueError("WeChat webhook only supports kf_mode")
    msg_signature = query_params.get("msg_signature", "")
    timestamp = query_params.get("timestamp", "")
    nonce = query_params.get("nonce", "")
    echostr = query_params.get("echostr", "")
    if echostr:
        return Response(
            content=adapter.verify_kf_url(msg_signature, timestamp, nonce, echostr),
            media_type="text/plain",
        )
    events = await asyncio.to_thread(
        adapter.handle_kf_callback,
        msg_signature, timestamp, nonce, body.decode("utf-8"),
    )
    for event_type, message in events:
        await _emitChannelMessage(adapter, event_type, message)
    return {"errcode": 0}


async def _handle_wecom_webhook(adapter, body: bytes, query_params, request) -> dict:
    """处理企业微信 Webhook"""
    msg_signature = request.query_params.get("msg_signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    echostr = request.query_params.get("echostr", "")

    # URL 验证
    if echostr:
        return Response(
            content=adapter.verify_url(msg_signature, timestamp, nonce, echostr),
            media_type="text/plain",
        )

    # 消息回调
    xml_data = body.decode("utf-8")
    reply_xml = adapter.handle_callback(msg_signature, timestamp, nonce, xml_data)

    if reply_xml:
        return Response(content=reply_xml, media_type="application/xml")
    return {"errcode": 0}


# ============================================================
# 健康检查
# ============================================================


@router.get("/health/all", summary="渠道健康检查")
async def health_check_all():
    """检查所有渠道的健康状态"""
    manager = get_channel_manager()
    return await manager.health_check()


# ============================================================
# B4-a 渠道管理能力面
# ============================================================


@router.post("/{channel_type}/restart", summary="重启指定渠道")
async def restart_channel(
    channel_type: str,
    agent_id: str = Query(default="default", description="Agent ID"),
    current_user: Any = Depends(get_current_user),
):
    """渠道重启（disconnect → connect，配置变更生效/断线重连）。

    agent 维度不可省：实例表主键是 `(agent_id, channel_type)`，同一平台在不
    同 agent 下可以是两个独立 bot。缺了它，用户在「凯蒂」视图点重启动的是
    default 的长连接 —— 屏幕上看不出差别。

    归属门同为不可省：重启是**破坏性运维动作**（拆掉该 agent 的 bot 长连接再重连），
    只验登录态等于任何登录用户都能让别人的机器人掉线。判据复用配置面的同一单源。
    """
    requireAgentOwner(_norm_agent(agent_id), current_user, action="重启")
    manager = get_channel_manager()
    result = await manager.restart_channel(channel_type, agent_id=_norm_agent(agent_id))
    if not result.get("success") and "error" in result:
        return {"code": 1, "message": result["error"], "data": result}
    return {"code": 0, "message": "Channel restarted", "data": result}


@router.post("/{channel_type}/clear-queue", summary="清空渠道待处理队列")
async def clear_channel_queue(
    channel_type: str,
    agent_id: str = Query(default="default", description="Agent ID"),
    current_user: Any = Depends(get_current_user),
):
    """清空该 (agent, 渠道) 入站队列中的待处理事件（积压清理）。

    同平台两个 agent 各有各的积压：按渠道裸名清会把别人的待办一起删掉，
    而用户只能看见自己视图里的积压数。
    清队列是**不可逆的删除**，故归属门与配置面同源（非属主不得清他人积压）。
    """
    agent = _norm_agent(agent_id)
    requireAgentOwner(agent, current_user, action="清空队列")
    manager = get_channel_manager()
    try:
        cleared = manager.clear_channel_queue(channel_type, agent_id=agent)
    except Exception as e:  # noqa: BLE001 — 队列不可用诚实报错
        raise HTTPException(status_code=503, detail=f"入站队列不可用: {e}")
    return {"code": 0, "message": "Queue cleared",
            "data": {"channel_type": channel_type, "agent_id": agent, "cleared": cleared}}


@router.get("/conflicts/check", summary="机器人身份冲突检测")
async def channel_conflict_check(current_user: Any = Depends(get_current_user)):
    """扫描**全量 agent** 已注册渠道，检测复用同一身份凭据（app_id/api_key）的冲突。

    扫描面覆盖所有 agent：同身份跨 agent 复用正是最容易漏、后果最重的一类
    （两个 bot 抢同一条平台事件流），只扫 default 视图等于对它完全失明。
    结果条目的 channel 带上 agent 前缀，便于分辨是哪两个实例。

    本条是**跨全量 agent 的读**：清单里带着各 bot 的平台身份（app_id），
    非管理员从中可读别人的机器人身份，故限管理员——判据不新造，仍是
    `requireAgentOwner` 的无主形态（`default` 即无主 agent：仅 admin）。
    """
    requireAgentOwner("default", current_user, action="检测全量渠道身份冲突")
    manager = get_channel_manager()
    result = manager.conflict_check()
    return {"code": 0, "message": "success", "data": result}
