/**
 * PlanPanel — 计划模式交互面板组件测试（ZCode 计划模式对齐）
 *
 * 锁定（全部走真实流程驱动：start → answers → awaiting → decide）：
 * 1. 初始态（无会话）：需求输入预填 + 「开始澄清」可用性随输入变化；
 * 2. startSession：调 startPlanSession 并渲染首轮问题（radio/checkbox 按题型渲染）；
 * 3. submitRound：提交选中答案 + 自由补充 → 新一轮问题替换渲染；空提交禁用；
 * 4. 计划生成：awaiting_approval 态加载 MD 全文渲染为 HTML（前端 MD 预览支持）；
 * 5. 审批：approve → emit approved(execute_prompt)；reject → 终态提示；
 * 6. 错误兜底：审批 5xx 显示错误条不炸组件。
 *
 * 注：a-modal 默认 Teleport 到 body，VTU 看不见 → stub AModal 为透传组件；
 * 其余 antd 组件用真插件。antd 两字中文按钮会插空格（"拒 绝"）→ 匹配前去空白。
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import Antd from 'ant-design-vue'
import PlanPanel from '../chat/PlanPanel.vue'
import type { PlanSession } from '@/api/modules/plans'

vi.mock('@/api/modules/plans', () => ({
  startPlanSession: vi.fn(),
  submitPlanAnswers: vi.fn(),
  decidePlan: vi.fn(),
  readPlanDocument: vi.fn(),
  listPlanDocuments: vi.fn(),
  getPlanSession: vi.fn(),
}))

import {
  startPlanSession,
  submitPlanAnswers,
  decidePlan,
  readPlanDocument,
} from '@/api/modules/plans'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      plan: {
        panelTitle: '计划模式',
        requestPlaceholder: '描述你要完成的目标…',
        introHint: 'AI 会先提出澄清问题…',
        startClarify: '开始澄清需求',
        thinking: '正在思考…',
        roundN: '第 {n} 轮澄清',
        customPlaceholder: '其他（自由填写）…',
        supplementPlaceholder: '继续补充…',
        submitAndContinue: '提交回答',
        supplementMore: '继续补充',
        approveExecute: '批准执行',
        reject: '拒绝',
        defaultTitle: '计划',
        generated: '计划已生成',
        approved: '计划已批准',
        rejected: '已拒绝该计划',
        approvedTitle: '计划已批准',
        approvedDesc: '执行指令已发送到聊天',
        rejectedTitle: '计划已拒绝',
        rejectedDesc: '可关闭面板或重新发起计划',
        startFailed: '发起计划失败',
        submitFailed: '提交失败',
        decideFailed: '审批操作失败',
        previewFailed: '计划预览加载失败',
        statusAsking: '澄清中',
        statusAwaitingApproval: '待审批',
        statusApproved: '已批准',
        statusRejected: '已拒绝',
      },
      common: { cancel: '取消', close: '关闭' },
    },
  },
})

/** a-modal 透传 stub：渲染默认 slot（绕开 Teleport），透传 attrs。 */
const ModalStub = defineComponent({
  name: 'ModalStub',
  inheritAttrs: false,
  setup(_, { slots, attrs }) {
    return () => h('div', { class: 'modal-stub', ...(attrs as Record<string, unknown>) }, slots.default?.())
  },
})

/** antd 两字中文按钮会插空格（"拒 绝"）→ 去空白后匹配。 */
const btnByText = (w: VueWrapper<any>, text: string) =>
  w.findAll('button').find((b) => b.text().replace(/\s+/g, '').includes(text))!

const FIRST_ROUND_QUESTIONS = [
  {
    id: 'q1',
    question: '目标平台是什么？',
    options: [
      { label: 'Web', description: '浏览器端' },
      { label: '桌面', description: 'Electron' },
    ],
    multi: false,
    allow_custom: true,
  },
  {
    id: 'q2',
    question: '要支持哪些端？',
    options: [{ label: '移动端', description: '' }],
    multi: true,
    allow_custom: false,
  },
]

const SESSION_ASKING: PlanSession = {
  session_id: 'plan-1',
  agent_id: 'default',
  request: '重构登录模块',
  status: 'asking',
  rounds: [{ questions: FIRST_ROUND_QUESTIONS, answers: [] }],
  document: null,
  created_at: 1,
  updated_at: 1,
}

const SESSION_AWAITING: PlanSession = {
  ...SESSION_ASKING,
  status: 'awaiting_approval',
  document: {
    name: '20260908-120000-plan.md',
    rel_path: 'docs/plan/20260908-120000-plan.md',
    title: '重构登录模块',
  },
}

const PLAN_MD = '# 计划：重构登录模块\n\n1. 梳理现状'

function resp<T>(data: T) {
  // axios 拦截器已解一层 response.data，组件拿到 {code,message,data} 后
  // 按单层 res.data.xxx 读（2026-09-10 组件解包口径修正的配套 mock 更新）
  return { data } as any
}

function mountPanel(initialRequest = ''): VueWrapper<any> {
  return mount(PlanPanel, {
    props: { open: true, agentId: 'default', initialRequest },
    global: { plugins: [i18n, Antd], stubs: { AModal: ModalStub } },
  })
}

