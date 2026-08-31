/**
 * canvasClipboard — 画布节点复制粘贴纯函数（遗留 D）。
 *
 * duplicateNodesForPaste：选中集深拷贝（新 id/位置平移/config 保留），
 * 内部边重映射端点，外部边丢弃。供 Ctrl+C/V 键盘事件消费。
 */
import type { CanvasNodeSnapshot, CanvasEdgeSnapshot } from '@/api/modules/collaboration'

export interface PasteResult {
  nodes: CanvasNodeSnapshot[]
  edges: CanvasEdgeSnapshot[]
  /** 旧节点 id → 新节点 id 映射（供同步选中态） */
  idMap: Record<string, string>
}

let pasteSeq = 0

function newId(oldId: string): string {
  pasteSeq += 1
  return `${oldId}_copy_${Date.now().toString(36)}_${pasteSeq}`
}

export function duplicateNodesForPaste(
  nodes: CanvasNodeSnapshot[],
  edges: CanvasEdgeSnapshot[],
  sourceIds: string[],
  offsetX: number,
  offsetY: number,
): PasteResult {
  const selected = new Set(sourceIds)
  const idMap: Record<string, string> = {}
  const result: PasteResult = { nodes: [], edges: [], idMap }

  for (const n of nodes) {
    if (!selected.has(n.id)) continue
    const id = newId(n.id)
    idMap[n.id] = id
    result.nodes.push({
      ...n,
      id,
      position: {
        x: (n.position?.x ?? 0) + offsetX,
        y: (n.position?.y ?? 0) + offsetY,
      },
      config: JSON.parse(JSON.stringify(n.config ?? {})),
    })
  }

  for (const e of edges) {
    const srcId = e.source?.nodeId
    const tgtId = e.target?.nodeId
    if (!srcId || !tgtId || !selected.has(srcId) || !selected.has(tgtId)) continue
    if (idMap[srcId] === undefined || idMap[tgtId] === undefined) continue
    result.edges.push({
      ...e,
      id: newId(e.id),
      source: { nodeId: idMap[srcId], portId: e.source?.portId ?? 'out' },
      target: { nodeId: idMap[tgtId], portId: e.target?.portId ?? 'in' },
    })
  }

  return result
}
