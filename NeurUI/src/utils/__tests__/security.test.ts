import { describe, it, expect } from 'vitest'
import {
  validateUsername,
  validateEmail,
  validatePasswordStrength,
  safeJsonParse,
  limitInputLength,
  sanitizeHtml,
  secureStorage,
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
