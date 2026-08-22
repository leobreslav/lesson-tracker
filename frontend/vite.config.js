import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // bind-mount из WSL2 не отдаёт inotify-события, иначе HMR не срабатывает
    watch: { usePolling: true },
    proxy: {
      // changeOrigin не включаем: тогда Host остаётся localhost:5173 и
      // проходит ALLOWED_HOSTS Django, иначе прилетает DisallowedHost
      '/api': { target: 'http://backend:8000' },
    },
  },
})
