import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStore } from '@/stores/app'
import { useChatStore } from '@/stores/chat'
import { storeToRefs } from 'pinia'
import { useASRRestartGuard } from '@/composables/useASRRestartGuard'
import { StreamingAsrSession } from '@/composables/useStreamingASR'
import { transcribeAudio } from '@/api/modules/asr'
import { uiMessage } from '@/utils/message'

/**
 * ASR 语音输入状态机（2026-09-08 ChatPage 拆分产物；B4-1 流式通道接入）。
 *
 * 通道优先级：后端流式 WS（/api/v1/audio/asr/stream，任何浏览器可用，实时
 * partial/final 由服务端 turn 终结）→ Web Speech API → 录音上传
 * /audio/transcribe 兜底。流式启动失败自动回落 Web Speech；模块级单例：
 * ChatComposerArea（录音条/按钮 UI）与页面编排层 sendMessage（发送前停止
 * 录音）共享状态。转写回填走 chatStore.setInputText；回填后的 textarea
 * 自适应高度经 setResizeHook 由组件侧注册。
 */

const asrAvailable = ref(false)
const isRecording = ref(false)
const recordingTimeStr = ref('0:00')
const usingStreaming = ref(false)
let recognition: any = null
// Guard against infinite ASR auto-restart when the recognizer keeps dying.
const asrRestartGuard = useASRRestartGuard(3)
let recordingTimer: ReturnType<typeof setInterval> | null = null
let recordingSeconds = 0
// Timer for the delayed ASR restart (breaks tight onend→start loops)
let asrRestartTimer: ReturnType<typeof setTimeout> | null = null
let resizeHook: (() => void) | null = null
// 流式通道状态（同一时刻至多一个会话；partial/final 以「起始文本为基座 +
// 已终结轮累加 + 当前轮 interim」的口径回填输入框）
let streamingSession: StreamingAsrSession | null = null
let streamingBase = ''
let streamingCommitted = ''
let streamingFallbackTried = false

function setResizeHook(fn: () => void): void {
  resizeHook = fn
}

function joinTexts(...parts: string[]): string {
  return parts.filter((p) => p && p.trim()).join(' ')
}

function stopRecordingTimer(): void {
  if (recordingTimer) {
    clearInterval(recordingTimer)
    recordingTimer = null
  }
  if (asrRestartTimer) {
    clearTimeout(asrRestartTimer)
    asrRestartTimer = null
  }
}

function initASR(): void {
  const appStore = useAppStore()
  const { t } = useI18n()
  const chatStore = useChatStore()
  const { inputText } = storeToRefs(chatStore)

  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (SpeechRecognition) {
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
        stopRecordingTimer()
        uiMessage.warning(t('chat.asrRestartLimit') || 'Speech recognition stopped after multiple retries. Please try again.')
      }
    }
  } else {
    console.warn('[ASR] Web Speech API not available')
  }

  // 流式通道不依赖 Web Speech（Firefox/Safari 亦可）：有麦克风能力即开放语音入口，
  // 真正可用性由启动时的通道协商决定（失败自动回落）。
  if (!asrAvailable.value && !!navigator.mediaDevices?.getUserMedia) {
    asrAvailable.value = true
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
  const chatStore = useChatStore()
  isRecording.value = true
  recordingSeconds = 0
  recordingTimeStr.value = '0:00'
  // Fresh user-initiated start → reset the restart counter
  asrRestartGuard.reset()
  streamingFallbackTried = false
  streamingBase = chatStore.inputText ?? ''
  streamingCommitted = ''
  recordingTimer = setInterval(() => {
    recordingSeconds++
    const mins = Math.floor(recordingSeconds / 60)
    const secs = recordingSeconds % 60
    recordingTimeStr.value = `${mins}:${secs.toString().padStart(2, '0')}`
  }, 1000)

  // 流式优先；异步启动失败时回落 Web Speech（见 tryStartStreaming 的 catch）
  if (!tryStartStreaming()) {
    startWebSpeech()
  }
}

