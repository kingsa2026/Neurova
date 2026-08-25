import { describe, it, expect, beforeEach } from 'vitest'
import {
  validateUsername,
  validateEmail,
  validatePasswordStrength,
  safeJsonParse,
  limitInputLength,
  sanitizeHtml,
  secureStorage,
  escapeHtml,
  sanitizeUrl,
  sanitizeHtmlStrict,
} from '@/utils/security'

describe('validateUsername', () => {
  it('accepts valid usernames', () => {
    expect(validateUsername('abc')).toBe(true)
    expect(validateUsername('user_name')).toBe(true)
    expect(validateUsername('User123')).toBe(true)
    expect(validateUsername('a'.repeat(20))).toBe(true)
  })

  it('rejects invalid usernames', () => {
    expect(validateUsername('ab')).toBe(false)
    expect(validateUsername('a'.repeat(21))).toBe(false)
    expect(validateUsername('user-name')).toBe(false)
    expect(validateUsername('user name')).toBe(false)
    expect(validateUsername('')).toBe(false)
    expect(validateUsername(null as any)).toBe(false)
    expect(validateUsername(undefined as any)).toBe(false)
  })
})

describe('validateEmail', () => {
  it('accepts valid emails', () => {
    expect(validateEmail('user@example.com')).toBe(true)
    expect(validateEmail('test.name+tag@domain.co')).toBe(true)
  })

  it('rejects invalid emails', () => {
    expect(validateEmail('')).toBe(false)
    expect(validateEmail('notanemail')).toBe(false)
    expect(validateEmail('@domain.com')).toBe(false)
    expect(validateEmail('user@')).toBe(false)
    expect(validateEmail(null as any)).toBe(false)
    expect(validateEmail('a'.repeat(255))).toBe(false)
  })
})

describe('validatePasswordStrength', () => {
  it('returns score 0 for empty password', () => {
    const result = validatePasswordStrength('')
    expect(result.valid).toBe(false)
    expect(result.score).toBe(0)
  })

  it('returns low score for weak password', () => {
    const result = validatePasswordStrength('abc')
    expect(result.valid).toBe(false)
    expect(result.score).toBeLessThan(2)
  })

  it('returns high score for strong password', () => {
    const result = validatePasswordStrength('MyStr0ng!Pass')
    expect(result.score).toBeGreaterThanOrEqual(3)
  })

  it('penalizes common patterns', () => {
    const weak = validatePasswordStrength('password123')
    const strong = validatePasswordStrength('xK9!mP2@nQ7')
    expect(weak.score).toBeLessThan(strong.score)
  })

  it('penalizes repeated characters', () => {
    const repeated = validatePasswordStrength('aaa111!!!')
    expect(repeated.score).toBeLessThan(4)
    expect(repeated.feedback).toContain('Avoid repeated characters')
  })
})

describe('safeJsonParse', () => {
  it('parses valid JSON', () => {
    expect(safeJsonParse('{"a":1}', {})).toEqual({ a: 1 })
    expect(safeJsonParse('[1,2,3]', [])).toEqual([1, 2, 3])
  })

  it('returns fallback for invalid JSON', () => {
    expect(safeJsonParse('not json', 'default')).toBe('default')
    expect(safeJsonParse('', 'default')).toBe('default')
    expect(safeJsonParse(null as any, 'default')).toBe('default')
  })
})

describe('limitInputLength', () => {
  it('truncates long strings', () => {
    expect(limitInputLength('hello world', 5)).toBe('hello')
  })

  it('returns short strings unchanged', () => {
    expect(limitInputLength('hi', 5)).toBe('hi')
  })

  it('handles edge cases', () => {
    expect(limitInputLength('', 5)).toBe('')
    expect(limitInputLength(null as any, 5)).toBe('')
    expect(limitInputLength('hello', -1)).toBe('')
  })
})

describe('sanitizeHtml', () => {
  it('removes script tags', () => {
    const html = 'Hello<script>alert("xss")</script>World'
    expect(sanitizeHtml(html)).toBe('HelloWorld')
  })

  it('removes on* event handlers', () => {
    const html = '<div onclick="alert(1)">test</div>'
    expect(sanitizeHtml(html)).toBe('<div>test</div>')
  })

  it('removes javascript: protocol', () => {
    const html = '<a href="javascript:alert(1)">link</a>'
    const result = sanitizeHtml(html)
    expect(result).not.toContain('javascript')
    expect(result).toContain('link')
  })

  it('removes iframe tags', () => {
    const html = '<iframe src="evil.com"></iframe>'
    expect(sanitizeHtml(html)).toBe('')
  })

  it('returns empty for invalid input', () => {
    expect(sanitizeHtml('')).toBe('')
    expect(sanitizeHtml(null as any)).toBe('')
  })

  it('preserves safe HTML', () => {
    const html = '<p>Hello <strong>World</strong></p>'
    expect(sanitizeHtml(html)).toBe(html)
  })
})

describe('secureStorage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('stores and retrieves strings', () => {
    secureStorage.set('key', 'value')
    expect(secureStorage.get('key')).toBe('value')
  })

  it('returns null for missing keys', () => {
    expect(secureStorage.get('nonexistent')).toBe(null)
  })

  it('removes keys', () => {
    secureStorage.set('key', 'value')
    secureStorage.remove('key')
    expect(secureStorage.get('key')).toBe(null)
  })

  it('stores and retrieves objects', () => {
    const obj = { name: 'test', count: 42 }
    secureStorage.setObject('obj', obj)
    expect(secureStorage.getObject('obj', {})).toEqual(obj)
  })

  it('returns fallback for missing objects', () => {
    expect(secureStorage.getObject('missing', { default: true })).toEqual({ default: true })
  })
})

