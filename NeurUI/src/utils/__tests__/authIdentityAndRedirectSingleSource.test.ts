/**
 * 身份失败分类与登录位置构造：一份实现，多处消费
 *
 * 收编前实测到的手抄面（同一件事各写一遍）：
 * - `MobilePairingPanel.vue:216`  `if (code === 401 || code === 403) return t('channel.pairingDenied')`
 * - `api/index.ts:160`            `window.location.href = '/login'`（把目的地丢了）
 * - `MemoryPage.vue` 的 catch     通用红 toast + 页面渲染「暂无数据」
 * 三处合起来就是「未登录被说成没数据」。按教义第 6/7 条收成一处分类 + 一处构造，
 * 消费方（记忆页 / 扫码面板 / 拦截器 / 路由守卫 / 登录页）全部改指它。
 *
 * 另钉一条安全边界：深链 `?redirect=` 只认站内路径。登录页今天是
 * `router.push(route.query.redirect)` 直接吃外来字符串——本批让跳转保住目的地，
 * 就同时把「保住的是别站 URL」这条路堵掉。
 */
import { describe, expect, it } from 'vitest'
import pairingSource from '@/components/MobilePairingPanel.vue?raw'
import { identityFailureOf } from '@/utils/authIdentity'
import { loginHref, safeRedirectTarget } from '@/utils/authRedirect'

describe('身份失败分类单源', () => {
  it('401 是「没登录」，403 是「无权」，两态不合并', () => {
    expect(identityFailureOf(401)).toBe('anonymous')
    expect(identityFailureOf(403)).toBe('forbidden')
  })

  it('反向：500/502/无状态码都不算身份失败（不许借道把真故障说成请登录）', () => {
    expect(identityFailureOf(500)).toBeNull()
    expect(identityFailureOf(502)).toBeNull()
    expect(identityFailureOf(404)).toBeNull()
    expect(identityFailureOf(undefined)).toBeNull()
    expect(identityFailureOf('401')).toBeNull()
  })

  it('扫码面板改问单源，不再自己判 401||403', () => {
    expect(pairingSource).toContain('identityFailureOf(')
    expect(pairingSource).not.toMatch(/code\s*===\s*401\s*\|\|\s*code\s*===\s*403/)
    // 文案输出守恒：这一批只收形状，不改那句人话
    expect(pairingSource).toContain("t('channel.pairingDenied')")
  })

  it('全仓成对手抄只剩单源一处（401&&403 同一条件里的那种写法）', () => {
    const sources = import.meta.glob('/src/**/*.{vue,ts}', {
      query: '?raw',
      import: 'default',
      eager: true,
    }) as Record<string, string>
    const compound = [
      /(status|code)\s*===\s*401\s*\|\|\s*(status|code)\s*===\s*403/,
      /(status|code)\s*===\s*403\s*\|\|\s*(status|code)\s*===\s*401/,
    ]
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.endsWith('utils/authIdentity.ts') && !path.includes('__tests__'))
      .filter(([, src]) => compound.some((re) => re.test(src)))
      .map(([path]) => path)

    expect(offenders).toEqual([])
    // 正检：单源那份确实两个码都判（否则「零命中」是大家都没判，而不是收口了）
    const single = Object.entries(sources).find(([path]) => path.endsWith('utils/authIdentity.ts'))
    expect(single?.[1]).toContain('401')
    expect(single?.[1]).toContain('403')
  })
})

describe('登录位置构造单源', () => {
  it('loginHref 把目的地编码进 redirect', () => {
    expect(loginHref('/memory')).toBe('/login?redirect=%2Fmemory')
    const withQuery = loginHref('/memory?tab=stats')
    expect(new URL(withQuery, 'http://x').searchParams.get('redirect')).toBe('/memory?tab=stats')
  })

  it('只认站内路径：协议形、协议相对形、反斜杠花招一律不接', () => {
    expect(safeRedirectTarget('/memory?tab=stats')).toBe('/memory?tab=stats')
    expect(safeRedirectTarget('//evil.com/x')).toBeNull()
    expect(safeRedirectTarget('http://evil.com')).toBeNull()
    expect(safeRedirectTarget('\\evil.com')).toBeNull()
    expect(safeRedirectTarget('javascript:alert(1)')).toBeNull()
    expect(safeRedirectTarget('')).toBeNull()
    expect(safeRedirectTarget(undefined)).toBeNull()
    expect(safeRedirectTarget(42)).toBeNull()
  })

  it('登录页自己不算目的地（跳完就回到原点，等于自循环）', () => {
    expect(safeRedirectTarget('/login')).toBeNull()
    expect(safeRedirectTarget('/login?redirect=%2Fmemory')).toBeNull()
  })
})
