import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Capacitor webDir 为 www/（capacitor.config.json）；构建后由脚本归档至 Mobile/dist/android
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 8200,
    strictPort: true,
    proxy: {
      // 本机联调：直连后端 9527（内网直连形态 A）
      '/api': { target: 'http://127.0.0.1:9527', changeOrigin: true },
    },
  },
  build: {
    outDir: fileURLToPath(new URL('./www', import.meta.url)),
    emptyOutDir: true,
  },
})
