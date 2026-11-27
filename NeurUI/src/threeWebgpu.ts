// three-render-objects 默认走 WebGL；显式失败边界避免未使用的 WebGPU/TSL 进入包体。
export class WebGPURenderer {
  constructor() {
    throw new Error('Neurova 三维图仅支持 WebGL，未启用 WebGPU 渲染器')
  }
}
