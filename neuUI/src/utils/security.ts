import DOMPurify from 'dompurify'

/**
 * XSS安全工具
 */

/**
 * 安全清理HTML内容
 * @param html 待清理的HTML
 * @returns 清理后的安全HTML
 */
export function sanitizeHtml(html: string): string {
  if (!html || typeof html !== 'string') {
    return ''
  }
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'u', 'b', 'i', 'code', 'pre', 'ul', 'ol', 'li', 'a', 'span'],
    ALLOWED_ATTR: ['href', 'target', 'class'],
  })
}

/**
 * 安全显示文本（防止XSS）
 * @param text 待显示的文本
 * @returns 转义后的安全文本
 */
export function sanitizeText(text: string): string {
  if (!text || typeof text !== 'string') {
    return ''
  }
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

/**
 * 输入验证工具
 */

/**
 * 验证用户名格式
 * @param username 用户名
 * @returns 是否有效
 */
export function validateUsername(username: string): boolean {
  if (!username || typeof username !== 'string') {
    return false
  }
  // 3-20个字符，只允许字母、数字、下划线
  return /^[a-zA-Z0-9_]{3,20}$/.test(username)
}

/**
 * 验证邮箱格式
 * @param email 邮箱地址
 * @returns 是否有效
 */
export function validateEmail(email: string): boolean {
  if (!email || typeof email !== 'string') {
    return false
  }
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}

/**
 * 验证密码强度
 * @param password 密码
 * @returns { valid: boolean; score: number }
 *   score: 0-5, 0=很弱, 5=很强
 */
export function validatePasswordStrength(password: string): { valid: boolean; score: number } {
  let score = 0
  if (!password || typeof password !== 'string') {
    return { valid: false, score: 0 }
  }

  if (password.length >= 8) score++
  if (password.length >= 12) score++
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++
  if (/\d/.test(password)) score++
  if (/[^a-zA-Z0-9]/.test(password)) score++

  return {
    valid: score >= 3,
    score
  }
}

/**
 * 限制输入长度
 * @param text 输入文本
 * @param maxLength 最大长度
 * @returns 裁剪后的文本
 */
export function limitInputLength(text: string, maxLength: number = 10000): string {
  if (!text || typeof text !== 'string') {
    return ''
  }
  return text.slice(0, maxLength)
}

/**
 * 安全的JSON解析
 * @param jsonStr JSON字符串
 * @param fallback 默认值
 * @returns 解析结果或默认值
 */
export function safeJsonParse<T>(jsonStr: string, fallback: T): T {
  try {
    return JSON.parse(jsonStr)
  } catch {
    return fallback
  }
}
