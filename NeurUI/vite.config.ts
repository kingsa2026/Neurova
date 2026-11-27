import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: [
      { find: /^ant-design-vue$/, replacement: resolve(__dirname, 'src/antd.ts') },
      { find: /^@ant-design\/icons-vue$/, replacement: resolve(__dirname, 'src/icons.ts') },
      { find: /^ant-design-vue\/locale\/(.+)$/, replacement: 'ant-design-vue/es/locale/$1' },
      { find: /^three\/webgpu$/, replacement: resolve(__dirname, 'src/threeWebgpu.ts') },
      { find: '@', replacement: resolve(__dirname, 'src') },
    ],
  },
  css: {
    preprocessorOptions: {},
  },
  server: {
    port: 8100,
    strictPort: true,
    watch: {
      // src-tauri/target 是 Rust 构建产物目录：体积巨大且 exe 被构建器/杀软锁定，
      // Vite 监听会触发 EBUSY 使 dev server 崩溃（2026-09-02 实测），必须排除
      ignored: ['**/src-tauri/target/**'],
    },
    proxy: {
      '/api': {
        target: 'http://localhost:9527',
        changeOrigin: true,
        // 后端 WebSocket 端点挂在 /api/v1/sync/ws/... 下，
        // 必须允许 /api 前缀的请求升级为 WebSocket，否则连接被 HTTP 代理吞掉
        ws: true,
        headers: {
          'Cache-Control': 'no-cache',
          'X-Accel-Buffering': 'no',
        },
      },
      // 3.7-3：原 /ws 代理退役——前端 WS 全部走 /api 前缀（useSessionSync
      // buildUrl → /api/v1/sync/ws/...），/ws 路径全仓零消费方（死配置）。
    },
  },
  build: {
    target: 'es2022',
    outDir: 'dist',
    sourcemap: false,
    cssCodeSplit: false,
    modulePreload: { polyfill: false },
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: {
        experimentalMinChunkSize: 50 * 1024,
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia', 'vue-i18n'],
          'vendor-charts': ['echarts', 'vue-echarts'],
          'vendor-flow': ['@vue-flow/core', '@vue-flow/background', '@vue-flow/controls', '@vue-flow/minimap'],
        },
      },
    },
  },
})
