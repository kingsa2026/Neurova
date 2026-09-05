import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    Components({
      resolvers: [AntDesignVueResolver({ importStyle: false })]
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      'liquid-glass-vue': resolve(__dirname, 'liquid-glass-vue-main/src')
    }
  },
  server: {
    port: 8100,
    strictPort: true, // 严格固定端口，被占用时直接报错而不自动切换
    proxy: {
      '/api': {
        target: 'http://localhost:9527',
        changeOrigin: true,
        // 禁用代理缓冲，确保 SSE 流式响应正常工作
        configure: (proxy, options) => {
          proxy.on('error', (err, req, res) => {
            console.log('代理错误:', err)
          })
          proxy.on('proxyReq', (proxyReq, req, res) => {
            console.log('代理请求:', req.method, req.url, '->', options.target + req.url)
          })
          // 关键：禁用响应缓冲，让 SSE 数据实时转发
          proxy.on('proxyRes', (proxyRes, req, res) => {
            proxyRes.headers['Cache-Control'] = 'no-cache'
            proxyRes.headers['X-Accel-Buffering'] = 'no'
          })
        }
      }
    }
  }
})
