/**
 * StudioShapesSection「SHACL 运行时体检」（U1）交互契约测试。
 *
 * 三态咬合：
 * - 真跑态：conforms 标签＋违规清单（severity/component/message/value）；
 * - 诚实降级态：supported=false（环境缺 pyshacl）→ 显式「依赖未安装」面板，
 *   不当错误吞掉、不渲染空违规表冒充「无违规」；
 * - 失败态：请求失败 → 显式错误行（后端 detail 原话优先）。
 * 调用参数：无主体=全库 dry-run（body 空对象）；填了 subject_key 必须原样带上。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import StudioShapesSection from '../StudioShapesSection.vue'
import { listOntologyShapes, validateShacl } from '@/api/modules/ontology'
import { ontologySection } from '@/i18n/locales/_ontologySection'

vi.mock('@/api/modules/ontology', () => ({
  listOntologyShapes: vi.fn(),
  createOntologyShape: vi.fn(),
  deleteOntologyShape: vi.fn(),
  validateShacl: vi.fn(),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      ontology: ontologySection('zh-CN'),
      common: { confirm: '确认', cancel: '取消', delete: '删除', error: '操作失败', required: '必填' },
    },
  },
})

const shapesMock = listOntologyShapes as unknown as ReturnType<typeof vi.fn>
const shaclMock = validateShacl as unknown as ReturnType<typeof vi.fn>

function mountSection() {
  return mount(StudioShapesSection, {
    props: { isAdmin: false },
    global: {
      plugins: [i18n],
      stubs: {
        'a-input': {
          props: ['value'],
          emits: ['update:value'],
          template: '<input class="stub-input" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
        },
        'a-select': { template: '<div class="stub-select"><slot /></div>' },
        'a-select-option': { template: '<div><slot /></div>' },
        'a-textarea': { template: '<textarea class="stub-textarea" />' },
        'a-checkbox': { template: '<input type="checkbox" />' },
        'a-spin': { template: '<div class="stub-spin"><slot /></div>' },
        'a-pagination': { template: '<div class="stub-pagination" />' },
        'a-empty': { props: ['description'], template: '<div class="stub-empty">{{ description }}</div>' },
        'a-tag': { template: '<span class="stub-tag"><slot /></span>' },
        'a-button': { template: '<button class="stub-btn"><slot /></button>' },
        'a-alert': {
          props: ['message', 'description'],
          template: '<div class="stub-alert">{{ message }}<span class="stub-alert-desc">{{ description }}</span></div>',
        },
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  shapesMock.mockResolvedValue({ data: { items: [], total: 0 } } as never)
  shaclMock.mockReset()
})

describe('StudioShapesSection SHACL 运行时体检', () => {
  it('无主体点击：POST validate/shacl 以空 body 真跑（全库 dry-run），通过态渲染无违规', async () => {
    shaclMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { supported: true, mode: 'enforce', conforms: true, violations: [], text: '' },
    } as never)
    const wrapper = mountSection()
    await flushPromises()

    await wrapper.find('[data-testid="shacl-run"]').trigger('click')
    await flushPromises()

    expect(shaclMock).toHaveBeenCalledTimes(1)
    expect(shaclMock).toHaveBeenCalledWith({})
    const result = wrapper.find('[data-testid="shacl-result"]')
    expect(result.exists()).toBe(true)
    expect(wrapper.find('[data-testid="shacl-conforms"]').text()).toContain('通过')
    expect(wrapper.find('[data-testid="shacl-no-violations"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="shacl-violations"]').exists()).toBe(false)
  })

  it('填了 subject_key：调用参数原样带上主体（主体邻域子图）', async () => {
    shaclMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: { supported: true, mode: 'enforce', conforms: true, violations: [], text: '' },
    } as never)
    const wrapper = mountSection()
    await flushPromises()

    await wrapper.find('input[data-testid="shacl-subject"]').setValue('device0')
    await wrapper.find('[data-testid="shacl-run"]').trigger('click')
    await flushPromises()

    expect(shaclMock).toHaveBeenCalledWith({ subject_key: 'device0' })
  })

  it('违规清单：逐条渲染 severity/component/message/value', async () => {
    shaclMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        supported: true,
        mode: 'enforce',
        conforms: false,
        violations: [
          {
            focusNode: 'kbg:device0',
            path: 'kbg:risk_flag',
            value: 'ultra',
            message: 'Value is not in the allowed set',
            severity: 'Violation',
            component: 'InConstraintComponent',
          },
        ],
        text: 'Constraint Violation...',
      },
    } as never)
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="shacl-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="shacl-conforms"]').text()).toContain('未通过')
    expect(wrapper.find('[data-testid="shacl-violations"]').exists()).toBe(true)
    const row = wrapper.find('[data-testid="shacl-violation-0"]')
    expect(row.exists()).toBe(true)
    expect(row.text()).toContain('Violation')
    expect(row.text()).toContain('InConstraintComponent')
    expect(row.text()).toContain('Value is not in the allowed set')
    expect(row.text()).toContain('ultra')
    expect(wrapper.find('[data-testid="shacl-no-violations"]').exists()).toBe(false)
  })

  it('诚实降级态：supported=false 显式「依赖未安装」＋后端 reason，不渲染通过/违规面', async () => {
    shaclMock.mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        supported: false,
        mode: 'enforce',
        reason: 'pyshacl 未安装：No module named pyshacl（依赖已入 requirements.txt，首启链自动补齐）',
        conforms: true,
        violations: [],
        text: '',
      },
    } as never)
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="shacl-run"]').trigger('click')
    await flushPromises()

    const unsupported = wrapper.find('[data-testid="shacl-unsupported"]')
    expect(unsupported.exists()).toBe(true)
    expect(unsupported.text()).toContain('依赖未安装')
    expect(unsupported.text()).toContain('No module named pyshacl')
    expect(wrapper.find('[data-testid="shacl-conforms"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="shacl-violations"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="shacl-error"]').exists()).toBe(false)
  })

  it('失败态：请求失败显式报错（后端 detail 原话优先），不留旧报告冒充读数', async () => {
    shaclMock.mockRejectedValue({ response: { data: { detail: '形状求值器不可用' } } })
    const wrapper = mountSection()
    await flushPromises()
    await wrapper.find('[data-testid="shacl-run"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="shacl-error"]').text()).toContain('形状求值器不可用')
    expect(wrapper.find('[data-testid="shacl-result"]').exists()).toBe(false)
  })
})
