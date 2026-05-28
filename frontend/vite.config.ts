import path from 'path'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve(__dirname, '..'), '')
  const backendPort = env.BACKEND_PORT || '8000'
  const frontendPort = env.FRONTEND_PORT || '5173'
  return {
    plugins: [vue()],
    server: {
      port: parseInt(frontendPort),
      host: true,
      proxy: {
        '^/(subjects|chat|health)': {
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
