import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API is a single WebSocket. Vite proxies it in dev so the browser talks to
// one origin and no CORS or cookie-domain rules apply to the socket handshake.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.NODUS_API_URL ?? 'https://nodus-research-x7k2m9pz.vercel.app',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
