/**
 * KnowledgeGraphApi - 知识图谱 API 模块（同源 PC GraphWorkbenchPage）
 *
 * 后端事实源：neurova/api/endpoints/knowledge_graph_api.py（挂 /v1/knowledge-graph）：
 *   GET /knowledge-graph/{agent_id}/spatial-nodes → {code:0,data:[{node_id,label,type,geo}]}
 *   GET /knowledge-graph/{agent_id}/subgraph      → 子图（连线，M 后续接入）
 * 连线数据 v1 未接（spatial 仅节点落图）；图谱速览页先按节点散布 + 类型着色呈现。
 */

import { HttpClient } from '../HttpClient';
import { ApiResponse } from '../../types';

/** 空间节点（spatial-nodes 条目原样） */
export interface GraphNodeDto {
  node_id: string;
  label: string;
  type: string;
  geo: string;
}

export class KnowledgeGraphApi {
  private client: HttpClient;

  constructor(client: HttpClient) {
    this.client = client;
  }

  /** 空间节点落图 */
  async spatialNodes(agentId: string): Promise<ApiResponse<GraphNodeDto[]>> {
    return this.client.get<GraphNodeDto[]>(`/knowledge-graph/${agentId}/spatial-nodes`);
  }

  /** 子图检索 */
  async subgraph(agentId: string, keyword?: string): Promise<ApiResponse<Object>> {
    const q = keyword && keyword.length > 0 ? '?keyword=' + encodeURIComponent(keyword) : '';
    return this.client.get<Object>(`/knowledge-graph/${agentId}/subgraph${q}`);
  }
}
