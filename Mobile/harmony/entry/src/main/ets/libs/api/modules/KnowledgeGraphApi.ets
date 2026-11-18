/**
 * KnowledgeGraphApi - 知识图谱 API 模块（同源 PC GraphWorkbenchPage）
 *
 * 后端事实源：neurova/api/endpoints/knowledge_graph_api.py（挂 /v1/knowledge-graph）：
 *   GET /knowledge-graph/{agent_id}/spatial-nodes        →geo 落图节点（仅含已填坐标者）
 *   GET /knowledge-graph/{agent_id}/subgraph             →按需子图 {nodes,edges,dropped_by_limit}
 *       （focus 空=全图子集；hops/limit/types 裁剪；节点含 description/weight）
 *   GET /knowledge-graph/{agent_id}/knowledge-graph/search?q=  →节点搜索
 *   GET /knowledge-graph/{agent_id}/knowledge-graph/nodes/{id} →节点详情（含关联边/节点）
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 空间节点（spatial-nodes 条目：仅携带 geo 坐标的节点） */
export interface GraphNodeDto {
  node_id: string;
  label: string;
  type: string;
  geo: string;
}

/** 子图/详情节点（_node_to_dict 形状） */
export interface GraphNodeFullDto {
  id: string;
  label: string;
  type: string;
  description: string;
  weight: number;
  created_at: string | null;
}

/** 关系边（_edge_to_dict 形状） */
export interface GraphEdgeDto {
  source: string;
  target: string;
  relation: string;
  weight: number;
}

/** 子图载荷 */
export interface GraphSubgraphDto {
  nodes: GraphNodeFullDto[];
  edges: GraphEdgeDto[];
  dropped_by_limit: boolean;
}

/** 节点详情载荷（node + 关联边 + 关联节点） */
export interface GraphNodeDetailDto {
  node: GraphNodeFullDto;
  edges: GraphEdgeDto[];
  related_nodes: GraphNodeFullDto[];
}

/** 节点搜索载荷 */
export interface GraphSearchDto {
  nodes: GraphNodeFullDto[];
  total: number;
  query: string;
}

export class KnowledgeGraphApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 空间节点落图（仅含已填 geo 坐标的节点） */
  async spatialNodes(agentId: string): Promise<ApiResponse<GraphNodeDto[]>> {
    return this.client.get<GraphNodeDto[]>(`/knowledge-graph/${agentId}/spatial-nodes`);
  }

  /**
   * 按需子图：focus 空=全图子集（首屏）；非空=以该节点为中心 BFS hops 跳。
   * 服务端裁剪渲染预算，客户端不养大图。
   */
  async subgraph(agentId: string, focus?: string, hops?: number, limit?: number): Promise<ApiResponse<GraphSubgraphDto>> {
    const parts: string[] = [];
    if (focus && focus.length > 0) {
      parts.push('focus=' + encodeURIComponent(focus));
    }
    if (hops !== undefined) {
      parts.push('hops=' + hops.toString());
    }
    if (limit !== undefined) {
      parts.push('limit=' + limit.toString());
    }
    const q = parts.length > 0 ? '?' + parts.join('&') : '';
    return this.client.get<GraphSubgraphDto>(`/knowledge-graph/${agentId}/subgraph${q}`);
  }

  /** 节点搜索（走服务端 search_nodes 索引） */
  async searchNodes(agentId: string, q: string, limit: number = 20): Promise<ApiResponse<GraphSearchDto>> {
    return this.client.get<GraphSearchDto>(`/knowledge-graph/${agentId}/knowledge-graph/search?q=${encodeURIComponent(q)}&limit=${limit}`);
  }

  /** 节点详情（含关联边与关联节点） */
  async nodeDetail(agentId: string, nodeId: string): Promise<ApiResponse<GraphNodeDetailDto>> {
    return this.client.get<GraphNodeDetailDto>(`/knowledge-graph/${agentId}/knowledge-graph/nodes/${encodeURIComponent(nodeId)}`);
  }
}
