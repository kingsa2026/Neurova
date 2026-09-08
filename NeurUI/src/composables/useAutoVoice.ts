import { ref } from 'vue'

/**
 * 自动语音开关（2026-09-08 ChatPage 拆分产物）。
 *
 * 模块级单例：ChatComposerArea（工具条开关）与页面编排层（流式 TTS
 * runner 接线、SSE chunk/done 分支判断 autoVoice）共享状态。
 */

const AUTO_VOICE_KEY = 'neurova_auto_voice'
const autoVoice = ref(localStorage.getItem(AUTO_VOICE_KEY) === '1')

function toggleAutoVoice(onDisabled?: () => void): void {
  autoVoice.value = !autoVoice.value
  localStorage.setItem(AUTO_VOICE_KEY, autoVoice.value ? '1' : '0')
  if (!autoVoice.value) onDisabled?.()
}

export function useAutoVoice() {
  return { autoVoice, toggleAutoVoice }
}
