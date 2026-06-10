/**
 * Security utilities for input validation and sanitization.
 */

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
