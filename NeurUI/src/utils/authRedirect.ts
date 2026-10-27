/**
 * 「未登录该去哪儿、回来后去哪」——全仓唯一一处构造与校验。
 *
 * 此前路由守卫用 `{ name: 'Login', query: { redirect } }`，401 拦截器另拼一份裸
 * `window.location.href = '/login'`，登录页再直接 `router.push(route.query.redirect)`
 * ——同一件事三份写法，后果是拦截器那一枪把守卫已经生成的深链整个覆盖掉：未登录打开
 * 记忆页，登完回来落在总览，而不是记忆页。
 *
 * 目的地既然要留住，就得同时把它验住：`?redirect=` 直接喂给 `router.push` 时，
 * `//evil.com`、`/\evil.com`、`http://evil.com` 都会被浏览器当外站，所以只有站内路径
 * 才算目的地；登录页自己也不算（跳完回原点，等于自循环）。
 */

export const REDIRECT_QUERY_KEY = 'redirect'
export const LOGIN_PATH = '/login'

/** 登录位置带目的地。三处消费者：路由守卫、401 拦截器、页面里的「登录」入口。 */
export function loginHref(destination: string): string {
  return `${LOGIN_PATH}?${REDIRECT_QUERY_KEY}=${encodeURIComponent(destination)}`
}

/** 只认站内路径；外站形、协议形、登录页自身一律回 null（调用方按「没有目的地」处置）。 */
export function safeRedirectTarget(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const target = raw.trim()
  if (!target.startsWith('/')) return null
  if (target.startsWith('//') || target.startsWith('/\\')) return null
  if (target === LOGIN_PATH || target.startsWith(`${LOGIN_PATH}?`) || target.startsWith(`${LOGIN_PATH}/`)) {
    return null
  }
  return target
}
