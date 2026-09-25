/**
 * 契约：挂在 MainLayout 路由过渡下的页面组件，模板根必须是「唯一元素节点」。
 *
 * 为什么是硬约束：MainLayout/ChatLayout 用
 *   <transition name="fade-slide" mode="out-in"><component :is="Component" :key="route.path"/></transition>
 * 包裹 router-view。若页面模板根位置存在静态注释（或 v-if 根 / 多根），
 * 组件的 subTree 便是 Fragment，out-in 的离场永不完成、state.isLeaving 永久挂起，
 * 此后所有路由页只渲染成空注释节点 —— 表现为「内容区空白，刷新才恢复」，且无任何控制台报错。
 *
 * 2026-09-19 实证：CollaborationHubPage.vue 与 CanvasDesignerPage.vue 的根级注释触发，
 * 在真实浏览器中可稳定复现（点协作中心 → 点仪表盘：内容区仅剩注释节点，DashboardPage 未挂载）。
 * jsdom 无真实 CSS 过渡时长，leave 会立即完成，故行为层无法复现 —— 守卫落在源码结构层。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { parse, compileTemplate } from '@vue/compiler-sfc'

const SRC = join(__dirname, '..', '..')

/** 从路由表提取全部懒加载页面组件（覆盖 MainLayout 下所有子路由 + 嵌套布局）。 */
function routedPageComponents(): string[] {
  const routerSrc = readFileSync(join(SRC, 'router', 'index.ts'), 'utf8')
  const found = [...routerSrc.matchAll(/import\(['"]@\/([^'"]+\.vue)['"]\)/g)].map((m) => m[1])
  return [...new Set(found)]
}

/** 模板根节点（剔除纯空白文本），用于判定组件根是否为唯一元素。 */
function templateRoots(rel: string) {
  const file = join(SRC, rel)
  const { descriptor } = parse(readFileSync(file, 'utf8'), { filename: file })
  if (!descriptor.template) return { file, roots: [] as Array<{ type: number; tag?: string }> }
  // comments: true 对齐开发编译管道（dev 保留根级注释，故注释会参与根节点判定）
  const { ast } = compileTemplate({
    source: descriptor.template.content,
    filename: file,
    id: rel,
    compilerOptions: { comments: true },
  })
  const roots = (ast?.children ?? []).filter(
    (n) => !(n.type === 2 && !n.content.trim()),
  )
  return { file, roots: roots as Array<{ type: number; tag?: string }> }
}

const NODE_KIND: Record<number, string> = {
  1: 'Element',
  2: 'Text',
  3: 'Comment',
  4: 'Expression',
  9: 'IfBranch(v-if)',
  11: 'For(v-for)',
}

describe('路由页面模板根节点契约', () => {
  const pages = routedPageComponents()

  it('路由表解析出页面组件清单', () => {
    // 断言清单非空，防止正则失配导致契约测试静默空转
    expect(pages.length).toBeGreaterThan(50)
  })

  it.each(pages)('%s 的模板根为唯一元素节点（可安全包裹 out-in 过渡）', (rel) => {
    const { roots } = templateRoots(rel)
    const shape = roots.map((n) => (n.type === 1 ? `Element<${n.tag}>` : NODE_KIND[n.type] ?? `type${n.type}`))
    expect(
      roots.length === 1 && roots[0].type === 1,
      `${rel} 模板根为 ${roots.length} 个节点 [${shape.join(', ')}]；` +
        '根级注释/多根/v-if 根会使 MainLayout 的 out-in 路由过渡永久挂起（切页后内容区空白）',
    ).toBe(true)
  })
})
