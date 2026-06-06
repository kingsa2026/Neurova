import { request } from '@/api'

// 知识图谱节点
export interface KnowledgeGraphNode {
  id: string
  label: string
  type: string
  description: string
  weight: number
  created_at: string
}

// 知识图谱边
export interface KnowledgeGraphEdge {
  source: string
  target: string
  relation: string
  weight: number
}

// 知识图谱数据
export interface KnowledgeGraphData {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  total_nodes: number
  total_edges: number
}

// 搜索结果
export interface GraphSearchResult {
  nodes: KnowledgeGraphNode[]
  total: number
  query: string
}

// 节点详情
export interface NodeDetail {
  node: KnowledgeGraphNode
  edges: KnowledgeGraphEdge[]
  related_nodes: KnowledgeGraphNode[]
}

/**
 * 获取知识图谱
 * @param agentId Agent ID
 * @param limit 返回节点数量限制
 * @returns 知识图谱数据
 */
export async function getKnowledgeGraph(
  agentId: string,
  limit: number = 100
): Promise<{ code: number; message: string; data: KnowledgeGraphData }> {
  return request({
    url: `/api/v1/knowledge-graph/${agentId}/knowledge-graph`,
    method: 'get',
    params: { limit },
  })
}

/**
 * 搜索知识图谱节点
 * @param agentId Agent ID
 * @param query 搜索关键词
 * @param limit 返回数量限制
 * @returns 搜索结果
 */
export async function searchGraphNodes(
  agentId: string,
  query: string,
  limit: number = 20
): Promise<{ code: number; message: string; data: GraphSearchResult }> {
  return request({
    url: `/api/v1/knowledge-graph/${agentId}/knowledge-graph/search`,
    method: 'get',
    params: { q: query, limit },
  })
}

/**
 * 获取节点详情
 * @param agentId Agent ID
 * @param nodeId 节点ID
 * @returns 节点详情
 */
export async function getGraphNodeDetail(
  agentId: string,
  nodeId: string
): Promise<{ code: number; message: string; data: NodeDetail }> {
  return request({
    url: `/api/v1/knowledge-graph/${agentId}/knowledge-graph/nodes/${nodeId}`,
    method: 'get',
  })
}

export default {
  getKnowledgeGraph,
  searchGraphNodes,
  getGraphNodeDetail,
}