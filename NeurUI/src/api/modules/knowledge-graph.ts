import api from '@/api'
import type { ApiResponse } from '@/types/response'

// ---------------------------------------------------------------------------
// API（P2-21：自 GraphWorkbenchPage / GeoMapPanel 裸写 URL 收编；
// 路径/参数逐字对齐原调用）
// ---------------------------------------------------------------------------

/** 图谱工作台全量快照（GET /knowledge-graph/{agentId}/studio 信封 data）。 */
export function getKnowledgeGraphStudio(agentId: string) {
  return api.get<ApiResponse<Record<string, unknown>>>(`/knowledge-graph/${agentId}/studio`)
}

/** 全图索引检索（GET /knowledge-graph/{agentId}/knowledge-graph/search）。 */
export function searchKnowledgeGraphNodes(
  agentId: string,
  params: { q: string; limit?: number },
) {
  return api.get<ApiResponse<{ nodes?: unknown[] }>>(
    `/knowledge-graph/${agentId}/knowledge-graph/search`,
    { params },
  )
}

/** 命中节点邻域子图（GET /knowledge-graph/{agentId}/subgraph）。 */
export function getKnowledgeGraphSubgraph(
  agentId: string,
  params: { focus: string; hops?: number },
) {
  return api.get<ApiResponse<Record<string, unknown>>>(
    `/knowledge-graph/${agentId}/subgraph`,
    { params },
  )
}

/** 节点地理坐标（GET /knowledge-graph/{agentId}/spatial-nodes 信封 data）。 */
export function getKnowledgeGraphSpatialNodes(agentId: string) {
  return api.get<ApiResponse<unknown[]>>(`/knowledge-graph/${agentId}/spatial-nodes`)
}
