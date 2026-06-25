<template>
  <div
    class="nr-chat-page"
    :class="{ 'nr-chat-page--main': isMainLayout }"
    @dragenter.prevent="onDragEnter"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- Drag & Drop Overlay -->
    <transition name="fade-scale">
      <div v-if="isDragOver" class="nr-drop-overlay">
        <div class="nr-drop-overlay-content">
          <span class="nr-drop-icon">📂</span>
          <span class="nr-drop-text">{{ t('chat.dropFiles') }}</span>
        </div>
      </div>
    </transition>

    <!-- Left Sidebar: Sessions -->
    <aside v-if="!isMainLayout" class="nr-chat-sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="nr-sidebar-header">
        <GlassButton variant="primary" size="md" style="flex: 1" @click="createSession">
          + {{ t('chat.newChat') }}
        </GlassButton>
      </div>

      <div class="nr-sidebar-search">
        <GlassInput
          v-model:model-value="searchQuery"
          :placeholder="t('common.search')"
          @update:model-value="searchQuery = $event"
        />
      </div>

      <div class="nr-session-list">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="nr-session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="switchSession(session.id)"
        >
          <span class="nr-session-icon">💬</span>
          <span class="nr-session-name">{{ session.title }}</span>
          <a-dropdown :trigger="['click']" @click.stop>
            <span class="nr-session-menu-btn" @click.stop>⋯</span>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="renameSession(session.id)">
                  {{ t('chat.rename') }}
                </a-menu-item>
                <a-menu-item danger @click="deleteSession(session.id)">
                  {{ t('chat.deleteSession') }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
        <div v-if="filteredSessions.length === 0" class="nr-session-empty">
          {{ t('chat.noSessions') }}
        </div>
      </div>
    </aside>

    <!-- Main Chat Area -->
    <main class="nr-chat-main">
      <!-- Page Header (when inside MainLayout) -->
      <div v-if="isMainLayout" class="nr-chat-page-header">
        <div class="nr-chat-header-left">
          <a-dropdown :trigger="['click']" placement="bottomLeft">
            <button class="nr-chat-session-select">
              <span class="nr-chat-session-select-icon">💬</span>
              <span class="nr-chat-session-select-name">{{ currentSessionTitle || t('chat.noSessions') }}</span>
              <span class="nr-chat-session-select-arrow">▾</span>
            </button>
            <template #overlay>
              <div class="nr-glass-dropdown">
                <div class="nr-glass-dropdown-item" style="font-weight:600; color: var(--nr-text-primary);" @click="createSession">
                  + {{ t('chat.newChat') }}
                </div>
                <div class="nr-glass-dropdown-divider" />
                <div
                  v-for="s in filteredSessions"
                  :key="s.id"
                  class="nr-glass-dropdown-item"
                  :class="{ 'is-active': s.id === currentSessionId }"
                  @click="switchSession(s.id)"
                >
                  <span>{{ s.title }}</span>
                </div>
                <div v-if="filteredSessions.length === 0" class="nr-glass-dropdown-item" style="opacity:0.5">
                  {{ t('common.noData') }}
                </div>
              </div>
            </template>
          </a-dropdown>
        </div>
        <div class="nr-chat-header-actions">
          <button class="nr-chat-toggle-btn" @click="historyPanelOpen = !historyPanelOpen" :title="t('chat.history')">
            {{ historyPanelOpen ? '›' : '‹' }}
          </button>
        </div>
      </div>
      <!-- Message List -->
      <div class="nr-chat-messages" ref="messagesRef">
        <div v-if="messages.length === 0" class="nr-chat-empty">
          <div v-if="isMainLayout && !agentId" class="nr-chat-empty">
            <div class="nr-chat-empty-icon">💬</div>
            <h3>{{ t('nav.chat') }}</h3>
            <p>{{ t('chat.selectAgentFirst') }}</p>
          </div>
          <div v-else class="nr-chat-empty">
            <div class="nr-chat-empty-icon">🤖</div>
            <h3>{{ currentAgent?.name || t('agent.title') }}</h3>
            <p>{{ t('chat.placeholder') }}</p>
          </div>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          class="nr-msg"
          :class="`nr-msg--${msg.role}`"
        >
          <div class="nr-msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="nr-msg-body">
            <!-- Reasoning / Thinking Block -->
            <div v-if="msg.reasoning" class="nr-msg-reasoning">
              <div class="nr-reasoning-header" @click="msg.reasoningOpen = !msg.reasoningOpen">
                <span>💭 {{ t('chat.reasoning') }}</span>
                <span class="nr-reasoning-toggle">{{ msg.reasoningOpen ? '▾' : '▸' }}</span>
              </div>
              <div v-show="msg.reasoningOpen" class="nr-reasoning-content">
                {{ msg.reasoning }}
              </div>
            </div>

            <!-- Tool Call Block (collapsible, supports multi-round) -->
            <template v-if="msg.toolCalls && msg.toolCalls.length > 0">
              <div v-for="(tc, tcIdx) in msg.toolCalls" :key="tcIdx" class="nr-msg-tool-call">
                <div class="nr-tool-header" @click="msg.toolOpen = !msg.toolOpen">
                  <span class="nr-tool-icon">🔧</span>
                  <span class="nr-tool-name">{{ tc.name }}</span>
                  <a-tag :color="tc.result ? 'success' : 'processing'">
                    {{ tc.result ? t('chat.toolDone') : t('chat.toolCalling') }}
                  </a-tag>
                  <span class="nr-tool-toggle">{{ msg.toolOpen ? '▾' : '▸' }}</span>
                </div>
                <div v-show="msg.toolOpen">
                  <pre class="nr-tool-args">{{ formatJSON(tc.arguments) }}</pre>
                  <div v-if="tc.result" class="nr-tool-result">
                    <div class="nr-tool-result-header">{{ t('chat.toolResult') }}</div>
                    <pre class="nr-tool-result-content">{{ tc.result }}</pre>
                  </div>
                </div>
              </div>
            </template>
            <!-- Legacy single tool call (backward compat) -->
            <div v-else-if="msg.toolCall" class="nr-msg-tool-call">
              <div class="nr-tool-header" @click="msg.toolOpen = !msg.toolOpen">
                <span class="nr-tool-icon">🔧</span>
                <span class="nr-tool-name">{{ msg.toolCall.name }}</span>
                <a-tag :color="msg.toolResult ? 'success' : 'processing'">
                  {{ msg.toolResult ? t('chat.toolDone') : t('chat.toolCalling') }}
                </a-tag>
                <span class="nr-tool-toggle">{{ msg.toolOpen ? '▾' : '▸' }}</span>
              </div>
              <div v-show="msg.toolOpen">
                <pre class="nr-tool-args">{{ formatJSON(msg.toolCall.arguments) }}</pre>
                <div v-if="msg.toolResult" class="nr-tool-result">
                  <div class="nr-tool-result-header">{{ t('chat.toolResult') }}</div>
                  <pre class="nr-tool-result-content">{{ msg.toolResult }}</pre>
                </div>
              </div>
            </div>

            <!-- Message Content (Rich Media Rendering) -->
            <div
              v-if="msg.content"
              class="nr-msg-content"
              v-html="renderRichContent(msg.content)"
              @click="handleContentClick"
            />

            <!-- File Attachments (Enhanced) -->
            <div v-if="msg.attachments?.length" class="nr-msg-attachments">
              <div
                v-for="(file, fi) in msg.attachments"
                :key="fi"
                class="nr-attachment-thumb"
                :class="`nr-attachment--${getFileCategory(file.type)}`"
                @click="file.type?.startsWith('image/') && openLightbox(file.preview!, file.name)"
              >
                <img
                  v-if="file.type?.startsWith('image/')"
                  :src="file.preview"
                  :alt="file.name"
                  class="nr-attachment-img"
                />
                <span v-else class="nr-attachment-file-icon">{{ getFileIcon(file.type) }}</span>
                <div class="nr-attachment-info">
                  <span class="nr-attachment-name">{{ file.name }}</span>
                  <span v-if="file.size" class="nr-attachment-size">{{ formatFileSize(file.size) }}</span>
                </div>
              </div>
            </div>

            <!-- Custom Audio Player for TTS -->
            <div v-if="msg.audioUrl" class="nr-msg-audio-player">
              <div class="nr-audio-player">
                <button
                  class="nr-audio-play-btn"
                  @click="toggleAudioPlay(msg)"
                >
                  {{ msg.audioPlaying ? '⏸' : '▶' }}
                </button>
                <div class="nr-audio-progress-wrap" @click="seekAudio(msg, $event)">
                  <div class="nr-audio-progress-bar">
                    <div
                      class="nr-audio-progress-fill"
                      :style="{ width: (msg.audioProgress || 0) + '%' }"
                    />
                  </div>
                </div>
                <span class="nr-audio-time">{{ formatAudioTime(msg.audioCurrentTime || 0) }}</span>
                <button class="nr-audio-speed-btn" @click="cycleAudioSpeed(msg)">
                  {{ msg.audioSpeed || 1 }}x
                </button>
              </div>
              <!-- Hidden audio element -->
              <audio
                :ref="(el) => setAudioRef(msg, el as HTMLAudioElement)"
                :src="msg.audioUrl"
                preload="metadata"
                @timeupdate="onAudioTimeUpdate(msg)"
                @loadedmetadata="onAudioLoaded(msg)"
                @ended="onAudioEnded(msg)"
              />
            </div>

            <!-- TTS Action for assistant messages -->
            <div
              v-if="msg.role === 'assistant' && !msg.streaming && msg.content && !msg.audioUrl && ttsAvailable"
              class="nr-msg-tts-action"
            >
              <button class="nr-tts-btn" @click="synthesizeTTS(msg)" :disabled="msg.ttsLoading">
                {{ msg.ttsLoading ? '⏳' : '🔊' }}
                <span>{{ msg.ttsLoading ? t('chat.ttsLoading') : t('chat.playTTS') }}</span>
              </button>
            </div>

            <!-- Streaming indicator -->
            <div v-if="msg.streaming" class="nr-msg-streaming">
              <span class="nr-typing-dot" /><span class="nr-typing-dot" /><span class="nr-typing-dot" />
            </div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
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

        <div class="nr-input-row">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            accept="image/*,audio/*,video/*,.pdf,.doc,.docx,.txt,.csv,.json,.py,.js,.ts,.vue,.html,.css,.md"
            style="display: none"
            @change="handleFileSelect"
          />
          <GlassButton variant="ghost" size="md" @click="fileInputRef?.click()" :title="t('chat.upload')">
            📎
          </GlassButton>
          <!-- ASR Voice Button -->
          <GlassButton
            v-if="asrAvailable"
            variant="ghost"
            size="md"
            :class="{ 'nr-voice-active': isRecording }"
            @click="toggleRecording"
            :title="t('chat.voice')"
          >
            {{ isRecording ? '🔴' : '🎙️' }}
          </GlassButton>
          <textarea
            ref="textareaRef"
            v-model="inputText"
            class="nr-chat-textarea"
            :placeholder="isRecording ? t('chat.recording') : t('chat.placeholder')"
            rows="1"
            @keydown="handleKeydown"
            @input="autoResize"
            @paste="handlePaste"
          />
          <GlassButton
            v-if="isStreaming"
            variant="danger"
            size="md"
            @click="stopStreaming"
          >
            {{ t('chat.stop') }}
          </GlassButton>
          <GlassButton
            v-else
            variant="primary"
            size="md"
            :disabled="!inputText.trim() && pendingFiles.length === 0"
            @click="sendMessage"
          >
            {{ t('chat.send') }}
          </GlassButton>
        </div>
      </div>
    </main>

    <!-- Right Panel: Conversation History (main layout mode) -->
    <aside v-if="isMainLayout && agentId && historyPanelOpen" class="nr-chat-history-panel">
      <div class="nr-history-header">
        <GlassButton variant="primary" size="sm" @click="createSession">+ {{ t('chat.newChat') }}</GlassButton>
      </div>
      <div class="nr-history-search">
        <GlassInput
          v-model:model-value="searchQuery"
          :placeholder="t('common.search')"
          @update:model-value="searchQuery = $event"
        />
      </div>
      <div class="nr-session-list">
        <div
          v-for="session in filteredSessions"
          :key="session.id"
          class="nr-session-item"
          :class="{ active: session.id === currentSessionId }"
          @click="switchSession(session.id)"
        >
          <span class="nr-session-icon">💬</span>
          <span class="nr-session-name">{{ session.title }}</span>
          <a-dropdown :trigger="['click']" @click.stop>
            <span class="nr-session-menu-btn" @click.stop>⋯</span>
            <template #overlay>
              <a-menu>
                <a-menu-item @click="renameSession(session.id)">
                  {{ t('chat.rename') }}
                </a-menu-item>
                <a-menu-item danger @click="deleteSession(session.id)">
                  {{ t('chat.deleteSession') }}
                </a-menu-item>
              </a-menu>
            </template>
          </a-dropdown>
        </div>
        <div v-if="filteredSessions.length === 0" class="nr-session-empty">
          {{ t('chat.noSessions') }}
        </div>
      </div>
    </aside>

    <!-- Image Lightbox -->
    <transition name="fade-scale">
      <div v-if="lightbox.open" class="nr-lightbox" @click="lightbox.open = false">
        <div class="nr-lightbox-content" @click.stop>
          <img :src="lightbox.src" :alt="lightbox.alt" />
          <div class="nr-lightbox-caption">{{ lightbox.alt }}</div>
        </div>
        <button class="nr-lightbox-close" @click="lightbox.open = false">✕</button>
      </div>
    </transition>

    <!-- Rename Modal -->
    <a-modal
      v-model:open="renameModal.open"
      :title="t('chat.rename')"
      @ok="confirmRename"
    >
      <GlassInput
        v-model:model-value="renameModal.title"
        :placeholder="t('chat.rename')"
        @update:model-value="renameModal.title = $event"
      />
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAgentPage } from '@/composables/useAgentPage'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'
import { useAppStore } from '@/stores/app'
import { api } from '@/api'
import { deleteConsoleSession } from '@/api/modules/console'
import { secureStorage } from '@/utils/security'
import { uiMessage } from '@/utils/message'
import GlassButton from '@/components/GlassButton.vue'
import GlassInput from '@/components/GlassInput.vue'

