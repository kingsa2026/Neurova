<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { streamChat, listChatSessions, fetchChatHistory } from '@/api/chat'
import { MobileWsChannel } from '@/utils/ws'
import { useAgentsStore } from '@/stores/agents'
import { usePairingStore } from '@/stores/pairing'
import type { ChatMessage } from '@/types'

const agents = useAgentsStore()
const pairing = usePairingStore()

const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const errorMsg = ref('')
const sessionId = ref('')
const channelNote = ref('')
const sessions = ref<Array<{ session_id: string; label: string }>>([])
const showHistory = ref(false)
const abort = ref<AbortController | null>(null)
const listEl = ref<HTMLElement | null>(null)

let wsChannel: MobileWsChannel | null = null

onMounted(async () => {
  await agents.load()
  refreshSessions()
})

async function refreshSessions() {
  sessions.value = (await listChatSessions())
    .filter((s) => !!s.session_id)
    .map((s) => ({ session_id: s.session_id, label: s.title || s.session_id }))
    .slice(0, 30)
}

function scrollToBottom() {
  nextTick(() => listEl.value?.scrollTo({ top: listEl.value.scrollHeight }))
}

function tail(): ChatMessage {
  return messages.value[messages.value.length - 1]
}

function gotAnyChunk(): boolean {
  return (tail()?.content ?? '').length > 0
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  errorMsg.value = ''
  input.value = ''
  messages.value.push({ id: crypto.randomUUID(), role: 'user', content: text })
  messages.value.push({ id: crypto.randomUUID(), role: 'assistant', content: '', status: 'streaming' })
  scrollToBottom()

  streaming.value = true
  abort.value = new AbortController()
  let sseOk = false
  try {
    await streamChat(
      { message: text, agentId: agents.currentId, sessionId: sessionId.value || undefined, signal: abort.value.signal },
      {
        onStart: (info) => {
          sessionId.value = info.session_id || sessionId.value
        },
        onMessage: (chunk) => {
          sseOk = true
          tail().content += chunk
          scrollToBottom()
        },
        onReasoning: (chunk) => {
          tail().reasoning = (tail().reasoning ?? '') + chunk
          scrollToBottom()
        },
        onStatus: ({ kind, payload }) => {
          const hint = kind === 'retry' ? `重试中（${payload.wait_seconds ?? '?'}s）` : kind === 'parked' ? '回合已挂起' : '上游状态更新'
          tail().error = hint
        },
        onError: (msg) => {
          tail().status = 'error'
          tail().error = msg
          errorMsg.value = msg
        },
        onDone: () => {
          sseOk = true
          tail().status = 'done'
        },
      },
    )
    if (tail().status === 'streaming') tail().status = 'done'
    // 降级判据：SSE 未收到任何正文即失败/中断 → 切 WS 通道重发同一消息；
    // 已收到部分正文则不自动重发（避免双通道重复回答），只提示重试。
    if (!sseOk && !gotAnyChunk()) {
      await fallbackToWs(text)
    } else if (!sseOk) {
      errorMsg.value = '连接中断（已输出部分内容），请重试'
    }
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      tail().status = 'cancelled'
      tail().error = '已取消'
    } else if (!gotAnyChunk() && pairing.paired) {
      await fallbackToWs(text)
    } else {
      tail().status = 'error'
      errorMsg.value = e instanceof Error ? e.message : '对话失败'
    }
  } finally {
    streaming.value = false
    abort.value = null
    refreshSessions()
  }
}

/** WS 降级通道（设计方案 M2 判据：WS 与 SSE 同会话切换无串话） */
async function fallbackToWs(text: string) {
  if (!pairing.paired) {
    errorMsg.value = '连接失败（未配对设备，无 WS 备用通道）'
    tail().status = 'error'
    return
  }
  channelNote.value = '切换 WS 备用通道…'
  const channel = wsChannel ?? new MobileWsChannel(pairing.wsUrl)
  wsChannel = channel
  const wsSessionId = sessionId.value || `mobile-${crypto.randomUUID().slice(0, 8)}`
  sessionId.value = wsSessionId
  const ok = await channel.connect({
    onState: (s, detail) => {
      channelNote.value = detail ? `WS ${s}（${detail}）` : `WS ${s}`
    },
    onChunk: (content, sid) => {
      if (sid !== wsSessionId) return
      tail().content += content
      scrollToBottom()
    },
    onDone: (sid) => {
      if (sid !== wsSessionId) return
      tail().status = 'done'
      streaming.value = false
    },
    onCancelled: (sid) => {
      if (sid !== wsSessionId) return
      tail().status = 'cancelled'
      streaming.value = false
    },
    onError: (code, message) => {
      if (code === 'chat_failed') {
        tail().status = 'error'
        tail().error = message
        errorMsg.value = message
      }
    },
  })
  if (!ok) {
    channelNote.value = ''
    errorMsg.value = 'WS 备用通道不可用（检查配对状态）'
    tail().status = 'error'
    streaming.value = false
    return
  }
  channel.sendChat(text, agents.currentId, wsSessionId)
}

