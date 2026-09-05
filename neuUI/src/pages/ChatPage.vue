<template>
  <div class="chat-page">
    <!-- 顶部栏 -->
    <div class="chat-topbar glass-effect">
      <a-button type="text" class="sidebar-toggle" @click="sidebarOpen = !sidebarOpen">
        <MenuFoldOutlined v-if="sidebarOpen" />
        <MenuUnfoldOutlined v-else />
      </a-button>

      <!-- 当前 Agent 名称显示 -->
      <div class="agent-name-badge">
        <a-avatar :size="28" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}">
          {{ (currentAgentName || 'A').charAt(0).toUpperCase() }}
        </a-avatar>
        <span class="agent-name-label">{{ currentAgentName || '未选择' }}</span>
        <div v-if="activeModel" class="model-dot" />
        <span v-if="activeModel" class="model-badge">{{ activeModel }}</span>
      </div>

      <div v-if="convId" class="conv-title-badge">{{ currentConvTitle }}</div>
      <div class="topbar-spacer" />
      <a-button class="new-chat-btn" @click="startNew()">
        <PlusOutlined class="new-chat-icon" />
        <span class="new-chat-text">新对话</span>
      </a-button>
    </div>

    <div class="chat-body">
      <!-- 左侧历史会话侧栏 -->
      <Transition name="slide">
        <aside v-if="sidebarOpen" class="chat-sidebar">
          <div class="sidebar-header">
            <span class="sidebar-title">历史对话</span>
            <a-button type="text" size="small" @click="sidebarOpen = false"><CloseOutlined /></a-button>
          </div>
          <div class="conv-list">
            <div v-if="convs.length===0 && !convLoading" class="sidebar-empty">暂无历史对话</div>
            <div v-for="c in convs" :key="c.id" class="conv-item" :class="{active:c.id===convId}" @click="selectConv(c)">
              <MessageOutlined class="conv-icon" />
              <template v-if="renamingConvId === c.id">
                <a-input v-model:value="renameTitle" size="small" class="rename-input" @pressEnter="confirmRename" @blur="confirmRename" @keydown.escape="cancelRename" @click.stop />
              </template>
              <span v-else class="conv-text">{{ c.title || '新对话' }}</span>
              <div class="conv-actions">
                <a-button type="text" size="small" class="conv-rename" @click.stop="startRename(c)"><EditOutlined /></a-button>
                <a-popconfirm title="确定清空该 Agent 的所有对话历史吗？此操作不可恢复。" @confirm="delConv(c.id)" @click.stop>
                  <a-button type="text" size="small" danger class="conv-del"><DeleteOutlined /></a-button>
                </a-popconfirm>
              </div>
            </div>
          </div>
        </aside>
      </Transition>

      <!-- 聊天主区 -->
      <div class="chat-main-area" ref="msgContainer">
        <!-- 空状态 -->
        <div v-if="messages.length === 0 && !streaming" class="chat-empty">
          <div class="empty-avatar">
            <RobotOutlined />
          </div>
          <h3>开始对话</h3>
          <p>输入文字、上传文件或使用语音与 Agent 交流</p>
          <div class="empty-tips">
            <div class="tip"><PictureOutlined /> 支持图片识别</div>
            <div class="tip"><AudioOutlined /> 支持语音输入</div>
            <div class="tip"><FileTextOutlined /> 支持文档分析</div>
            <div class="tip"><VideoCameraOutlined /> 支持视频理解</div>
          </div>
        </div>

        <!-- 消息列表 -->
        <div v-for="(m,i) in messages" :key="i" class="msg-row" :class="m.role">
          <div class="msg-avatar" v-if="m.role==='assistant'">
            <a-avatar :size="36" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}">AI</a-avatar>
          </div>
          <div class="msg-body">
            <div class="msg-bubble glass-effect" :class="m.role">
              <!-- 附件预览 -->
              <div v-if="m.attachments?.length" class="msg-attachments">
                <div v-for="(att, ai) in m.attachments" :key="ai" class="att-item">
                  <img v-if="att.type==='image'" :src="att.preview" class="att-img" />
                  <div v-else-if="att.type==='audio'" class="voice-message" @click="toggleAudio(i, att)">
                    <div class="voice-icon">
                      <template v-if="playingAudioIndex === i">
                        <span class="voice-wave voice-wave-1"></span>
                        <span class="voice-wave voice-wave-2"></span>
                        <span class="voice-wave voice-wave-3"></span>
                      </template>
                      <template v-else>
                        <span class="voice-static"><AudioOutlined /></span>
                      </template>
                    </div>
                    <div class="voice-bar">
                      <div class="voice-progress" :style="{ width: playingAudioIndex === i && audioDuration > 0 ? (audioProgress / audioDuration * 100 + '%') : '0%' }"></div>
                    </div>
                    <span class="voice-duration">
                      {{ playingAudioIndex === i ? formatDuration(audioProgress) : (att.duration ? formatDuration(att.duration) : '00:00') }}
                    </span>
                  </div>
                  <div v-else-if="att.type==='video'" class="att-file"><VideoCameraOutlined /> {{ att.name }}</div>
                  <div v-else class="att-file"><FileOutlined /> {{ att.name }}</div>
                  <a-button type="text" size="small" class="att-remove" @click="m.attachments?.splice(ai,1)"><CloseOutlined /></a-button>
                </div>
              </div>
              <!-- 思考过程 -->
              <div v-if="m.role==='assistant' && m.reasoning_content && agentShowThinking" class="msg-reasoning">
                <div class="reasoning-header" @click="m._reasoningOpen = !m._reasoningOpen">
                  <BulbOutlined class="reasoning-icon" />
                  <span>思考过程</span>
                  <span class="reasoning-toggle">{{ m._reasoningOpen !== false ? '收起' : '展开' }}</span>
                </div>
                <div v-show="m._reasoningOpen !== false" class="reasoning-body">{{ m.reasoning_content }}</div>
              </div>
              <!-- 工具调用 -->
              <div v-if="m.role==='assistant' && m.tool_calls?.length && agentShowToolMessages" class="msg-tool-calls">
                <div v-for="(tc, ti) in m.tool_calls" :key="ti" class="tool-call-item">
                  <div class="tool-call-header">
                    <ToolOutlined class="tool-icon" />
                    <span class="tool-name">{{ tc.tool }}</span>
                  </div>
                  <div v-if="tc.input" class="tool-input"><span class="tool-label">输入：</span>{{ JSON.stringify(tc.input, null, 2) }}</div>
                  <div v-if="tc.output !== undefined" class="tool-output"><span class="tool-label">输出：</span>{{ typeof tc.output === 'string' ? tc.output : JSON.stringify(tc.output, null, 2) }}</div>
                  <div v-if="tc.error" class="tool-error"><span class="tool-label">错误：</span>{{ tc.error }}</div>
                </div>
              </div>
              <div class="msg-content">{{ m.content }}</div>
              <div class="msg-time">{{ formatTime(m.timestamp) }}</div>
            </div>
          </div>
          <div class="msg-avatar" v-if="m.role==='user'">
            <a-avatar :size="36" style="background:linear-gradient(135deg,#8b5cf6,#ec4899)">{{ usernameC }}</a-avatar>
          </div>
        </div>

        <!-- 流式回复 -->
        <div v-if="streaming" class="msg-row assistant">
          <div class="msg-avatar">
            <a-avatar :size="36" :style="{background:'linear-gradient(135deg,#3b82f6,#8b5cf6)'}">AI</a-avatar>
          </div>
          <div class="msg-bubble glass-effect streaming">
            <div class="msg-content">{{ currentReply }}<span class="cursor">|</span></div>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="chat-input-wrapper">
          <div v-if="recording" class="recording-bar">
            <div class="rec-pulse" />
            <span>正在录音... {{ recordingTime }}s</span>
            <a-button type="primary" danger size="small" @click="stopRecording">停止</a-button>
          </div>

          <div class="chat-input-bar">
            <div class="input-toolbar">
              <a-upload :before-upload="handleFileUpload" :show-upload-list="false" accept="image/*" multiple>
                <a-tooltip title="上传图片"><a-button type="text" size="small"><PictureOutlined /></a-button></a-tooltip>
              </a-upload>
              <a-upload :before-upload="handleFileUpload" :show-upload-list="false" accept=".pdf,.doc,.docx,.txt,.md,.csv,.xlsx,.pptx" multiple>
                <a-tooltip title="上传文档"><a-button type="text" size="small"><FileTextOutlined /></a-button></a-tooltip>
              </a-upload>
              <a-upload :before-upload="handleFileUpload" :show-upload-list="false" accept="audio/*">
                <a-tooltip title="上传音频"><a-button type="text" size="small"><AudioOutlined /></a-button></a-tooltip>
              </a-upload>
              <a-upload :before-upload="handleFileUpload" :show-upload-list="false" accept="video/*">
                <a-tooltip title="上传视频"><a-button type="text" size="small"><VideoCameraOutlined /></a-button></a-tooltip>
              </a-upload>
              <a-divider type="vertical" />
              <a-tooltip :title="recording ? '停止录音' : '语音输入'">
                <a-button type="text" size="small" :class="{recording: recording}" @click="toggleRecording">
                  <AudioMutedOutlined v-if="!recording" /><PauseCircleOutlined v-else />
                </a-button>
              </a-tooltip>
            </div>
            <div class="input-row">
              <a-textarea ref="textareaRef" v-model:value="inputText" placeholder="输入消息... (Enter 发送，Shift+Enter 换行)" :auto-size="{ minRows:1, maxRows:4 }" :disabled="streaming" @pressEnter="onKeyDown" />
              <a-button type="primary" size="large" :loading="streaming" @click="handleSend" :disabled="!inputText.trim() && !pendingAttachments.length" class="send-btn"><SendOutlined /></a-button>
            </div>
            <Transition name="fade">
              <div v-if="pendingAttachments.length" class="upload-preview-bar">
                <div v-for="(f,i) in pendingAttachments" :key="i" class="up-item">
                  <img v-if="f.type==='image'" :src="f.preview" class="up-thumb" />
                  <FileOutlined v-else class="up-icon" />
                  <span class="up-name">{{ f.name }}</span>
                  <a-button type="text" size="small" @click="pendingAttachments.splice(i,1)"><CloseOutlined /></a-button>
                </div>
              </div>
            </Transition>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { modelAPI } from '@/api/modules/models'
