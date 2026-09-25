<template>
  <div class="room-page">
    <!-- 页头：返回 + 房间名 + 成员 + 默认应答者 -->
    <div class="room-header">
      <div class="room-header-left">
        <GlassButton variant="ghost" size="sm" @click="goBack">
          <ArrowLeftOutlined /> {{ t('collab.roomBack') }}
        </GlassButton>
        <div>
          <h2>{{ room?.name || t('collab.roomTitle') }}</h2>
          <p class="room-sub">
            {{ t('collab.roomMembers') }}:
            <a-tag v-for="m in room?.members || []" :key="m.id" color="blue">{{ m.name }}</a-tag>
            <span v-if="room?.responder_agent_id" class="room-responder">
              · {{ t('collab.roomResponder') }}: {{ responderName }}
            </span>
          </p>
        </div>
      </div>
    </div>

    <!-- 消息流 -->
    <GlassPanel variant="default" padding="0" class="room-body">
      <div ref="scroller" class="room-messages">
        <a-spin :spinning="loading">
          <p v-if="!loading && messages.length === 0" class="room-empty">{{ t('collab.roomEmpty') }}</p>
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="bubble-row"
            :class="[`from-${msg.sender_type}`, { 'is-error': msg.kind === 'error' }]"
          >
            <div class="bubble">
              <div v-if="msg.sender_type === 'agent'" class="bubble-sender">{{ senderName(msg.sender_id) }}</div>
              <MessageSteps v-if="msg.steps && msg.steps.length" :steps="msg.steps" />
              <MessageContent :content="msg.content" bare />
              <span v-if="msg.streaming" class="typing-caret">▋</span>
            </div>
          </div>
        </a-spin>
      </div>

      <!-- 输入区 -->
      <div class="room-input">
        <div class="composer-wrap">
          <!-- @ 提及弹层：列出房间成员，点选/回车插入 @显示名 -->
          <div v-if="mentionCtx && mentionCandidates.length" class="mention-pop">
            <div
              v-for="(c, i) in mentionCandidates"
              :key="c.id"
              class="mention-item"
              :class="{ active: i === mentionIndex }"
              @mousedown.prevent="selectMention(c)"
              @mouseenter="mentionIndex = i"
            >{{ c.name }}</div>
          </div>
          <a-textarea
            v-model:value="draft"
            :placeholder="t('collab.roomInputPlaceholder')"
            :auto-size="{ minRows: 1, maxRows: 4 }"
            @input="onComposerInput"
            @keydown="onComposerKeydown"
          />
        </div>
        <GlassButton variant="primary" size="md" :loading="sending" @click="send">{{ t('collab.roomSend') }}</GlassButton>
      </div>
    </GlassPanel>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ArrowLeftOutlined } from '@ant-design/icons-vue'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'
import MessageContent from '@/components/chat/MessageContent.vue'
import MessageSteps from '@/components/chat/MessageSteps.vue'
import { useSessionSync } from '@/composables/useSessionSync'
import {
  getRoom, getRoomMessages, postRoomMessage, applyRoomEvent,
  computeMentionQuery, applyMention, filterMembers,
  type RoomInfo, type RoomMessage, type RoomEvent, type MentionContext, type RoomMember,
} from '@/api/modules/collaborationRoom'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const roomId = String(route.params.roomId || '')
const room = ref<RoomInfo | null>(null)
const messages = ref<RoomMessage[]>([])
const loading = ref(false)
const sending = ref(false)
const draft = ref('')
const scroller = ref<HTMLElement | null>(null)

// 默认应答者展示名：优先用成员列表里的友好名，回落原始 id。
const responderName = computed(() => {
  const r = room.value?.responder_agent_id
  if (!r) return ''
  return room.value?.members?.find((m) => m.id === r)?.name || r
})

// 气泡发送者展示名：按成员表把 agent id 映为友好名（全程显示名）。
function senderName(id: string): string {
  return room.value?.members?.find((m) => m.id === id)?.name || id
}

function scrollToBottom() {
  nextTick(() => { if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight })
}

function onEvent(event: RoomEvent) {
  messages.value = applyRoomEvent(messages.value, event)
  scrollToBottom()
}

async function send() {
  const text = draft.value.trim()
  if (!text || sending.value) return
  sending.value = true
  // 乐观追加（后端 USER_MESSAGE 回显按 sender+content 去重）
  messages.value = [
    ...messages.value,
    { id: `local-${Date.now()}`, sender_type: 'user', sender_id: room.value?.owner || 'me', content: text },
  ]
  draft.value = ''
  scrollToBottom()
  try {
    await postRoomMessage(roomId, text)
  } finally {
    sending.value = false
  }
}

function goBack() {
  router.push('/collaboration/sessions')
}

// ── @ 提及弹层 ──
const mentionCtx = ref<MentionContext | null>(null)
const mentionIndex = ref(0)
const mentionCandidates = computed<RoomMember[]>(() =>
  mentionCtx.value ? filterMembers(room.value?.members || [], mentionCtx.value.query) : [],
)
let composerEl: HTMLTextAreaElement | null = null

