/**
 * `3d-force-graph` 的最小模块声明：本仓只用到构造 + 图数据 + 点击回调，
 * 不为整个 API 面抄类型——按需扩充，声明跟随真实用法。
 */
declare module '3d-force-graph' {
  interface ForceGraph3DInstance {
    (element: HTMLElement): ForceGraph3DInstance
    graphData(data: { nodes: unknown[]; links: unknown[] }): ForceGraph3DInstance
    nodeLabel(getter: (node: unknown) => string): ForceGraph3DInstance
    nodeColor(getter: (node: unknown) => string): ForceGraph3DInstance
    onNodeClick(handler: (node: unknown) => void): ForceGraph3DInstance
    width(px: number): ForceGraph3DInstance
    height(px: number): ForceGraph3DInstance
    backgroundColor(color: string): ForceGraph3DInstance
    _destructor?(): void
  }
  const ForceGraph3D: {
    new (): ForceGraph3DInstance
    (): ForceGraph3DInstance
  }
  export default ForceGraph3D
}