import { sendMessage, sendMessageStream, getConversations, getMessages, deleteConversation, uploadMedia, renameConversation } from '@/api/modules/chat'
import type { SendMessageRequest } from '@/api/types/ChatMessage'
import {
  MenuFoldOutlined, MenuUnfoldOutlined, PlusOutlined, CloseOutlined,
  MessageOutlined, DeleteOutlined, SendOutlined,
  PictureOutlined, AudioOutlined, VideoCameraOutlined, FileOutlined,
  FileTextOutlined, RobotOutlined, AudioMutedOutlined, PauseCircleOutlined,
  EditOutlined, BulbOutlined, ToolOutlined,
} from '@ant-design/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const agentStore = useAgentStore()

const sidebarOpen = ref(true)
const selectedAgentId = computed(() => (route.params.agentId as string) || agentStore.currentAgentId || '')
const currentAgentName = computed(() => agentStore.currentAgent?.name || '')
const usernameC = computed(() => (authStore.currentUser?.username || 'U')[0].toUpperCase())

// 路由参数变化时（Agent 切换器通过 router.push 触发）：加载配置 + 会话 + 重置对话
watch(() => route.params.agentId, (newAgentId) => {
  if (newAgentId && typeof newAgentId === 'string') {
    loadAgentDisplayConfig(newAgentId)
    loadConversations()
    startNew()
  }
}, { immediate: false })

