"""渠道身份绑定的流程层：发码 / 渠道内消费 / 列表 / 手工绑 / 解绑（工单 2026-10-10 批 4）。

放在 channels 包而不是端点文件里，是因为**两个入口都要走同一套规则**：Web 控制台发码，
渠道里那条消息消费码。把"码怎么用"抄两份，就会出现"网页发的码渠道认不了"这类无人认领的漂移。

三条刻意写在此处的口径：

1. 码只绑"这条渠道身份"，不绑"任意人"。目标键 `target = agent|渠道`，
   而**要绑成谁**存在码的 metadata 里（发码时由登录态写入）；渠道消息里的发送者
   取自身 `channel_user_id`。这样即使码被别人看到，也只会把**看到码的那个人**绑上去，
   不会把别人的渠道身份改写到第三方账号下——绑定动作的主体永远是发消息的那个发送者。
2. 码一次性：`verify_code(mark_as_used=True)` 成功即作废；重复使用返回 False。
3. 解绑不删行（`UserIdentityManager.revokeBinding`），留痕才答得出"这个人以前算谁的"。

不在此层做的事：不解析入站报文自带的 `user_id`（§6-127 红线，身份只由
`UserIdentityManager.resolveTurnIdentity` 单点给出）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from neurova.channels.user_identity import UserIdentityManager
from neurova.core.logger import get_logger

logger = get_logger(__name__)

#: 渠道里可用于绑定的写法：`绑定 123456` / `bind 123456`（大小写不限，允许全角空格）。
BIND_COMMAND = re.compile(r"^\s*(?:绑定|bind)\s*([0-9]{4,8})\s*$", re.IGNORECASE)

#: 码的目标键前缀（与注册/改密那些类型共用一张码表，靠 target 命名空间区隔）。
_TARGET_PREFIX = "channel-bind"

CODE_TTL_SECONDS = 600
CODE_LENGTH = 6


def targetFor(agentId: str, channelType: str) -> str:
    return f"{_TARGET_PREFIX}:{agentId}:{channelType}"


def parseBindCommand(text: Any) -> Optional[str]:
    """这条消息是在提交绑定码吗？是则返回码，否则 None（不改名、不猜测）。"""
    match = BIND_COMMAND.match(str(text or ""))
    return match.group(1) if match else None


def bindCommandText(code: str) -> str:
    """发给用户看的那句话——与上面的解析正则**同一出处**。

    前端/端点各自抄一份"绑定 XXXX"，正则一改就说错话；这里给一份，判据
    `test_bindCommandTextRoundTrips` 把两者咬死。
    """
    return f"绑定 {str(code or '').strip()}"


def issueBindingCode(
    agentId: str,
    channelType: str,
    userId: str,
    *,
    neuserId: Optional[str] = None,
    displayName: Optional[str] = None,
    ttl: int = CODE_TTL_SECONDS,
) -> str:
    """为"该 agent + 该渠道"发一张绑定码，码里记着要绑成的平台账号（来自登录态）。"""
    from neurova.auth.verification_code import VerificationType, get_verification_code_model

    return get_verification_code_model().create_code(
        target=targetFor(agentId, channelType),
        code_type=VerificationType.BIND_CHANNEL,
        expires_in=ttl,
        length=CODE_LENGTH,
        metadata={
            "user_id": userId,
            "neuser_id": neuserId or userId,
            "display_name": displayName or "",
        },
    )


def consumeBindingCode(agentId: str, channelType: str, channelUserId: str,
                       code: str) -> Dict[str, Any]:
    """渠道内用码绑定：成功→绑定已写入；失败→点名原因（不静默回"没绑上"三个字）。

    先读 metadata 再校验，是因为校验成功后行会被标记已用，之后再读可能拿到的是
    "已用过"的那条记录——顺序反了就会出现"码有效但拿不到归属"的假失败。
    """
    from neurova.auth.verification_code import VerificationType, get_verification_code_model

    model = get_verification_code_model()
    target = targetFor(agentId, channelType)
    info = model.get_code_info(target, VerificationType.BIND_CHANNEL)
    if not info:
        return {"ok": False, "reason": "no_pending_code"}
    if not model.verify_code(target, str(code or "").strip(),
                            VerificationType.BIND_CHANNEL, mark_as_used=True):
        return {"ok": False, "reason": "code_invalid_or_expired"}
    owner = (info.metadata or {}) if isinstance(info.metadata, dict) else {}
    userId = str(owner.get("user_id") or "").strip()
    if not userId:
        return {"ok": False, "reason": "code_without_account"}
    UserIdentityManager().bindIdentity(
        agentId, channelType, channelUserId, userId,
        neuserId=str(owner.get("neuser_id") or "") or None,
        displayName=owner.get("display_name") or None,
        boundBy="bind-code",
    )
    logger.info("渠道身份绑定成功: agent=%s 渠道=%s 发送者=%s → 账号=%s",
                agentId, channelType, channelUserId, userId)
    return {"ok": True, "user_id": userId, "channel_user_id": channelUserId}


def listBindings(agentId: str) -> List[Dict[str, Any]]:
    return UserIdentityManager().listBindings(agentId)


def manualBind(agentId: str, channelType: str, channelUserId: str, userId: str,
               *, neuserId: Optional[str] = None, boundBy: str = "") -> Dict[str, Any]:
    return UserIdentityManager().bindIdentity(
        agentId, channelType, channelUserId, userId,
        neuserId=neuserId, boundBy=boundBy or "console",
    )


def revoke(agentId: str, channelType: str, channelUserId: str) -> bool:
    return UserIdentityManager().revokeBinding(agentId, channelType, channelUserId)


def boundAccount(agentId: str, channelType: str,
                 channelUserId: str) -> Optional[str]:
    """这一格当前绑到谁（未绑定/已解绑 → None，由调用方决定回什么话）。"""
    return UserIdentityManager().resolveUserId(agentId, channelType, channelUserId)


__all__ = [
    "BIND_COMMAND", "CODE_TTL_SECONDS", "parseBindCommand", "bindCommandText",
    "issueBindingCode",
    "consumeBindingCode", "listBindings", "manualBind", "revoke", "boundAccount",
    "targetFor",
]
