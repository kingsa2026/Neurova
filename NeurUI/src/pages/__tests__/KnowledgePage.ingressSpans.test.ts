/**
 * KnowledgePage — 摄取任务 span 时间线 + stop-parse 接线契约（WeKnora P1#12 前端批）
 *
 * 后端 API（GET /knowledge/ingress-tasks[/{id}]、POST …/{id}/cancel）已就绪，
 * 本测试锁定前端接线的机制断言（SFC 源码契约模式，与 importAcceptFilter 同法）：
 * 1. header 有入口按钮且打开时拉取任务列表；
 * 2. 表格行状态用色码 tag；pending/processing 才出取消按钮（终结态不谎称可取消）；
 * 3. 展开行走 @expand 懒加载 getIngressTask 取 spans（列表接口不带 spans）；
 * 4. span 行渲染 stage/状态/时间/error 四要素；
 * 5. api 模块三个函数路径与后端路由字面一致（防漂移：后端 cancel 路由改动会被抓）。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const sfc = readFileSync(resolve(process.cwd(), 'src/pages/KnowledgePage.vue'), 'utf-8')
const api = readFileSync(resolve(process.cwd(), 'src/api/modules/knowledge.ts'), 'utf-8')

describe('KnowledgePage 摄取任务可视化接线', () => {
  it('header 入口按钮：点击 openIngress()', () => {
    expect(sfc).toMatch(/@click="openIngress\(\)"/)
    expect(sfc).toContain("t('knowledge.ingressBtn')")
  })

  it('任务表：status tag 色码 + 仅 pending/processing 出取消按钮', () => {
    expect(sfc).toMatch(/ingressStatusColor\(record\.status\)/)
    expect(sfc).toMatch(/record\.status === 'pending' \|\| record\.status === 'processing'/)
    expect(sfc).toMatch(/handleCancelIngress\(record\)/)
  })

  it('展开行懒加载 spans：@expand 调 handleIngressExpand（列表接口不带 spans）', () => {
    expect(sfc).toMatch(/@expand="[^"]*handleIngressExpand/)
    expect(sfc).toMatch(/await getIngressTask\(record\.task_id\)/)
  })

  it('span 行渲染 stage/状态/时间/error 四要素', () => {
    expect(sfc).toMatch(/ingressStageLabel\(sp\.stage\)/)
    expect(sfc).toMatch(/ingressStatusLabel\(sp\.status\)/)
    expect(sfc).toMatch(/sp\.updated_at/)
    expect(sfc).toMatch(/v-if="sp\.error"/)
  })

  it('api 模块三函数路径与后端路由一致（cancel 为 POST …/cancel）', () => {
    expect(api).toMatch(/ingress-tasks\`,\s*\{\s*params: \{ limit \}/)
    expect(api).toMatch(/`\$\{BASE\}\/ingress-tasks\/\$\{taskId\}`/)
    expect(api).toMatch(/`\$\{BASE\}\/ingress-tasks\/\$\{taskId\}\/cancel`/)
  })

  it('取消成功后刷新列表并提示（不静默）', () => {
    const block = sfc.match(/async function handleCancelIngress[\s\S]*?\n\s*\}/)
    expect(block?.[0]).toContain('t(\'knowledge.ingressCancelled\')')
    expect(block?.[0]).toContain('await refreshIngress()')
  })
})
