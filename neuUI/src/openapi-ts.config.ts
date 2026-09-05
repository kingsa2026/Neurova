import type { Config } from 'openapi-ts'
const config: Config = {
  // OpenAPI 规范文件路径
  input: 'http://localhost:8000/openapi.json',
  // 输出目录
  output: 'src/api/generated',
  // 生成配置
  options: {
    // 使用 fetch 客户端
    client: 'fetch',
    // 生成类型安全的 API 客户端
    useOptions: true,
    // 生成枚举
    useEnum: true,
    // 生成日期类型
    useDateType: true,
    // 生成大整数类型
    useBigint: true,
    // 生成数组最小长度
    useArrayLength: true,
    // 生成默认值
    useDefaultValue: true,
    // 生成导出类型
    exportType: true,
    // 生成运行时验证
    runtimeValidate: false,
    // 生成严格运行时验证
    strictRuntimeValidate: false,
    // 生成格式
    format: true,
    // 生成 Lint
    lint: false,
    // 生成空枚举
    emptyEnums: false,
    // 添加读导出
    addReadExport: false,
    // 签名
    signatures: [],
    // 类型
    types: {
      // 自定义类型映射
    },
    // 转换
    transforms: [],
    // 钩子
    hooks: {}
  }
}
export default config
 