function cancel() {
  abort.value?.abort()
  wsChannel?.cancelChat()
}

async function openSession(sessionId2: string) {
  const history = await fetchChatHistory(sessionId2)
  sessionId.value = sessionId2
  messages.value = history
    .filter((m) => m.content)
    .map((m) => ({
      id: crypto.randomUUID(),
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content,
      status: 'done' as const,
    }))
  showHistory.value = false
  scrollToBottom()
}
</script>

<template>
  <div class="chat-page">
    <div class="chat-toolbar">
      <button class="ghost" @click="showHistory = !showHistory">历史会话</button>
      <button
        class="ghost"
        @click="() => { messages = []; sessionId = ''; }"
      >新会话</button>
      <span v-if="channelNote" class="channel-note">{{ channelNote }}</span>
    </div>

    <div v-if="showHistory" class="history card">
      <div v-if="!sessions.length" class="muted">暂无会话</div>
      <div v-for="s in sessions" :key="s.session_id" class="session-row" @click="openSession(s.session_id)">
        {{ s.label }}
      </div>
    </div>

    <div ref="listEl" class="msg-list">
      <div v-if="!messages.length" class="muted empty">开始你的第一轮对话</div>
      <div v-for="m in messages" :key="m.id" class="msg-row" :class="m.role">
        <div class="bubble" :class="m.role">
          <details v-if="m.reasoning" class="reasoning"><summary>思考过程</summary><div>{{ m.reasoning }}</div></details>
          <div class="content">{{ m.content }}<span v-if="m.status === 'streaming'" class="cursor">▌</span></div>
          <div v-if="m.error && m.status !== 'streaming'" class="error-text">{{ m.error }}</div>
        </div>
      </div>
    </div>

    <div class="composer">
      <textarea
        v-model="input"
        rows="2"
        placeholder="输入消息…"
        :disabled="streaming"
        @keydown.enter.exact.prevent="send"
      />
      <button v-if="!streaming" class="send" :disabled="!input.trim()" @click="send">发送</button>
      <button v-else class="send cancel" @click="cancel">取消</button>
    </div>
  </div>
</template>

<style scoped>
.chat-page { display: flex; flex-direction: column; height: calc(100vh - 108px); }
.chat-toolbar { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; }
.ghost {
  background: var(--bg-card); border: 1px solid var(--border); color: var(--text-dim);
  border-radius: 8px; padding: 6px 10px; font-size: 12px;
}
.channel-note { font-size: 11px; color: var(--warning); }
.history { max-height: 220px; overflow: auto; }
.session-row { padding: 8px 4px; border-bottom: 1px solid var(--border); font-size: 13px; }
.msg-list { flex: 1; overflow-y: auto; padding-bottom: 8px; }
.empty { text-align: center; margin-top: 40px; }
.msg-row { display: flex; margin-bottom: 10px; }
.msg-row.user { justify-content: flex-end; }
.bubble {
  max-width: 86%; padding: 10px 12px; border-radius: 12px;
  background: var(--bg-card); border: 1px solid var(--border); font-size: 14px; line-height: 1.55;
  word-break: break-word; white-space: pre-wrap;
}
.bubble.user { background: var(--primary-dim); border-color: var(--primary-dim); }
.reasoning {
  border-left: 2px solid var(--border); color: var(--text-dim);
  font-size: 12px; padding: 2px 8px; margin-bottom: 6px;
}
.reasoning summary { cursor: pointer; }
.cursor { animation: blink 1s infinite; color: var(--primary); }
@keyframes blink { 50% { opacity: 0; } }
.composer { display: flex; gap: 8px; align-items: flex-end; padding-top: 8px; }
.composer textarea { resize: none; flex: 1; }
.send {
  background: var(--primary); color: #fff; border-radius: 10px; padding: 10px 16px; font-weight: 600;
}
.send.cancel { background: var(--error); }
.send:disabled { opacity: 0.5; }
</style>
