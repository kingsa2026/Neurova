<template>
  <div class="nr-chat-input-area">
    <!-- Attachment previews -->
    <div v-if="pendingFiles.length > 0" class="nr-pending-files">
      <div v-for="(file, i) in pendingFiles" :key="i" class="nr-pending-file">
        <img v-if="file.preview" :src="file.preview" :alt="file.name" />
        <span v-else class="nr-pending-file-icon">{{ getFileIcon(file.type) }}</span>
        <div class="nr-pending-file-info">
          <span class="nr-pending-file-name">{{ file.name }}</span>
          <span class="nr-pending-file-size">{{ formatFileSize(file.file.size) }}</span>
        </div>
        <button class="nr-pending-file-remove" @click="removePendingFile(i)">×</button>
      </div>
    </div>

    <!-- ASR Recording Indicator -->
    <transition name="fade-slide">
      <div v-if="isRecording" class="nr-recording-bar">
        <div class="nr-recording-dot" />
        <span class="nr-recording-label">{{ t('chat.recording') }}</span>
        <div class="nr-recording-wave">
          <span v-for="n in 12" :key="n" class="nr-wave-bar" :style="{ animationDelay: `${n * 0.08}s` }" />
        </div>
        <span class="nr-recording-time">{{ recordingTimeStr }}</span>
        <button class="nr-recording-cancel" @click="cancelRecording">{{ t('common.cancel') }}</button>
      </div>
    </transition>

    <!-- 实时记忆检索进度（临时态：回复开始即消失，不落消息历史） -->
    <div v-if="retrievalStatus" class="nr-retrieval-status">
      <span class="nr-retrieval-spinner"><UiIcon name="radar" :size="13" /></span>
      <span>{{ retrievalStatus }}</span>
    </div>
    <!-- Composer 一体化外壳（参考图：textarea + 工具条同框，玻璃容器承载边框） -->
    <div class="nr-composer-shell" :class="{ 'is-focus': composerFocused, 'has-queue-cards': currentSessionQueued.length > 0, 'is-editing-queued': !!editingQueuedId }">
      <!-- 顶入卡片（DeepSeek 截图对齐）：composer 内嵌消息队列。
           审计③：只展示当前会话的排队项（全局 store 按会话过滤） -->
      <QueuedMessageCards
        :editing-queued-id="editingQueuedId"
        :items="currentSessionQueued"
        @send-now="sendQueuedNow"
        @edit="startQueuedEdit"
      />
      <div class="nr-input-row">
        <textarea
          ref="textareaRef"
          v-model="inputText"
          class="nr-chat-textarea"
          :placeholder="queuedPlaceholder"
          rows="1"
          @compositionstart="onCompositionStart"
          @compositionend="onCompositionEnd"
          @keydown="handleKeydown"
          @input="onComposerInput"
          @paste="onPaste"
          @focus="composerFocused = true"
          @blur="composerFocused = false"
        />
        <!-- 斜杠命令面板（QwenPaw slash commands 对齐）：输入 / 开头时弹出 -->
        <div v-if="slashOpen" class="nr-slash-panel">
          <div
            v-for="(cmd, i) in slashFiltered"
            :key="cmd.name"
            class="nr-slash-item"
            :class="{ 'is-active': i === slashIndex }"
            @mousedown.prevent="runSlashCommand(cmd)"
            @mousemove="slashIndex = i"
          >
            <span class="nr-slash-name">{{ cmd.name }}</span>
            <span class="nr-slash-desc">{{ t(cmd.descKey) }}</span>
          </div>
        </div>
      </div>

      <!-- Composer 工具条（QwenPaw/ZCode composer 对齐）：
           左 = +附件 / 电脑操作(图标) / 语音输入；右 = 用量环 + 思考程度 + 语音开关 + 模型 + 发送 -->
      <div class="nr-composer-toolbar">
        <div class="nr-composer-left">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.txt,.csv,.json,.py,.js,.ts,.vue,.html,.css,.md"
            style="display: none"
            @change="handleFileSelect"
          />
          <button class="nr-composer-pill nr-composer-pill--icon" :title="t('chat.upload')" @click="fileInputRef?.click()"><svg class="nr-ico" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></button>
          <button
            class="nr-composer-pill nr-composer-pill--icon"
            :class="{ 'is-active': isComputerTabActive }"
            :title="t('computerPanel.title')"
            @click="toggleComputerPanel"><svg class="nr-ico" viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg></button>
          <button
            v-if="asrAvailable"
            class="nr-composer-pill nr-composer-pill--icon"
            :class="{ 'is-active': isRecording }"
            :title="t('chat.voice')"
            @click="toggleRecording"><svg v-if="isRecording" class="nr-ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/></svg><svg v-else class="nr-ico" viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3"/></svg></button>
        </div>
        <div class="nr-composer-right">
          <ContextUsageIndicator
            :usage="sessionUsage"
            :context-window="currentModelContextWindow"
            :agent-id="agentId"
            :session-id="currentSessionId"
          />
          <a-dropdown :trigger="['click']" placement="topRight">
            <button class="nr-composer-pill" :title="t('chat.thinkingEffort')">
              <svg class="nr-ico" viewBox="0 0 24 24"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/></svg>
              <span>{{ currentThinkingLabel }}</span>
              <span class="nr-composer-pill-arrow">▾</span>
            </button>
            <template #overlay>
              <div class="nr-glass-dropdown">
                <div
                  v-for="opt in thinkingOptions"
                  :key="opt.value"
                  class="nr-glass-dropdown-item nr-composer-menu-item"
                  :class="{ 'is-active': thinkingEffort === opt.value }"
                  @click="setThinkingEffort(opt.value)"
                >
                  <span>{{ t(opt.label) }}</span>
                  <span v-if="thinkingEffort === opt.value" class="nr-composer-check">✓</span>
                </div>
              </div>
            </template>
          </a-dropdown>
          <button
            class="nr-composer-pill nr-composer-pill--icon"
            :class="{ 'is-active': autoVoice }"
            :title="t('chat.autoVoiceTitle')"
            @click="onToggleAutoVoice">
            <svg v-if="autoVoice" class="nr-ico" viewBox="0 0 24 24"><path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>
            <svg v-else class="nr-ico" viewBox="0 0 24 24"><path d="M11 5L6 9H2v6h4l5 4z"/><path d="M22 9l-6 6M16 9l6 6"/></svg>
          </button>
          <div class="nr-model-menu-wrap">
            <button
              class="nr-composer-pill nr-composer-pill--model"
              :title="t('agent.model')"
              @click="modelMenuOpen = !modelMenuOpen"
            >
              <span class="nr-composer-pill-label">{{ selectedModelLabel }}</span>
              <span class="nr-composer-pill-arrow">▾</span>
            </button>
            <template v-if="modelMenuOpen">
              <div class="nr-model-backdrop" @click="modelMenuOpen = false" />
              <!-- 二级级联：左=服务商（含自动路由），右=该服务商可联通模型，底=管理模型 -->
              <div class="nr-model-cascade">
                <div class="nr-model-cascade-left">
                  <div
                    class="nr-model-provider"
                    :class="{ 'is-active': selectedModel === '' }"
                    @click="pickModel('')"
                  >
                    <span class="nr-model-provider-name">{{ t('ui.autoRoute') }}</span>
                    <span v-if="selectedModel === ''" class="nr-composer-check">✓</span>
                  </div>
                  <div class="nr-model-cascade-divider" />
                  <div
                    v-for="g in chatModelGroups"
                    :key="g.provider_id"
                    class="nr-model-provider"
                    :class="{ 'is-active': activeProviderId === g.provider_id }"
                    @mouseenter="activeProviderId = g.provider_id"
                    @click="activeProviderId = g.provider_id"
                  >
                    <span class="nr-model-provider-name">{{ g.provider_name }}</span>
                    <span class="nr-model-provider-count">{{ g.models.length }}</span>
                    <span class="nr-model-provider-arrow">›</span>
                  </div>
                  <div v-if="chatModelGroups.length === 0" class="nr-model-empty">
                    {{ t('chat.noConnectableModels') }}
                  </div>
                </div>
                <div class="nr-model-cascade-footer" @click="gotoModelsManage">
                  <svg class="nr-ico" viewBox="0 0 24 24"><path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                  <span>{{ t('chat.manageModels') }}</span>
                </div>
                <!-- 独立模型子菜单：固定高度+内部滚动，切换服务商不改变主菜单尺寸 -->
                <div v-if="activeGroupModels.length > 0" class="nr-model-flyout">
                  <div class="nr-model-flyout-title">{{ activeProviderName }}</div>
                  <div class="nr-model-flyout-list">
                    <div
                      v-for="m in activeGroupModels"
                      :key="m.value"
                      class="nr-glass-dropdown-item nr-composer-menu-item"
                      :class="{ 'is-active': selectedModel === m.value, 'is-unconnectable': !m.connectable }"
                      @click="pickModel(m.value, m.provider_id)"
                    >
                      <span class="nr-model-dot" :class="m.connectable ? 'is-ok' : 'is-off'" />
                      <span class="nr-composer-pill-label">{{ m.label }}</span>
                      <span v-if="selectedModel === m.value" class="nr-composer-check">✓</span>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <button
            class="nr-composer-send"
            :class="{ 'is-confirm': !!editingQueuedId }"
            :disabled="(!inputText.trim() && pendingFiles.length === 0 && !isStreaming) || !isSendLockOwner"
            :title="editingQueuedId ? t('common.confirm') : (!isSendLockOwner ? t('chat.anotherTabSending') : (isStreaming ? t('chat.stop') : t('chat.send')))"
            @click="editingQueuedId ? commitQueuedEdit() : (isStreaming ? $emit('stop') : $emit('send'))"
          >
            <svg v-if="isStreaming && !editingQueuedId" class="nr-ico nr-ico--send" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none"/></svg>
            <svg v-else-if="editingQueuedId" class="nr-ico nr-ico--send" viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>
            <svg v-else class="nr-ico nr-ico--send" viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>
          </button>
        </div>
      </div>
    </div>
    <!-- 429 限流横幅（补课 A1）：一键切换备选模型 -->
    <div v-if="rateLimitBanner" class="nr-rate-limit-banner">
      <span class="nr-rate-limit-text">
        ⚠ {{ t('chat.rateLimited', { model: rateLimitBanner.model || t('ui.autoRoute') }) }}
      </span>
      <div class="nr-rate-limit-alts">
        <button
          v-for="alt in rateLimitBanner.alternatives.slice(0, 3)"
          :key="alt.value"
          class="nr-rate-limit-alt"
          @click="switchAfterRateLimit(alt.value)"
        >
          {{ alt.label }}
        </button>
      </div>
      <button class="nr-rate-limit-dismiss" @click="rateLimitBanner = null">✕</button>
    </div>

    <!-- 实时事件丢失提示（seq gap 检测，OpenOcta 启发 P0-1）：仅提示，不可恢复 -->
    <div v-if="eventsLostBanner" class="nr-rate-limit-banner">
      <span class="nr-rate-limit-text">
        ⚠ {{ t('chat.eventsLost', { n: eventsLostBanner }) }}
      </span>
      <button class="nr-rate-limit-dismiss" @click="eventsLostBanner = null">✕</button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 输入区（Composer 一体化外壳 + 工具条 + 429/事件丢失横幅）。
 * 模板原样迁自 ChatPage（2026-09-08 拆分，含并行批次顶入卡片零改动）。
 *
 * 状态来源：inputText/isStreaming（chatStore）、队列（messageQueue store）、
 * 模型切换器/429 横幅（useChatModels 单例）、待传附件（usePendingFiles
 * 单例）、斜杠面板（useSlashCommands 单例）、电脑分屏开关（rightDock）、
 * ASR（useASRRecording 单例）、自动语音（useAutoVoice 单例）。
 * 发送/停止与流式状态机耦合，emit 上抛页面编排。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { storeToRefs } from 'pinia'