// ============================================================================
// P0-7 (C7): XSS 三层防御测试
// ============================================================================

describe('escapeHtml (P0-7: 层 1 — 引号转义)', () => {
  it('转义 & < > 基本字符', () => {
    expect(escapeHtml('a & b < c > d')).toBe('a &amp; b &lt; c &gt; d')
  })

  it('转义双引号（修复 P0-7：原实现遗漏）', () => {
    // 修复前：escapeHtml 只转义 & < >，双引号未转义
    // 攻击向量：注入 onclick="evil()" 可绕过
    expect(escapeHtml('"onmouseover="evil()')).toBe(
      '&quot;onmouseover=&quot;evil()',
    )
  })

  it('转义单引号（修复 P0-7：原实现遗漏）', () => {
    // 攻击向量：注入 onclick='evil()' 可绕过
    expect(escapeHtml("'onmouseover='evil()")).toBe(
      '&#x27;onmouseover=&#x27;evil()',
    )
  })

  it('组合攻击：完整 attribute injection payload', () => {
    const payload = `" onmouseover="alert(1)" title="`
    const result = escapeHtml(payload)
    expect(result).not.toContain('"')
    // 修复后所有双引号都被转义，无法逃逸属性
    expect(result).toBe('&quot; onmouseover=&quot;alert(1)&quot; title=&quot;')
  })

  it('处理空输入和非法输入', () => {
    expect(escapeHtml('')).toBe('')
    expect(escapeHtml(null as any)).toBe('')
    expect(escapeHtml(undefined as any)).toBe('')
  })
})

describe('sanitizeUrl (P0-7: 层 2 — URL 协议白名单)', () => {
  it('允许 http/https 协议', () => {
    expect(sanitizeUrl('http://example.com')).toBe('http://example.com')
    expect(sanitizeUrl('https://example.com/path?q=1')).toBe(
      'https://example.com/path?q=1',
    )
  })

  it('允许 mailto 协议', () => {
    expect(sanitizeUrl('mailto:user@example.com')).toBe(
      'mailto:user@example.com',
    )
  })

  it('允许 tel 协议', () => {
    expect(sanitizeUrl('tel:+8613800138000')).toBe('tel:+8613800138000')
  })

  it('拒绝 javascript: 协议（核心 XSS 向量）', () => {
    // 修复前：markdown 链接 [x](javascript:alert(1)) 直接插入 href，可执行
    expect(sanitizeUrl('javascript:alert(1)')).toBe('')
    expect(sanitizeUrl('JavaScript:alert(1)')).toBe('')
    expect(sanitizeUrl('  javascript:alert(1)  ')).toBe('')
  })

  it('拒绝 data: 协议（非 image 场景）', () => {
    expect(sanitizeUrl('data:text/html,<script>alert(1)</script>')).toBe('')
  })

  it('拒绝相对路径协议注入', () => {
    // 防止 //evil.com 或 /\evil.com 绕过
    expect(sanitizeUrl('//evil.com')).not.toBe('//evil.com')
  })

  it('允许 data:image/ 协议（图片内联）', () => {
    const dataImg = 'data:image/png;base64,iVBORw0KGgo='
    expect(sanitizeUrl(dataImg)).toBe(dataImg)
  })

  it('处理空输入和非法输入', () => {
    expect(sanitizeUrl('')).toBe('')
    expect(sanitizeUrl(null as any)).toBe('')
    expect(sanitizeUrl(undefined as any)).toBe('')
  })
})

describe('sanitizeHtmlStrict (P0-7: 层 3 — DOMPurify 兜底)', () => {
  it('保留安全 HTML（strong/em/a/code 等）', () => {
    const safe = '<p>Hello <strong>World</strong> <em>italic</em></p>'
    const result = sanitizeHtmlStrict(safe)
    expect(result).toContain('<strong>World</strong>')
    expect(result).toContain('<em>italic</em>')
  })

  it('保留带安全 href 的 <a> 标签', () => {
    const safe = '<a href="https://example.com" target="_blank">link</a>'
    const result = sanitizeHtmlStrict(safe)
    expect(result).toContain('href="https://example.com"')
    expect(result).toContain('>link</a>')
  })

  it('剥离 <script> 标签', () => {
    const evil = '<script>alert("xss")</script><p>safe</p>'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('<script')
    expect(result).not.toContain('alert')
    expect(result).toContain('<p>safe</p>')
  })

  it('剥离 on* 事件处理器（核心 XSS 向量）', () => {
    const evil = '<img src="x" onerror="alert(1)">'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('onerror')
    expect(result).not.toContain('alert')
  })

  it('剥离 javascript: 协议的 href', () => {
    const evil = '<a href="javascript:alert(1)">click</a>'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('javascript:')
    expect(result).not.toContain('alert')
  })

  it('剥离 javascript: 协议的 src', () => {
    const evil = '<img src="javascript:alert(1)">'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('javascript:')
  })

  it('剥离 iframe/object/embed 标签', () => {
    const evil = '<iframe src="evil.com"></iframe><object data="evil"></object>'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('<iframe')
    expect(result).not.toContain('<object')
  })

  it('组合攻击：img onerror payload', () => {
    const evil = '<img src=x onerror=alert(1)>'
    const result = sanitizeHtmlStrict(evil)
    expect(result).not.toContain('onerror')
    expect(result).not.toContain('alert')
  })

  it('处理空输入和非法输入', () => {
    expect(sanitizeHtmlStrict('')).toBe('')
    expect(sanitizeHtmlStrict(null as any)).toBe('')
    expect(sanitizeHtmlStrict(undefined as any)).toBe('')
  })
})
