import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.VITE_SKILLANYTHING_API_PROXY || 'http://127.0.0.1:8091'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5176,
    proxy: {
      '/api': apiTarget,
      '/profiles': apiTarget,
      '/skills': apiTarget,
      '/jobs': apiTarget,
      '/collect': apiTarget,
      '/settings': apiTarget,
      '/config': apiTarget,
      '/health': apiTarget
    }
  }
})
