/**
 * TunnelToken 单测（Node 直跑）：信封判定 / auth 首帧构造 / nv1 签名对拍
 *
 * 对拍基准：python `neurova/tunnel/protocol.signTunnelToken`（权威签发实现）
 * 用固定 issuedAt 与 nonce 产出的确定性向量——ArkTS 侧 buildNv1Envelope
 * （摘要经 node:crypto 注入）必须逐字节复现同一信封。
 */

import { createHmac } from 'node:crypto';
import {
  buildNv1Envelope,
  buildTunnelAuthFrame,
  isTunnelTokenEnvelope,
  resolveTunnelAuthFrame,
  signAgentTunnelToken,
  tunnelTokenClaimType,
  tunnelTokenMessage,
} from '../../entry/src/main/ets/libs/protocol/TunnelToken';
import { check, eqStr, source } from './Harness';

/** node:crypto 版 HMAC-SHA256（仅测试注入用；设备侧走 cryptoFramework） */
function nodeHmacSha256Hex(key: string, message: string): string {
  return createHmac('sha256', key).update(message).digest('hex');
}

/** python signTunnelToken(secret, type, issuedAt=..., nonce=...) 的确定性向量 */
const VECTORS: Array<[string, string, number, string, string]> = [
  ['k9-secret-0001', 'agent', 1763784000, '0123456789abcdef',
    'nv1:agent:1763784000:0123456789abcdef:20f3d128f1fccc7b3c159072a5126e59c68bc547368d8dceeaa21b4a07cbf3bf'],
  ['enrollment-token-for-live-s2', 'agent', 1763784000, '0123456789abcdef',
    'nv1:agent:1763784000:0123456789abcdef:a0bca36e304ebf94a31351aae61f287b6f8184863c712dbc72559db116da2118'],
  ['a-different-secret', 'service', 1763784000, '0123456789abcdef',
    'nv1:service:1763784000:0123456789abcdef:c4d75b92d1ac43d2bc38c683c12a20dcc6a5e2d05af0923fa629a6c57de56263'],
  ['abc', 'agent', 1, 'ff',
    'nv1:agent:1:ff:b4941d78576aa676ce849e529e276637f6491e9524a13d49648a8699f8fa2ba1'],
];

source('U9/U16 隧道认证加固——适配卡 B（鸿蒙 relay 鉴权新形态），nv1 口径对拍 protocol.signTunnelToken');

for (const v of VECTORS) {
  const secret = v[0];
  const tokenType = v[1];
  const stamp = v[2];
  const nonce = v[3];
  const expected = v[4];
  eqStr(`nv1 对拍 ${secret}/${tokenType}`,
    buildNv1Envelope(secret, tokenType, stamp, nonce, nodeHmacSha256Hex), expected);
  eqStr(`待签消息 ${secret}/${tokenType}`,
    tunnelTokenMessage(tokenType, stamp, nonce), expected.split(':').slice(0, 4).join(':'));
}

// 裸密钥签 agent 型：与 node:crypto 独立实现互证（service 向量换型后签名必须重算）
const agentFromService = signAgentTunnelToken('a-different-secret', 1763784000, '0123456789abcdef', nodeHmacSha256Hex);
const agentExpected = 'nv1:agent:1763784000:0123456789abcdef:' +
  createHmac('sha256', 'a-different-secret').update('nv1:agent:1763784000:0123456789abcdef').digest('hex');
eqStr('裸密钥签 agent 型 a-different-secret（node:crypto 互证）', agentFromService, agentExpected);

// 信封形状判定（对齐 protocol.parseTunnelToken）
check('信封：标准 agent 形态判真',
  isTunnelTokenEnvelope('nv1:agent:1763784000:0123456789abcdef:20f3d128f1fccc7b3c159072a5126e59c68bc547368d8dceeaa21b4a07cbf3bf'));
check('信封：service 型判真', isTunnelTokenEnvelope('nv1:service:1:ff:ab'));
check('信封：user 型判真', isTunnelTokenEnvelope('nv1:user:1:ff:ab'));
check('信封：裸密钥判假', !isTunnelTokenEnvelope('enrollment-token-for-live-s2'));
check('信封：段数不对判假', !isTunnelTokenEnvelope('nv1:agent:1:ff'));
check('信封：未知型判假', !isTunnelTokenEnvelope('nv1:admin:1:ff:ab'));
check('信封：非数字戳判假', !isTunnelTokenEnvelope('nv1:agent:x1:ff:ab'));
check('信封：空 nonce 判假', !isTunnelTokenEnvelope('nv1:agent:1::ab'));
check('信封：空串判假', !isTunnelTokenEnvelope(''));
eqStr('声明型读取：agent', tunnelTokenClaimType('nv1:agent:1:ff:ab'), 'agent');
eqStr('声明型读取：裸密钥回空', tunnelTokenClaimType('raw-secret'), '');

// auth 首帧构造（U9.1：连接建立后第一条消息）
const frame = buildTunnelAuthFrame('nv1:agent:1:ff:ab', 'agent');
eqStr('auth 帧 type', frame.type, 'auth');
eqStr('auth 帧 token', frame.token, 'nv1:agent:1:ff:ab');
eqStr('auth 帧 tokenType', frame.tokenType, 'agent');

// 端侧决策：裸密钥 → 本地签 nv1:agent（正解，凭据不进帧）
const resolved = resolveTunnelAuthFrame('my-raw-secret', 1763784000, '0123456789abcdef', nodeHmacSha256Hex);
eqStr('决策：裸密钥签出信封', resolved.token,
  'nv1:agent:1763784000:0123456789abcdef:' +
  createHmac('sha256', 'my-raw-secret').update('nv1:agent:1763784000:0123456789abcdef').digest('hex'));
eqStr('决策：裸密钥声明 agent 型', resolved.tokenType, 'agent');

// 端侧决策：已是信封 → 原样用，tokenType 取信封签名内的型（声明型必须与签名型一致）
const envelope = 'nv1:service:1763784000:0123456789abcdef:c4d75b92d1ac43d2bc38c683c12a20dcc6a5e2d05af0923fa629a6c57de56263';
const passthrough = resolveTunnelAuthFrame(envelope, 999, 'ffff', nodeHmacSha256Hex);
eqStr('决策：信封原样透传', passthrough.token, envelope);
eqStr('决策：信封声明取签名内型', passthrough.tokenType, 'service');
