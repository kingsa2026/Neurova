import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const viteConfigSource = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8')

describe('GraphExplorer3D 构建依赖边界', () => {
  it('未启用的 WebGPU 渲染器不得把 WebGPU/TSL 运行时拖入包体', () => {
    expect(viteConfigSource).toMatch(
      /find:\s*\/\^three\\\/webgpu\$\/[\s\S]{0,160}threeWebgpu\.ts/,
    )
  })

  it('组件语言包走 ESM 入口，避免 CommonJS 副本重复打包', () => {
    expect(viteConfigSource).toMatch(
      /find:\s*\/\^ant-design-vue\\\/locale\\\/\(\.\+\)\$\/[\s\S]{0,160}ant-design-vue\/es\/locale\/\$1/,
    )
  })
})
