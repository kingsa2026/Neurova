/**
 * PairingPayload - 配对二维码载荷解析**单源**（设计方案 §3.4／§5.6）
 *
 * 二维码文本格式（服务端 neurova/tunnel/protocol.py::pairingQrPayload 为唯一事实源）：
 *   一扫配全：neurova://pair?ref=<22位base62一次性引用>&host=<URL编码的对外地址>
 *     （2026-11-16 用户裁定：扫码即完成终端档案配置与设备配对）
 *   旧：neurova://pair?ref=<22位base62一次性引用>   （只带引用，地址另行录入）
 *   旧：neurova://pair?code=<6位配对码>             （兼容保留；confirm 直连通道）
 *
 * 页面不得各自写正则解析（教义第 6 条：载荷形状不允许第二份定义）。
 */

/** 解析结果：kind=ref 走 resolve→confirm 新流程；kind=code 走旧 confirm 直连；
 *  host=终端对外地址（一扫配全；旧形状为空串，由页面按需建档） */
export interface ParsedPairingPayload {
  kind: string;
  value: string;
  host: string;
}

export class PairingPayload {
  /** 一次性引用长度（服务端 PAIRING_REF_LENGTH=22，base62） */
  static readonly REF_LENGTH: number = 22;
  /** 旧 6 位配对码 */
  static readonly CODE_PATTERN: RegExp = /code=([A-Za-z0-9]{6})/;
  /** 新高熵引用 */
  static readonly REF_PATTERN: RegExp = /ref=([A-Za-z0-9]{22})/;
  /** 终端对外地址（URL 编码） */
  static readonly HOST_PATTERN: RegExp = /host=([^&]+)/;

  /** 解析扫码内容；无法识别返回 null（由页面给出"无效的配对二维码"） */
  static parse(raw: string): ParsedPairingPayload | null {
    if (!raw) {
      return null;
    }
    const hostMatch = raw.match(PairingPayload.HOST_PATTERN);
    const host = hostMatch ? decodeURIComponent(hostMatch[1]) : '';
    const refMatch = raw.match(PairingPayload.REF_PATTERN);
    if (refMatch) {
      return { kind: 'ref', value: refMatch[1], host: host };
    }
    const codeMatch = raw.match(PairingPayload.CODE_PATTERN);
    if (codeMatch) {
      return { kind: 'code', value: codeMatch[1], host: host };
    }
    return null;
  }
}
