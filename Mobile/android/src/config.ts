/** 运行配置：后端地址一律来自"服务器档案"（设计方案 §4.5），不在代码里写死服务器。 */
export const APP_VERSION = '0.1.0'

/** 默认档案（首次启动的引导项；真机使用时用户应改为实际内网/中继地址） */
export const DEFAULT_SERVER_PROFILE = {
  id: 'default',
  name: '本机开发',
  baseUrl: 'http://127.0.0.1:9527',
  entryMode: 'direct' as const,
}
