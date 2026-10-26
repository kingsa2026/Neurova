/**
 * 会话存储键只允许一把出处（§6-431 仍开② 的落地，本批复算把命中面读大了）
 *
 * 现算命中面（`grep -rn "auth_token" NeurUI/src`，剔掉伪命中后）：**12 处**，不是 4 处——
 * 4 份 `const TOKEN_KEY = 'auth_token'`（`api/index.ts`／`api/modules/collaboration.ts`／
 * `api/modules/notifications.ts`／`stores/auth.ts`）+ 8 份裸字面量读
 * （`composables/useSessionSync.ts` 1、`pages/ChatPage.vue` 5、`utils/audioUrl.ts` 1、
 * `utils/genFiles.ts` 1）。`refresh_token` 另有 2 份 const，`'user'` 另有
 * `api/index.ts:162` 一处裸 `remove('user')`。
 *
 * 为什么这不是"只是难看"：写侧在 `stores/auth.ts`，读侧散在 8 处。键名一旦在某一份里改了
 * （改名、加前缀、桌面端换 storage），那几处就安静地发出**空头**——而这正是 §6-429 之后
 * 记忆面必 401 的那几条腿。§6-431 上一批刚把登录态收口，留着 12 份键名出处就是留 12 个
 * 分家点。
 *
 * 还抓到一条不在票面上的真断链：`pages/AgentSkillPage.vue:1134` 绕过 `secureStorage` 直摸
 * `localStorage`，且它的第一个兜底读的是 `'auth_user'`——**全仓没有任何地方写过这把键**
 * （`grep -rn auth_user` 在本仓只命中这一行，其余全是 `.venv` 里的第三方包）。
 *
 * 扫描口径两个坑（都在下面反钉住了）：
 * - 伪命中必须剔：`api/modules/tool-layers.ts`／`pages/KnowledgePage.vue`／
 *   `pages/ToolLayerPage.vue` 里的 `auth_token` 是 **MCP 服务器的凭据字段名**，
 *   `modules/collaboration/CanvasStoreDrawer.vue` 的 `key: 'refresh_token'` 是 Amazon
 *   凭据表单项——它们跟"会话存储键"是两回事，一刀切会把判据做成误伤。
 * - 只按字面量计数会漏：正检要求属主那份确实定义了这三把键，否则"零 offender"
 *   可能只是大家都没键了。
 */
import { describe, expect, it } from 'vitest'

const sources = import.meta.glob('/src/**/*.{vue,ts}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const OWNER = '/src/utils/authSession.ts'
const IDENTITY_KEYS = ['auth_token', 'refresh_token', 'user'] as const

/** 「作为存储键出现」的两种形态：存储调用的实参、键常量的定义右侧。 */
function storageKeyForms(key: string): RegExp[] {
  return [
    new RegExp(
      `(?:secureStorage|localStorage|sessionStorage)\\s*\\.\\s*(?:get|set|getObject|setObject|remove|getItem|setItem|removeItem)\\s*\\(\\s*['"]${key}['"]`,
    ),
    new RegExp(`(?:const|let)\\s+[A-Za-z_$][\\w$]*\\s*=\\s*['"]${key}['"]`),
  ]
}

function offenders(key: string): string[] {
  const forms = storageKeyForms(key)
  return Object.entries(sources)
    .filter(([path]) => !path.includes('__tests__'))
    .filter(([path]) => path !== OWNER)
    .filter(([, src]) => forms.some((re) => re.test(src)))
    .map(([path]) => path)
}

describe('会话存储键单源', () => {
  it('三把身份键的「存储键形态」除属主外零命中（12 份手抄收成一处的常驻钉）', () => {
    const found = IDENTITY_KEYS.flatMap(offenders)
    expect(found, `以下文件仍在自己拼会话键:\n${found.join('\n')}`).toEqual([])
  })

  it('正检：属主那份确实定义了这三把键（否则「零命中」是大家都没键，不是收口）', () => {
    const owner = sources[OWNER]
    expect(owner, `属主不存在：${OWNER}`).toBeTruthy()
    for (const key of IDENTITY_KEYS) {
      expect(
        storageKeyForms(key).some((re) => re.test(owner)),
        `属主里没有把 '${key}' 定义成键常量`,
      ).toBe(true)
    }
  })

  it('旁路禁令：任何人都不许绕过 secureStorage 直摸身份键', () => {
    const bypass = Object.entries(sources)
      .filter(([path]) => !path.includes('__tests__'))
      .filter(([path]) => path !== '/src/utils/security.ts')
      .filter(([, src]) =>
        IDENTITY_KEYS.some((key) =>
          new RegExp(`localStorage\\s*\\.\\s*(?:getItem|setItem|removeItem)\\s*\\(\\s*['"]${key}['"]`).test(src),
        ),
      )
      .map(([path]) => path)
    expect(bypass, `绕过 secureStorage 取身份键的落点:\n${bypass.join('\n')}`).toEqual([])
  })

  it('真断链退役：那把没人写过的 auth_user 不再被任何存储调用读', () => {
    // 钉代码形态，不钉词（本仓教训：正则守卫被自己的文档措辞撞红）——
    // 「为什么退役」这段说明留在注释里是正当的，读它的调用没了才算闭。
    const readers = Object.keys(sources)
      .filter((p) => !p.includes('__tests__'))
      .filter((p) =>
        /(?:localStorage|sessionStorage|secureStorage)\s*\.\s*(?:getItem|setItem|removeItem|get|set|remove|getObject|setObject)\s*\(\s*['"]auth_user['"]/
          .test(sources[p]),
      )
    expect(readers).toEqual([])
  })

  it('反向：MCP 凭据字段与 Amazon 凭据表单项不许被判成 offender（口径不误伤伪命中）', () => {
    const pseudoHits = ['/src/api/modules/tool-layers.ts', '/src/pages/KnowledgePage.vue']
    for (const path of pseudoHits) {
      expect(sources[path], `${path} 应当还在（改动面复核）`).toBeTruthy()
      expect(sources[path]).toContain('auth_token')
      expect(offenders('auth_token'), `${path} 的 auth_token 是 payload 字段，不是会话键`).not.toContain(path)
    }
    expect(sources['/src/modules/collaboration/CanvasStoreDrawer.vue']).toContain("'refresh_token'")
    expect(offenders('refresh_token')).not.toContain('/src/modules/collaboration/CanvasStoreDrawer.vue')
  })

  it('消费面确实改接：四份 const 定义处不再自己拼，且取 token 走同一读取口', () => {
    for (const path of [
      '/src/api/index.ts',
      '/src/api/modules/collaboration.ts',
      '/src/api/modules/notifications.ts',
      '/src/stores/auth.ts',
      '/src/pages/ChatPage.vue',
      '/src/composables/useSessionSync.ts',
      '/src/utils/audioUrl.ts',
      '/src/utils/genFiles.ts',
    ]) {
      expect(sources[path], `${path} 应当还在`).toBeTruthy()
      expect(sources[path], `${path} 未引会话键单源`).toContain('@/utils/authSession')
    }
  })
})
