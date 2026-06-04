import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 8100,
    host: '0.0.0.0',
    proxy: {
      // SSE 流式接口 - 专用代理规则
      '/api/v1/chat/stream': {
        target: 'http://localhost:9527',
        changeOrigin: true,
        headers: {
          'Accept': 'text/event-stream',
        },
      },
      // 通用 API 代理
      '/api': {
        target: 'http://localhost:9527',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'pinia'],
          antd: ['ant-design-vue', '@ant-design/icons-vue'],
        },
      },
    },
  },
})