// 其他组件直接修改 store 时（无路由跳转场景）：同步路由
watch(() => agentStore.currentAgentId, (newId) => {
  const routeAgentId = route.params.agentId as string
  if (newId && newId !== routeAgentId) { router.push(`/agent/${newId}/chat`) }
}, { immediate: false })

interface Cnv { id: string; title?: string }
const convs = ref<Cnv[]>([])
const convId = ref('')
const convLoading = ref(false)
const currentConvTitle = computed(() => convs.value.find(c => c.id === convId.value)?.title || '')
const renamingConvId = ref('')
const renameTitle = ref('')

function startRename(c: Cnv) { renamingConvId.value = c.id; renameTitle.value = c.title || '' }
async function confirmRename() {
  if (!renameTitle.value.trim() || !renamingConvId.value) { renamingConvId.value = ''; return }
  try {
    const agentId = selectedAgentId.value || 'default'
    await renameConversation(agentId, renamingConvId.value, renameTitle.value.trim())
    const item = convs.value.find(c => c.id === renamingConvId.value)
    if (item) item.title = renameTitle.value.trim()
  } catch { /* ignore */ }
  renamingConvId.value = ''
}
function cancelRename() { renamingConvId.value = '' }

interface Attachment { type: string; name: string; preview?: string; _file?: File; url?: string }
interface ToolCallInfo { tool: string; input?: unknown; output?: unknown; error?: string }
interface Msg { role: 'user'|'assistant'; content: string; timestamp: number; attachments?: Attachment[]; reasoning_content?: string; tool_calls?: ToolCallInfo[] }
interface RawConversation { id?: string; conversation_id?: string; title?: string }
interface RawMessage { role?: string; content?: string; timestamp?: number | string; reasoning_content?: string; tool_calls?: RawToolMessage[] }
interface RawToolMessage { type?: string; tool_name?: string; tool?: string; params?: unknown; input?: unknown; result?: unknown; output?: unknown; success?: boolean; error?: string }
const messages = ref<Msg[]>([])
const msgContainer = ref<HTMLElement | null>(null)
const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const streaming = ref(false)
const currentReply = ref('')
const pendingAttachments = ref<Attachment[]>([])
const recording = ref(false)
const recordingTime = ref(0)
let recordingTimer: ReturnType<typeof setInterval> | null = null

const audioRef = ref<HTMLAudioElement | null>(null)
const playingAudioIndex = ref<number | null>(null)
const audioProgress = ref<number>(0)
const audioDuration = ref<number>(0)
let audioInterval: ReturnType<typeof setInterval> | null = null

function startNew() { convId.value = ''; messages.value = []; pendingAttachments.value = []; clearInput() }

const agentShowThinking = ref(true)
const agentShowToolMessages = ref(true)

async function loadAgentDisplayConfig(agentId: string) {
  try {
    const cfg = await agentStore.getAgentConfig(agentId)
    if (cfg) {
      agentShowThinking.value = cfg.showThinking !== false
      agentShowToolMessages.value = cfg.showToolMessages !== false
    }
  } catch { /* default true */ }
}

async function loadConversations() {
  convLoading.value = true
  try {
    const agentId = selectedAgentId.value || agentStore.agents[0]?.id || ''
    if (!agentId) { convs.value = []; return }
    const data = await getConversations(agentId)
    // 始终更新列表，避免切换到无会话的 Agent 时残留旧数据
    convs.value = (data || []).map((c: RawConversation | unknown) => { const r = c as RawConversation; return { id: r.id || r.conversation_id || '0', title: r.title || '新对话' } })
  } catch {
    convs.value = [] // API 失败时清空，避免显示错误 Agent 的会话
  } finally { convLoading.value = false }
}
async function selectConv(c: Cnv) {
  convId.value = c.id
  const agentId = selectedAgentId.value || agentStore.agents[0]?.id || ''
  await loadAgentDisplayConfig(agentId)
  try {
    const msgs = await getMessages(agentId, 50, 0, c.id)
    if (msgs?.length) {
      messages.value = msgs.map((m: RawMessage | unknown) => {
        const r = m as RawMessage
        return {
          role: (r.role === 'user' ? 'user' : 'assistant') as 'user'|'assistant',
          content: r.content || '',
          timestamp: typeof r.timestamp === 'number' ? r.timestamp : (r.timestamp ? new Date(r.timestamp).getTime() : Date.now()),
          reasoning_content: r.reasoning_content || undefined,
          tool_calls: mergeToolCalls(r.tool_calls || []),
        }
      })
      return
    }
  } catch { /* fallback */ }
  messages.value = [{ role: 'assistant', content: '已加载对话：' + (c.title||''), timestamp: Date.now() }]
}
/** 合并 tool_call + tool_result 配对为单条记录（用于历史消息和 API 响应） */
function mergeToolCalls(toolMsgs: RawToolMessage[]): ToolCallInfo[] {
  if (!toolMsgs?.length) return []
  const merged: ToolCallInfo[] = []
  const resultMap: Record<string, { output?: unknown; error?: string }> = {}
  for (const tm of toolMsgs) {
    const name = tm.tool_name || tm.tool || 'unknown'
    if (tm.type === 'tool_result') {
      resultMap[name] = { output: tm.result || tm.output, error: tm.success === false ? '执行失败' : undefined }
    }
  }
  for (const tm of toolMsgs) {
    const name = tm.tool_name || tm.tool || 'unknown'
    if (tm.type === 'tool_call') {
      const resEntry = resultMap[name] || {}
      merged.push({ tool: name, input: tm.params || tm.input, output: resEntry.output, error: tm.error || resEntry.error })
    }
  }
  // 补充没有配对 call 的独立 result
  for (const tm of toolMsgs) {
    const name = tm.tool_name || tm.tool || 'unknown'
    if (tm.type === 'tool_result' && !toolMsgs.some(t => (t.tool_name || t.tool) === name && t.type === 'tool_call')) {
      merged.push({ tool: name, output: tm.result || tm.output, error: tm.success === false ? '执行失败' : undefined })
    }
  }
  return merged
}

