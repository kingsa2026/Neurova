/**
 * 知识图谱节点归一化（从 KnowledgeGraphPage 抽出的纯函数，供单测）。
 *
 * 后端 knowledge_graph_api 返回节点 {id,label,type,description,weight,created_at}；
 * 页面统一消费 {category,name,...}。type 缺失落 'default'。
 */
export interface NormalizedNode extends Record<string, unknown> {
  category: string
  name: string
  description?: string
}

export function normalizeNode(n: Record<string, unknown>): NormalizedNode {
  return {
    ...n,
    category: (n.category as string) ?? (n.type as string) ?? 'default',
    name: (n.label as string) ?? (n.name as string) ?? (n.id as string),
  }
}