import { useChatStore } from '@/stores/chat'
import { useMessageQueueStore } from '@/stores/messageQueue'
import { useRightDockStore } from '@/stores/rightDock'
import { useSessionSendLock } from '@/composables/useSessionSendLock'
import { useChatModels } from '@/composables/useChatModels'
import { usePendingFiles } from '@/composables/usePendingFiles'
import { useASRRecording } from '@/composables/useASRRecording'
import { useAutoVoice } from '@/composables/useAutoVoice'
import { useSlashCommands, setupSlashCommands } from '@/composables/useSlashCommands'
import { useThinkingEffort, type ThinkingEffort } from '@/composables/useThinkingEffort'
import { useInputHistory } from '@/composables/useInputHistory'
import { useIMEComposition } from '@/composables/useIMEComposition'
import ContextUsageIndicator from '@/components/chat/ContextUsageIndicator.vue'
import QueuedMessageCards from '@/components/chat/QueuedMessageCards.vue'
import { useAgentPage } from '@/composables/useAgentPage'
import { useSessionOps } from '@/composables/useSessionOps'
import UiIcon from '@/components/UiIcon.vue'

defineOptions({ name: 'ChatComposerArea' })

const emit = defineEmits<{
  send: []
  stop: []
  /** 「↑ 立即」排队项（页面编排层调 drainMessageQueue force 入口） */
  sendQueuedNow: [id: string]
  /** /plan 斜杠命令（页面持有 planPanelOpen/planRequestSeed） */
  slashPlan: [seed: string]
}>()

