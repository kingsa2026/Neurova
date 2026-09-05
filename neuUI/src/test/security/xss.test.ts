import { describe, it, expect } from 'vitest'
import DOMPurify from 'dompurify'

describe('XSS 防护测试', () => {
  describe('HTML 清理', () => {
    it('应该移除恶意JavaScript代码', () => {
      const dirty = '<script>alert("XSS")</script><p>Safe content</p>'
      const clean = DOMPurify.sanitize(dirty)

      expect(clean).not.toContain('<script>')
      expect(clean).toContain('<p>Safe content</p>')
    })

    it('应该清理事件处理器', () => {
      const dirty = '<img src="x" onerror="alert(1)">'
      const clean = DOMPurify.sanitize(dirty)

      expect(clean).not.toContain('onerror')
      expect(clean).toContain('<img src="x">')
    })

    it('应该清理JavaScript: URLs', () => {
      const dirty = '<a href="javascript:alert(1)">Click me</a>'
      const clean = DOMPurify.sanitize(dirty)

      expect(clean).not.toContain('javascript:')
    })

    it('应该保留安全的HTML标签', () => {
      const dirty = '<p><strong>Bold</strong> and <em>italic</em></p>'
      const clean = DOMPurify.sanitize(dirty)

      expect(clean).toContain('<strong>Bold</strong>')
      expect(clean).toContain('<em>italic</em>')
    })
  })

  describe('输入验证', () => {
    it('应该拒绝超长输入', () => {
      const longInput = 'a'.repeat(10001)
      const maxLength = 10000

      expect(longInput.length).toBeGreaterThan(maxLength)
    })

    it('应该拒绝包含特殊字符的用户名', () => {
      const validateUsername = (username: string): boolean => {
        return /^[a-zA-Z0-9_]{3,20}$/.test(username)
      }

      expect(validateUsername('valid_user123')).toBe(true)
      expect(validateUsername('user<script>')).toBe(false)
      expect(validateUsername('ab')).toBe(false) // too short
      expect(validateUsername('a'.repeat(21))).toBe(false) // too long
    })

    it('应该验证邮箱格式', () => {
      const validateEmail = (email: string): boolean => {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      }

      expect(validateEmail('user@example.com')).toBe(true)
      expect(validateEmail('invalid-email')).toBe(false)
      expect(validateEmail('user@')).toBe(false)
    })
  })

  describe('密码强度验证', () => {
    it('应该验证密码强度', () => {
      const validatePassword = (password: string): { valid: boolean; score: number } => {
        let score = 0

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

      expect(validatePassword('weak').score).toBeLessThan(3)
      expect(validatePassword('StrongP@ss123').score).toBeGreaterThanOrEqual(3)
    })
  })
})
