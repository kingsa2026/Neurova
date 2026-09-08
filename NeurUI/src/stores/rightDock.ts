import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import i18n from '@/i18n'

/**
 * 对话页右侧多标签 dock（浏览器标签页模式，2026-09-08）。
 *
 * 收编四类右侧面板：产物文档预览（md/html/image/text/audio）、
 * 历史会话、存档会话、电脑操作分屏（ComputerUsePanel）。
 * 任一 tab 可随时关闭；全部关闭则 dock 收起；左缘 resizer 可拖拽调宽。
 *
 * id 约定（去重键）：
 * - singleton kind：history / archive / computer 以 kind 为 id；
 * - 文档产物：`doc:{artifactId|pathHash}`；代码块：`code:{hash}`；
 *   图片：`img:{url}`；上传件：`file:{fileId}`（调用方构造，见 utils/artifacts.ts）。
 */

export type DockTabKind =
  | 'markdown'
  | 'html'
  | 'image'
  | 'audio'
  | 'text'
  | 'history'
  | 'archive'
  | 'computer'

export interface DockTabData {
  /** md/html/text 源内容（代码块预览/本地渲染场景） */
  content?: string
  /** 代码块语言（text 面板高亮/预览分派用） */
  language?: string
  /** /v1/artifacts/{id}/content（后端 artifact 注册产物） */
  artifactId?: string
  /** /v1/files/{id}/preview（用户上传件） */
  fileId?: string
  /** 图片直链 / data URL / blob URL */
  url?: string
  /** 源文件路径（标题与展示用） */
  path?: string
}

export interface DockTab {
  id: string
  kind: DockTabKind
  title: string
  icon: string
  data: DockTabData
  openedAt: number
}

export interface OpenTabInput {
  id?: string
  kind: DockTabKind
  title?: string
  icon?: string
  data?: DockTabData
}

/** singleton kind：同 kind 只保留一个 tab */
const SINGLETON_KINDS = new Set<DockTabKind>(['history', 'archive', 'computer'])

const WIDTH_KEY = 'neurova_dock_width'
const DEFAULT_WIDTH = 420
const MIN_WIDTH = 320

function maxDockWidth(): number {
  return Math.round(window.innerWidth * 0.6)
}

function clampWidth(w: number): number {
  const max = maxDockWidth()
  return Math.min(Math.max(Math.round(w), MIN_WIDTH), Math.max(max, MIN_WIDTH))
}

function loadWidth(): number {
  try {
    const raw = localStorage.getItem(WIDTH_KEY)
    if (!raw) return DEFAULT_WIDTH
    return clampWidth(Number(raw))
  } catch {
    return DEFAULT_WIDTH
  }
}

function defaultTitle(kind: DockTabKind): string {
  const key: Record<DockTabKind, string> = {
    markdown: 'dock.kindMarkdown',
    html: 'dock.kindHtml',
    image: 'dock.kindImage',
    audio: 'dock.kindAudio',
    text: 'dock.kindText',
    history: 'chat.history',
    archive: 'chat.archivedSessions',
    computer: 'computerPanel.title',
  }
  try {
    return i18n.global.t(key[kind])
  } catch {
    return kind
  }
}

export const useRightDockStore = defineStore('rightDock', () => {
  const tabs = ref<DockTab[]>([])
  const activeTabId = ref('')
  const width = ref(clampWidth(loadWidth()))

  const isOpen = computed(() => tabs.value.length > 0)
  const activeTab = computed(() => tabs.value.find((t) => t.id === activeTabId.value) ?? null)

  // 宽度持久化（secureStorage 无必要：纯 UI 偏好，非敏感）。
  // flush:'sync' 让 setWidth 同步落盘（jsdom 断言与真实重载一致）
  watch(
    width,
    (w) => {
      try {
        localStorage.setItem(WIDTH_KEY, String(w))
      } catch {
        /* 隐私模式等场景静默 */
      }
    },
    { flush: 'sync' },
  )

  /** 打开 tab（幂等）：已存在同 id → 合并 data 并聚焦；否则追加并激活。返回 id。 */
  function openTab(input: OpenTabInput): string {
    const id = input.id ?? (SINGLETON_KINDS.has(input.kind) ? input.kind : `tab:${Date.now()}`)
    const existing = tabs.value.find((t) => t.id === id)
    if (existing) {
      existing.title = input.title || existing.title
      existing.icon = input.icon || existing.icon
      existing.data = { ...existing.data, ...(input.data ?? {}) }
      activeTabId.value = id
      return id
    }
    tabs.value.push({
      id,
      kind: input.kind,
      title: input.title || defaultTitle(input.kind),
      icon: input.icon || '',
      data: { ...(input.data ?? {}) },
      openedAt: Date.now(),
    })
    activeTabId.value = id
    return id
  }

  function closeTab(id: string): void {
    const idx = tabs.value.findIndex((t) => t.id === id)
    if (idx === -1) return
    const wasActive = activeTabId.value === id
    tabs.value.splice(idx, 1)
    if (wasActive) {
      // 右邻优先，没有则左邻（浏览器行为）
      const next = tabs.value[idx] ?? tabs.value[idx - 1]
      activeTabId.value = next?.id ?? ''
    }
  }

  function activate(id: string): void {
    if (tabs.value.some((t) => t.id === id)) activeTabId.value = id
  }

  function closeAll(): void {
    tabs.value.splice(0)
    activeTabId.value = ''
  }

  function setWidth(w: number): void {
    width.value = clampWidth(w)
  }

  function resetWidth(): void {
    width.value = clampWidth(DEFAULT_WIDTH)
  }

  function openHistory(): void {
    openTab({ kind: 'history' })
  }

  function openArchive(): void {
    openTab({ kind: 'archive' })
  }

  function openComputer(): void {
    openTab({ kind: 'computer' })
  }

  return {
    tabs,
    activeTabId,
    width,
    isOpen,
    activeTab,
    openTab,
    closeTab,
    activate,
    closeAll,
    setWidth,
    resetWidth,
    openHistory,
    openArchive,
    openComputer,
  }
})
