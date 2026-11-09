/**
 * CategoryManagerModal 知识库分类管理弹窗测试
 *
 * 契约:
 *  1. admin 打开弹窗即拉全量清单（include_inactive，停用分类可见可复用）。
 *  2. 列表按注册表渲染：名称/标识/描述/停用标签；空态 noData。
 *  3. 注册提交调 createKnowledgeCategory（category_id/name/description），
 *     成功后刷新清单并 emit changed。
 *  4. 行内编辑回填表单（id 只读），提交走 updateKnowledgeCategory。
 *  5. 停用/启用切换 is_active；删除经确认后调 deleteKnowledgeCategory。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listKnowledgeCategories = vi.fn()
const createKnowledgeCategory = vi.fn()
const updateKnowledgeCategory = vi.fn()
const deleteKnowledgeCategory = vi.fn()

vi.mock('@/api/modules/knowledge', () => ({
  listKnowledgeCategories: (...a: unknown[]) => listKnowledgeCategories(...a),
  createKnowledgeCategory: (...a: unknown[]) => createKnowledgeCategory(...a),
  updateKnowledgeCategory: (...a: unknown[]) => updateKnowledgeCategory(...a),
  deleteKnowledgeCategory: (...a: unknown[]) => deleteKnowledgeCategory(...a),
}))

vi.mock('ant-design-vue', () => ({
  message: { success: vi.fn(), error: vi.fn() },
}))

import CategoryManagerModal from '../CategoryManagerModal.vue'

const messages = {
  common: {
    noData: '暂无数据', create: '创建', edit: '编辑', delete: '删除', cancel: '取消',
    save: '保存', name: '名称', description: '描述', confirm: '确认', success: '成功', error: '失败',
  },
  knowledge: {
    catMgmtTitle: '分类管理',
    catMgmtNew: '注册分类',
    catMgmtId: '分类标识',
    catMgmtIdHint: '小写标识，注册后不可修改',
    catMgmtDeleteConfirm: '删除该分类？引用它的分组白名单将如实剔除。',
    catMgmtCreated: '分类已注册',
    catMgmtUpdated: '分类已更新',
    catMgmtDeleted: '分类已删除',
    catMgmtEnable: '启用',
    catMgmtDisable: '停用',
    catMgmtInactiveTag: '已停用',
  },
}

const globalStubs = {
  GlassButton: { props: ['variant', 'size'], emits: ['click'], template: '<button class="glass-btn" :data-variant="variant" @click="$emit(\'click\')"><slot/></button>' },
  'a-modal': { props: ['open'], template: '<div class="ant-modal" v-if="open"><slot/></div>' },
  'a-input': { props: ['value', 'disabled'], emits: ['update:value'], template: '<input class="ant-input" :data-disabled="disabled ? \'1\' : \'0\'" :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
  'a-tag': { props: ['color'], template: '<span class="ant-tag" :data-color="color"><slot/></span>' },
  'a-spin': { props: ['spinning'], template: '<div><slot/></div>' },
  'a-empty': { template: '<div class="ant-empty" />' },
  'a-popconfirm': { emits: ['confirm'], template: '<span class="ant-popconfirm" @click="$emit(\'confirm\')"><slot /></span>' },
}

function makeI18n() {
  const { createI18n } = require('vue-i18n') as typeof import('vue-i18n')
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': messages } })
}

function mountModal(open = true) {
  return mount(CategoryManagerModal, {
    props: { open, 'onUpdate:open': vi.fn(), onChanged: vi.fn() },
    global: { plugins: [makeI18n()], stubs: globalStubs },
  })
}

const seeded = [
  { category_id: 'product', name: '产品手册', description: '产品文档', is_active: true },
  { category_id: 'legacy', name: '旧规范', description: '', is_active: false },
]

beforeEach(() => {
  vi.clearAllMocks()
  listKnowledgeCategories.mockResolvedValue({ code: 0, data: seeded })
  createKnowledgeCategory.mockResolvedValue({ code: 0, data: {} })
  updateKnowledgeCategory.mockResolvedValue({ code: 0, data: {} })
  deleteKnowledgeCategory.mockResolvedValue({ code: 0, data: {} })
})

describe('CategoryManagerModal 分类管理弹窗', () => {
  it('打开即拉全量清单（include_inactive=true），停用分类带标签渲染', async () => {
    const wrapper = mountModal()
    await flushPromises()
    expect(listKnowledgeCategories).toHaveBeenCalledWith(true)
    const rows = wrapper.findAll('.cat-row')
    expect(rows.length).toBe(2)
    expect(rows[0].text()).toContain('产品手册')
    expect(rows[0].text()).toContain('product')
    const inactiveTag = wrapper.findAll('.ant-tag').find(t => t.text() === '已停用')
    expect(inactiveTag).toBeDefined()
  })

  it('空清单渲染空态', async () => {
    listKnowledgeCategories.mockResolvedValue({ code: 0, data: [] })
    const wrapper = mountModal()
    await flushPromises()
    expect(wrapper.find('.ant-empty').exists()).toBe(true)
  })

  it('注册提交调 createKnowledgeCategory，成功后刷新并 emit changed', async () => {
    const wrapper = mountModal()
    await flushPromises()
    const inputs = wrapper.findAll('input.ant-input')
    await inputs[0].setValue(' engineering ') // 含空格,提交前应 trim
    await inputs[0].setValue('engineering')
    await inputs[1].setValue('工程规范')
    await inputs[2].setValue('基建文档')
    await wrapper.findAll('.glass-btn').find(b => b.text() === '注册分类')!.trigger('click')
    await flushPromises()
    expect(createKnowledgeCategory).toHaveBeenCalledWith({
      category_id: 'engineering',
      name: '工程规范',
      description: '基建文档',
    })
    expect(listKnowledgeCategories).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('changed')).toBeTruthy()
  })

  it('行内编辑回填表单且 id 只读，提交走 updateKnowledgeCategory', async () => {
    const wrapper = mountModal()
    await flushPromises()
    const rows = wrapper.findAll('.cat-row')
    await rows[0].findAll('.glass-btn').find(b => b.text() === '编辑')!.trigger('click')
    const inputs = wrapper.findAll('input.ant-input')
    expect(inputs[0].attributes('data-disabled')).toBe('1')
    expect((inputs[0].element as HTMLInputElement).value).toBe('product')
    await inputs[1].setValue('产品手册（修订）')
    await wrapper.findAll('.glass-btn').find(b => b.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(updateKnowledgeCategory).toHaveBeenCalledWith('product', { name: '产品手册（修订）', description: '产品文档' })
    expect(createKnowledgeCategory).not.toHaveBeenCalled()
  })

  it('停用切换 is_active=true（复用走 update）', async () => {
    const wrapper = mountModal()
    await flushPromises()
    const rows = wrapper.findAll('.cat-row')
    await rows[1].findAll('.glass-btn').find(b => b.text() === '启用')!.trigger('click')
    await flushPromises()
    expect(updateKnowledgeCategory).toHaveBeenCalledWith('legacy', { is_active: true })
  })

  it('启用切换 is_active=false（停用走 update）', async () => {
    const wrapper = mountModal()
    await flushPromises()
    const rows = wrapper.findAll('.cat-row')
    await rows[0].findAll('.glass-btn').find(b => b.text() === '停用')!.trigger('click')
    await flushPromises()
    expect(updateKnowledgeCategory).toHaveBeenCalledWith('product', { is_active: false })
  })

  it('删除经确认调 deleteKnowledgeCategory', async () => {
    const wrapper = mountModal()
    await flushPromises()
    const rows = wrapper.findAll('.cat-row')
    await rows[0].find('.ant-popconfirm').trigger('click')
    await flushPromises()
    expect(deleteKnowledgeCategory).toHaveBeenCalledWith('product')
  })
})
