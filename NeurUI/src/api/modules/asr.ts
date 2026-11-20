import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// API（P2-21：自 VoiceTranscriptionSettingsPage / useASRRecording 裸写 URL
// 收编；路径/参数/超时逐字对齐原调用）
// ---------------------------------------------------------------------------

/** Local Whisper 状态（consent / model_ready / active_engine）。 */
export function getLocalWhisperStatus() {
  return api.get<ApiResponse<Record<string, unknown>>>('/audio/asr/local-whisper/status')
}

/** 授予 local-whisper 同意；服务端随后阻塞下载模型+重跑链（可能数分钟）。 */
export function grantLocalWhisperConsent() {
  return api.post<ApiResponse<Record<string, unknown>>>(
    '/audio/asr/local-whisper/consent',
    {},
    { timeout: 660_000 },
  )
}

/** 上传音频文件转写（multipart；后端 ASR 兜底通道）。 */
export function transcribeAudio(formData: FormData) {
  return api.post<ApiResponse<unknown>>('/audio/transcribe', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ---------------------------------------------------------------------------
// 录音纪要链（B4-8：录音 → 纪要 → Ask 判定问题/办事 → 办事落任务看板）
// ---------------------------------------------------------------------------

/** 上传录音入队（有界队列；满时后端 429 + input_gap 证据，不静默丢）。 */
export function createVoiceMinutes(formData: FormData) {
  return api.post<ApiResponse<Record<string, unknown>>>('/audio/minutes', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 轮询纪要作业状态/结果（transcript/summary/kind/task_id/error）。 */
export function getVoiceMinutesStatus(jobId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(`/audio/minutes/${jobId}`)
}