async function delConv(id: string) {
  const agentId = selectedAgentId.value || ''
  try { await deleteConversation(agentId, id) } catch { /* ignore */ }
  convs.value = convs.value.filter(c=>c.id!==id)
  if (convId.value === id) startNew()
}

function handleFileUpload(file: File): boolean {
  const isImage = file.type.startsWith('image/')
  const type = isImage ? 'image' : file.type.startsWith('audio/') ? 'audio' : file.type.startsWith('video/') ? 'video' : 'document'
  const att: Attachment = { type, name: file.name, _file: file }
  if (isImage) { const reader = new FileReader(); reader.onload = (e) => { att.preview = e.target?.result as string }; reader.readAsDataURL(file) }
  pendingAttachments.value.push(att)
  message.success(`已添加: ${file.name}`)
  return false
}

async function toggleRecording() {
  if (recording.value) { stopRecording(); return }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    recording.value = true; recordingTime.value = 0
    recordingTimer = setInterval(() => recordingTime.value++, 1000)
    const w = window as unknown as Record<string, unknown>
    const SpeechRecognition = (w.SpeechRecognition || w.webkitSpeechRecognition) as (new () => { lang: string; interimResults: boolean; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; start: () => void }) | undefined
    if (SpeechRecognition) {
      const recognition = new SpeechRecognition(); recognition.lang = 'zh-CN'; recognition.interimResults = true
      recognition.onresult = (e) => { inputText.value = Array.from(e.results).map((r) => r[0].transcript).join('') }
      recognition.onend = () => { recording.value = false; clearInterval(recordingTimer); stream.getTracks().forEach(t => t.stop()) }
      recognition.start()
    } else {
      setTimeout(() => { inputText.value = '这是模拟语音输入的结果。'; stopRecording() }, 3000)
    }
  } catch (e: unknown) { const err = e as Error; message.error('无法访问麦克风: ' + (err.message || '权限被拒绝')) }
}
function stopRecording() { recording.value = false; clearInterval(recordingTimer); recordingTime.value = 0 }

function toggleAudio(index: number, attachment: Attachment) {
  if (playingAudioIndex.value === index) { pauseAudio(); return }
  playAudio(index, attachment)
}
function playAudio(index: number, attachment: Attachment) {
  pauseAudio()
  let audioUrl: string | null = null
  if (attachment._file) audioUrl = URL.createObjectURL(attachment._file)
  else if (attachment.url) audioUrl = attachment.url
  else if (attachment.preview) audioUrl = attachment.preview
  if (!audioUrl) { message.error('无法播放此音频'); return }
  if (!audioRef.value) audioRef.value = new Audio(audioUrl)
  else audioRef.value.src = audioUrl
  audioRef.value.onloadedmetadata = () => { audioDuration.value = audioRef.value?.duration || 0 }
  audioRef.value.onended = () => { pauseAudio() }
  audioRef.value.onerror = () => { message.error('音频播放失败'); pauseAudio() }
  audioRef.value.play(); playingAudioIndex.value = index; audioProgress.value = 0
  audioInterval = setInterval(() => { if (audioRef.value) audioProgress.value = audioRef.value.currentTime }, 100)
}
function pauseAudio() {
  if (audioRef.value) audioRef.value.pause()
  if (audioInterval) { clearInterval(audioInterval); audioInterval = null }
  playingAudioIndex.value = null; audioProgress.value = 0
}
function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60); const secs = Math.floor(seconds % 60)
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

function onKeyDown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }
function clearInput() { inputText.value = ''; if (textareaRef.value) textareaRef.value.value = ''; nextTick(() => { inputText.value = '' }) }

const activeModel = ref('')
const activeProvider = ref('')

