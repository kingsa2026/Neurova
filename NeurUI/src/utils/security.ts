/**
 * Security utilities for input validation and sanitization.
 */

import DOMPurify from 'dompurify'

const USERNAME_REGEX = /^[a-zA-Z0-9_]{3,20}$/
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/

/**
 * Validate a username: 3-20 characters, letters, numbers, and underscores only.
 */
export function validateUsername(username: string): boolean {
  if (!username || typeof username !== 'string') return false
  return USERNAME_REGEX.test(username)
}

/**
 * Validate an email address format.
 */
export function validateEmail(email: string): boolean {
  if (!email || typeof email !== 'string') return false
  if (email.length > 254) return false
  return EMAIL_REGEX.test(email)
}

/**
 * Evaluate password strength.
 * Returns a score (0-4) and human-readable feedback.
 */
export function validatePasswordStrength(password: string): {
  valid: boolean
  score: number
  feedback: string
} {
  if (!password || typeof password !== 'string') {
    return { valid: false, score: 0, feedback: 'Password is required.' }
  }

  let score = 0
  const feedbackParts: string[] = []

  // Length checks
  if (password.length >= 8) {
    score += 1
  } else {
    feedbackParts.push('At least 8 characters required')
  }

  if (password.length >= 12) {
    score += 1
  }

  // Character variety checks
  if (/[a-z]/.test(password)) {
    score += 0.5
  } else {
    feedbackParts.push('Add lowercase letters')
  }

  if (/[A-Z]/.test(password)) {
    score += 0.5
  } else {
    feedbackParts.push('Add uppercase letters')
  }

  if (/[0-9]/.test(password)) {
    score += 0.5
  } else {
    feedbackParts.push('Add numbers')
  }

  if (/[^a-zA-Z0-9]/.test(password)) {
    score += 0.5
  } else {
    feedbackParts.push('Add special characters')
  }

  // Penalize common patterns
  if (/(.)\1{2,}/.test(password)) {
    score -= 0.5
    feedbackParts.push('Avoid repeated characters')
  }

  if (/^(123|abc|qwerty|password|admin)/i.test(password)) {
    score -= 1
    feedbackParts.push('Avoid common patterns')
  }

  // Clamp score to 0-4
  const finalScore = Math.max(0, Math.min(4, Math.round(score)))
  const valid = finalScore >= 2 && password.length >= 8

  const feedback =
    feedbackParts.length > 0 ? feedbackParts.join('. ') + '.' : valid ? 'Password is strong.' : 'Password is too weak.'

  return { valid, score: finalScore, feedback }
}

/**
 * Safely parse a JSON string, returning a fallback value on failure.
 */
export function safeJsonParse<T>(str: string, fallback: T): T {
  if (!str || typeof str !== 'string') return fallback
  try {
    return JSON.parse(str) as T
  } catch {
    return fallback
  }
}

/**
 * Limit a string to a maximum number of characters.
 */
export function limitInputLength(str: string, max: number): string {
  if (!str || typeof str !== 'string') return ''
  if (max < 0) return ''
  return str.length > max ? str.slice(0, max) : str
}

/**
 * Basic HTML sanitization for XSS prevention.
 * Strips script tags, event handlers, and dangerous attributes.
 * For full sanitization, use DOMPurify in the consuming code.
 */