/** 尝试走后端流式通道；返回 false 表示环境不支持（无麦克风能力），需回落 */
function tryStartStreaming(): boolean {
  if (!navigator.mediaDevices?.getUserMedia) {
    return false
  }
  const chatStore = useChatStore()
  const appStore = useAppStore()
  const { inputText } = storeToRefs(chatStore)
  // 识别语言随界面语言（服务端仅支持 zh/en，其余 locale 归到 en）
  const language = (appStore.locale || 'zh-CN').startsWith('zh') ? 'zh' : 'en'
  const session = new StreamingAsrSession(
    {
      onPartial: (text) => {
        // 本轮 interim 覆盖式显示（基座 + 已终结轮 + 当前轮）
        chatStore.setInputText(joinTexts(streamingBase, streamingCommitted, text))
        nextTick(() => resizeHook?.())
      },
      onFinal: (text) => {
        const trimmed = text.trim()
        if (trimmed) {
          streamingCommitted = joinTexts(streamingCommitted, trimmed)
        }
        chatStore.setInputText(joinTexts(streamingBase, streamingCommitted))
        nextTick(() => resizeHook?.())
      },
      onError: (code, message) => {
        console.warn('[ASR] 流式通道错误:', code, message)
        fallbackFromStreaming()
      },
      onClose: () => {
        // 服务端/网络断开且仍在录音态：回落 Web Speech（正常收尾时 isRecording 已为 false）
        if (usingStreaming.value && isRecording.value) {
          fallbackFromStreaming()
        }
      },
    },
    language,
  )
  streamingSession = session
  session
    .start()
    .then(() => {
      usingStreaming.value = true
    })
    .catch((e) => {
      console.warn('[ASR] 流式通道不可用，回落 Web Speech:', e)
      if (streamingSession === session) {
        streamingSession = null
        usingStreaming.value = false
      }
      if (isRecording.value && !streamingFallbackTried) {
        streamingFallbackTried = true
        startWebSpeech()
      }
    })
  return true
}

/** 流式通道失败/断开时的回落：放弃会话并改用 Web Speech（每轮至多一次） */
function fallbackFromStreaming(): void {
  if (streamingSession) {
    const session = streamingSession
    streamingSession = null
    usingStreaming.value = false
    session.abort()
  }
  if (isRecording.value && !streamingFallbackTried) {
    streamingFallbackTried = true
    startWebSpeech()
  }
}

/** Web Speech 兜底启动（定时器已由 startRecording 统一拉起） */
function startWebSpeech(): void {
  if (!recognition) {
    isRecording.value = false
    stopRecordingTimer()
    const { t } = useI18n()
    uiMessage.warning(t('chat.asrUnavailable') || '语音识别当前不可用')
    return
  }
  try {
    recognition.start()
  } catch {
    // Already started
  }
}

function stopRecording(): void {
  isRecording.value = false
  stopRecordingTimer()
  if (streamingSession) {
    const session = streamingSession
    streamingSession = null
    usingStreaming.value = false
    // stop：补发 finish 终结尾轮并等待 final（内部有 3s 上限），失败即放弃
    session.stop().catch(() => session.abort())
    return
  }
  try {
    recognition?.stop()
  } catch {
    // Ignore
  }
}

function cancelRecording(): void {
  isRecording.value = false
  stopRecordingTimer()
  if (streamingSession) {
    const session = streamingSession
    streamingSession = null
    usingStreaming.value = false
    // 取消：不终结当前轮，直接放弃
    session.abort()
    return
  }
  try {
    recognition?.stop()
  } catch {
    // Ignore
  }
}

/** Backend ASR fallback for uploaded audio files */
async function transcribeAudioFile(file: File): Promise<string | null> {
  const appStore = useAppStore()
  try {
    const formData = new FormData()
    formData.append('audio_file', file)
    formData.append('language', appStore.locale === 'zh-CN' ? 'zh' : 'en')
    const res: any = await transcribeAudio(formData)
    const data = res?.data ?? res
    return data?.data?.text || data?.text || null
  } catch (err) {
    console.error('[ASR] Backend transcription failed:', err)
    return null
  }
}

/** locale 切换时同步识别语言（页面 watch 调用；流式通道为服务端 zh 引擎，不受影响） */
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
    usingStreaming,
    setResizeHook,
    initASR,
    toggleRecording,
    cancelRecording,
    stopRecording,
    transcribeAudioFile,
    syncLocale,
  }
}