async function handleSend() {
  const txt = inputText.value.trim()
  if ((!txt && !pendingAttachments.value.length) || streaming.value) return
  const content = txt || (pendingAttachments.value.length ? '请分析以下文件' : '')
  clearInput()
  const atts = [...pendingAttachments.value]; pendingAttachments.value = []
  const agentId = selectedAgentId.value || 'default'
  let uploadedMediaIds: string[] = []
  if (atts.length) {
    const contentTypes = atts.map(a => a.type)
    try {
      const res = await modelAPI.autoDetect({ content_types: contentTypes, message_text: txt || undefined, auto_switch: true })
      if (res?.success || res?.code === 0) {
        const d = res.data; activeModel.value = d.model; activeProvider.value = d.provider_name || d.provider_id || ''
        message.info(`${atts.map(a => ({image:'📷',audio:'🎵',video:'🎬',document:'📄'}[a.type]||a.type)).join('+')} 内容 → 自动切换至 ${d.model}` + (d.warning ? `（${d.warning}）` : ''))
      }
    } catch { /* continue */ }
    for (const att of atts) {
      if (att._file) { try { const fd = new FormData(); fd.append('file', att._file); fd.append('agent_id', agentId || 'default'); const uploaded = await uploadMedia(fd); if (uploaded?.id) uploadedMediaIds.push(uploaded.id) } catch { /* skip */ } }
    }
  }
  messages.value.push({ role: 'user', content, timestamp: Date.now(), attachments: atts.length ? atts : undefined })
  const agentConfig = await agentStore.getAgentConfig(agentId).catch(() => null)
  const enableStreaming = agentConfig?.enableStreaming ?? false
  const showThinking = agentConfig?.showThinking ?? true
  const showToolMessages = agentConfig?.showToolMessages ?? true
  streaming.value = true; currentReply.value = ''
  try {
    if (enableStreaming) {
      let assistantMsg: Msg | null = null; let reasoningContent = ''; let toolCalls: ToolCallInfo[] = []
      const callbacks = {
        onReasoning: (content: string) => { if (!showThinking) return; reasoningContent += content; if (assistantMsg) assistantMsg.reasoning_content = reasoningContent },
        onToolCall: (toolName: string, params: unknown) => { if (!showToolMessages) return; toolCalls.push({ tool: toolName, input: params, output: undefined, error: undefined }); if (assistantMsg) assistantMsg.tool_calls = [...toolCalls] },
        onToolResult: (toolName: string, result: string, success: boolean) => { if (!showToolMessages) return; const tc = toolCalls.find(t => t.tool === toolName && t.output === undefined); if (tc) { tc.output = result; tc.error = !success ? '执行失败' : undefined }; if (assistantMsg) assistantMsg.tool_calls = [...toolCalls] },
        onMessage: (content: string) => { currentReply.value += content; if (!assistantMsg) { assistantMsg = { role: 'assistant', content: '', timestamp: Date.now(), reasoning_content: showThinking ? reasoningContent : undefined, tool_calls: showToolMessages ? toolCalls : [] }; messages.value.push(assistantMsg) }; assistantMsg.content += content; nextTick().then(() => scrollBottom()) },
        onDone: (reply: string) => {
          if (!assistantMsg) { assistantMsg = { role: 'assistant', content: reply, timestamp: Date.now(), reasoning_content: showThinking ? reasoningContent : undefined, tool_calls: showToolMessages ? toolCalls : [] }; messages.value.push(assistantMsg) }
          else { assistantMsg.reasoning_content = showThinking ? reasoningContent : undefined; assistantMsg.tool_calls = showToolMessages ? toolCalls : [] }
          if (!convId.value) { const newSessionId = `session_${Date.now()}`; convId.value = newSessionId; convs.value = [{ id: newSessionId, title: content.substring(0, 50) + (content.length > 50 ? "..." : "") }, ...convs.value] }
          else { const idx = convs.value.findIndex(c => c.id === convId.value); if (idx >= 0) { const [item] = convs.value.splice(idx, 1); convs.value.unshift(item) } }
          streaming.value = false; currentReply.value = ''; nextTick().then(() => scrollBottom())
        },
        onError: (error: string) => { console.error('[ChatPage] 流式对话错误:', error); message.error('流式对话失败: ' + error); messages.value.push({ role: 'assistant', content: '抱歉，对话服务暂时不可用，请稍后重试。\n错误详情: ' + error, timestamp: Date.now() }); streaming.value = false; currentReply.value = '' },
      }
      await sendMessageStream(agentId, content, convId.value || undefined, callbacks)
    } else {
      const requestParams: SendMessageRequest = { message: content, agent_id: agentId, session_id: convId.value || undefined, stream: false, save_memory: true, ...(uploadedMediaIds.length ? { attachments: uploadedMediaIds.map(id => ({ filename: id, content_type: undefined, size: undefined })) } : {}) }
      const res = await sendMessage(requestParams)
      const reply = res?.reply || res?.data?.reply || ''
      const audioInfo = res?.audio || res?.data?.audio
      // 更新会话到侧栏顶部
      const sid = res?.session_id || res?.data?.session_id
      if (sid) {
        if (!convId.value) {
          convId.value = sid
          convs.value = [{ id: sid, title: content.substring(0, 50) + (content.length > 50 ? "..." : "") }, ...convs.value]
        } else {
          // 已有会话：移到顶部，更新标题（仅首次用户消息）
          const idx = convs.value.findIndex(c => c.id === sid)
          if (idx >= 0) {
            const [item] = convs.value.splice(idx, 1)
            convs.value.unshift(item)
          }
        }
      }
      const toolMsgs = res?.tool_messages || res?.data?.tool_messages || []
      const mergedToolCalls = mergeToolCalls(toolMsgs)
      if (toolMsgs.length > 0) {
        console.log('[ChatPage] 后端返回 tool_messages:', toolMsgs.length, '条 → 合并后 tool_calls:', mergedToolCalls.length)
      }
      const newMessage: Msg = { role: 'assistant', content: reply, timestamp: Date.now(), reasoning_content: showThinking ? (res?.reasoning || res?.data?.reasoning || undefined) : undefined, tool_calls: showToolMessages ? mergedToolCalls : [] }
      if (audioInfo) { newMessage.attachments = [{ type: 'audio', name: audioInfo.filename || 'voice.wav', url: audioInfo.url, duration: 0 }] }
      messages.value.push(newMessage)
      if (audioInfo?.url) { await nextTick(); toggleAudio(messages.value.length - 1, newMessage.attachments[0]) }
    }
  } catch (e: unknown) { const err = e as { response?: { data?: { message?: string } }; message?: string }; const errMsg = err?.response?.data?.message || err?.message || '网络错误'; console.error('[ChatPage] 对话请求失败:', e); message.error('对话请求失败: ' + errMsg); messages.value.push({ role: 'assistant', content: '抱歉，对话服务暂时不可用，请稍后重试。\n错误详情: ' + errMsg, timestamp: Date.now() }) }
  finally { if (!enableStreaming) { currentReply.value = ''; streaming.value = false; await nextTick(); scrollBottom() } }
}

function scrollBottom() {
  nextTick(() => {
    const el = msgContainer.value
    if (el) el.scrollTop = el.scrollHeight
  })
}
function formatTime(ts: number) { return new Date(ts).toLocaleTimeString('zh-CN') }

// 自动滚动：监听消息数量变化和流式内容变化
watch(
  () => messages.value.length,
  () => scrollBottom()
)
watch(
  () => currentReply.value,
  () => { if (streaming.value) scrollBottom() }
)

onMounted(async () => {
  streaming.value = false; currentReply.value = ''
  if (!agentStore.agents.length) await agentStore.loadAgents()
  if (agentStore.agents.length && !selectedAgentId.value) { agentStore.setCurrentAgent(agentStore.agents[0].id) }
  if (selectedAgentId.value) { loadAgentDisplayConfig(selectedAgentId.value) }
  loadConversations()
  try { const res = await modelAPI.getCurrent(); if (res?.success || res?.code === 0) { activeModel.value = res.data?.model || ''; activeProvider.value = res.data?.provider_name || '' } } catch { /* ignore */ }
})

onUnmounted(() => { streaming.value = false; currentReply.value = ''; pauseAudio(); if (audioRef.value) { audioRef.value.pause(); audioRef.value = null } })
</script>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: calc(100vh - 130px); min-height: 500px; max-height: 100vh; }