export function sanitizeHtml(html: string): string {
  if (!html || typeof html !== 'string') return ''

  return (
    html
      // Remove script tags and their content
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
      // Remove on* event handlers
      .replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi, '')
      // Remove javascript: protocol in attributes
      .replace(/(?:href|src|action)\s*=\s*(?:"javascript:[^"]*"|'javascript:[^']*')/gi, '')
      // Remove iframe, object, embed, form tags
      .replace(/<\/?(?:iframe|object|embed|form|base|link|meta)\b[^>]*>/gi, '')
      // Remove data: URIs in src/href (potential XSS vector)
      .replace(/(?:href|src)\s*=\s*(?:"data:[^"]*"|'data:[^']*')/gi, '')
  )
}

// ============================================================================
// P0-7 (C7): XSS 三层防御
// ============================================================================

/**
 * 转义 HTML 特殊字符（层 1：引号转义）
 *
 * 修复 P0-7：原 ChatPage.vue 的 escapeHtml 只转义 & < >，
 * 未转义 " ' → 注入 onclick="evil()" 或 onclick='evil()' 可绕过。
 *
 * 转义 5 个字符：& < > " '
 * - & → &amp; (必须最先)
 * - < → &lt;
 * - > → &gt;
 * - " → &quot;
 * - ' → &#x27;
 */
export function escapeHtml(text: string): string {
  if (!text || typeof text !== 'string') return ''
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;')
}

/**
 * 允许的 URL 协议白名单（层 2：URL 协议校验）
 */
const SAFE_URL_PROTOCOLS = ['http:', 'https:', 'mailto:', 'tel:']

/**
 * 校验 URL 协议安全性（层 2：URL 协议白名单）
 *
 * 修复 P0-7：原 ChatPage.vue markdown 链接替换直接插入 URL，
 * 无协议校验 → [x](javascript:alert(1)) 可执行。
 *
 * 允许：http, https, mailto, tel, data:image/*（图片内联）
 * 拒绝：javascript:, data:text/html, data:application/, 协议相对 URL 等
 *
 * 返回空字符串表示 URL 不安全（调用方应原样转义显示而非插入 href）。
 */
export function sanitizeUrl(url: string): string {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (!trimmed) return ''

  // 拒绝协议相对 URL（//evil.com）— 已知反模式，可能被用于绕过协议校验
  if (trimmed.startsWith('//')) return ''

  // data:image/ 协议允许（图片内联场景）
  if (/^data:image\//i.test(trimmed)) {
    return trimmed
  }

  try {
    // 用 URL 构造函数解析协议；第二个参数 base 兜底无 window 场景
    const parsed = new URL(trimmed, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
    if (SAFE_URL_PROTOCOLS.includes(parsed.protocol.toLowerCase())) {
      return trimmed
    }
    return ''
  } catch {
    // URL 解析失败，不安全
    return ''
  }
}

/**
 * DOMPurify 严格 HTML 清洗（层 3：DOMPurify 兜底）
 *
 * 修复 P0-7：即使 escapeHtml 和 sanitizeUrl 有遗漏，DOMPurify 作为最终兜底
 * 剥离所有危险标签和属性（script, on*, javascript:, iframe 等）。
 *
 * 允许的标签：p, br, strong, em, a, code, pre, div, span, img, ul, ol, li 等
 * 允许的属性：href (仅安全协议), src (仅安全协议), alt, title, class, target, rel, loading
 */
export function sanitizeHtmlStrict(html: string): string {
  if (!html || typeof html !== 'string') return ''
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'a', 'code', 'pre', 'div', 'span',
      'img', 'ul', 'ol', 'li', 'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'table', 'thead', 'tbody', 'tr', 'th', 'td', 'button',
    ],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title', 'class', 'target', 'rel', 'loading'],
    ALLOW_DATA_ATTR: false,
  })
}

/**
 * Secure storage wrapper that handles errors gracefully.
 */
export const secureStorage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },

  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      console.warn(`[secureStorage] Failed to set key: ${key}`)
    }
  },

  remove(key: string): void {
    try {
      localStorage.removeItem(key)
    } catch {
      console.warn(`[secureStorage] Failed to remove key: ${key}`)
    }
  },

  getObject<T>(key: string, fallback: T): T {
    const raw = this.get(key)
    if (raw === null) return fallback
    return safeJsonParse<T>(raw, fallback)
  },

  setObject<T>(key: string, value: T): void {
    try {
      this.set(key, JSON.stringify(value))
    } catch {
      console.warn(`[secureStorage] Failed to serialize and set key: ${key}`)
    }
  },
}
