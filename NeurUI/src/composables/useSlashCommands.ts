import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useSessionOps } from '@/composables/useSessionOps'
import { useSubAgentWindows } from '@/composables/useSubAgentWindows'

/**
 * 斜杠命令面板（QwenPaw slash commands 对齐，2026-09-08 ChatPage 拆分产物）。
 *
 * 输入框以 "/" 开头时弹出本地命令面板，Enter 执行 / Tab 补全 / ↑↓ 导航。
 * 纯前端交互：命令落地为既有函数（新会话/清屏/存档），不发后端。
 * /plan 例外：打开计划模式交互面板（种子经 openPlanPanel 回调上抛页面）。
 *
 * 契约测试：src/pages/__tests__/ChatPage.planCommand.test.ts 锁定
 * 首词前缀过滤与 /plan run 的种子提取语义。
 */

export interface SlashCommand {
  name: string
  descKey: string
  /** rawInput = 清输入框前的完整原文（带参命令 /plan xxx 自取参数） */
  run: (rawInput: string) => void | Promise<void>
}

const slashOpen = ref(false)
const slashIndex = ref(0)
let slashCommands: SlashCommand[] = []

const slashFiltered = computed<SlashCommand[]>(() => {
  const chatStore = useChatStore()
  const { inputText } = storeToRefs(chatStore)
  const q = inputText.value.trim().toLowerCase()
  if (!q.startsWith('/')) return []
  // /plan 等带参命令：首词命中即弹面板（参数部分不算入前缀匹配）
  const firstWord = q.split(/\s+/)[0]
  return slashCommands.filter((c) => c.name.startsWith(firstWord))
})

function onSlashInput(): void {
  slashIndex.value = 0
  slashOpen.value = slashFiltered.value.length > 0
}

function closeSlashPanel(): void {
  slashOpen.value = false
}

async function runSlashCommand(cmd?: SlashCommand): Promise<void> {
  const chatStore = useChatStore()
  const { inputText } = storeToRefs(chatStore)
  const target = cmd ?? slashFiltered.value[slashIndex.value]
  closeSlashPanel()
  if (!target) return
  // /plan 带参命令：先快照原文（含参数）再清输入框，run() 内自取种子
  const rawInput = inputText.value
  chatStore.setInputText('')
  await target.run(rawInput)
}

function onSlashKeydown(e: KeyboardEvent): boolean {
  if (!slashOpen.value) return false
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    slashIndex.value = (slashIndex.value + 1) % slashFiltered.value.length
    return true
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    slashIndex.value = (slashIndex.value - 1 + slashFiltered.value.length) % slashFiltered.value.length
    return true
  }
  if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault()
    void runSlashCommand()
    return true
  }
  if (e.key === 'Escape') {
    e.preventDefault()
    closeSlashPanel()
    return true
  }
  return false
}

/**
 * 组装命令注册表（模块级共享：ChatPage 与 ChatComposerArea 共用同一面板态）。
 * openPlanPanel：/plan 触发时回调（页面持有 planPanelOpen/planRequestSeed）。
 * onCompact：/compact 触发时回调（页面经 sendMessage 原链路发往后端命令分发）。
 */
export function setupSlashCommands(
  openPlanPanel: (seed: string) => void,
  onCompact?: () => void,
): void {
  const { t } = useI18n()
  const chatStore = useChatStore()
  const { createSession, archiveSession } = useSessionOps()
  const { currentSessionId } = storeToRefs(chatStore)
  // 清屏命令清空的是消息视图；子 Agent 浮窗随新会话一并收起
  const { subAgentWindows } = useSubAgentWindows()

  slashCommands = [
    {
      name: '/plan',
      descKey: 'chat.slashPlan',
      run: (rawInput: string) => {
        // /plan 后的剩余文本作为初始需求（可空，面板内可再补）
        const seed = rawInput.replace(/^\/plan\b\s*/i, '').trim()
        openPlanPanel(seed)
      },
    },
    {
      name: '/new',
      descKey: 'chat.slashNew',
      run: () => createSession(),
    },
    {
      name: '/clear',
      descKey: 'chat.slashClear',
      run: () => {
        chatStore.clearMessages()
        subAgentWindows.value = {}
      },
    },
    {
      name: '/archive',
      descKey: 'chat.slashArchive',
      run: async () => {
        if (currentSessionId.value) {
          await archiveSession(currentSessionId.value)
        }
      },
    },
    {
      // /compact 手动压缩上下文（zcode 对齐）：不走前端本地处理，
      // 经 sendMessage 原链路发往后端命令分发（报告为该轮回复）
      name: '/compact',
      descKey: 'chat.slashCompact',
      run: () => {
        if (onCompact) {
          onCompact()
        }
      },
    },
  ]
  void t
}

export function useSlashCommands() {
  return { slashOpen, slashIndex, slashFiltered, onSlashInput, closeSlashPanel, runSlashCommand, onSlashKeydown }
}