/** 附件类型分类（文件图标/附件缩略图着色用），原样迁自 ChatPage */
function getFileCategory(type?: string): string {
  if (!type) return 'unknown'
  if (type.startsWith('image/')) return 'image'
  if (type.startsWith('audio/')) return 'audio'
  if (type.startsWith('video/')) return 'video'
  if (type === 'application/pdf') return 'pdf'
  return 'file'
}

function getFileIcon(type?: string): string {
  const icons: Record<string, string> = {
    image: 'image',
    audio: 'audio',
    video: 'image',
    pdf: 'fileText',
    file: 'file',
  }
  return icons[getFileCategory(type)] || 'file'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const { t } = useI18n()
const chatStore = useChatStore()
const messageQueue = useMessageQueueStore()
const rightDock = useRightDockStore()
const { inputText, isStreaming, currentSessionId, retrievalStatus, eventsLostBanner } = storeToRefs(chatStore)
const { agentId } = useAgentPage()
const { isOwner: isSendLockOwner } = useSessionSendLock(currentSessionId)

// ── 模型切换器 / 429 横幅（共享单例）─────────────────────
const {
  chatModelGroups,
  selectedModel,
  rateLimitBanner,
  modelMenuOpen,
  activeProviderId,
  selectedModelLabel,
  currentModelContextWindow,
  activeGroupModels,
  activeProviderName,
  pickModel,
  gotoModelsManage,
  switchAfterRateLimit,
} = useChatModels()

// ── 待传附件（共享单例）────────────────────────────────
const { pendingFiles, removePendingFile, handleFileSelect, handlePaste } = usePendingFiles()

// ── ASR（共享单例）────────────────────────────────────
const { asrAvailable, isRecording, recordingTimeStr, toggleRecording, cancelRecording } = useASRRecording()

// ── 自动语音开关（共享单例，流式 TTS runner 由页面接线）───────
const { autoVoice, toggleAutoVoice } = useAutoVoice()
function onToggleAutoVoice(): void {
  toggleAutoVoice()
  if (!autoVoice.value) emit('stop')
}


// ── 斜杠命令面板（共享单例；命令注册表在本组件 setup 内组装）────
setupSlashCommands((seed) => emit('slashPlan', seed))
const { slashOpen, slashIndex, slashFiltered, runSlashCommand, onSlashKeydown, onSlashInput, closeSlashPanel } =
  useSlashCommands()

// ── 思考程度 ──────────────────────────────────────────
const { effort: thinkingEffort, setEffort: setThinkingEffort } = useThinkingEffort()
const thinkingOptions: Array<{ value: ThinkingEffort; label: string }> = [
  { value: 'light', label: 'chat.thinkingLight' },
  { value: 'standard', label: 'chat.thinkingStandard' },
  { value: 'deep', label: 'chat.thinkingDeep' },
]
const currentThinkingLabel = computed<string>(() => {
  const opt = thinkingOptions.find((o) => o.value === thinkingEffort.value)
  return opt ? t(opt.label) : ''
})

// ── 电脑分屏开关 ───────────────────────────────────────
const isComputerTabActive = computed(() => rightDock.tabs.some((tab) => tab.kind === 'computer'))
function toggleComputerPanel(): void {
  if (rightDock.tabs.some((tab) => tab.kind === 'computer')) {
    rightDock.closeTab('computer')
  } else {
    rightDock.openComputer()
  }
}

// ── 顶入卡片（队列编辑态，DeepSeek 截图对齐）────────────────
const editingQueuedId = ref<string | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const composerFocused = ref(false)

const queuedPlaceholder = computed(() => {
  if (isRecording.value) return t('chat.recording')
  if (editingQueuedId.value) return t('chat.queueEditInline')
  return t('chat.placeholder')
})

/** ✎ 重新编辑顶入内容：文案回填输入框（进入编辑态，卡片高亮）。 */
function startQueuedEdit(item: { id: string; text: string }): void {
  editingQueuedId.value = item.id
  chatStore.setInputText(item.text)
  nextTick(() => {
    textareaRef.value?.focus()
    autoResize()
  })
}

/** 编辑态下提交：改写队列文案并退出编辑态（不改排队位次）。 */
function commitQueuedEdit(): boolean {
  const id = editingQueuedId.value
  if (!id) return false
  const text = inputText.value.trim()
  if (text) messageQueue.updateText(id, text)
  editingQueuedId.value = null
  chatStore.setInputText('')
  return true
}

/** 取消顶入编辑：还原原文案回卡片，清空输入框退出编辑态。 */
function cancelQueuedEdit(): void {
  editingQueuedId.value = null
  chatStore.setInputText('')
  nextTick(() => textareaRef.value?.focus())
}

/** 「↑ 立即」：排队项插队（drain 由页面编排层执行）。 */
function sendQueuedNow(id: string): void {
  emit('sendQueuedNow', id)
}

/** 当前会话的排队卡片（审计③：全局 store 按会话过滤，跨会话项不混入）。 */
const currentSessionQueued = computed(() =>
  messageQueue.items.filter(
    (i) => !currentSessionId.value || i.sessionId === currentSessionId.value,
  ),
)

// 编辑目标被删除/出队 → 自动退出编辑态（防悬挂高亮与错误 placeholder）
watch(
  () => editingQueuedId.value && messageQueue.items.some((i) => i.id === editingQueuedId.value),
  (exists) => {
    if (editingQueuedId.value && !exists) {
      editingQueuedId.value = null
      chatStore.setInputText('')
    }
  },
)

// 会话/agent 切换 → 编辑态作废（编辑草稿属于原会话输入框，只清态不动
// 输入框——新会话草稿恢复晚于此回调，清输入会误删草稿）
watch(currentSessionId, () => {
  if (editingQueuedId.value) editingQueuedId.value = null
})

// ── 键盘 / 输入 / 自适应高度 ───────────────────────────
const { record: recordInputHistory, up: historyUp, down: historyDown } = useInputHistory()
const { onCompositionStart, onCompositionEnd, shouldBlockSend } = useIMEComposition()

function handleKeydown(e: KeyboardEvent) {
  // 斜杠命令面板键盘导航（↑↓/Enter/Tab/Esc），打开时独占按键
  if (onSlashKeydown(e)) return
  // 顶入编辑态（DeepSeek 截图对齐）：Enter=提交改写，Esc=取消还原
  if (editingQueuedId.value) {
    if (e.key === 'Enter' && !e.shiftKey) {
      if (shouldBlockSend(e)) return
      e.preventDefault()
      commitQueuedEdit()
      return
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      cancelQueuedEdit()
      return
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    // IME 合成防误发（补课 A）：输入法选词回车不发送
    if (shouldBlockSend(e)) return
    e.preventDefault()
    recordInputHistory(inputText.value.trim())
    emit('send')
    return
  }
  // ↑↓ 历史回溯（补课 C）：仅无修饰键时生效
  if (e.key === 'ArrowUp' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    const next = historyUp(inputText.value)
    if (next !== null) {
      e.preventDefault()
      chatStore.setInputText(next)
    }
  } else if (e.key === 'ArrowDown' && !e.shiftKey && !e.ctrlKey && !e.metaKey) {
    const next = historyDown(inputText.value)
    if (next !== null) {
      e.preventDefault()
      chatStore.setInputText(next)
    }
  }
}

/** 输入框 @input 统一入口：保留 autoResize 高度自适应 + 斜杠面板开合判定。 */
function onComposerInput(_e: Event): void {
  autoResize()
  onSlashInput()
}

/** 粘贴：附件捕获优先，未消费时走默认文本粘贴（关闭斜杠面板） */
function onPaste(e: ClipboardEvent): void {
  const consumed = handlePaste(e)
  if (!consumed) closeSlashPanel()
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

// ASR 转写回填后需要自适应高度（textarea 在本组件内）
useASRRecording().setResizeHook?.(autoResize)

// 用量环数据（per-session 累计，store 单一事实源）
const sessionUsage = computed(() => chatStore.getSessionTokenUsage(currentSessionId.value))

// 会话工具（/clear 等命令注册表需要）——setup 内调用以建立注入上下文
void useSessionOps()

defineExpose({ closeSlashPanel, autoResize })
</script>

<style scoped>
.nr-glass-dropdown {
  background: var(--nr-bg-surface); backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border); border-radius: 14px;
  padding: 6px; min-width: 220px; box-shadow: var(--nr-shadow-lg);
  display: flex; flex-direction: column; gap: 2px;
}
.nr-glass-dropdown-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-radius: 10px; color: var(--nr-text-secondary);
  font-size: 13px; cursor: pointer; transition: all 0.18s ease; white-space: nowrap;
}
.nr-glass-dropdown-item:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-glass-dropdown-item.is-active { color: var(--nr-primary-light); background: var(--nr-primary-soft); font-weight: 550; }
.nr-glass-dropdown-divider { height: 1px; background: var(--nr-glass-border); margin: 4px 8px; }
.nr-chat-input-area {
  position: relative;
  padding: 12px 24px 20px;
}
.nr-pending-files {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.nr-pending-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-radius: 10px;
  background: var(--nr-glass-bg);
  border: 1px solid var(--nr-glass-border);
  font-size: 12px;
  color: var(--nr-text-secondary);
}
.nr-pending-file img {
  width: 32px;
  height: 32px;
  object-fit: cover;
  border-radius: 6px;
}
.nr-pending-file-icon {
  font-size: 20px;
}
.nr-pending-file-info {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.nr-pending-file-name {
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-pending-file-size {
  font-size: 10px;
  color: var(--nr-text-muted);
}
.nr-pending-file-remove {
  background: none;
  border: none;
  color: var(--nr-text-muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0 2px;
  line-height: 1;
}
.nr-pending-file-remove:hover {
  color: var(--nr-error);
}
.nr-recording-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 16px;
  margin-bottom: 8px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 10px;
}
.nr-recording-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #ef4444;
  animation: rec-pulse 1s ease infinite;
}
@keyframes rec-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}
.nr-recording-label {
  font-size: 13px;
  color: var(--nr-error);
  font-weight: 500;
}
.nr-recording-wave {
  display: flex;
  align-items: center;
  gap: 2px;
  height: 20px;
  flex: 1;
}
.nr-wave-bar {
  width: 3px;
  height: 100%;
  background: rgba(239, 68, 68, 0.5);
  border-radius: 2px;
  animation: wave-anim 0.8s ease-in-out infinite alternate;
}
@keyframes wave-anim {
  0% { height: 20%; }
  100% { height: 90%; }
}
.nr-recording-time {
  font-size: 13px;
  font-family: var(--nr-font-mono);
  color: var(--nr-text-secondary);
}
.nr-recording-cancel {
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--nr-error);
  cursor: pointer;
  transition: background 0.2s;
}
.nr-recording-cancel:hover {
  background: rgba(239, 68, 68, 0.25);
}
.nr-input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.nr-voice-active {
  animation: voice-glow 1s ease infinite alternate;
}
@keyframes voice-glow {
  from { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.2); }
  to { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
}
.nr-composer-shell {
  position: relative;
  border: 1px solid var(--nr-glass-border);
  border-radius: 16px;
  background: var(--nr-glass-bg);
  padding: 12px 14px 10px;
  transition: border-color 0.25s, box-shadow 0.25s;
}
.nr-composer-shell.is-focus {
  border-color: var(--nr-primary);
  box-shadow: 0 0 0 3px var(--nr-primary-ring);
}
.nr-input-row {
  display: flex;
  align-items: flex-end;
  gap: 10px;
}
.nr-chat-textarea {
  flex: 1;
  resize: none;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 4px 6px 10px;
  min-height: 60px;
  color: var(--nr-text-primary);
  font-size: 14px;
  font-family: var(--nr-font-body);
  line-height: 1.55;
  outline: none;
  max-height: 200px;
}
.nr-chat-textarea:focus {
  outline: none;
}
.nr-chat-textarea::placeholder {
  color: var(--nr-text-muted);
}
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.nr-retrieval-status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  margin: 0 16px 6px;
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: var(--nr-bg-secondary);
  border: 1px solid var(--nr-border);
  border-radius: 10px;
}
.nr-retrieval-spinner {
  display: inline-block;
  animation: nr-retrieval-spin 1.2s linear infinite;
  color: var(--nr-accent);
}
@keyframes nr-retrieval-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
.nr-rate-limit-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin: 0 0 8px;
  padding: 8px 12px;
  border-radius: 10px;
  border: 1px solid rgba(245, 158, 11, 0.4);
  background: rgba(245, 158, 11, 0.08);
  font-size: 12px;
}
.nr-rate-limit-text {
  color: var(--nr-text-primary);
}
.nr-rate-limit-alts {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.nr-rate-limit-alt {
  padding: 3px 10px;
  border-radius: 8px;
  border: 1px solid rgba(99, 102, 241, 0.5);
  background: rgba(99, 102, 241, 0.1);
  color: var(--nr-text-primary);
  cursor: pointer;
  font-size: 12px;
}
.nr-rate-limit-alt:hover {
  background: rgba(99, 102, 241, 0.2);
}
.nr-rate-limit-dismiss {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--nr-text-tertiary);
  cursor: pointer;
}
.nr-composer-shell.has-queue-cards .nr-input-row {
  border: 1px solid var(--nr-glass-border);
  border-radius: 12px;
  padding: 0 6px;
  transition: border-color 0.25s;
}
.nr-composer-shell.has-queue-cards.is-editing-queued .nr-input-row {
  border-color: var(--nr-primary);
}
.nr-slash-panel {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin-bottom: 6px;
  border-radius: 10px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-secondary, rgba(30, 32, 40, 0.95));
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
  overflow: hidden;
  z-index: 30;
}
.nr-slash-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
}
.nr-slash-item.is-active {
  background: rgba(74, 158, 255, 0.15);
}
.nr-slash-name {
  font-family: var(--nr-font-mono, monospace);
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-primary, #4a9eff);
  min-width: 72px;
}
.nr-slash-desc {
  font-size: 12px;
  color: var(--nr-text-secondary);
}
.nr-composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 0 0;
}
.nr-composer-left,
.nr-composer-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.nr-composer-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border-radius: 13px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg);
  color: var(--nr-text-secondary);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.2s, border-color 0.2s, background 0.2s;
}
.nr-composer-pill:hover {
  color: var(--nr-text-primary);
  border-color: var(--nr-primary, #4a9eff);
}
.nr-composer-pill.is-active {
  color: var(--nr-primary, #4a9eff);
  border-color: var(--nr-primary, #4a9eff);
}
.nr-composer-pill--icon {
  width: 26px;
  padding: 0;
  justify-content: center;
  font-size: 13px;
}
.nr-ico {
  width: 15px;
  height: 15px;
  flex: none;
  stroke: currentColor;
  fill: none;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.nr-ico--send {
  width: 16px;
  height: 16px;
  stroke-width: 2;
}
.nr-composer-pill--model {
  max-width: 240px;
}
.nr-composer-pill-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-composer-pill-arrow {
  font-size: 9px;
  opacity: 0.65;
}
.nr-composer-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-width: 132px;
}
.nr-composer-check {
  color: var(--nr-primary, #4a9eff);
  font-size: 12px;
}
.nr-composer-model-menu {
  max-height: 320px;
  overflow-y: auto;
}
.nr-model-menu-wrap {
  position: relative;
}
.nr-model-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
}
.nr-model-cascade {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  width: 184px;
  border-radius: 12px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-secondary, rgba(30, 32, 40, 0.98));
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.4);
  overflow: visible;
}
.nr-model-cascade-left {
  max-height: 320px;
  overflow-y: auto;
  padding: 6px;
}
.nr-model-provider {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--nr-text-secondary);
}
.nr-model-provider:hover {
  background: rgba(255, 255, 255, 0.05);
}
.nr-model-provider.is-active {
  background: rgba(74, 158, 255, 0.14);
  color: var(--nr-text-primary);
}
.nr-model-provider-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.nr-model-provider-count {
  font-size: 11px;
  color: var(--nr-text-tertiary);
}
.nr-model-provider-arrow {
  font-size: 12px;
  opacity: 0.5;
}
.nr-model-cascade-divider {
  height: 1px;
  margin: 4px 8px;
  background: var(--nr-glass-border);
}
.nr-model-empty {
  padding: 10px;
  text-align: center;
  font-size: 12px;
  color: var(--nr-text-tertiary);
}
.nr-model-cascade-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-top: 1px solid var(--nr-glass-border);
  font-size: 12px;
  color: var(--nr-text-secondary);
  cursor: pointer;
  border-radius: 0 0 12px 12px;
}
.nr-model-cascade-footer:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--nr-text-primary);
}
.nr-model-dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.nr-model-dot.is-ok {
  background: #22c55e;
  box-shadow: 0 0 4px rgba(34, 197, 94, 0.55);
}
.nr-model-dot.is-off {
  background: rgba(128, 128, 128, 0.45);
}
.nr-composer-menu-item.is-unconnectable .nr-composer-pill-label {
  color: var(--nr-text-tertiary);
}
.nr-model-flyout {
  position: absolute;
  right: calc(100% + 8px);
  bottom: 0;
  width: 248px;
  height: 360px;
  display: flex;
  flex-direction: column;
  border-radius: 12px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-secondary, rgba(30, 32, 40, 0.98));
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
.nr-model-flyout-title {
  flex: none;
  padding: 9px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--nr-text-tertiary);
  border-bottom: 1px solid var(--nr-glass-border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nr-model-flyout-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.nr-composer-send {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 8px;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-primary, #4a9eff);
  color: #fff;
  cursor: pointer;
  transition: transform 0.15s, filter 0.15s, background 0.2s, border-color 0.2s;
}

.nr-composer-send:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.12);
}
.nr-composer-send:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.nr-composer-send.is-stop {
  background: var(--nr-danger, #f56c6c);
}
.nr-composer-send.is-confirm {
  color: var(--nr-primary);
}
</style>
