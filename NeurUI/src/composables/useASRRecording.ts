import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'
import { api } from '@/api'
import { uiMessage } from '@/utils/message'

/**
 * ASR 语音输入状态机（2026-09-08 ChatPage 拆分产物）。
 *
 * Web Speech API 为主，后端转写为音频文件兜底；模块级单例：ChatComposerArea
 * （录音条/按钮 UI）与页面编排层 sendMessage（发送前停止录音）共享状态。
 * 转写回填走 chatStore.setInputText；回填后的 textarea 自适应高度经
 * setResizeHook 由组件侧注册。
 */

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
let resizeHook: (() => void) | null = null

function setResizeHook(fn: () => void): void {
  resizeHook = fn
}

function initASR(): void {
  const appStore = useAppStore()
  const { t } = useI18n()
  const chatStore = useChatStore()
  const { inputText } = storeToRefs(chatStore)

  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
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
      chatStore.setInputText(inputText.value + (inputText.value ? ' ' : '') + finalTranscript)
      nextTick(() => resizeHook?.())
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

function toggleRecording(): void {
  if (isRecording.value) {
    stopRecording()
  } else {
    startRecording()
  }
}

function startRecording(): void {
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

function stopRecording(): void {
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

function cancelRecording(): void {
  stopRecording()
}

/** Backend ASR fallback for uploaded audio files */
async function transcribeAudioFile(file: File): Promise<string | null> {
  const appStore = useAppStore()
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

/** locale 切换时同步识别语言（页面 watch 调用） */
function syncLocale(locale: string): void {
  if (recognition) {
    recognition.lang = locale === 'zh-CN' ? 'zh-CN' : 'en-US'
  }
}

export function useASRRecording() {
  return {
    asrAvailable,
    isRecording,
    recordingTimeStr,
    setResizeHook,
    initASR,
    toggleRecording,
    cancelRecording,
    stopRecording,
    transcribeAudioFile,
    syncLocale,
  }
}
