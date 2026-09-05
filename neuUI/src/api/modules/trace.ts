import { request } from '@/api'

export interface StartTrajectoryRequest {
  agent_id: string
  session_id: string
  user_id?: string
  metadata?: Record<string, unknown>
}

export interface ListTracesRequest {
  user_id?: string
  agent_id?: string
  session_id?: string
  limit?: number
}

export interface GetTrajectoryRequest {
  trace_id: string
  include_events?: boolean
}

export interface ReplayTrajectoryRequest {
  trace_id: string
  speed?: number
  enable_callback?: boolean
}

export interface DeleteTrajectoryRequest {
  trace_id: string
}

export interface QueryTrajectoriesRequest {
  user_id?: string
  agent_id?: string
  session_id?: string
  start_time?: string
  end_time?: string
  min_duration_ms?: number
  max_duration_ms?: number
  has_error?: boolean
  limit?: number
}

export interface ExportTrajectoryRequest {
  trace_id: string
  format?: 'json' | 'html'
}

export const traceAPI = {
  start: (data: StartTrajectoryRequest) =>
    request.post('/trajectory/start', data),
  end: (traceId: string) =>
    request.post('/trajectory/end', { trace_id: traceId }),
  list: (data: ListTracesRequest) =>
    request.post('/trajectory/list', data),
  get: (data: GetTrajectoryRequest) =>
    request.post('/trajectory/get', data),
  replay: (data: ReplayTrajectoryRequest) =>
    request.post('/trajectory/replay', data),
  delete: (data: DeleteTrajectoryRequest) =>
    request.post('/trajectory/delete', data),
  getStatus: () => request.get('/trajectory/status'),
  setEnabled: (enabled: boolean) =>
    request.post('/trajectory/set-enabled', { enabled }),
  setAutoSave: (autoSave: boolean) =>
    request.post('/trajectory/set-auto-save', { auto_save: autoSave }),
  query: (data: QueryTrajectoriesRequest) =>
    request.post('/trajectory/query', data),
  export: (data: ExportTrajectoryRequest) =>
    request.post('/trajectory/export', data),
}
