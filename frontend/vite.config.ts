import { fileURLToPath } from 'url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('..', import.meta.url)), '')
  const backendPort = env.BACKEND_PORT || '8000'
  const frontendPort = env.FRONTEND_PORT || '5173'
  return {
    plugins: [vue()],
    server: {
      port: parseInt(frontendPort),
      host: true,
      proxy: {
        '^/(subjects|health)': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
        },
        // chat 的 API 只有 POST /chat、/chat/stream、/chat/quiz[/stream]。
        // 不能用 '^/chat' 前缀匹配：页面路由 /chat/:subject 会被一并代理到后端，
        // 导致直接访问/刷新聊天页时收到 FastAPI 的 {"detail":"Not Found"}
        '^/chat($|/stream|/quiz)': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
        },
        '^/admin/': {
          target: `http://localhost:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
    define: {
      __API_BASE_URL__: JSON.stringify(''),
    },
  }
})
