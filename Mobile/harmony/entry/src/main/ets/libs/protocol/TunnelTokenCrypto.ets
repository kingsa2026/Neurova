/**
 * TunnelTokenCrypto - 隧道令牌签名的设备侧 HMAC 实现
 *
 * 纯逻辑（信封组装/解析/auth 帧决策）在 `TunnelToken.ets`（不依赖 @kit，Node 可测）；
 * 本文件只提供 @ohos.security.cryptoFramework 的 HMAC-SHA256 摘要与随机 nonce，
 * 供 WebSocketAdapter 在 relay 模式发首条 auth 前本地签 `nv1:agent` 信封。
 */

import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { util } from '@kit.ArkTS';
import {
  TunnelAuthFrame,
  TUNNEL_TOKEN_TYPE_AGENT,
  buildTunnelAuthFrame,
  isTunnelTokenEnvelope,
  tunnelTokenClaimType,
  tunnelTokenMessage,
  assembleTunnelTokenEnvelope,
} from './TunnelToken';

function utf8Bytes(value: string): Uint8Array {
  const encoder = new util.TextEncoder();
  return encoder.encodeInto(value);
}

function bytesToHex(bytes: Uint8Array): string {
  const hex: string[] = [];
  for (let i = 0; i < bytes.length; i++) {
    hex.push((bytes[i] & 0xFF).toString(16).padStart(2, '0'));
  }
  return hex.join('');
}

/** HMAC-SHA256(key, message) → 小写 hex（与 python hmac.hexdigest 同形） */
export async function hmacSha256Hex(key: string, message: string): Promise<string> {
  // 密钥经 convertKey 导入（生成器用裸 'HMAC'：任意长度密钥均可；摘要型由 Mac 侧定 SHA256）
  const keyGenerator = cryptoFramework.createSymKeyGenerator('HMAC');
  const keyBlob: cryptoFramework.DataBlob = { data: utf8Bytes(key) };
  const symKey = await keyGenerator.convertKey(keyBlob);
  const mac = cryptoFramework.createMac('HMAC|SHA256');
  await mac.init(symKey);
  const input: cryptoFramework.DataBlob = { data: utf8Bytes(message) };
  await mac.update(input);
  const digest: cryptoFramework.DataBlob = await mac.doFinal();
  return bytesToHex(digest.data);
}

/** 16 位 hex 随机 nonce（对齐 protocol.signTunnelToken 的 secrets.token_hex(8)） */
export async function randomNonceHex(byteLength: number = 8): Promise<string> {
  const random = cryptoFramework.createRandom();
  const blob: cryptoFramework.DataBlob = await random.generateRandom(byteLength);
  return bytesToHex(blob.data);
}

/** 裸密钥 → nv1:agent 信封（设备侧签名） */
export async function signAgentTunnelToken(secret: string, issuedAtSeconds: number,
                                           nonce: string): Promise<string> {
  const message = tunnelTokenMessage(TUNNEL_TOKEN_TYPE_AGENT, issuedAtSeconds, nonce);
  const signature = await hmacSha256Hex(secret, message);
  return assembleTunnelTokenEnvelope(message, signature);
}

/**
 * relay 鉴权首帧（设备侧，异步签名）：
 * - 已是 nv1 信封 → 原样用，tokenType 取信封签名内的型；
 * - 裸密钥 → 本地签 nv1:agent 信封（凭据全文不进 auth 帧）。
 */
export async function resolveTunnelAuthFrame(token: string, issuedAtSeconds: number,
                                             nonce: string): Promise<TunnelAuthFrame> {
  if (isTunnelTokenEnvelope(token)) {
    return buildTunnelAuthFrame(token, tunnelTokenClaimType(token));
  }
  return buildTunnelAuthFrame(
    await signAgentTunnelToken(token, issuedAtSeconds, nonce),
    TUNNEL_TOKEN_TYPE_AGENT);
}