/** 走真实流到 awaiting_approval 态（start → 答首题 → 提交 → 计划生成）。 */
async function mountToAwaiting(): Promise<VueWrapper<any>> {
  vi.mocked(startPlanSession).mockResolvedValue(resp({ session: SESSION_ASKING }))
  vi.mocked(submitPlanAnswers).mockResolvedValue(resp({ session: SESSION_AWAITING }))
  vi.mocked(readPlanDocument).mockResolvedValue(
    resp({ name: '20260908-120000-plan.md', rel_path: 'docs/plan/x.md', content: PLAN_MD })
  )

  const w = mountPanel('重构登录模块')
  await flushPromises()

  await btnByText(w, '开始澄清需求').trigger('click')
  await flushPromises()
  expect(w.text()).toContain('目标平台是什么？')

  await w.find('input[type="radio"]').setValue()
  await btnByText(w, '提交回答').trigger('click')
  await flushPromises()

  expect(w.text()).toContain('梳理现状') // MD 预览渲染成功
  return w
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('PlanPanel — 初始需求态', () => {
  it('无会话时渲染需求输入并预填 initialRequest，「开始澄清」可用', async () => {
    const w = mountPanel('重构登录模块')
    await flushPromises()
    const ta = w.find('textarea')
    expect(ta.exists()).toBe(true)
    expect((ta.element as HTMLTextAreaElement).value).toBe('重构登录模块')
    expect(btnByText(w, '开始澄清需求').attributes('disabled')).toBeUndefined()
  })

  it('startSession 调 startPlanSession 并渲染首轮问题：单选 radio + 多选 checkbox', async () => {
    vi.mocked(startPlanSession).mockResolvedValue(resp({ session: SESSION_ASKING }))
    const w = mountPanel('')
    await flushPromises()

    await w.find('textarea').setValue('重构登录模块')
    await btnByText(w, '开始澄清需求').trigger('click')
    await flushPromises()

    expect(startPlanSession).toHaveBeenCalledWith('default', '重构登录模块')
    expect(w.find('input[type="radio"]').exists()).toBe(true)
    expect(w.find('input[type="checkbox"]').exists()).toBe(true)
  })
})

describe('PlanPanel — 问答推进', () => {
  it('选中答案+自由补充提交 → 新一轮问题替换渲染；空提交禁用', async () => {
    const NEXT_ROUND = {
      done: false,
      questions: [{ id: 'q1', question: '预算？', options: [], multi: false, allow_custom: true }],
    }
    vi.mocked(startPlanSession).mockResolvedValue(resp({ session: SESSION_ASKING }))
    vi.mocked(submitPlanAnswers).mockResolvedValue(
      resp({
        session: {
          ...SESSION_ASKING,
          rounds: [SESSION_ASKING.rounds[0], { questions: NEXT_ROUND.questions, answers: [] }],
        },
      })
    )

    const w = mountPanel('重构登录模块')
    await flushPromises()
    await btnByText(w, '开始澄清需求').trigger('click')
    await flushPromises()

    // 空提交禁用
    const submitBtn = btnByText(w, '提交回答')
    expect(submitBtn.attributes('disabled')).toBeDefined()

    await w.find('input[type="radio"]').setValue()
    await w.find('textarea.nr-plan-supplement').setValue('我还想支持移动端')
    expect(submitBtn.attributes('disabled')).toBeUndefined()
    await submitBtn.trigger('click')
    await flushPromises()

    expect(submitPlanAnswers).toHaveBeenCalledWith(
      'plan-1',
      [expect.objectContaining({ id: 'q1', selected: ['Web'] })],
      '我还想支持移动端'
    )
    expect(w.text()).toContain('预算？')
    expect(w.text()).not.toContain('目标平台是什么？')
  })
})

describe('PlanPanel — 计划预览与审批', () => {
  it('完整流：问答收口 → awaiting 态加载 MD 全文渲染为 HTML', async () => {
    const w = await mountToAwaiting()

    expect(readPlanDocument).toHaveBeenCalledWith('default', '20260908-120000-plan.md')
    expect(w.find('.nr-plan-markdown h1').exists()).toBe(true)
    expect(w.text()).toContain('20260908-120000-plan.md') // 落盘路径展示
  })

  it('approve → emit approved(execute_prompt)', async () => {
    const w = await mountToAwaiting()
    vi.mocked(decidePlan).mockResolvedValue(
      resp({
        session: { ...SESSION_AWAITING, status: 'approved' },
        execute_prompt: '请按照以下计划执行任务。\n\n--- 计划全文开始 ---\n# 计划\n--- 计划全文结束 ---',
      })
    )

    await btnByText(w, '批准执行').trigger('click')
    await flushPromises()

    expect(decidePlan).toHaveBeenCalledWith('plan-1', 'approve')
    expect(w.emitted('approved')).toBeTruthy()
    expect(w.emitted('approved')![0][0]).toContain('计划全文开始')
  })

  it('reject → 终态提示无 approved 事件', async () => {
    const w = await mountToAwaiting()
    vi.mocked(decidePlan).mockResolvedValue(
      resp({ session: { ...SESSION_AWAITING, status: 'rejected' }, execute_prompt: null })
    )

    await btnByText(w, '拒绝').trigger('click')
    await flushPromises()

    expect(decidePlan).toHaveBeenCalledWith('plan-1', 'reject')
    expect(w.emitted('approved')).toBeFalsy()
    expect(w.text().replace(/\s+/g, '')).toContain('计划已拒绝')
  })

  it('审批接口 5xx → 错误条展示不炸组件', async () => {
    const w = await mountToAwaiting()
    vi.mocked(decidePlan).mockRejectedValue({
      response: { data: { message: 'Plan decision failed: boom' } },
    })

    await btnByText(w, '批准执行').trigger('click')
    await flushPromises()

    expect(w.find('.nr-plan-alert').exists()).toBe(true)
    expect(w.text()).toContain('Plan decision failed: boom')
  })
})
