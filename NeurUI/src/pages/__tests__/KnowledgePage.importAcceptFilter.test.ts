/**
 * 知识库导入 — 文件选择器必须显示支持的文件类型（bugfix 2026-09-15）
 *
 * 症状：知识库导入点"选择文件"，系统文件对话框里看不到支持的文件类型。
 * 根因：a-upload-dragger 上挂了裸 `directory` 属性（Vue 布尔转换为 true →
 * 渲染 webkitdirectory），Chromium 系浏览器的原生目录选择器会整体忽略
 * `accept` 属性 → 类型过滤器不出现，非支持文件也不置灰。
 * 修法：主拖拽区不再带 directory（恢复 accept 过滤）；"选择整个文件夹"
 * 降级为独立入口（原生目录对话框本就无法按类型过滤，靠入队前扩展名过滤兜底）。
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { UploadDragger, Upload } from 'ant-design-vue'

const sfc = readFileSync(resolve(process.cwd(), 'src/pages/KnowledgePage.vue'), 'utf-8')

/** 提取 <a-upload-dragger ...> 开标签 */
function draggerTag(source: string): string {
  const m = source.match(/<a-upload-dragger[^>]*>/s)
  expect(m, '导入弹窗应有主文件拖拽区').toBeTruthy()
  return m![0]
}

describe('KnowledgePage 导入文件类型过滤', () => {
  it('主拖拽区不得带 directory（否则原生对话框忽略 accept，看不到支持类型）', () => {
    const tag = draggerTag(sfc)
    expect(tag).not.toMatch(/\bdirectory\b/)
  })

  it('主拖拽区必须绑定 accept（accept 列表单源于 KB_IMPORT_EXTS，防漂移）', () => {
    const tag = draggerTag(sfc)
    expect(tag).toMatch(/:accept="kbImportAcceptAttr"/)
    expect(sfc).toMatch(/const kbImportAcceptAttr\s*=\s*computed\(/)
    // 单源：不再手写第二份扩展名字符串
    expect(sfc).not.toMatch(/accept="\.json,/)
  })

  it('整文件夹导入保留为独立入口（不丢功能），且复用同一入队过滤', () => {
    expect(sfc).toMatch(/<a-upload[^>]*\bdirectory\b[^>]*>/)
    const folderBlock = sfc.match(/<a-upload[^>]*\bdirectory\b[^>]*>[\s\S]*?<\/a-upload>/)
    expect(folderBlock?.[0]).toContain('beforeImportUpload')
  })

  it('机制回归：无 directory 的 dragger，input 携带 accept 且无 webkitdirectory', () => {
    const wrapper = mount(UploadDragger, {
      props: { accept: '.json,.pdf', multiple: true },
    })
    const input = wrapper.find('input[type=file]')
    expect(input.exists()).toBe(true)
    expect(input.attributes('accept')).toBe('.json,.pdf')
    expect('webkitdirectory' in input.element.attributes).toBe(false)
    expect(input.element.hasAttribute('webkitdirectory')).toBe(false)
  })

  it('机制回归：directory 模式会挂 webkitdirectory（即原生对话框忽略 accept 的元凶）', () => {
    const wrapper = mount(Upload, {
      props: { accept: '.json,.pdf', directory: true },
    })
    const input = wrapper.find('input[type=file]')
    expect(input.element.hasAttribute('webkitdirectory')).toBe(true)
  })
})
