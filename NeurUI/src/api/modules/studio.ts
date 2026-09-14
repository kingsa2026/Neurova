import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// 创作专区（R3 后端 /api/v1/studio）前端契约 —— 类型逐字段对齐 studio_api
// ---------------------------------------------------------------------------

const BASE = '/studio'

export interface StudioProject {
  id: string
  owner_user_id: string
  title: string
  description: string
  genre: string
  style: string
  aspect_ratio: string
  total_episodes: number
  status: string
  thumbnail: string
  created_at: number
  updated_at: number
}

export interface StudioEpisode {
  id: string
  project_id: string
  number: number
  title: string
  content: string
  synopsis: string
  status: string
  duration: number
  video_path: string
  subtitle_path: string
  shot_count?: number
  shots_ready?: number
}

export interface StudioCharacter {
  id: string
  project_id: string
  name: string
  role: string
  description: string
  appearance: string
  styling: string
  personality: string
  final_prompt: string
  image_path: string
  seed_value: string
  status: string
}

export interface StudioScene {
  id: string
  project_id: string
  episode_id: string
  location: string
  time: string
  prompt: string
  lighting: string
  final_prompt: string
  image_path: string
  status: string
}

export interface StudioProp {
  id: string
  project_id: string
  name: string
  description: string
  final_prompt: string
  image_path: string
  status: string
}

export interface ShotRef { name: string; id: string }

export interface StudioStoryboard {
  id: string
  episode_id: string
  number: number
  title: string
  description: string
  image_prompt: string
  video_prompt: string
  narration: string
  camera: string
  movement: string
  atmosphere: string
  bgm_prompt: string
  sound_effect: string
  duration: number
  characters_json: string
  props_json: string
  first_frame_path: string
  /** A1：镜头尾帧（Seedance first+last 插值；WAN 无通道 ignored_params 标注） */
  end_frame_path?: string
  injected_prompt: string
  video_path: string
  video_status: string
  ledger_task_id: string
  subtitle_path: string
  audio_path: string
  status: string
  error: string
}

export interface StudioMerge {
  id: string
  project_id: string
  episode_id: string
  mode: string
  status: string
  output_path: string
  output_url: string
  error: string
  items_json: string
}

export interface StudioRun {
  id: string
  project_id: string
  kind: string
  status: string
  detail_json: string
  error: string
  created_at: number
}

export interface ProjectDetail {
  project: StudioProject
  episodes: StudioEpisode[]
  characters: StudioCharacter[]
  scenes: StudioScene[]
  props: StudioProp[]
  runs: StudioRun[]
}

// ── projects ──────────────────────────────────────────────────────────────

export function listProjects() {
  return api.get<ApiResponse<{ projects: StudioProject[] }>>(`${BASE}/projects`)
}

export function createProject(data: {
  title: string
  description?: string
  genre?: string
  style?: string
  aspect_ratio?: string
  total_episodes?: number
}) {
  return api.post<ApiResponse<{ project: StudioProject }>>(`${BASE}/projects`, data)
}

export function getProject(pid: string) {
  return api.get<ApiResponse<ProjectDetail>>(`${BASE}/projects/${pid}`)
}

export function updateProject(pid: string, fields: Record<string, unknown>) {
  return api.put<ApiResponse<{ project: StudioProject }>>(`${BASE}/projects/${pid}`, fields)
}

export function deleteProject(pid: string) {
  return api.delete<ApiResponse<{ deleted: boolean }>>(`${BASE}/projects/${pid}`)
}

// ── 长任务（后台 runs，立即返回 run_id）───────────────────────────────────

export interface RunAccepted { run_id: string; status: string }

export function runSplitScript(pid: string, content: string, model?: string) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/projects/${pid}/script`, { content, model })
}

export function runExtract(eid: string) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/episodes/${eid}/extract`)
}

export function runStoryboards(eid: string, force = false) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/episodes/${eid}/storyboards`, { force })
}

export function runGenerateImages(eid: string, opts?: { provider?: string; model?: string }) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/episodes/${eid}/generate-images`, opts ?? {})
}

export function runGenerateVideos(eid: string, opts?: {
  provider?: string; model?: string; resolution?: string; duration?: number
}) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/episodes/${eid}/generate-videos`, opts ?? {})
}

export function runNarration(eid: string, voice = 'default') {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/episodes/${eid}/narration`, { voice })
}

export function runAssetImages(pid: string, opts?: { provider?: string; ids?: string[] }) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/projects/${pid}/assets/images`, opts ?? {})
}

export function retryStoryboard(sid: string, opts?: { stage?: 'image' | 'video'; provider?: string; model?: string }) {
  return api.post<ApiResponse<RunAccepted>>(`${BASE}/storyboards/${sid}/retry`, opts ?? {})
}

// ── episodes / storyboards ────────────────────────────────────────────────

export function getEpisode(eid: string) {
  return api.get<ApiResponse<{ episode: StudioEpisode; storyboards: StudioStoryboard[] }>>(
    `${BASE}/episodes/${eid}`)
}

export function updateEpisode(eid: string, fields: Record<string, unknown>) {
  return api.put<ApiResponse<{ episode: StudioEpisode }>>(`${BASE}/episodes/${eid}`, fields)
}

export function updateStoryboard(sid: string, fields: Record<string, unknown>) {
  return api.put<ApiResponse<{ storyboard: StudioStoryboard }>>(`${BASE}/storyboards/${sid}`, fields)
}

/** 手动新增镜头（LLM 拆解失败/不可用时工作台不被阻塞；与后台拆解
 * POST /episodes/{eid}/storyboards 区分路径） */
export function addStoryboardManually(eid: string, data: Record<string, unknown>) {
  return api.post<ApiResponse<{ storyboard: StudioStoryboard }>>(`${BASE}/episodes/${eid}/storyboards/manual`, data)
}

// ── merge / assets ────────────────────────────────────────────────────────

export interface MergeResult {
  ok: boolean
  composed: boolean
  mode: string
  url?: string
  error?: string
  // A5：字幕烧录诚实降级（无中文字体/烧录失败 → 无字幕成片 + warning 原文）
  subtitle_burned?: boolean
  warning?: string
  merge: StudioMerge
  items: Array<{
    index: number
    shot?: number
    image: string
    video: string
    audio: string
    text: string
  }>
}

export function mergeEpisode(eid: string) {
  return api.post<ApiResponse<MergeResult>>(`${BASE}/episodes/${eid}/merge`)
}

export function getMerge(mid: string) {
  return api.get<ApiResponse<{ merge: StudioMerge }>>(`${BASE}/merges/${mid}`)
}

export function updateAsset(
  table: 'characters' | 'scenes' | 'props', id: string, fields: Record<string, unknown>) {
  return api.put<ApiResponse<{ asset: Record<string, unknown> }>>(`${BASE}/assets/${table}/${id}`, fields)
}