const { t } = useI18n()
const appStore = useAppStore()
const { agentId, currentAgent } = useAgentPage()

const props = defineProps<{
  layoutMode?: 'chat' | 'main'
}>()

const isMainLayout = computed(() => props.layoutMode === 'main')

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  reasoningOpen?: boolean
  toolCalls?: Array<{ name: string; arguments: string; result?: string }>
  toolOpen?: boolean
  toolCall?: { name: string; arguments: string }  // legacy single, kept for compat
  toolResult?: string  // legacy single, kept for compat
  attachments?: Array<{ name: string; type?: string; preview?: string; size?: number }>
  audioUrl?: string
  audioPlaying?: boolean
  audioProgress?: number
  audioCurrentTime?: number
  audioDuration?: number
  audioSpeed?: number
  audioEl?: HTMLAudioElement | null
  ttsLoading?: boolean
  streaming?: boolean
}

interface Session {
  id: string
  title: string
  updatedAt?: string
}

interface PendingFile {
  name: string
  file: File
  type?: string
  preview?: string
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const messagesRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

const messages = ref<ChatMessage[]>([])
const sessions = ref<Session[]>([])
const currentSessionId = ref<string | null>(null)
const inputText = ref('')
const searchQuery = ref('')
const isStreaming = ref(false)
const pendingFiles = ref<PendingFile[]>([])
const sidebarCollapsed = computed(() => appStore.sidebarCollapsed)
const historyPanelOpen = ref(true)

// Drag & Drop
const isDragOver = ref(false)
let dragCounter = 0

// ASR
const asrAvailable = ref(false)
const isRecording = ref(false)
const recordingTimeStr = ref('0:00')
let recognition: any = null
// Guard against infinite ASR auto-restart when the recognizer keeps dying.
const asrRestartGuard = useASRRestartGuard(3)
let recordingTimer: ReturnType<typeof setInterval> | null = null
let recordingSeconds = 0
// Timer for the delayed ASR restart (breaks tight onend→start loops)
let asrRestartTimer: ReturnType<typeof setTimeout> | null = null

// MediaRecorder for backend ASR fallback
let mediaRecorder: MediaRecorder | null = null
let recordedChunks: Blob[] = []

// TTS
const ttsAvailable = ref(true) // assume available, verify on mount

// Lightbox
const lightbox = reactive({ open: false, src: '', alt: '' })

const renameModal = reactive({ open: false, sessionId: '', title: '' })

let abortController: AbortController | null = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const currentSessionTitle = computed(() => sessions.value.find(s => s.id === currentSessionId.value)?.title ?? '')

const filteredSessions = computed(() => {
  if (!searchQuery.value) return sessions.value
  const q = searchQuery.value.toLowerCase()
  return sessions.value.filter((s) => s.title.toLowerCase().includes(q))
})

// ---------------------------------------------------------------------------
// Session Management
// ---------------------------------------------------------------------------
async function loadSessions() {
  try {
    const agentParam = agentId.value ? `?agent_id=${agentId.value}` : ''
    const res: any = await api.get(`/console/chat/sessions${agentParam}`)
    const data = res?.data ?? res
    const sessionList = data?.sessions ?? data ?? []
    sessions.value = sessionList.map(
      (s: any) => ({ id: s.session_id || s.id, title: s.title || s.name || '新对话', updatedAt: s.created_at || s.updated_at }),
    )
    if (sessions.value.length > 0 && !currentSessionId.value) {
      switchSession(sessions.value[0].id)
    }
  } catch {
    sessions.value = []
  }
}

async function createSession() {
  const newId = crypto.randomUUID()
  const newSession: Session = { id: newId, title: `${t('chat.newChat')} - ${new Date().toLocaleString()}` }
  sessions.value.unshift(newSession)
  switchSession(newId)
}

async function switchSession(sessionId: string) {
  currentSessionId.value = sessionId
  messages.value = []
  try {
    const res: any = await api.get(`/console/chat/history?session_id=${sessionId}`)
    const data = res?.data ?? res
    const history = Array.isArray(data) ? data : data?.messages ?? data?.items ?? []
    messages.value = history.map((m: any) => {
      // Build toolCalls array from tool_messages
      const toolCalls: Array<{ name: string; arguments: string; result?: string }> = []
      const toolMessages = m.tool_messages || []
      for (const tm of toolMessages) {
        if (tm.type === 'tool_call') {
          toolCalls.push({
            name: tm.tool_name || tm.name || '',
            arguments: typeof tm.params === 'string' ? tm.params : JSON.stringify(tm.params || tm.arguments || {}, null, 2),
          })
        } else if (tm.type === 'tool_result') {
          const resultText = typeof tm.result === 'string' ? tm.result : JSON.stringify(tm.result || '', null, 2)
          if (toolCalls.length > 0) {
            toolCalls[toolCalls.length - 1].result = resultText
          }
        }
      }
      // legacy single fallback
      const toolCall = toolCalls.length > 0 ? toolCalls[0] : (m.tool_call ? {
        name: m.tool_call.name || m.tool_call.function?.name || '',
        arguments: m.tool_call.arguments || m.tool_call.function?.arguments || '',
      } : undefined)
      const toolResult = toolCalls.length > 0 ? toolCalls[0].result : (m.tool_result || undefined)
      return {
        role: m.role === 'user' ? 'user' : 'assistant',
        content: m.content || '',
        reasoning: m.reasoning || m.reasoning_content || undefined,
        reasoningOpen: false,
        toolCalls: toolCalls.length > 0 ? toolCalls : undefined,
        toolCall,
        toolResult,
      }
    })
    scrollToBottom()
  } catch (err) {
    console.error('[Chat] Failed to load history:', err)
  }
}

function renameSession(sessionId: string) {
  const session = sessions.value.find((s) => s.id === sessionId)
  if (!session) return
  renameModal.sessionId = sessionId
  renameModal.title = session.title
  renameModal.open = true
}

async function confirmRename() {
  if (!renameModal.title.trim()) return
  try {
    await api.put(`/chat/sessions/${renameModal.sessionId}`, { title: renameModal.title.trim() })
    const session = sessions.value.find((s) => s.id === renameModal.sessionId)
    if (session) session.title = renameModal.title.trim()
  } catch (err) {
    console.error('[Chat] Rename failed:', err)
  }
  renameModal.open = false
}

async function deleteSession(sessionId: string) {
  try {
    await deleteConsoleSession(sessionId)
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    if (currentSessionId.value === sessionId) {
      currentSessionId.value = null
      messages.value = []
      if (sessions.value.length > 0) switchSession(sessions.value[0].id)
    }
  } catch (err) {
    console.error('[Chat] Delete session failed:', err)
  }
}

// ---------------------------------------------------------------------------
// Message Sending with SSE Streaming
// ---------------------------------------------------------------------------
async function sendMessage() {
  const text = inputText.value.trim()
  if (!text && pendingFiles.length === 0) return
  if (isStreaming.value) return
  if (!agentId.value) return

  // Stop any active ASR recording
  if (isRecording.value) stopRecording()

  // Build user message
  const userMsg: ChatMessage = {
    role: 'user',
    content: text,
    attachments: pendingFiles.value.map((f) => ({
      name: f.name,
      type: f.type,
      preview: f.preview,
      size: f.file.size,
    })),
  }
  messages.value.push(userMsg)

  // Prepare assistant placeholder
  const assistantMsg: ChatMessage = {
    role: 'assistant',
    content: '',
    reasoning: '',
    reasoningOpen: false,
    toolCalls: [],
    toolOpen: false,
    streaming: true,
  }
  messages.value.push(assistantMsg)

  inputText.value = ''
  const filesToUpload = [...pendingFiles.value]
  pendingFiles.value = []
  isStreaming.value = true
  scrollToBottom()

  // Upload files first if any
  const fileIds: string[] = []
  for (const pf of filesToUpload) {
    try {
      const uploadRes: any = await api.upload('/files/upload', pf.file, 'file', {
        agent_id: agentId.value,
      })
      const uploadData = uploadRes?.data ?? uploadRes
      if (uploadData?.id) fileIds.push(uploadData.id)
    } catch (err) {
      console.error('[Chat] File upload failed:', err)
    }
  }

  // Initiate SSE streaming request
  abortController = new AbortController()
  const token = secureStorage.get('auth_token')

  try {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const response = await fetch(`${baseUrl}/console/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        agent_id: agentId.value,
        session_id: currentSessionId.value,
        message: text,
        file_ids: fileIds.length > 0 ? fileIds : undefined,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      const errBody = await response.text()
      throw new Error(errBody || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6).trim()
        if (!data || data === '[DONE]') continue

        try {
          const event = JSON.parse(data)
          processSSEEvent(event, assistantMsg)
        } catch {
          // Non-JSON line, skip
        }
      }
      scrollToBottom()
    }
  } catch (err: any) {
    if (err.name !== 'AbortError') {
      assistantMsg.content += `\n\n**Error:** ${err.message || 'Stream failed.'}`
    }
  } finally {
    assistantMsg.streaming = false
    isStreaming.value = false
    abortController = null
    scrollToBottom()
  }
}

/** Process a single SSE event and update the assistant message. */
function processSSEEvent(event: any, msg: ChatMessage) {
  const type = event.type || event.event

  switch (type) {
    case 'reasoning':
    case 'thinking':
      msg.reasoning = (msg.reasoning || '') + (event.content || event.text || '')
      break

    case 'tool_call':
      if (!msg.toolCalls) msg.toolCalls = []
      msg.toolCalls.push({
        name: event.name || event.tool_name || 'unknown',
        arguments: event.arguments || event.input || '',
      })
      // legacy compat
      msg.toolCall = msg.toolCalls[msg.toolCalls.length - 1]
      break

    case 'tool_result':
      if (msg.toolCalls && msg.toolCalls.length > 0) {
        const last = msg.toolCalls[msg.toolCalls.length - 1]
        last.result = typeof event.result === 'string' ? event.result : JSON.stringify(event.result, null, 2)
      }
      // legacy compat
      msg.toolResult = typeof event.result === 'string' ? event.result : JSON.stringify(event.result, null, 2)
      break

    case 'message':
    case 'content':
    case 'delta':
    case 'chunk':
      msg.content += event.content || event.text || event.delta || ''
      break

    case 'audio':
    case 'tts':
      if (event.url) {
        msg.audioUrl = event.url
        msg.audioProgress = 0
        msg.audioCurrentTime = 0
        msg.audioSpeed = 1
      }
      break

    case 'image':
      // Inline image from backend (e.g., AIGC generated image)
      if (event.url) {
        msg.content += `\n![${event.alt || 'image'}](${event.url})\n`
      }
      break

    case 'done':
    case 'complete':
      msg.streaming = false
      // Auto-create session if this is the first exchange
      if (!currentSessionId.value && event.session_id) {
        currentSessionId.value = event.session_id
        sessions.value.unshift({
          id: event.session_id,
          title: inputText.value.slice(0, 50) || t('chat.newChat'),
        })
      }
      break

    case 'error':
      msg.content += `\n\n**Error:** ${event.message || event.error || 'Unknown error'}`
      break
  }
}

function stopStreaming() {
  abortController?.abort()
  isStreaming.value = false
}

// ---------------------------------------------------------------------------
// ASR - Voice Input (Web Speech API + Backend Fallback)
// ---------------------------------------------------------------------------
function initASR() {
  const SpeechRecognition =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognition) {
    asrAvailable.value = false
    console.warn('[ASR] Web Speech API not available')
    return
  }

  asrAvailable.value = true
  recognition = new SpeechRecognition()
  recognition.continuous = true
  recognition.interimResults = true
  recognition.lang = appStore.locale === 'zh-CN' ? 'zh-CN' : 'en-US'

  recognition.onresult = (event: any) => {
    let finalTranscript = ''
    let interimTranscript = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript
      if (event.results[i].isFinal) {
        finalTranscript += transcript
      } else {
        interimTranscript += transcript
      }
    }
    if (finalTranscript) {
      inputText.value += (inputText.value ? ' ' : '') + finalTranscript
      nextTick(() => autoResize())
    }
  }

  recognition.onerror = (event: any) => {
    console.error('[ASR] Error:', event.error)
    if (event.error !== 'aborted') {
      stopRecording()
    }
  }

  recognition.onend = () => {
    // Auto-restart if still in recording mode, but cap consecutive restarts
    // to avoid an infinite loop when isRecording is stuck true or the
    // recognizer keeps dying. After the cap, stop and tell the user.
    if (isRecording.value && asrRestartGuard.canRestart()) {
      asrRestartGuard.recordRestart()
      // Delay restart by 1s to break tight onend→start loops and give the
      // recognizer time to fully reset before we start() it again.
      asrRestartTimer = setTimeout(() => {
        asrRestartTimer = null
        if (!isRecording.value) return
        try {
          recognition.start()
        } catch {
          // Already started
        }
      }, 1000)
    } else if (isRecording.value && asrRestartGuard.limitReached.value) {
      console.warn('[ASR] Restart limit reached, stopping auto-restart')
      isRecording.value = false
      if (recordingTimer) {
        clearInterval(recordingTimer)
        recordingTimer = null
      }
      uiMessage.warning(t('chat.asrRestartLimit') || 'Speech recognition stopped after multiple retries. Please try again.')
    }
  }
}

function toggleRecording() {
  if (isRecording.value) {
    stopRecording()
  } else {
    startRecording()
  }
}

function startRecording() {
  if (!recognition) return
  isRecording.value = true
  recordingSeconds = 0
  recordingTimeStr.value = '0:00'
  // Fresh user-initiated start → reset the restart counter
  asrRestartGuard.reset()

  try {
    recognition.start()
  } catch {
    // Already started
  }

  recordingTimer = setInterval(() => {
    recordingSeconds++
    const mins = Math.floor(recordingSeconds / 60)
    const secs = recordingSeconds % 60
    recordingTimeStr.value = `${mins}:${secs.toString().padStart(2, '0')}`
  }, 1000)
}

function stopRecording() {
  isRecording.value = false
  if (recordingTimer) {
    clearInterval(recordingTimer)
    recordingTimer = null
  }
  if (asrRestartTimer) {
    clearTimeout(asrRestartTimer)
    asrRestartTimer = null
  }
  try {
    recognition?.stop()
  } catch {
    // Ignore
  }
}

function cancelRecording() {
  stopRecording()
}

// Backend ASR fallback for uploaded audio files
async function transcribeAudioFile(file: File): Promise<string | null> {
  try {
    const formData = new FormData()
    formData.append('audio_file', file)
    formData.append('language', appStore.locale === 'zh-CN' ? 'zh' : 'en')
    const res: any = await api.post('/audio/transcribe', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const data = res?.data ?? res
    return data?.data?.text || data?.text || null
  } catch (err) {
    console.error('[ASR] Backend transcription failed:', err)
    return null
  }
}

// ---------------------------------------------------------------------------
// TTS - Voice Output
// ---------------------------------------------------------------------------
async function checkTTSAvailability() {
  try {
    const res: any = await api.get('/audio/status')
    const data = res?.data ?? res
    const ttsInfo = data?.data?.tts || data?.tts
    ttsAvailable.value = ttsInfo?.initialized ?? false
  } catch {
    ttsAvailable.value = false
  }
}

async function synthesizeTTS(msg: ChatMessage) {
  if (!msg.content || msg.ttsLoading) return
  msg.ttsLoading = true

  try {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = secureStorage.get('auth_token')
    const response = await fetch(`${baseUrl}/audio/synthesize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        text: msg.content.replace(/[*`#\[\]()]/g, '').slice(0, 5000),
        speed: 1.0,
        format: 'wav',
      }),
    })

    if (!response.ok) throw new Error(`TTS failed: ${response.status}`)

    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    msg.audioUrl = url
    msg.audioProgress = 0
    msg.audioCurrentTime = 0
    msg.audioSpeed = 1

    // Auto-play
    nextTick(() => {
      if (msg.audioEl) {
        msg.audioEl.play().catch(() => {})
      }
    })
  } catch (err) {
    console.error('[TTS] Synthesis failed:', err)
  } finally {
    msg.ttsLoading = false
  }
}

// Custom Audio Player Controls
function setAudioRef(msg: ChatMessage, el: HTMLAudioElement | null) {
  msg.audioEl = el
}

function toggleAudioPlay(msg: ChatMessage) {
  if (!msg.audioEl) return
  if (msg.audioPlaying) {
    msg.audioEl.pause()
    msg.audioPlaying = false
  } else {
    msg.audioEl.play().catch(() => {})
    msg.audioPlaying = true
  }
}

function onAudioTimeUpdate(msg: ChatMessage) {
  if (!msg.audioEl) return
  msg.audioCurrentTime = msg.audioEl.currentTime
  if (msg.audioDuration) {
    msg.audioProgress = (msg.audioEl.currentTime / msg.audioDuration) * 100
  }
}

function onAudioLoaded(msg: ChatMessage) {
  if (!msg.audioEl) return
  msg.audioDuration = msg.audioEl.duration
}

function onAudioEnded(msg: ChatMessage) {
  msg.audioPlaying = false
  msg.audioProgress = 0
  msg.audioCurrentTime = 0
}

function seekAudio(msg: ChatMessage, event: MouseEvent) {
  if (!msg.audioEl || !msg.audioDuration) return
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const x = event.clientX - rect.left
  const pct = x / rect.width
  msg.audioEl.currentTime = pct * msg.audioDuration
}

function cycleAudioSpeed(msg: ChatMessage) {
  const speeds = [0.5, 0.75, 1, 1.25, 1.5, 2]
  const current = msg.audioSpeed || 1
  const idx = speeds.indexOf(current)
  const next = speeds[(idx + 1) % speeds.length]
  msg.audioSpeed = next
  if (msg.audioEl) msg.audioEl.playbackRate = next
}

function formatAudioTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// File Handling (Enhanced with Drag & Drop, Paste, Type Detection)
// ---------------------------------------------------------------------------
const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

function handleFileSelect(e: Event) {
  const target = e.target as HTMLInputElement
  if (!target.files) return
  addFiles(Array.from(target.files))
  target.value = ''
}

function addFiles(files: File[]) {
  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      console.warn(`[File] ${file.name} exceeds 50MB limit, skipped`)
      continue
    }

    const pf: PendingFile = { name: file.name, file, type: file.type }
    if (file.type.startsWith('image/')) {
      pf.preview = URL.createObjectURL(file)
    }
    pendingFiles.value.push(pf)
  }
}

function removePendingFile(index: number) {
  const pf = pendingFiles.value[index]
  if (pf.preview) URL.revokeObjectURL(pf.preview)
  pendingFiles.value.splice(index, 1)
}

// Drag & Drop
function onDragEnter(e: DragEvent) {
  dragCounter++
  isDragOver.value = true
}

function onDragOver(e: DragEvent) {
  // needed for drop to work
}

function onDragLeave(e: DragEvent) {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragOver.value = false
  }
}

function onDrop(e: DragEvent) {
  dragCounter = 0
  isDragOver.value = false
  if (e.dataTransfer?.files) {
    addFiles(Array.from(e.dataTransfer.files))
  }
}

// Paste from clipboard
function handlePaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return

  const files: File[] = []
  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file) files.push(file)
    }
  }
  if (files.length > 0) {
    e.preventDefault()
    addFiles(files)
  }
}

// File type utilities
function getFileCategory(type?: string): string {
  if (!type) return 'unknown'
  if (type.startsWith('image/')) return 'image'
  if (type.startsWith('audio/')) return 'audio'
  if (type.startsWith('video/')) return 'video'
  if (type === 'application/pdf') return 'pdf'
  if (type.includes('spreadsheet') || type.includes('csv')) return 'spreadsheet'
  if (type.includes('presentation') || type.includes('powerpoint')) return 'presentation'
  if (
    type.includes('document') ||
    type.includes('msword') ||
    type.includes('wordprocessing')
  )
    return 'document'
  if (type.startsWith('text/')) return 'text'
  return 'file'
}

function getFileIcon(type?: string): string {
  const cat = getFileCategory(type)
  const icons: Record<string, string> = {
    image: '🖼️',
    audio: '🎵',
    video: '🎬',
    pdf: '📕',
    spreadsheet: '📊',
    presentation: '📑',
    document: '📄',
    text: '📝',
    file: '📎',
    unknown: '📎',
  }
  return icons[cat] || '📎'
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

// ---------------------------------------------------------------------------
// Rich Content Rendering
// ---------------------------------------------------------------------------
function renderRichContent(text: string): string {
  let html = escapeHtml(text)

  // Code blocks with language label and copy button
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_, lang, code) =>
      `<div class="nr-code-wrap">` +
      `<div class="nr-code-header">` +
      `<span class="nr-code-lang">${lang || 'code'}</span>` +
      `<button class="nr-code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('.nr-code-wrap').querySelector('code').textContent).then(()=>{this.textContent='✓';setTimeout(()=>{this.textContent='${t('common.copy')}'},1500)})">${t('common.copy')}</button>` +
      `</div>` +
      `<pre class="nr-code-block"><code>${code.trim()}</code></pre>` +
      `</div>`,
  )

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="nr-code-inline">$1</code>')

  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  // Italic
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')

  // Images (inline markdown images → clickable lightbox)
  html = html.replace(
    /!\[([^\]]*)\]\(([^)]+)\)/g,
    '<div class="nr-inline-image">' +
      '<img src="$2" alt="$1" loading="lazy" />' +
      '<span class="nr-img-caption">$1</span>' +
      '</div>',
  )

  // Links
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener" class="nr-msg-link">$1</a>',
  )

  // Line breaks
  html = html.replace(/\n/g, '<br/>')

  return html
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/** Handle clicks within rendered content (e.g., image lightbox). */
function handleContentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (target.tagName === 'IMG' && target.closest('.nr-inline-image')) {
    const img = target as HTMLImageElement
    openLightbox(img.src, img.alt)
  }
}

// Lightbox
function openLightbox(src: string, alt: string) {
  lightbox.src = src
  lightbox.alt = alt
  lightbox.open = true
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function autoResize() {
  const el = textareaRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

function formatJSON(str: string): string {
  try {
    return JSON.stringify(JSON.parse(str), null, 2)
  } catch {
    return str
  }
}

// ---------------------------------------------------------------------------
// Watch locale change → update ASR language
// ---------------------------------------------------------------------------
watch(
  () => appStore.locale,
  (newLocale) => {
    if (recognition) {
      recognition.lang = newLocale === 'zh-CN' ? 'zh-CN' : 'en-US'
    }
  },
)

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
// 切换 agent 时重新加载 sessions
watch(agentId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    messages.value = []
    currentSessionId.value = null
    loadSessions()
  }
})

onMounted(() => {
  loadSessions()
  initASR()
  checkTTSAvailability()
})

onBeforeUnmount(() => {
  abortController?.abort()
  stopRecording()
  for (const pf of pendingFiles.value) {
    if (pf.preview) URL.revokeObjectURL(pf.preview)
  }
  // Revoke TTS blob URLs
  for (const msg of messages.value) {
    if (msg.audioUrl?.startsWith('blob:')) {
      URL.revokeObjectURL(msg.audioUrl)
    }
  }
})
</script>

<style scoped>
.nr-chat-page {
  display: flex;
  height: calc(100vh - 64px);
  gap: 0;
  animation: chat-enter 0.4s ease both;
  position: relative;
}

@keyframes chat-enter {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Drag & Drop Overlay */
.nr-drop-overlay {
  position: absolute;
  inset: 0;
  z-index: 100;
  background: rgba(99, 102, 241, 0.12);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 2px dashed var(--nr-primary);
  border-radius: 16px;
  pointer-events: none;
}

.nr-drop-overlay-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.nr-drop-icon {
  font-size: 48px;
  animation: drop-bounce 0.6s ease infinite alternate;
}

@keyframes drop-bounce {
  from { transform: translateY(0); }
  to { transform: translateY(-8px); }
}

.nr-drop-text {
  font-size: 18px;
  font-weight: 600;
  color: var(--nr-primary-light);
}

/* Sidebar */
.nr-chat-sidebar {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.15);
  transition: width 0.3s ease, min-width 0.3s ease;
}

.nr-chat-sidebar.collapsed {
  width: 0;
  min-width: 0;
  overflow: hidden;
  border-right: none;
}

.nr-sidebar-header {
  display: flex;
  gap: 8px;
  padding: 16px;
}

.nr-sidebar-search {
  padding: 0 16px 12px;
}

.nr-session-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.nr-session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 2px;
}

.nr-session-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.nr-session-item.active {
  background: rgba(99, 102, 241, 0.12);
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.nr-session-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nr-session-name {
  flex: 1;
  font-size: 13px;
  color: var(--nr-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nr-session-menu-btn {
  color: var(--nr-text-muted);
  font-size: 16px;
  padding: 2px 6px;
  border-radius: 4px;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
}

.nr-session-item:hover .nr-session-menu-btn {
  opacity: 1;
}

.nr-chat-page-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px; border-bottom: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg); flex-shrink: 0;
}
.nr-chat-header-left { display: flex; align-items: center; gap: 12px; }
.nr-chat-header-left .page-title { margin: 0; font-family: var(--nr-font-display); font-size: 20px; font-weight: 700; color: var(--nr-text-primary); }
.nr-chat-header-actions { display: flex; gap: 8px; }
.nr-chat-toggle-btn {
  width: 32px; height: 32px; border: 1px solid var(--nr-glass-border); border-radius: 8px;
  background: var(--nr-glass-bg); color: var(--nr-text-secondary); font-size: 18px;
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  transition: all 0.2s ease;
}
.nr-chat-toggle-btn:hover { border-color: var(--nr-glass-border-hover); color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-chat-session-select {
  display: flex; align-items: center; gap: 8px; padding: 6px 14px;
  border-radius: 10px; border: 1px solid var(--nr-glass-border);
  background: var(--nr-glass-bg); color: var(--nr-text-primary);
  font-size: 14px; font-weight: 500; cursor: pointer;
  transition: all 0.2s ease;
}
.nr-chat-session-select:hover { border-color: var(--nr-glass-border-hover); background: var(--nr-glass-bg-hover); }
.nr-chat-session-select-icon { font-size: 16px; }
.nr-chat-session-select-name { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.nr-chat-session-select-arrow { font-size: 10px; opacity: 0.5; }
.nr-glass-dropdown {
  background: var(--nr-bg-surface); backdrop-filter: blur(40px) saturate(180%);
  border: 1px solid var(--nr-glass-border); border-radius: 14px;
  padding: 6px; min-width: 220px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  display: flex; flex-direction: column; gap: 2px;
}
.nr-glass-dropdown-item {
  display: flex; align-items: center; gap: 10px; padding: 9px 12px;
  border-radius: 10px; color: var(--nr-text-secondary);
  font-size: 13px; cursor: pointer; transition: all 0.18s ease; white-space: nowrap;
}
.nr-glass-dropdown-item:hover { color: var(--nr-text-primary); background: var(--nr-glass-bg-hover); }
.nr-glass-dropdown-item.is-active { color: var(--nr-primary-light); background: rgba(99, 102, 241, 0.1); font-weight: 550; }
.nr-glass-dropdown-divider { height: 1px; background: var(--nr-glass-border); margin: 4px 8px; }

.nr-session-empty {
  text-align: center;
  color: var(--nr-text-muted);
  padding: 32px 16px;
  font-size: 13px;
}

/* Main Chat Area */
.nr-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.nr-chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.nr-chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--nr-text-tertiary);
  gap: 8px;
}

.nr-chat-empty-icon {
  font-size: 48px;
  margin-bottom: 8px;
}

.nr-chat-empty h3 {
  font-family: var(--nr-font-display);
  font-size: 20px;
  color: var(--nr-text-primary);
  margin: 0;
}

.nr-chat-empty p {
  font-size: 14px;
  margin: 0;
}

/* Message Bubbles */
.nr-msg {
  display: flex;
  gap: 12px;
  max-width: 85%;
  animation: msg-in 0.3s ease both;
}

@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.nr-msg--user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.nr-msg--assistant {
  align-self: flex-start;
}

.nr-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
  background: rgba(255, 255, 255, 0.04);
}

.nr-msg-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.nr-msg--user .nr-msg-body {
  align-items: flex-end;
}

.nr-msg-content {
  padding: 12px 16px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.nr-msg--user .nr-msg-content {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.25), rgba(139, 92, 246, 0.2));
  border: 1px solid rgba(99, 102, 241, 0.2);
  color: var(--nr-text-primary);
}

.nr-msg--assistant .nr-msg-content {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  color: var(--nr-text-primary);
}

/* Reasoning Block */
.nr-msg-reasoning {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
  overflow: hidden;
}

.nr-reasoning-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  color: var(--nr-text-secondary);
  font-weight: 500;
  transition: background 0.2s;
}

.nr-reasoning-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.nr-reasoning-toggle {
  font-size: 14px;
  color: var(--nr-text-muted);
}

.nr-reasoning-content {
  padding: 8px 12px 12px;
  font-size: 13px;
  color: var(--nr-text-tertiary);
  line-height: 1.5;
  white-space: pre-wrap;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

/* Tool Call Block */
.nr-msg-tool-call {
  background: rgba(245, 158, 11, 0.06);
  border: 1px solid rgba(245, 158, 11, 0.15);
  border-radius: 10px;
  padding: 10px 14px;
}

.nr-tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.nr-tool-header:hover {
  opacity: 0.8;
}

.nr-tool-toggle {
  margin-left: auto;
  font-size: 14px;
  color: var(--nr-text-muted);
}

.nr-tool-icon {
  font-size: 16px;
}

.nr-tool-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-tool-args {
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  max-height: 120px;
}

.nr-tool-result {
  margin-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 8px;
}

.nr-tool-result-header {
  font-size: 11px;
  color: var(--nr-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.nr-tool-result-content {
  font-size: 12px;
  color: var(--nr-text-secondary);
  background: rgba(0, 0, 0, 0.15);
  border-radius: 6px;
  padding: 8px 10px;
  margin: 0;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  max-height: 120px;
}

/* Enhanced Attachments */
.nr-msg-attachments {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.nr-attachment-thumb {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  font-size: 12px;
  color: var(--nr-text-secondary);
  transition: background 0.2s, border-color 0.2s;
}

.nr-attachment-thumb:hover {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.12);
}

.nr-attachment--image {
  cursor: pointer;
}

.nr-attachment-img {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 8px;
}

.nr-attachment-file-icon {
  font-size: 24px;
}

.nr-attachment-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nr-attachment-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.nr-attachment-size {
  font-size: 10px;
  color: var(--nr-text-muted);
}

/* Custom Audio Player */
.nr-msg-audio-player {
  margin-top: 4px;
}

.nr-audio-player {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: rgba(99, 102, 241, 0.08);
  border: 1px solid rgba(99, 102, 241, 0.15);
  border-radius: 12px;
  min-width: 280px;
}

.nr-audio-play-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: none;
  background: var(--nr-primary);
  color: var(--nr-text-primary);
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.15s, background 0.2s;
}

.nr-audio-play-btn:hover {
  transform: scale(1.08);
  background: var(--nr-primary-light);
}

.nr-audio-progress-wrap {
  flex: 1;
  cursor: pointer;
  padding: 4px 0;
}

.nr-audio-progress-bar {
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.nr-audio-progress-fill {
  height: 100%;
  background: var(--nr-primary);
  border-radius: 2px;
  transition: width 0.1s linear;
}

.nr-audio-time {
  font-size: 11px;
  color: var(--nr-text-muted);
  font-family: var(--nr-font-mono);
  min-width: 36px;
  text-align: right;
}

.nr-audio-speed-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  color: var(--nr-text-secondary);
  cursor: pointer;
  transition: background 0.2s;
}

.nr-audio-speed-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

/* TTS Action Button */
.nr-msg-tts-action {
  margin-top: 4px;
}

.nr-tts-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: var(--nr-text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, border-color 0.2s;
}

.nr-tts-btn:hover {
  background: rgba(99, 102, 241, 0.1);
  border-color: rgba(99, 102, 241, 0.2);
}

.nr-tts-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Streaming indicator */
.nr-msg-streaming {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.nr-typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--nr-primary-light);
  animation: typing 1.4s infinite;
}

.nr-typing-dot:nth-child(2) { animation-delay: 0.2s; }
.nr-typing-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-4px); }
}

/* Input Area */
.nr-chat-input-area {
  padding: 12px 24px 20px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
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
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
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

/* ASR Recording Bar */
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

.nr-chat-textarea {
  flex: 1;
  resize: none;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  padding: 10px 14px;
  color: var(--nr-text-primary);
  font-size: 14px;
  font-family: var(--nr-font-body);
  line-height: 1.5;
  outline: none;
  transition: border-color 0.25s;
  max-height: 160px;
}

.nr-chat-textarea:focus {
  border-color: var(--nr-primary);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.nr-chat-textarea::placeholder {
  color: var(--nr-text-muted);
}

/* Rich Content: Code Blocks */
:deep(.nr-code-wrap) {
  margin: 10px 0;
  border-radius: 10px;
  overflow: hidden;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

:deep(.nr-code-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

:deep(.nr-code-lang) {
  font-size: 11px;
  color: var(--nr-primary-light);
  font-family: var(--nr-font-mono);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

:deep(.nr-code-copy-btn) {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 11px;
  color: var(--nr-text-muted);
  cursor: pointer;
  transition: background 0.2s, color 0.2s;
}

:deep(.nr-code-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.1);
  color: var(--nr-text-primary);
}

:deep(.nr-code-block) {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 10px 14px;
  overflow-x: auto;
  font-family: var(--nr-font-mono);
  font-size: 12px;
  line-height: 1.6;
  margin: 0;
}

:deep(.nr-code-inline) {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  padding: 1px 5px;
  font-family: var(--nr-font-mono);
  font-size: 0.9em;
  color: var(--nr-accent-secondary);
}

/* Rich Content: Inline Images */
:deep(.nr-inline-image) {
  margin: 10px 0;
  display: inline-block;
  max-width: 100%;
  cursor: pointer;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(255, 255, 255, 0.08);
  transition: border-color 0.2s;
}

:deep(.nr-inline-image:hover) {
  border-color: rgba(99, 102, 241, 0.3);
}

:deep(.nr-inline-image img) {
  display: block;
  max-width: 100%;
  max-height: 400px;
  object-fit: contain;
}

:deep(.nr-img-caption) {
  display: block;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--nr-text-muted);
  background: rgba(0, 0, 0, 0.15);
  text-align: center;
}

/* Message Links */
:deep(.nr-msg-link) {
  color: var(--nr-primary-light);
  text-decoration: underline;
  text-underline-offset: 2px;
}

:deep(.nr-msg-link:hover) {
  color: var(--nr-accent);
}

/* Lightbox */
.nr-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9999;
  background: rgba(0, 0, 0, 0.85);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}

.nr-lightbox-content {
  max-width: 90vw;
  max-height: 85vh;
  cursor: default;
}

.nr-lightbox-content img {
  max-width: 90vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.nr-lightbox-caption {
  text-align: center;
  padding: 12px;
  color: rgba(255, 255, 255, 0.7);
  font-size: 13px;
}

.nr-lightbox-close {
  position: absolute;
  top: 20px;
  right: 24px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--nr-glass-border);
  background: var(--nr-bg-overlay);
  color: var(--nr-text-primary);
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s;
}

.nr-lightbox-close:hover {
  background: rgba(255, 255, 255, 0.1);
}

/* Transitions */
.fade-scale-enter-active,
.fade-scale-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.fade-scale-enter-from,
.fade-scale-leave-to {
  opacity: 0;
  transform: scale(0.95);
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

/* Main layout mode: fill parent container instead of viewport */
.nr-chat-page--main {
  height: calc(100vh - var(--nr-header-h) - 48px);
  border-radius: 12px;
}

/* Right-side conversation history panel (main layout mode) */
.nr-chat-history-panel {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-left: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.15);
}

.nr-history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}

.nr-history-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--nr-text-primary);
}

.nr-history-search {
  padding: 0 16px 12px;
}
</style>
