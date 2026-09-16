/**
 * 跳至最新悬浮钮契约测试（2026-09-16 需求防回归）。
 *
 * ChatPage 体量太大不便整体挂载（同 ChatPage.streamLifecycle.test.ts 的
 * 取舍：useAgentPage 依赖 vue-router route.params，mock 链脆弱），这里以
 * 源码契约锁定行为形态：
 * 1. onMessagesScroll 内计算距底距离（scrollHeight - scrollTop - clientHeight）
 *    超阈值 → isAwayFromBottom 置真（上翻远离底部显示悬浮钮）
 * 2. 阈值常量存在（防魔法数回退 + 抖动容差语义）
 * 3. jumpToLatest 走 scrollToBottomForHistory（窗口化渲染归位 + ResizeObserver
 *    兜底通道，而非裸 scrollToBottom）并清显隐态
 * 4. 模板结构：transition 包裹 + 纯 CSS 液态玻璃圆钮 + chevronsDown 图标
 *    （不用 GlassSurface：其 SVG 位移滤镜按容器尺寸生成折射区，小圆整体落入
 *    圆角扭曲带、背景被搅成糊斑——2026-09-16 实机预览确认的视觉缺陷）
 * 5. 定位在输入区上方（bottom 依赖 --nr-composer-h）
 * 6. i18n：tooltip/aria 走 chat.jumpToLatest（11 语言包齐备）
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/pages/ChatPage.vue'), 'utf-8')
const guardSource = readFileSync(
  resolve(process.cwd(), 'src/tests/i18n-hardcoded-copy.guard.test.ts'),
  'utf-8',
)

function blockAfter(anchor: string): string {
  const idx = source.indexOf(anchor)
  if (idx === -1) return ''
  const braceStart = source.indexOf('{', idx)
  if (braceStart === -1) return ''
  let depth = 0
  for (let i = braceStart; i < source.length; i++) {
    if (source[i] === '{') depth++
    else if (source[i] === '}') {
      depth--
      if (depth === 0) return source.slice(braceStart + 1, i)
    }
  }
  return ''
}

describe('跳至最新悬浮钮 — 滚动显隐逻辑', () => {
  it('onMessagesScroll 计算距底距离并驱动 isAwayFromBottom', () => {
    const fn = blockAfter('function onMessagesScroll(): void')
    expect(fn).not.toBe('')
    // 距底公式（三量齐备，缺一回退误差不可接受）
    expect(fn).toContain('el.scrollHeight - el.scrollTop - el.clientHeight')
    expect(fn).toContain('isAwayFromBottom.value = distToBottom > JUMP_LATEST_THRESHOLD')
  })

  it('阈值常量 160 存在（贴底抖动容差）', () => {
    expect(source).toMatch(/const JUMP_LATEST_THRESHOLD = 160/)
  })
})

describe('跳至最新悬浮钮 — 点击跳底通道', () => {
  it('jumpToLatest 复用 scrollToBottomForHistory（窗口化渲染归位 + RO 兜底）并清显隐态', () => {
    const fn = blockAfter('function jumpToLatest(): void')
    expect(fn).not.toBe('')
    expect(fn).toContain('scrollToBottomForHistory()')
    expect(fn).toContain('isAwayFromBottom.value = false')
    // 不得退化为裸 scrollToBottom（无渲染膨胀兜底，打开历史会话会停在旧位置）
    expect(fn).not.toContain('scrollToBottom()')
  })

  it('scrollToBottomForHistory 通道本身具备窗口归位与 ResizeObserver 兜底', () => {
    const fn = blockAfter('function scrollToBottomForHistory(): void')
    expect(fn).toContain('renderStart.value = Math.max(0, messages.value.length - RENDER_WINDOW)')
    expect(fn).toContain('new ResizeObserver(')
  })
})

describe('跳至最新悬浮钮 — 模板与样式结构', () => {
  it('transition 包裹 + v-if 显隐 + chevronsDown 图标，且不套 GlassSurface（小圆位移滤镜糊斑缺陷防回归）', () => {
    const tpl = source.slice(0, source.indexOf('<script'))
    expect(tpl).toMatch(/<transition name="jump-latest">[\s\S]*?v-if="isAwayFromBottom"[\s\S]*?class="nr-jump-latest-btn"/)
    expect(tpl).toContain('<UiIcon name="chevronsDown"')
    // 反向断言：按钮内部不得再引 GlassSurface / 遗留双圈结构（外泡+内环）
    const btnBlock = tpl.slice(tpl.indexOf('nr-jump-latest-btn'), tpl.indexOf('<!-- 输入区'))
    expect(btnBlock).not.toContain('GlassSurface')
    expect(btnBlock).not.toContain('nr-jump-latest-ico')
  })

  it('玻璃质感由纯 CSS 承担：blur+saturate 折射 + 顶部高光 + 浮投影（四皮肤 token 齐备）', () => {
    const css = blockAfter('.nr-jump-latest-btn {')
    expect(css).toContain('backdrop-filter: blur(var(--nr-glass-blur)) saturate(180%)')
    expect(css).toContain('inset 0 1px 0 var(--nr-glass-specular-top)')
    expect(css).toContain('rgba(var(--nr-glass-rgb)')
    expect(source).toMatch(/\.nr-jump-latest-btn\s*\{[^}]*border-radius:\s*50%/)
  })

  it('定位在输入区上方（bottom 依赖 --nr-composer-h）且紧邻居中', () => {
    expect(source).toMatch(/\.nr-jump-latest-btn\s*\{[^}]*position:\s*absolute/)
    expect(source).toMatch(/\.nr-jump-latest-btn\s*\{[^}]*bottom:\s*calc\(var\(--nr-composer-h, 0px\)/)
    // 直径 26px + 紧邻输入框（6px 间隙）+ 水平居中（left 半宽偏移，
    // 不用 transform 居中——transform 已被 hover/进出场过渡占用）
    expect(source).toMatch(/\.nr-jump-latest-btn\s*\{[^}]*width:\s*26px/)
    expect(source).toMatch(/\.nr-jump-latest-btn\s*\{[^}]*left:\s*calc\(50% - 13px\)/)
    expect(source).not.toMatch(/\.nr-jump-latest-btn\s*\{[^}]*right:\s*\d+px/)
  })

  it('进出场过渡类定义存在（浮现/沉没动画）', () => {
    expect(source).toContain('.jump-latest-enter-from')
    expect(source).toContain('.jump-latest-leave-to')
  })

  it('26px 视觉钮配 44px 级透明命中区（::after 外扩，触达性不低于 HIG 最小标准）', () => {
    // 视觉 26px 仍低于 44px 可点击最小标准，命中区必须由 ::after 外扩补齐
    const hit = blockAfter('.nr-jump-latest-btn::after {')
    expect(hit).not.toBe('')
    expect(hit).toContain("content: ''")
    expect(hit).toContain('position: absolute')
    // 外扩量：侧/上 9px（26+9×2=44），下 6px（不过度侵占 composer）
    expect(hit).toMatch(/inset:\s*-9px\s+-9px\s+-6px/)
    expect(hit).toContain('border-radius: 50%')
  })
})

describe('跳至最新悬浮钮 — i18n', () => {
  it('tooltip/aria 绑定 chat.jumpToLatest', () => {
    const tpl = source.slice(0, source.indexOf('<script'))
    expect(tpl).toContain(`:title="t('chat.jumpToLatest')"`)
    expect(tpl).toContain(`:aria-label="t('chat.jumpToLatest')"`)
  })

  it('硬编码文案守卫白名单保持清空（零豁免态未被回填）', () => {
    expect(guardSource).toMatch(/const WHITELIST: Record<string, string\[\]> = \{\}/)
  })
})