/* ===== 顶部栏 ===== */
.chat-topbar { display: flex; align-items: center; gap: 10px; padding: 6px 14px; border-radius: 14px; margin-bottom: 10px; flex-shrink: 0; min-height: 52px; border: 1px solid rgba(255,255,255,0.06); }
.sidebar-toggle { color: rgba(255,255,255,0.45) !important; font-size: 1rem; transition: color 0.2s; }
.sidebar-toggle:hover { color: rgba(255,255,255,0.8) !important; }

/* Agent 名称徽章 */
.agent-name-badge { display: flex; align-items: center; gap: 8px; padding: 4px 10px; border-radius: 10px; background: rgba(96,165,250,0.08); border: 1px solid rgba(96,165,250,0.12); transition: all 0.2s; }
.agent-name-badge:hover { background: rgba(96,165,250,0.14); border-color: rgba(96,165,250,0.2); }
.agent-name-label { font-size: 0.85rem; font-weight: 600; color: #e2e8f0; letter-spacing: 0.01em; }
.model-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; margin-left: 4px; flex-shrink: 0; }
.model-badge { font-size: 0.65rem; color: rgba(255,255,255,0.35); font-family: monospace; background: rgba(255,255,255,0.06); padding: 2px 6px; border-radius: 4px; }

.conv-title-badge { color: rgba(255,255,255,0.35); font-size: 0.78rem; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.topbar-spacer { flex: 1; }

/* 新对话按钮 — 液态玻璃效果 */
::deep(.new-chat-btn) {
  border-radius: 12px !important; font-size: 0.82rem;
  height: 36px; padding: 0 16px !important;
  background: rgba(15,20,45,0.55) !important;
  backdrop-filter: blur(12px) saturate(160%);
  -webkit-backdrop-filter: blur(12px) saturate(160%);
  border: 1px solid rgba(255,255,255,0.1) !important;
  color: rgba(255,255,255,0.6) !important; font-weight: 500;
  box-shadow: 0 2px 12px rgba(0,0,0,0.3), 0 0 0 0.5px rgba(255,255,255,0.08) inset;
  transition: all 0.3s ease;
}
::deep(.new-chat-btn:hover) {
  background: rgba(96,165,250,0.12) !important;
  border-color: rgba(96,165,250,0.3) !important;
  color: #93c5fd !important;
  box-shadow: 0 4px 20px rgba(59,130,246,0.15), 0 0 0 0.5px rgba(96,165,250,0.15) inset;
  transform: translateY(-1px);
}
::deep(.new-chat-btn .anticon) { font-size: 0.88rem; transition: transform 0.3s ease; }
::deep(.new-chat-btn:hover .anticon) { transform: rotate(90deg); }
.new-chat-text { letter-spacing: 0.02em; }

.chat-body { display: flex; flex: 1; gap: 12px; overflow: hidden; min-height: 0; }

/* ===== 侧栏 ===== */
.chat-sidebar {
  width: 260px; flex-shrink: 0; padding: 16px 12px;
  overflow-y: auto; border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.05);
  display: flex; flex-direction: column; min-height: 0;
  background: linear-gradient(180deg, rgba(15,21,50,0.85), rgba(10,14,39,0.9));
}
.sidebar-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; flex-shrink: 0;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.sidebar-title { font-weight: 600; color: rgba(255,255,255,0.65); font-size: 0.85rem; letter-spacing: 0.03em; text-transform: uppercase; }
.sidebar-empty {
  color: rgba(255,255,255,0.15); text-align: center; padding: 40px 0 32px; font-size: 0.82rem;
  display: flex; flex-direction: column; align-items: center; gap: 8px;
}
.sidebar-empty::before { content: '💬'; font-size: 1.8rem; opacity: 0.3; display: block; }
.conv-list { flex: 1; overflow-y: auto; min-height: 0; padding-right: 2px; }
.conv-item {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-radius: 10px; cursor: pointer;
  margin-bottom: 3px; color: rgba(255,255,255,0.45);
  font-size: 0.83rem; transition: all 0.2s ease;
  position: relative; border: 1px solid transparent;
}
.conv-item:hover {
  background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.8);
  border-color: rgba(255,255,255,0.06);
}
.conv-item.active {
  background: rgba(96,165,250,0.1); color: #93c5fd;
  border-color: rgba(96,165,250,0.18);
  box-shadow: inset 0 0 0 1px rgba(96,165,250,0.1);
}
.conv-item.active::before {
  content: ''; position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  width: 3px; height: 24px; border-radius: 2px;
  background: linear-gradient(180deg, #60a5fa, #a78bfa);
}
.conv-icon { font-size: 0.82rem; opacity: 0.4; flex-shrink: 0; transition: opacity 0.2s; }
.conv-item:hover .conv-icon, .conv-item.active .conv-icon { opacity: 0.7; }
.conv-text { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 400; }
.conv-item.active .conv-text { font-weight: 500; }
.conv-actions { display: flex; align-items: center; gap: 2px; flex-shrink: 0; }
.conv-rename, .conv-del { opacity: 0; transition: opacity 0.2s; color: rgba(255,255,255,0.35) !important; }
.conv-item:hover .conv-rename, .conv-item:hover .conv-del { opacity: 1; }
.rename-input { flex: 1; max-width: 140px; }
::deep(.rename-input .ant-input) { background: rgba(255,255,255,0.08) !important; border: 1px solid rgba(96,165,250,0.3) !important; color: #e2e8f0 !important; font-size: 0.82rem; padding: 4px 8px; height: 30px; border-radius: 6px; }

/* ===== 聊天主区 ===== */
.chat-main-area { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 14px; padding: 4px 6px 12px; min-height: 0; scroll-behavior: smooth; }

/* ===== 空状态 ===== */
.chat-empty { text-align: center; padding: 80px 0 40px; color: rgba(255,255,255,0.3); flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.empty-avatar { width: 80px; height: 80px; border-radius: 50%; background: linear-gradient(135deg, rgba(59,130,246,0.2), rgba(139,92,246,0.15)); display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; font-size: 2.2rem; color: #60a5fa; border: 1px solid rgba(96,165,250,0.15); }
.chat-empty h3 { color: rgba(255,255,255,0.55); margin-bottom: 10px; font-size: 1.1rem; font-weight: 600; }
.chat-empty p { font-size: 0.88rem; margin-bottom: 24px; color: rgba(255,255,255,0.3); }
.empty-tips { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
.tip { padding: 8px 16px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; font-size: 0.8rem; display: flex; align-items: center; gap: 7px; color: rgba(255,255,255,0.4); cursor: pointer; transition: all 0.2s; }
.tip:hover { background: rgba(255,255,255,0.07); border-color: rgba(255,255,255,0.1); color: rgba(255,255,255,0.6); }

/* ===== 消息行 ===== */
.msg-row { display: flex; align-items: flex-start; gap: 10px; padding: 0 4px; animation: msgIn 0.25s ease-out; }
.msg-row.user { justify-content: flex-end; }
.msg-avatar { flex-shrink: 0; margin-top: 2px; }
.msg-body { max-width: 72%; }
.msg-bubble { padding: 12px 18px; border-radius: 16px; }
.msg-row.user .msg-bubble { background: linear-gradient(135deg, rgba(59,130,246,0.35), rgba(139,92,246,0.25)); border: 1px solid rgba(96,165,250,0.25); border-bottom-right-radius: 6px; box-shadow: 0 2px 12px rgba(59,130,246,0.1); }
.msg-row.assistant .msg-bubble { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.07); border-bottom-left-radius: 6px; }
.msg-content { color: #e2e8f0; line-height: 1.6; white-space: pre-wrap; font-size: 0.93rem; }
.msg-time { font-size: 0.68rem; color: rgba(255,255,255,0.18); margin-top: 8px; }

@keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
.cursor { animation: blink 0.8s infinite; color: #60a5fa; }
@keyframes blink { 50% { opacity: 0; } }

/* ===== 思考过程 ===== */
.msg-reasoning { margin-bottom: 10px; border: 1px solid rgba(168,85,247,0.25); border-radius: 10px; overflow: hidden; background: rgba(168,85,247,0.05); }
.reasoning-header { display: flex; align-items: center; gap: 6px; padding: 7px 12px; cursor: pointer; font-size: 0.78rem; color: rgba(192,132,252,0.8); background: rgba(168,85,247,0.08); user-select: none; }
.reasoning-header:hover { background: rgba(168,85,247,0.14); }
.reasoning-icon { font-size: 0.9rem; color: #a78bfa; }
.reasoning-toggle { margin-left: auto; font-size: 0.7rem; opacity: 0.5; transition: opacity 0.2s; }
.reasoning-header:hover .reasoning-toggle { opacity: 0.8; }
.reasoning-body { padding: 10px 14px; font-size: 0.8rem; color: rgba(192,132,252,0.65); line-height: 1.5; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }

/* ===== 工具调用 ===== */
.msg-tool-calls { margin-bottom: 10px; display: flex; flex-direction: column; gap: 6px; }
.tool-call-item { border: 1px solid rgba(59,130,246,0.2); border-radius: 10px; overflow: hidden; background: rgba(59,130,246,0.04); }
.tool-call-header { display: flex; align-items: center; gap: 6px; padding: 6px 12px; font-size: 0.78rem; color: rgba(96,165,250,0.8); background: rgba(59,130,246,0.08); }
.tool-icon { font-size: 0.85rem; color: #60a5fa; }
.tool-name { font-weight: 500; }
.tool-input, .tool-output, .tool-error { padding: 6px 14px; font-size: 0.76rem; color: rgba(255,255,255,0.45); line-height: 1.45; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
.tool-label { color: rgba(255,255,255,0.25); margin-right: 4px; }
.tool-output { color: rgba(74,222,128,0.65); }
.tool-error { color: rgba(248,113,113,0.75); }

/* ===== 附件 ===== */
.msg-attachments { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.att-item { position: relative; }
.att-img { width: 120px; height: 90px; object-fit: cover; border-radius: 10px; border: 1px solid rgba(255,255,255,0.12); cursor: pointer; transition: transform 0.2s; }
.att-img:hover { transform: scale(1.05); }
.att-file { padding: 8px 12px; background: rgba(255,255,255,0.05); border-radius: 8px; font-size: 0.78rem; display: flex; align-items: center; gap: 6px; color: rgba(255,255,255,0.5); border: 1px solid rgba(255,255,255,0.06); }
.att-remove { position: absolute; top: -6px; right: -6px; background: rgba(0,0,0,0.7) !important; border-radius: 50% !important; padding: 0 !important; width: 20px !important; height: 20px !important; line-height: 20px !important; font-size: 10px !important; color: #fff !important; opacity: 0; transition: opacity 0.2s; }
.att-item:hover .att-remove { opacity: 1; }

/* ===== 语音消息 ===== */
.voice-message { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 20px; background: rgba(255,255,255,0.08); min-width: 120px; max-width: 240px; cursor: pointer; transition: all 0.2s ease; position: relative; }
.voice-message:hover { background: rgba(255,255,255,0.14); }
.msg-row.user .voice-message { background: rgba(99,102,241,0.25); border: 1px solid rgba(99,102,241,0.3); }
.msg-row.user .voice-message:hover { background: rgba(99,102,241,0.35); }
.voice-icon { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; flex-shrink: 0; }
.voice-wave { display: inline-block; width: 4px; margin: 0 1px; border-radius: 2px; background: #93c5fd; animation: wave 0.8s ease-in-out infinite; }
.voice-wave-1 { animation-delay: 0s; } .voice-wave-2 { animation-delay: 0.2s; } .voice-wave-3 { animation-delay: 0.4s; }
@keyframes wave { 0%, 100% { height: 8px; } 50% { height: 20px; } }
.voice-static { color: #93c5fd; font-size: 18px; }
.msg-row.user .voice-static { color: #fff; }
.msg-row.user .voice-wave { background: #fff; }
.voice-bar { flex: 1; height: 4px; background: rgba(255,255,255,0.15); border-radius: 2px; overflow: hidden; position: relative; }
.voice-progress { height: 100%; background: linear-gradient(90deg, #6366f1, #8b5cf6); border-radius: 2px; transition: width 0.1s linear; }
.msg-row.user .voice-progress { background: linear-gradient(90deg, #fff, #e2e8f0); }
.voice-duration { font-size: 0.78rem; color: rgba(255,255,255,0.55); min-width: 42px; text-align: right; flex-shrink: 0; }
.msg-row.user .voice-duration { color: rgba(255,255,255,0.85); }

/* ===== 输入区 ===== */
.chat-input-wrapper {
  position: sticky; bottom: 0; margin-top: 8px; z-index: 10;
  backdrop-filter: blur(30px) saturate(220%);
  -webkit-backdrop-filter: blur(30px) saturate(220%);
  background: rgba(10,16,36,0.28);
  border-radius: 20px;
  transform: translateZ(0);
}

/* 液态玻璃输入框 */
.chat-input-bar {
  padding: 12px 16px; border-radius: 18px; position: relative;
  background: rgba(255,255,255,0.04);
  backdrop-filter: blur(10px) saturate(150%);
  -webkit-backdrop-filter: blur(10px) saturate(150%);
  border: none;
  box-shadow:
    0 4px 24px rgba(0,0,0,0.3),
    0 0 0 0.5px rgba(255,255,255,0.1) inset,
    0 1px 0 rgba(255,255,255,0.15) inset;
  transition: box-shadow 0.35s ease;
}

.chat-input-bar::before {
  content: '';
  position: absolute; inset: 0; border-radius: 18px; pointer-events: none; z-index: 0;
  padding: 2px;
  background: linear-gradient(140deg, rgba(255,255,255,0) 10%, rgba(255,255,255,0.3) 30%, rgba(200,230,255,0.6) 50%, rgba(255,255,255,0.18) 70%, rgba(255,255,255,0) 90%);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  transition: background 0.35s ease;
}

.chat-input-bar::after {
  content: '';
  position: absolute; inset: 0; border-radius: 18px; pointer-events: none; z-index: 1;
  padding: 2px;
  background: linear-gradient(140deg, rgba(255,255,255,0) 10%, rgba(255,255,255,0.55) 30%, rgba(255,255,255,0.95) 50%, rgba(255,255,255,0.3) 70%, rgba(255,255,255,0) 90%);
  -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  mix-blend-mode: overlay;
  opacity: 0.6;
  transition: opacity 0.35s ease, background 0.35s ease;
}

.chat-input-bar:focus-within {
  box-shadow: 0 4px 28px rgba(59,130,246,0.2), 0 0 0 0.5px rgba(96,165,250,0.2) inset, 0 1px 0 rgba(168,220,255,0.2) inset;
}
.chat-input-bar:focus-within::before {
  background: linear-gradient(140deg, rgba(96,165,250,0) 10%, rgba(96,165,250,0.35) 30%, rgba(168,220,255,0.7) 50%, rgba(139,92,246,0.25) 70%, rgba(255,255,255,0) 90%);
}
.chat-input-bar:focus-within::after { opacity: 1; }

.upload-preview-bar { display: flex; gap: 8px; padding: 8px 0; flex-wrap: wrap; }
.up-item { display: flex; align-items: center; gap: 6px; padding: 6px 10px; background: rgba(255,255,255,0.06); border-radius: 8px; font-size: 0.8rem; color: rgba(255,255,255,0.5); }
.up-thumb { width: 32px; height: 32px; object-fit: cover; border-radius: 6px; }
.up-icon { font-size: 1rem; }
.up-name { max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.recording-bar { display: flex; align-items: center; gap: 12px; padding: 10px 16px; border-radius: 12px; margin-bottom: 8px; color: #ef4444; font-size: 0.85rem; border: 1px solid rgba(239,68,68,0.2); }
.rec-pulse { width: 10px; height: 10px; border-radius: 50%; background: #ef4444; animation: pulse 1s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(1.3); } }
.input-toolbar { display: flex; align-items: center; gap: 2px; margin-bottom: 4px; }
.input-toolbar .ant-btn {
  color: rgba(255,255,255,0.35) !important;
  transition: all 0.25s ease;
  border-radius: 8px;
}
.input-toolbar .ant-btn:hover {
  color: #93c5fd !important;
  background: rgba(96,165,250,0.1) !important;
}
.input-toolbar .recording { color: #ef4444 !important; background: rgba(239,68,68,0.1) !important; }
.input-toolbar :deep(.ant-divider) { border-color: rgba(255,255,255,0.08); margin: 0 6px; }
.input-row { display: flex; align-items: flex-end; gap: 10px; }
.input-row :deep(.ant-input) { background: transparent !important; border: none !important; color: #e2e8f0 !important; font-size: 0.93rem; resize: none; padding: 6px 0; outline: none !important; box-shadow: none !important; }
.input-row :deep(.ant-input::placeholder) { color: rgba(255,255,255,0.25); }
.send-btn {
  flex-shrink: 0; border-radius: 14px; width: 42px; height: 42px; padding: 0;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
  border: none !important; box-shadow: 0 2px 12px rgba(59,130,246,0.3);
  transition: all 0.25s ease;
}
.send-btn:hover:not(:disabled) {
  box-shadow: 0 4px 20px rgba(59,130,246,0.5);
  transform: scale(1.05);
}
.send-btn:disabled {
  background: rgba(255,255,255,0.08) !important;
  box-shadow: none;
  color: rgba(255,255,255,0.2) !important;
}

/* 过渡动画 */
.slide-enter-active,.slide-leave-active { transition: all 0.25s ease; }
.slide-enter-from,.slide-leave-to { transform: translateX(-100%); opacity: 0; }
.fade-enter-active,.fade-leave-active { transition: all 0.2s ease; }
.fade-enter-from,.fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
