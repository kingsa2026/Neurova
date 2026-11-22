/**
 * TunnelToken - 隧道准入令牌信封与 auth 首帧构造（端侧镜像）
 *
 * 权威口径在服务端 `neurova/tunnel/protocol.py`（signTunnelToken/verifyTunnelToken）：
 *   信封 `nv1:{type}:{issuedAt}:{nonce}:{hmac}`，
 *   HMAC-SHA256(secret, "nv1:{type}:{stamp}:{nonce}")，stamp 为秒级整数。
 * 本文件只做**端侧构造**：连接建立后的首条 auth 帧（U9.1）。
 *   - 令牌已是 nv1 信封 → 原样用，tokenType 取信封签名内的型（声明型必须与签名型一致）；
 *   - 令牌是裸密钥（legacy）→ 本地签 nv1:agent 信封（数据面正解，凭据全文不进 auth 帧）。
 *
 * HMAC 摘要经参数注入：设备侧实现见 `TunnelTokenCrypto.ets`
 * （@ohos.security.cryptoFramework）；本文件不 import 任何 @kit 模块，
 * 保持纯逻辑，可被 Node 直跑单测对拍（test/node）。
 */

/** 信封版本前缀（protocol.TUNNEL_TOKEN_ENVELOPE） */
export const TUNNEL_TOKEN_ENVELOPE = 'nv1';
/** 数据面令牌型（protocol.TOKEN_TYPE_AGENT） */
export const TUNNEL_TOKEN_TYPE_AGENT = 'agent';
/** 令牌型全集（protocol.TUNNEL_TOKEN_TYPES） */
const TOKEN_TYPES: string[] = ['agent', 'user', 'service'];

/** HMAC-SHA256 摘要函数形态：回小写 hex（与 python hexdigest 同形） */
export type HmacSha256Hex = (key: string, message: string) => string;

/** U9.1 auth 首帧（连接建立后的第一条消息） */
export interface TunnelAuthFrame {
  type: string;
  token: string;
  tokenType: string;
}

function isAllDigits(value: string): boolean {
  if (value.length === 0) {
    return false;
  }
  for (let i = 0; i < value.length; i++) {
    const c = value.charAt(i);
    if (c < '0' || c > '9') {
      return false;
    }
  }
  return true;
}

/** 信封形状判定（对齐 protocol.parseTunnelToken：5 段、型合法、秒级整数戳） */
export function isTunnelTokenEnvelope(token: string): boolean {
  if (!token.startsWith(TUNNEL_TOKEN_ENVELOPE + ':')) {
    return false;
  }
  const parts = token.split(':');
  if (parts.length !== 5) {
    return false;
  }
  if (TOKEN_TYPES.indexOf(parts[1]) === -1) {
    return false;
  }
  if (!isAllDigits(parts[2])) {
    return false;
  }
  return parts[3].length > 0 && parts[4].length > 0;
}

/** 信封签名内的令牌型；非信封回空串 */
export function tunnelTokenClaimType(token: string): string {
  return isTunnelTokenEnvelope(token) ? token.split(':')[1] : '';
}

/** 待签消息 `nv1:{type}:{stamp}:{nonce}`（stamp 向下取整到秒） */
export function tunnelTokenMessage(tokenType: string, issuedAtSeconds: number, nonce: string): string {
  return TUNNEL_TOKEN_ENVELOPE + ':' + tokenType + ':' + Math.floor(issuedAtSeconds).toString() + ':' + nonce;
}

/** 信封 = 待签消息 + ':' + HMAC hex */
export function assembleTunnelTokenEnvelope(message: string, signatureHex: string): string {
  return message + ':' + signatureHex;
}

/** 定型签发（protocol.signTunnelToken 端侧镜像；摘要注入） */
export function buildNv1Envelope(secret: string, tokenType: string, issuedAtSeconds: number,
                                 nonce: string, hmacSha256Hex: HmacSha256Hex): string {
  const message = tunnelTokenMessage(tokenType, issuedAtSeconds, nonce);
  return assembleTunnelTokenEnvelope(message, hmacSha256Hex(secret, message));
}

/** 裸密钥 → nv1:agent 信封（数据面正解） */
export function signAgentTunnelToken(secret: string, issuedAtSeconds: number,
                                     nonce: string, hmacSha256Hex: HmacSha256Hex): string {
  return buildNv1Envelope(secret, TUNNEL_TOKEN_TYPE_AGENT, issuedAtSeconds, nonce, hmacSha256Hex);
}

/** 组装 auth 首帧对象（发送时 JSON.stringify） */
export function buildTunnelAuthFrame(token: string, tokenType: string): TunnelAuthFrame {
  const frame: TunnelAuthFrame = { type: 'auth', token: token, tokenType: tokenType };
  return frame;
}

/**
 * relay 鉴权首帧的端侧决策（纯函数，同步摘要注入）：
 * - 已是 nv1 信封：原样用，tokenType 取信封签名内的型；
 * - 裸密钥：本地签 nv1:agent 信封（正解，legacy 裸密钥也可原样进 auth 帧降级放行，
 *   但那会把凭据全文送上线——本端默认不走）。
 */
export function resolveTunnelAuthFrame(token: string, issuedAtSeconds: number, nonce: string,
                                       hmacSha256Hex: HmacSha256Hex): TunnelAuthFrame {
  if (isTunnelTokenEnvelope(token)) {
    return buildTunnelAuthFrame(token, tunnelTokenClaimType(token));
  }
  return buildTunnelAuthFrame(
    signAgentTunnelToken(token, issuedAtSeconds, nonce, hmacSha256Hex),
    TUNNEL_TOKEN_TYPE_AGENT);
}