function onComposerInput(e: Event) {
  const el = e.target as HTMLTextAreaElement
  composerEl = el
  const text = el.value
  const caret = el.selectionStart ?? text.length
  mentionCtx.value = computeMentionQuery(text, caret)
  mentionIndex.value = 0
}

function selectMention(c: RoomMember) {
  const ctx = mentionCtx.value
  if (!ctx) return
  const caret = composerEl ? (composerEl.selectionStart ?? draft.value.length) : draft.value.length
  draft.value = applyMention(draft.value, ctx.start, caret, c.name)
  mentionCtx.value = null
  const pos = ctx.start + c.name.length + 1
  nextTick(() => {
    if (composerEl) {
      composerEl.focus()
      composerEl.setSelectionRange(pos, pos)
    }
  })
}

function onComposerKeydown(e: KeyboardEvent) {
  const cands = mentionCandidates.value
  if (mentionCtx.value && cands.length) {
    if (e.key === 'ArrowDown') { e.preventDefault(); mentionIndex.value = (mentionIndex.value + 1) % cands.length; return }
    if (e.key === 'ArrowUp') { e.preventDefault(); mentionIndex.value = (mentionIndex.value - 1 + cands.length) % cands.length; return }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); selectMention(cands[mentionIndex.value]); return }
    if (e.key === 'Escape') { e.preventDefault(); mentionCtx.value = null; return }
  }
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
}

// 实时订阅：复用 session-sync WS（session_id=room_id）
useSessionSync(() => roomId, (e) => onEvent(e as RoomEvent))

onMounted(async () => {
  loading.value = true
  try {
    const [info, history] = await Promise.all([getRoom(roomId), getRoomMessages(roomId)])
    room.value = info
    messages.value = history
    scrollToBottom()
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.room-page { display: flex; flex-direction: column; gap: 16px; padding: 24px; height: 100%; box-sizing: border-box; }
.room-header { display: flex; justify-content: space-between; align-items: flex-start; }
.room-header-left { display: flex; align-items: flex-start; gap: 12px; }
.room-header h2 { color: var(--nr-text-primary); font-family: var(--nr-font-display); font-weight: 700; margin: 0; }
.room-sub { color: var(--nr-text-secondary); font-size: 13px; margin: 4px 0 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.room-responder { color: var(--nr-text-tertiary); }
.room-body { display: flex; flex-direction: column; flex: 1; min-height: 0; overflow: hidden; }
/* GlassPanel 的 slot 包在 .nr-glass-content（block、无界高）里，需让它填满面板高并成为 flex 列，
   否则 .room-messages 的 flex:1 无参照、内容撑高被外层 overflow:hidden 裁掉而无法滚动。 */
.room-body :deep(.nr-glass-content) { height: 100%; display: flex; flex-direction: column; box-sizing: border-box; }
.room-messages { flex: 1; min-height: 0; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; }
.room-empty { color: var(--nr-text-muted); text-align: center; margin-top: 40px; }
.bubble-row { display: flex; }
.bubble-row.from-user { justify-content: flex-end; }
.bubble-row.from-agent, .bubble-row.from-system { justify-content: flex-start; }
.bubble { max-width: 72%; padding: 10px 14px; border-radius: 14px; border: 1px solid var(--nr-glass-border); background: var(--nr-glass-bg); }
.from-user .bubble { background: var(--nr-primary-soft); border-color: var(--nr-primary-soft-border); }
.from-system .bubble, .is-error .bubble { background: rgba(239, 68, 68, 0.1); border-color: rgba(239, 68, 68, 0.35); }
.bubble-sender { font-size: 11px; color: var(--nr-text-tertiary); margin-bottom: 2px; }
.bubble-content { color: var(--nr-text-primary); font-size: 14px; white-space: pre-wrap; word-break: break-word; }
.bubble-content.typing::after { content: '▋'; animation: blink 1s steps(2) infinite; color: var(--nr-primary-light); }
.typing-caret { color: var(--nr-primary-light); animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.room-input { display: flex; gap: 8px; align-items: flex-end; padding: 12px 16px; border-top: 1px solid var(--nr-glass-border); }
.composer-wrap { position: relative; flex: 1; min-width: 0; }
.mention-pop {
  position: absolute; bottom: 100%; left: 0; margin-bottom: 6px; z-index: 20;
  min-width: 180px; max-height: 220px; overflow-y: auto; padding: 4px;
  background: var(--nr-bg-elevated, rgba(20, 22, 34, 0.98)); border: 1px solid var(--nr-glass-border);
  border-radius: 10px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.mention-item { padding: 6px 10px; border-radius: 7px; cursor: pointer; color: var(--nr-text-primary); font-size: 13px; }
.mention-item:hover, .mention-item.active { background: var(--nr-primary-soft); color: var(--nr-primary-light); }
</style>
