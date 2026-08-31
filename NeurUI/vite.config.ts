import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  css: {
    preprocessorOptions: {},
  },
  server: {
    port: 8100,
    strictPort: true,
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
      '/ws': {
        target: 'ws://localhost:9527',
        ws: true,
      },
    },
  },
  build: {
    target: 'es2020',
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia', 'vue-i18n'],
          'vendor-ant': ['ant-design-vue'],
          'vendor-charts': ['echarts', 'vue-echarts'],
          'vendor-flow': ['@vue-flow/core', '@vue-flow/background', '@vue-flow/controls', '@vue-flow/minimap'],
        },
      },
    },
  },
})
