<template>
  <div >
    <!-- 消息列表 -->
    <div  ref="messagesContainer">
      <TransitionGroup name="message" tag="div">
        <div
          v-for="message in messages"
          :key="message.id"
          :
        >
          <div >
            {{ message.role === 'user' ? 'U' : 'A' }}
          </div>
          <div >
            <div >{{ message.role === 'user' ? '用户' : '助手' }}</div>
            <div  v-if="message.role === 'user'">{{ message.content }}</div>
            <div  v-else>
              <span >{{ message.content }}</span>
              <span v-if="isStreaming && message === messages[messages.length - 1]" >|</span>
            </div>
          </div>
        </div>
      </TransitionGroup>
      <!-- 正在输入指示器 -->
      <div v-if="isStreaming && messages.length === 0" >
        <div ></div>
        <div ></div>
        <div ></div>
      </div>
    </div>
    <!-- 输入区域 -->
    <div >
      <div >
        <a-button
          v-if="isStreaming"
          type="text"
          @click="stopGeneration"
        >
          <StopOutlined />
          停止生成
        </a-button>
      </div>
      <div >
        <a-textarea
          v-model:value="inputMessage"
          placeholder="输入消息..."
          :auto-size="{ minRows: 1, maxRows: 4 }"
          @press-enter="sendMessage"
        />
        <a-button
          type="primary"
          :disabled="!inputMessage.trim()"
          @click="sendMessage"
        >
          <SendOutlined />
        </a-button>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { ref, nextTick, onUnmounted } from 'vue'
import { StopOutlined, SendOutlined } from '@ant-design/icons-vue'
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}
const props = defineProps<{
  modelValue?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'send', message: string): void
  (e: 'stop'): void
}>()
const messages = ref<Message[]>([])
const inputMessage = ref<string>('')
const isStreaming = ref<boolean>(false)
const messagesContainer = ref<HTMLElement | null>(null)
// 逐字动画相关
const streamingMessageId = ref<string | null>(null)
const displayedContent = ref<string>('')
let streamingTimer: number | null = null
const STREAMING_SPEED = 30 // 每个字符的延迟（毫秒）
function sendMessage() {
  if (!inputMessage.value.trim() || isStreaming.value) return
  // 添加用户消息
  const userMessage: Message = {
    id: Date.now().toString(),
    role: 'user',
    content: inputMessage.value,
    timestamp: Date.now()
  }
  messages.value.push(userMessage)
  // 触发发送事件
  emit('send', inputMessage.value)
  inputMessage.value = ''
  // 滚动到底部
  scrollToBottom()
}
function addAssistantMessage(content: string) {
  const assistantMessage: Message = {
    id: Date.now().toString(),
    role: 'assistant',
    content: '', // 初始为空，逐字显示
    timestamp: Date.now()
  }
  messages.value.push(assistantMessage)
  streamingMessageId.value = assistantMessage.id
  displayedContent.value = ''
  scrollToBottom()
  // 开始逐字动画
  startStreamingAnimation(assistantMessage.id, content)
}
function updateLastAssistantMessage(content: string) {
  const lastMessage = messages.value[messages.value.length - 1]
  if (lastMessage && lastMessage.role === 'assistant') {
    // 更新目标内容，动画会继续显示新内容
    if (streamingMessageId.value === lastMessage.id) {
      // 动画会继续进行，只需更新目标
      return
    }
    lastMessage.content = content
  }
}
// 逐字显示动画
function startStreamingAnimation(messageId: string, fullContent: string) {
  // 清除之前的定时器
  if (streamingTimer !== null) {
    clearInterval(streamingTimer)
  }
  let currentIndex = 0
  const targetMessage = messages.value.find(m => m.id === messageId)
  if (!targetMessage) return
  streamingTimer = window.setInterval(() => {
    if (currentIndex < fullContent.length) {
      // 每次添加几个字符，速度更快
      const chunkSize = Math.random() > 0.5 ? 2 : 1
      currentIndex = Math.min(currentIndex + chunkSize, fullContent.length)
      targetMessage.content = fullContent.substring(0, currentIndex)
      displayedContent.value = targetMessage.content
      scrollToBottom()
    } else {
      // 动画完成
      if (streamingTimer !== null) {
        clearInterval(streamingTimer)
        streamingTimer = null
      }
      streamingMessageId.value = null
    }
  }, STREAMING_SPEED)
}
// 组件卸载时清理定时器
onUnmounted(() => {
  if (streamingTimer !== null) {
    clearInterval(streamingTimer)
    streamingTimer = null
  }
})
function stopGeneration() {
  isStreaming.value = false
  emit('stop')
}
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}
// 暴露方法给父组件
defineExpose({
  addAssistantMessage,
  updateLastAssistantMessage,
  setStreaming: (value: boolean) => { isStreaming.value = value }
})
</script>
<style scoped>
.streaming-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(10, 14, 39, 0.9);
  border-radius: 1rem;
  overflow: hidden;
}
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}
.message-item {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}
.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.9rem;
  flex-shrink: 0;
}
.message-user .message-avatar {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: white;
}
.message-assistant .message-avatar {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}
.message-content {
  flex: 1;
  min-width: 0;
}
.message-role {
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 4px;
}
.message-text {
  color: rgba(255, 255, 255, 0.9);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.streaming-text {
  position: relative;
}
.streaming-text .cursor {
  display: inline-block;
  color: #60a5fa;
  font-weight: bold;
  animation: cursor-blink 1s infinite;
  margin-left: 2px;
}
@keyframes cursor-blink {
  0%, 50% {
    opacity: 1;
  }
  51%, 100% {
    opacity: 0;
  }
}
/* 消息进入/离开动画 */
.message-enter-active {
  animation: message-slide-in 0.3s ease;
}
.message-leave-active {
  animation: message-slide-out 0.2s ease;
}
@keyframes message-slide-in {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes message-slide-out {
  from {
    opacity: 1;
    transform: translateY(0);
  }
  to {
    opacity: 0;
    transform: translateY(-10px);
  }
}
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 0;
}
.typing-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  animation: typing 1.4s infinite;
}
.typing-dot:nth-child(2) {
  animation-delay: 0.2s;
}
.typing-dot:nth-child(3) {
  animation-delay: 0.4s;
}
@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.4;
  }
  30% {
    transform: translateY(-8px);
    opacity: 1;
  }
}
.input-container {
  padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}
.input-actions {
  margin-bottom: 8px;
}
.stop-btn {
  color: #ef4444 !important;
  font-size: 0.9rem;
}
.input-box {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.chat-input {
  flex: 1;
  :deep(.ant-textarea) {
    background: rgba(255, 255, 255, 0.05) !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
    color: white !important;
    border-radius: 0.5rem !important;
    resize: none;
    &:focus {
      border-color: #3b82f6 !important;
      box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2) !important;
    }
    &::placeholder {
      color: rgba(255, 255, 255, 0.4) !important;
    }
  }
}
.send-btn {
  width: 48px;
  height: 48px;
  border-radius: 0.5rem !important;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
 