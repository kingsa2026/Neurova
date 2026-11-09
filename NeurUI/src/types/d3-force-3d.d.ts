/**
 * d3-force-3d 类型垫片：包内无自带 .d.ts，API 与 d3-force 同构（仅
 * forceSimulation 多一个 dimensions 维度参数）——用 @types/d3-force
 * 再导出并补齐二维签名。@types/d3-force 由 devDependencies 显式登记。
 */
declare module 'd3-force-3d' {
  import type { Simulation, SimulationNodeDatum } from 'd3-force'
  export * from 'd3-force'
  export function forceSimulation<N extends SimulationNodeDatum>(
    nodes?: N[],
    dimensions?: number,
  ): Simulation<N, undefined>
}
